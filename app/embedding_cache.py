import array
import asyncio
import contextlib
import hashlib
import json
import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path

from llama_index.core.base.embeddings.base import BaseEmbedding
from pydantic import PrivateAttr


def _vector_to_blob(vec: list[float]) -> bytes:
    return array.array("f", vec).tobytes()


def _blob_to_vector(blob: bytes | str) -> list[float]:
    if isinstance(blob, str):
        try:
            return json.loads(blob)
        except Exception:
            pass
    a = array.array("f")
    a.frombytes(blob if isinstance(blob, (bytes, bytearray)) else bytes(blob))
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

    Document vectors are cached on disk as compact float32 binary blobs.
    User queries are kept in an in-memory LRU cache to avoid persisting sensitive queries.
    """
    _inner: BaseEmbedding = PrivateAttr()
    _path: Path = PrivateAttr()
    _namespace: str = PrivateAttr()
    _query_cache: OrderedDict = PrivateAttr(default_factory=OrderedDict)
    _query_lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    def __init__(self, inner: BaseEmbedding, path: Path, namespace: str):
        super().__init__(model_name=inner.model_name, embed_batch_size=32)
        self._inner, self._path, self._namespace = inner, path, namespace
        path.parent.mkdir(parents=True, exist_ok=True)
        with _connect(path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, value BLOB NOT NULL)")

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
        with _connect(self._path) as db:
            for i in range(0, len(unique_keys), 250):
                batch = unique_keys[i : i + 250]
                placeholders = ",".join("?" * len(batch))
                cur = db.execute(f"SELECT key, value FROM vectors WHERE key IN ({placeholders})", batch)
                for r_key, r_val in cur.fetchall():
                    known[r_key] = _blob_to_vector(r_val)
        missing = dict((key, text) for key, text in zip(keys, texts, strict=True) if key not in known)
        if missing:
            vectors = self._inner.get_text_embedding_batch(list(missing.values()))
            if len(vectors) != len(missing):
                raise ValueError("Embedding server returned an incorrect batch length")
            new = dict(zip(missing, vectors, strict=True))
            with _connect(self._path) as db:
                db.executemany(
                    "INSERT OR REPLACE INTO vectors VALUES (?,?)",
                    [(key, _vector_to_blob(vector)) for key, vector in new.items()],
                )
            known.update(new)
        return [known[key] for key in keys]

    async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._get_text_embeddings, texts)
