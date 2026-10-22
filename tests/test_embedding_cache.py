import sqlite3

from app.rag import DemoHashEmbedding
from app.rag.embedding_cache import CachedEmbedding


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


def test_postgres_cached_embedding(settings):
    """Kiểm tra CachedEmbedding hoạt động mượt mà trên PostgreSQL."""
    if not settings.postgres_url:
        return
    inner = DemoHashEmbedding()
    cached = CachedEmbedding(inner, None, "test_pg_ns", postgres_url=settings.postgres_url)
    assert cached._use_postgres

    # Query embedding in RAM
    q_vec = cached.get_query_embedding("câu hỏi test postgres")
    assert len(q_vec) == 256

    # Doc embedding in PostgreSQL
    d_vec = cached.get_text_embedding("tài liệu nghiệp vụ bưu chính test")
    assert len(d_vec) == 256

    # Verify hit cache on second call
    d_vec2 = cached.get_text_embedding("tài liệu nghiệp vụ bưu chính test")
    assert d_vec == d_vec2

