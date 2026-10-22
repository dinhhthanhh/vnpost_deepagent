from __future__ import annotations

import array
import asyncio
import contextlib
import hashlib
import json
import logging
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from llama_index.core.base.embeddings.base import BaseEmbedding
from pydantic import PrivateAttr

from app.core.postgres import get_sync_pool

logger = logging.getLogger(__name__)


def _vector_to_blob(vec: list[float]) -> bytes:
    return array.array("f", vec).tobytes()


def _blob_to_vector(blob: bytes | memoryview | str) -> list[float]:
    if isinstance(blob, str):
        try:
            return json.loads(blob)
        except Exception:
            pass
    a = array.array("f")
    a.frombytes(bytes(blob))
    return a.tolist()


@contextlib.contextmanager
def _connect(path: Path):
    conn = sqlite3.connect(path, timeout=30)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


class CachedEmbedding(BaseEmbedding):
    """Persistent, namespaced cache; query and document vectors have separate keys.

    Document vectors are stored in PostgreSQL (Production) or on-disk SQLite (Offline test fallback).
    User queries are kept in an in-memory LRU cache to avoid persisting sensitive queries.
    """

    _inner: BaseEmbedding = PrivateAttr()
    _path: Path | None = PrivateAttr(default=None)
    _namespace: str = PrivateAttr()
    _postgres_url: str = PrivateAttr(default="")
    _pool: Any = PrivateAttr(default=None)
    _use_postgres: bool = PrivateAttr(default=False)
    _query_cache: OrderedDict = PrivateAttr(default_factory=OrderedDict)
    _query_lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    def __init__(
        self,
        inner: BaseEmbedding,
        path: Path | None,
        namespace: str,
        postgres_url: str | None = None,
    ):
        super().__init__(model_name=inner.model_name, embed_batch_size=32)
        self._inner = inner
        self._path = Path(path).resolve() if path else None
        self._namespace = namespace
        self._postgres_url = (postgres_url or "").strip()

        if self._postgres_url:
            self._pool = get_sync_pool(self._postgres_url)
            self._use_postgres = self._pool is not None

        if self._use_postgres:
            logger.info("CachedEmbedding đang sử dụng PostgreSQL Database.")
            if self._path:
                self._migrate_sqlite_to_postgres()
        elif self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with _connect(self._path) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, value BLOB NOT NULL)"
                )

    def _migrate_sqlite_to_postgres(self):
        """Tự động chuyển toàn bộ vector từ SQLite sang PostgreSQL và xóa file sqlite."""
        if not self._path or not self._path.is_file():
            return
        try:
            sdb = sqlite3.connect(self._path, timeout=15)
            migrated_count = 0
            now = time.time()
            try:
                cur = sdb.execute("SELECT key, value FROM vectors")
                rows = cur.fetchall()
                if rows:
                    with self._pool.connection() as pconn:
                        with pconn.cursor() as pcur:
                            # Migrate in batches of 500
                            for i in range(0, len(rows), 500):
                                batch = [
                                    (r[0], bytes(r[1]), now)
                                    for r in rows[i : i + 500]
                                ]
                                pcur.executemany(
                                    """
                                    INSERT INTO embedding_cache (key, value, created_at)
                                    VALUES (%s, %s, %s)
                                    ON CONFLICT (key) DO NOTHING;
                                    """,
                                    batch,
                                )
                                migrated_count += len(batch)
            finally:
                sdb.close()

            # Xóa các file sqlite sau khi đã migrate thành công
            for ext in ("", "-shm", "-wal"):
                target = Path(str(self._path) + ext)
                target.unlink(missing_ok=True)
            logger.info(
                "Đã di chuyển thành công %d vector từ SQLite sang PostgreSQL và xóa %s.",
                migrated_count,
                self._path.name,
            )
        except Exception as exc:
            logger.warning("Không thể di chuyển embedding cache sang PostgreSQL: %s", exc)

    def _key(self, text: str, kind: str) -> str:
        return hashlib.sha256(f"{self._namespace}|{kind}|{text}".encode()).hexdigest()

    def _get_query_embedding(self, query: str) -> list[float]:
        key = self._key(query, "query")
        with self._query_lock:
            if key in self._query_cache:
                self._query_cache.move_to_end(key)
                return self._query_cache[key]
        vector = self._inner.get_query_embedding(query)
        with self._query_lock:
            self._query_cache[key] = vector
            self._query_cache.move_to_end(key)
            while len(self._query_cache) > 1024:
                self._query_cache.popitem(last=False)
        return vector

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return await asyncio.to_thread(self._get_query_embedding, query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embeddings([text])[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        keys = [self._key(text, "document") for text in texts]
        known: dict[str, list[float]] = {}
        unique_keys = list(set(keys))

        if self._use_postgres:
            try:
                with self._pool.connection() as conn:
                    # In PostgreSQL, ANY(%s) handles array lookup efficiently
                    for i in range(0, len(unique_keys), 500):
                        batch = unique_keys[i : i + 500]
                        cur = conn.execute(
                            "SELECT key, value FROM embedding_cache WHERE key = ANY(%s);",
                            (batch,),
                        )
                        for row in cur.fetchall():
                            known[row["key"]] = _blob_to_vector(row["value"])
            except Exception as exc:
                logger.error("Lỗi đọc embedding_cache từ PostgreSQL: %s", exc)
        elif self._path and self._path.is_file():
            with _connect(self._path) as db:
                for i in range(0, len(unique_keys), 250):
                    batch = unique_keys[i : i + 250]
                    placeholders = ",".join("?" * len(batch))
                    cur = db.execute(
                        f"SELECT key, value FROM vectors WHERE key IN ({placeholders})", batch
                    )
                    for r_key, r_val in cur.fetchall():
                        known[r_key] = _blob_to_vector(r_val)

        missing = dict(
            (key, text) for key, text in zip(keys, texts, strict=True) if key not in known
        )
        if missing:
            vectors = self._inner.get_text_embedding_batch(list(missing.values()))
            if len(vectors) != len(missing):
                raise ValueError("Embedding server returned an incorrect batch length")
            new = dict(zip(missing, vectors, strict=True))

            if self._use_postgres:
                try:
                    now = time.time()
                    batch_data = [(k, _vector_to_blob(v), now) for k, v in new.items()]
                    with self._pool.connection() as conn:
                        with conn.cursor() as cur:
                            cur.executemany(
                                """
                                INSERT INTO embedding_cache (key, value, created_at)
                                VALUES (%s, %s, %s)
                                ON CONFLICT (key) DO NOTHING;
                                """,
                                batch_data,
                            )
                except Exception as exc:
                    logger.error("Lỗi ghi embedding_cache vào PostgreSQL: %s", exc)
            elif self._path:
                with _connect(self._path) as db:
                    db.executemany(
                        "INSERT OR REPLACE INTO vectors VALUES (?,?)",
                        [(key, _vector_to_blob(vector)) for key, vector in new.items()],
                    )
            known.update(new)

        return [known[key] for key in keys]

    async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._get_text_embeddings, texts)
