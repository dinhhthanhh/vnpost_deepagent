import io
import zipfile

import pytest
from docx import Document

from app.config import Settings
from app.embedding_cache import CachedEmbedding
from app.rag import DemoHashEmbedding, KnowledgeBases, read_document


def test_txt_ingest_search_deduplicate_restart_delete(settings):
    bases = KnowledgeBases(settings)
    kb = bases.for_tenant("a")
    raw = "Thời hạn hoàn cước là 7 ngày. Hồ sơ gồm hóa đơn.".encode()
    record = kb.ingest("hoan_cuoc.txt", raw)
    hits = kb.retrieve("thời hạn hoàn cước")
    assert hits and "7 ngày" in hits[0]["excerpt"]
    assert hits[0]["filename"] == "hoan_cuoc.txt"
    assert kb.ingest("another.txt", raw)["duplicate"]
    assert len(kb.snapshot.records) == 1
    assert KnowledgeBases(settings).for_tenant("a").retrieve("hoàn cước")
    assert kb.remove(record["id"])
    assert not kb.retrieve("hoàn cước")
    assert not KnowledgeBases(settings).for_tenant("a").snapshot.nodes


def test_docx_preserves_tables_and_locations(settings):
    document = Document()
    document.add_heading("Chính sách mẫu", 1)
    document.add_paragraph("Mã bưu gửi được kiểm tra trước khi trả lời khách hàng.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Dịch vụ", "Thời hạn"
    table.cell(1, 0).text, table.cell(1, 1).text = "Hoàn cước", "7 ngày"
    buffer = io.BytesIO()
    document.save(buffer)
    docs = read_document("policy.docx", buffer.getvalue(), "docid", settings)
    assert any("bảng 1, hàng 2" in d.metadata["location"] and "7 ngày" in d.text for d in docs)
    assert all("trang" not in d.metadata["location"] for d in docs)
    kb = KnowledgeBases(settings).for_tenant("a")
    kb.ingest("policy.docx", buffer.getvalue())
    assert any("7 ngày" in h["excerpt"] for h in kb.retrieve("hoàn cước thời hạn"))


@pytest.mark.parametrize("filename,raw", [("x.doc", b"data"), ("x.dox", b"data"),
                                         ("x.exe", b"data"), ("x.txt", b"\x00"),
                                         ("x.txt", b"\xff"), ("x.txt", b"   "), ("x.docx", b"bad zip")])
def test_rejects_invalid_uploads(settings, filename, raw):
    with pytest.raises(ValueError):
        read_document(filename, raw, "x", settings)


def test_docx_expansion_limit(settings):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "x" * 2000)
    small = settings.model_copy(update={"max_docx_expanded_bytes": 1024})
    with pytest.raises(ValueError, match="giải nén"):
        read_document("x.docx", buffer.getvalue(), "x", small)


def test_tenant_isolation_filename_traversal_and_no_match(settings):
    bases = KnowledgeBases(settings)
    a, b = bases.for_tenant("a"), bases.for_tenant("b")
    a.ingest("../../secret.txt", "Thời hạn hoàn cước là 7 ngày".encode())
    assert a.snapshot.records[0]["filename"] == "secret.txt"
    assert not b.retrieve("hoàn cước")
    assert not a.retrieve("quasar neutrino gamma")


def test_config_change_requires_reindex(settings):
    KnowledgeBases(settings).for_tenant("a").ingest("x.txt", "Hoàn cước 7 ngày".encode())
    changed = settings.model_copy(update={"chunk_size": 256})
    with pytest.raises(ValueError, match="reindex"):
        KnowledgeBases(changed).for_tenant("a")


def test_failed_rebuild_does_not_publish_partial_document(settings, monkeypatch):
    kb = KnowledgeBases(settings).for_tenant("a")
    kb.ingest("good.txt", "Hoàn cước 7 ngày".encode())
    before = kb.snapshot.revision
    monkeypatch.setattr(kb, "_commit", lambda *args: (_ for _ in ()).throw(RuntimeError("provider failed")))
    with pytest.raises(RuntimeError):
        kb.ingest("new.txt", "Doanh thu 120 triệu đồng".encode())
    assert kb.snapshot.revision == before and len(kb.snapshot.records) == 1
    assert len(list(kb.raw_dir.iterdir())) == 1


def test_embedding_cache_reuses_vectors_and_separates_query_from_document(tmp_path):
    class CountingEmbedding(DemoHashEmbedding):
        calls: int = 0

        def _get_text_embedding(self, text):
            self.calls += 1
            return super()._get_text_embedding(text)

    inner = CountingEmbedding()
    cache = CachedEmbedding(inner, tmp_path / "cache.sqlite3", "m1")
    cache.get_text_embedding_batch(["hoàn cước", "hoàn cước"])
    assert inner.calls == 1
    cache.get_text_embedding_batch(["hoàn cước", "doanh thu"])
    assert inner.calls == 2
    reloaded = CachedEmbedding(inner, tmp_path / "cache.sqlite3", "m1")
    reloaded.get_text_embedding("hoàn cước")
    assert inner.calls == 2
    with __import__("sqlite3").connect(tmp_path / "cache.sqlite3") as db:
        before = db.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
    reloaded.get_query_embedding("hoàn cước")
    with __import__("sqlite3").connect(tmp_path / "cache.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM vectors").fetchone()[0] == before + 1


def test_live_mode_rejects_demo_embedding_and_missing_keys(tmp_path):
    with pytest.raises(ValueError):
        Settings(_env_file=None, demo_mode=False, data_dir=tmp_path)
    with pytest.raises(ValueError, match="demo-only"):
        Settings(_env_file=None, demo_mode=False, data_dir=tmp_path,
                 api_keys_json='{"1234567890123456":"a"}', llm_api_key="dummy", llm_model="real")
