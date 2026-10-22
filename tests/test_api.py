import json

from fastapi.testclient import TestClient

from app.api.main import create_app

KEY_A, KEY_B = "test-key-a-1234567890", "test-key-b-1234567890"


def test_api_upload_chat_sse_and_tenant_authorization(settings):
    settings = settings.model_copy(
        update={
            "api_keys_json": json.dumps({KEY_A: "a", KEY_B: "b"}),
            "allow_anonymous_demo": False,
        }
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").json()["upstream_status"] == "not_probed"
        assert client.get("/api/documents").status_code == 401
        ha, hb = {"X-API-Key": KEY_A}, {"X-API-Key": KEY_B}
        uploaded = client.post(
            "/api/documents",
            headers=ha,
            files={"file": ("rules.txt", "Hoàn cước trong 7 ngày.".encode(), "text/plain")},
        )
        assert uploaded.status_code == 201
        assert not client.get("/api/documents", headers=hb).json()["documents"]
        response = client.post("/api/chat", headers=ha, json={"message": "Hoàn cước bao lâu?"})
        assert response.status_code == 200 and response.json()["sources"]
        result = response.json()
        assert client.get("/api/replies/" + result["request_id"], headers=hb).status_code == 404
        assert not client.get("/api/sessions/" + result["session_id"], headers=hb).json()[
            "messages"
        ]

        # Check sessions listing & isolation
        sessions_a = client.get("/api/sessions", headers=ha).json()["sessions"]
        assert any(s["id"] == result["session_id"] for s in sessions_a)
        assert not client.get("/api/sessions", headers=hb).json()["sessions"]

        stream = client.post(
            "/api/chat/stream", headers=ha, json={"message": "Hoàn cước bao lâu?", "voice": True}
        )
        assert "event: answer" in stream.text and "event: done" in stream.text
        assert stream.text.index("event: answer") < stream.text.index("event: speech_error")
        assert (
            client.delete("/api/documents/" + uploaded.json()["id"], headers=hb).status_code == 404
        )
        assert (
            client.delete("/api/documents/" + uploaded.json()["id"], headers=ha).status_code == 200
        )

        # Check session deletion
        del_res = client.delete("/api/sessions/" + result["session_id"], headers=ha)
        assert del_res.status_code == 200
        assert not any(
            s["id"] == result["session_id"]
            for s in client.get("/api/sessions", headers=ha).json()["sessions"]
        )


def test_api_rejects_invalid_inputs_and_limits(settings):
    settings = settings.model_copy(update={"max_upload_bytes": 1024})
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/chat", json={"message": "   "}).status_code == 422
        assert (
            client.post("/api/chat", json={"message": "hi", "session_id": "../bad"}).status_code
            == 422
        )
        assert (
            client.post("/api/documents", files={"file": ("big.txt", b"a" * 1025)}).status_code
            == 413
        )
        assert (
            client.post("/api/documents", files={"file": ("legacy.doc", b"a")}).status_code == 422
        )
        assert client.get("/api/audio/" + "a" * 32).status_code == 404
        assert client.post("/api/tts", json={"text": "hi"}).status_code == 502
        assert client.get("/api/tts/voices").json()["enabled"] is False


def test_anonymous_demo_blocked_for_remote_peers(settings):
    with TestClient(create_app(settings), client=("203.0.113.1", 1234)) as client:
        assert client.get("/api/documents").status_code == 401


def test_verified_upload_requires_admin_key_and_official_host(settings):
    settings = settings.model_copy(update={"trusted_ingest_key": "source-admin-secret"})
    with TestClient(create_app(settings)) as client:
        payload = {"file": ("source.txt", b"Official evidence", "text/plain")}
        assert (
            client.post(
                "/api/documents/verified?source_url=https://vietnampost.vn/vi", files=payload
            ).status_code
            == 403
        )
        headers = {"X-Source-Admin-Key": "source-admin-secret"}
        rejected = client.post(
            "/api/documents/verified?source_url=https://example.com/",
            headers=headers,
            files=payload,
        )
        assert rejected.status_code == 422
        accepted = client.post(
            "/api/documents/verified?source_url=https://vietnampost.vn/vi",
            headers=headers,
            files=payload,
        )
        assert accepted.status_code == 201
        assert accepted.json()["authority"] == "official_public"
        regular = client.post(
            "/api/documents", files={"file": ("note.txt", b"Untrusted note", "text/plain")}
        )
        assert regular.status_code == 201
        assert regular.json()["authority"] == "user_upload"
