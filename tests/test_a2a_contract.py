"""Contract tests for A2A (Agent-to-Agent) client-server protocol.

Tests A2A Card resolution, JSON-RPC SendMessage, and CustomA2AClient roundtrip.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from a2a.client import A2ACardResolver, ClientCallContext, ClientConfig, create_client
from a2a.types import Message, Part, Role, SendMessageRequest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.a2a_client import CustomA2AClient
from app.core.config import Settings


def _create_mock_service():
    service = MagicMock()
    mock_resp = MagicMock()
    mock_resp.reply = "Mipo VNPost: Chào bạn, tôi có thể hỗ trợ tra cứu bưu gửi và tính cước."
    mock_resp.answer = mock_resp.reply
    service.chat = AsyncMock(return_value=mock_resp)
    service.warmup = AsyncMock()
    service.close = AsyncMock()
    return service


def test_a2a_agent_card_endpoint_and_resolution():
    """Kiểm tra endpoint /.well-known/agent-card.json phục vụ AgentCard chuẩn A2A spec và A2ACardResolver phân giải thành công."""
    settings = Settings(checkpointer_enabled=False, demo_mode=True)
    app = create_app(settings=settings, service=_create_mock_service())

    # 1. Kiểm tra qua TestClient thông thường
    with TestClient(app) as test_client:
        resp = test_client.get("/.well-known/agent-card.json")
        assert resp.status_code == 200
        card_dict = resp.json()
        assert card_dict["name"] == "vnpost-mipo-agent"
        assert card_dict["version"] == "1.1.0"
        assert len(card_dict.get("skills", [])) == 5
        assert len(card_dict.get("supportedInterfaces", [])) >= 1


@pytest.mark.asyncio
async def test_a2a_card_resolver_and_client_roundtrip():
    """Kiểm tra A2ACardResolver và create_client gọi endpoint /a2a qua JSON-RPC theo đúng A2A SDK 1.2.3."""
    settings = Settings(checkpointer_enabled=False, demo_mode=True)
    mock_svc = _create_mock_service()
    app = create_app(settings=settings, service=mock_svc)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        # 1. Khám phá tác tử qua A2ACardResolver
        resolver = A2ACardResolver(httpx_client=http_client, base_url="http://testserver")
        card = await resolver.get_agent_card()
        assert card.name == "vnpost-mipo-agent"
        assert len(card.skills) == 5

        # 2. Khởi tạo client A2A chuẩn SDK
        client_cfg = ClientConfig(streaming=False, httpx_client=http_client)
        client = await create_client(agent=card, client_config=client_cfg)

        # 3. Gửi thông điệp SendMessage theo A2A Protocol
        req = SendMessageRequest(
            message=Message(
                message_id="msg-test-001",
                role=Role.ROLE_USER,
                parts=[Part(text="Tra cứu bưu gửi EB123456789VN")],
            )
        )
        ctx = ClientCallContext(service_parameters={"A2A-Version": "1.0"})

        received_parts = []
        async for item in client.send_message(req, context=ctx):
            msg = getattr(item, "message", None) or item
            if hasattr(msg, "parts"):
                for part in msg.parts:
                    if part.text:
                        received_parts.append(part.text)

        full_reply = "".join(received_parts)
        assert len(full_reply) > 0
        assert "Mipo VNPost" in full_reply
        mock_svc.chat.assert_called_once()


@pytest.mark.asyncio
async def test_custom_a2a_client_integration():
    """Kiểm tra lớp CustomA2AClient của ứng dụng gọi thành công remote agent theo đúng A2A spec."""
    settings = Settings(checkpointer_enabled=False, demo_mode=True)
    mock_svc = _create_mock_service()
    app = create_app(settings=settings, service=mock_svc)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        a2a_client = await CustomA2AClient.create(
            a2a_server_urls=["http://testserver"],
            http_client=http_client,
        )
        assert "vnpost-mipo-agent" in a2a_client.agents

        reply = await a2a_client.call_remote_agent(
            agent_name="vnpost-mipo-agent",
            message="Xin chào Mipo VNPost",
        )
        assert "Mipo VNPost" in reply
        mock_svc.chat.assert_called_once()
        await a2a_client.close()


def test_a2a_jsonrpc_direct_protocol():
    """Kiểm tra gọi trực tiếp JSON-RPC 2.0 SendMessage vào endpoint /a2a."""
    settings = Settings(checkpointer_enabled=False, demo_mode=True)
    mock_svc = _create_mock_service()
    app = create_app(settings=settings, service=mock_svc)

    with TestClient(app) as client:
        # Gọi hợp lệ với A2A-Version: 1.0
        rpc_payload = {
            "jsonrpc": "2.0",
            "id": "req-1",
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": "msg-123",
                    "role": "ROLE_USER",
                    "parts": [{"text": "Hỏi giá cước chuyển phát"}],
                }
            },
        }
        res = client.post("/a2a", json=rpc_payload, headers={"A2A-Version": "1.0"})
        assert res.status_code == 200
        data = res.json()
        assert data.get("jsonrpc") == "2.0"
        assert "result" in data
        assert data["result"]["message"]["role"] == "ROLE_AGENT"
        assert "Mipo VNPost" in data["result"]["message"]["parts"][0]["text"]
        mock_svc.chat.assert_called_once()

        # Gọi phương thức không tồn tại -> -32601 Method not found
        bad_rpc = {
            "jsonrpc": "2.0",
            "id": "req-2",
            "method": "NonExistentMethod",
            "params": {},
        }
        res_bad = client.post("/a2a", json=bad_rpc, headers={"A2A-Version": "1.0"})
        assert res_bad.status_code == 200
        data_bad = res_bad.json()
        assert "error" in data_bad
        assert data_bad["error"]["code"] == -32601
