import json

from fastapi.testclient import TestClient

from app.main import create_app

KEY_A, KEY_B = "test-key-a-1234567890", "test-key-b-1234567890"


def test_api_upload_chat_sse_and_tenant_authorization(settings):
    settings = settings.model_copy(update={"api_keys_json": json.dumps({KEY_A: "a", KEY_B: "b"}), "allow_anonymous_demo": False})
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").json()["upstream_status"] == "not_probed"
        assert client.get("/api/documents").status_code == 401
        ha, hb = {"X-API-Key": KEY_A}, {"X-API-Key": KEY_B}
        uploaded = client.post("/api/documents", headers=ha, files={"file": ("rules.txt", "Hoàn cước trong 7 ngày.".encode(), "text/plain")})
        assert uploaded.status_code == 201
        assert not client.get("/api/documents", headers=hb).json()["documents"]
        response = client.post("/api/chat", headers=ha, json={"message": "Hoàn cước bao lâu?"})
        assert response.status_code == 200 and response.json()["sources"]
        result = response.json()
        assert client.get("/api/replies/" + result["request_id"], headers=hb).status_code == 404
        assert not client.get("/api/sessions/" + result["session_id"], headers=hb).json()["messages"]
        stream = client.post("/api/chat/stream", headers=ha, json={"message": "Hoàn cước bao lâu?", "voice": True})
        assert "event: answer" in stream.text and "event: done" in stream.text
        assert stream.text.index("event: answer") < stream.text.index("event: speech_error")
        assert client.delete("/api/documents/" + uploaded.json()["id"], headers=hb).status_code == 404
        assert client.delete("/api/documents/" + uploaded.json()["id"], headers=ha).status_code == 200


def test_api_rejects_invalid_inputs_and_limits(settings):
    settings = settings.model_copy(update={"max_upload_bytes": 1024})
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/chat", json={"message": "   "}).status_code == 422
        assert client.post("/api/chat", json={"message": "hi", "session_id": "../bad"}).status_code == 422
        assert client.post("/api/documents", files={"file": ("big.txt", b"a" * 1025)}).status_code == 413
        assert client.post("/api/documents", files={"file": ("legacy.doc", b"a")}).status_code == 422
        assert client.get("/api/audio/" + "a" * 32).status_code == 404
        assert client.post("/api/tts", json={"text": "hi"}).status_code == 502
        assert client.get("/api/tts/voices").json()["enabled"] is False


def test_anonymous_demo_blocked_for_remote_peers(settings):
    with TestClient(create_app(settings), client=("203.0.113.1", 1234)) as client:
        assert client.get("/api/documents").status_code == 401
