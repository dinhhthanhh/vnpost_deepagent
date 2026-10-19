import pytest

from app.schemas import ChatRequest


@pytest.mark.parametrize("bad_url", [
    "http://10.0.0.5/test.png",
    "http://192.168.1.10/test.png",
    "http://169.254.169.254/latest/meta-data",
    "http://[::ffff:127.0.0.1]/test.png",
    "http://[::ffff:10.0.0.5]/test.png",
    "http://127.0.0.1/test.png",
    "http://localhost/test.png",
    "http://100.64.0.1/test.png",
    "http://100.127.255.254/test.png",
])
def test_ssrf_rejects_internal_ips(bad_url):
    with pytest.raises(ValueError, match="mạng nội bộ|máy chủ nội bộ"):
        ChatRequest(message="test", image=bad_url)

def test_ssrf_allows_valid_data_url():
    req = ChatRequest(message="test", image="data:image/png;base64,iVBORw0KGgo=")
    assert req.image.startswith("data:image/")


@pytest.mark.parametrize("bad_url", [
    "http://10.0.0.5/doc.pdf",
    "http://127.0.0.1:8000/doc.pdf",
    "http://169.254.169.254/latest/meta-data",
    "http://localhost:8000/doc.pdf",
    "http://[::1]/doc.pdf",
])
def test_s3_ingest_schema_ssrf_rejects_internal_ips(bad_url):
    from app.schemas import S3IngestRequest
    with pytest.raises(ValueError, match="mạng nội bộ|máy chủ nội bộ"):
        S3IngestRequest(url=bad_url)
