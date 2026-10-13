import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

from llama_index.core.base.embeddings.base import BaseEmbedding
from pydantic import PrivateAttr


class CachedEmbedding(BaseEmbedding):
    """Persistent, namespaced cache; query and document vectors have separate keys.

    The cache contains hashes and vectors, not original document text. New uploads
    reuse unchanged chunk embeddings, even though the small pilot rebuilds its index.
    """
    _inner: BaseEmbedding = PrivateAttr()
    _path: Path = PrivateAttr()
    _namespace: str = PrivateAttr()

    def __init__(self, inner: BaseEmbedding, path: Path, namespace: str):
        super().__init__(model_name=inner.model_name, embed_batch_size=32)
        self._inner, self._path, self._namespace = inner, path, namespace
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path, timeout=30) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def _key(self, text, kind):
        return hashlib.sha256(f"{self._namespace}|{kind}|{text}".encode()).hexdigest()

    def _get_query_embedding(self, query):
        key = self._key(query, "query")
        with sqlite3.connect(self._path, timeout=30) as db:
            row = db.execute("SELECT value FROM vectors WHERE key=?", (key,)).fetchone()
        if row:
            return json.loads(row[0])
        vector = self._inner.get_query_embedding(query)
        with sqlite3.connect(self._path, timeout=30) as db:
            db.execute("INSERT OR REPLACE INTO vectors VALUES (?,?)", (key, json.dumps(vector)))
        return vector

    async def _aget_query_embedding(self, query):
        return await asyncio.to_thread(self._get_query_embedding, query)

    def _get_text_embedding(self, text):
        return self._get_text_embeddings([text])[0]

    def _get_text_embeddings(self, texts):
        keys = [self._key(text, "document") for text in texts]
        known = {}
        with sqlite3.connect(self._path, timeout=30) as db:
            for key in set(keys):
                row = db.execute("SELECT value FROM vectors WHERE key=?", (key,)).fetchone()
                if row:
                    known[key] = json.loads(row[0])
        missing = dict((key, text) for key, text in zip(keys, texts, strict=True) if key not in known)
        if missing:
            vectors = self._inner.get_text_embedding_batch(list(missing.values()))
            if len(vectors) != len(missing):
                raise ValueError("Embedding server returned an incorrect batch length")
            new = dict(zip(missing, vectors, strict=True))
            with sqlite3.connect(self._path, timeout=30) as db:
                db.executemany("INSERT OR REPLACE INTO vectors VALUES (?,?)",
                               [(key, json.dumps(vector)) for key, vector in new.items()])
            known.update(new)
        return [known[key] for key in keys]

    async def _aget_text_embeddings(self, texts):
        return await asyncio.to_thread(self._get_text_embeddings, texts)
