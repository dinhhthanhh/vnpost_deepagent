import sqlite3
import pytest
from app.embedding_cache import CachedEmbedding
from app.rag import DemoHashEmbedding

def test_query_embedding_is_ram_only_and_not_in_sqlite(tmp_path):
    db_path = tmp_path / "test_cache.sqlite3"
    inner = DemoHashEmbedding()
    cached = CachedEmbedding(inner, db_path, "test_ns")

    # Get query embedding
    q_vec = cached.get_query_embedding("câu hỏi nhạy cảm của người dùng")
    assert len(q_vec) == 256

    # Verify query is NOT in SQLite database
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    rows = cur.execute("SELECT key FROM vectors").fetchall()
    assert len(rows) == 0, "Query embedding must NOT be written to SQLite disk"

    # Get text/document embedding
    d_vec = cached.get_text_embedding("văn bản tài liệu công ty")
    assert len(d_vec) == 256

    # Verify document embedding IS written to SQLite database
    rows = cur.execute("SELECT key FROM vectors").fetchall()
    assert len(rows) == 1, "Document embedding should be written to SQLite disk"
    conn.close()
