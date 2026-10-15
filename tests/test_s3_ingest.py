import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import create_app


def test_s3_ingest_missing_params(settings):
    with TestClient(create_app(settings)) as client:
        resp = client.post("/api/documents/s3", json={})
        assert resp.status_code == 422


def test_s3_ingest_invalid_scheme(settings):
    with TestClient(create_app(settings)) as client:
        resp = client.post("/api/documents/s3", json={"url": "ftp://example.com/file.pdf"})
        assert resp.status_code == 422


def test_s3_ingest_presigned_url_success(settings):
    target_url = "https://s3.amazonaws.com/vnpost-bucket/quy_trinh.txt?AWSAccessKeyId=test"
    with respx.mock(assert_all_called=False) as router:
        router.get(target_url).mock(
            return_value=httpx.Response(200, content=b"# Quy trinh chuyen phat\nNoi dung huong dan chuyen phat nhanh")
        )
        with TestClient(create_app(settings)) as client:
            resp = client.post("/api/documents/s3", json={
                "url": target_url,
                "authority": "official_public",
                "source_url": "https://vietnampost.vn/quy-trinh"
            })
            assert resp.status_code == 201
            data = resp.json()
            assert data["filename"] == "quy_trinh.txt"
            assert data["authority"] == "official_public"


def test_s3_ingest_rejects_ssrf(settings):
    with TestClient(create_app(settings)) as client:
        resp = client.post("/api/documents/s3", json={"url": "http://127.0.0.1:8000/internal"})
        assert resp.status_code == 422
        assert "SSRF" in resp.text or "nội bộ" in resp.text


def test_s3_ingest_domain_allowlist_enforcement(settings):
    settings.allowed_s3_domains = "s3.vnpost.vn,vnpost-bucket.s3.ap-southeast-1.amazonaws.com"
    target_url = "https://unauthorized-bucket.s3.amazonaws.com/test.pdf"
    with TestClient(create_app(settings)) as client:
        resp = client.post("/api/documents/s3", json={"url": target_url})
        assert resp.status_code == 422
        assert "danh sách cho phép" in resp.text
