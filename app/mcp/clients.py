"""MCP Client module supporting STDIO, SSE, and Streamable HTTP transports.

Enables VNPost Deep Agent or its subagents to connect to external MCP servers
and dynamically fetch and execute tools following strict allowlists, authentication,
and lifecycle management.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import pathlib
import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client

try:
    from mcp.client.streamable_http import streamablehttp_client
except ImportError:
    streamablehttp_client = None

logger = logging.getLogger(__name__)

# Dangerous metadata / internal IP addresses to reject unconditionally
BLOCKED_NETWORKS = {
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local / AWS / GCP / Azure metadata
    ipaddress.ip_network("0.0.0.0/8"),  # Current network
    ipaddress.ip_network("100.64.0.0/10"),  # Carrier-grade NAT
}


class MCPConnectionError(Exception):
    """Raised when connection to an MCP server fails or is rejected by security policy."""

    pass


def validate_mcp_url(url: str, allowed_hosts: set[str] | list[str] | None = None) -> None:
    """Xác thực URL của remote MCP server chống SSRF và truy cập trái phép metadata.

    Chỉ cho phép HTTP/HTTPS, kiểm tra hostname theo allowlist và chặn các IP nhạy cảm.
    """
    if not url or not isinstance(url, str):
        raise MCPConnectionError("MCP URL không hợp lệ: chuỗi rỗng")

    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise MCPConnectionError(
            f"Giao thức URL không an toàn: '{parsed.scheme}'. Chỉ chấp nhận 'http' hoặc 'https'."
        )

    hostname = (parsed.hostname or "").lower().strip()
    if not hostname:
        raise MCPConnectionError(f"Không thể xác định hostname từ MCP URL: {url}")

    # Chặn direct metadata hostnames
    if hostname in {"metadata.google.internal", "instance-data"}:
        raise MCPConnectionError(f"Truy cập vào cloud metadata host '{hostname}' bị nghiêm cấm.")

    # Kiểm tra IP nguy hiểm nếu hostname là IP
    try:
        ip_obj = ipaddress.ip_address(hostname)
        for net in BLOCKED_NETWORKS:
            if ip_obj in net:
                raise MCPConnectionError(
                    f"Truy cập vào dải IP nhạy cảm '{hostname}' bị từ chối bởi chính sách an toàn."
                )
    except ValueError:
        pass  # Domain name thông thường

    if allowed_hosts is not None:
        normalized_allowed = {h.lower().strip() for h in allowed_hosts if h.strip()}
        matched = False
        for allowed in normalized_allowed:
            if hostname == allowed:
                matched = True
                break
            if allowed.startswith(".") and hostname.endswith(allowed):
                matched = True
                break
            if hostname.endswith("." + allowed):
                matched = True
                break
        if not matched:
            raise MCPConnectionError(
                f"MCP URL hostname '{hostname}' không nằm trong allowlist được cấp phép: {sorted(normalized_allowed)}"
            )


def validate_mcp_command(
    command: str, allowed_commands: set[str] | list[str] | None = None
) -> None:
    """Xác thực binary command của STDIO MCP client để chống Command Injection và RCE.

    Chỉ cho phép binary basename nằm trong whitelist và không chứa ký tự shell nguy hiểm.
    """
    if not command or not isinstance(command, str):
        raise MCPConnectionError("MCP command không hợp lệ: chuỗi rỗng")

    # Chặn shell metacharacters
    if re.search(r"[;&|`$<>\n\r]", command):
        raise MCPConnectionError(
            f"MCP command '{command}' chứa ký tự shell không an toàn, nguy cơ command injection."
        )

    # Lấy tên file thực thi cơ sở
    base_name = pathlib.Path(command).name.lower()
    if base_name.endswith(".exe"):
        base_name = base_name[:-4]

    if allowed_commands is not None:
        normalized_allowed = {c.lower().strip() for c in allowed_commands if c.strip()}
        if base_name not in normalized_allowed:
            raise MCPConnectionError(
                f"Lệnh MCP '{base_name}' không nằm trong whitelist cho phép: {sorted(normalized_allowed)}"
            )


class MCPToolWrapper:
    """Wrapper encapsulating MCP tool schema and callable invocation."""

    def __init__(self, tool_name: str, tool_define: dict[str, Any], call_fn: Callable) -> None:
        self.tool_name = tool_name
        self.tool_define = tool_define
        self.call_fn = call_fn

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.call_fn(*args, **kwargs)

    def to_langchain_tool(self) -> Any:
        """Chuyển đổi wrapper sang StructuredTool của LangChain cho Sub-agents sử dụng."""
        try:
            from langchain_core.tools import StructuredTool

            async def _arun(**kwargs: Any) -> str:
                return await self.call_fn(arguments=kwargs)

            def _run(**kwargs: Any) -> str:
                return asyncio.run(self.call_fn(arguments=kwargs))

            return StructuredTool.from_function(
                func=_run,
                coroutine=_arun,
                name=self.tool_name,
                description=self.tool_define.get("description", "")
                or f"External MCP tool {self.tool_name}",
            )
        except Exception as exc:
            logger.warning(
                "Không thể chuyển đổi tool '%s' sang StructuredTool: %s", self.tool_name, exc
            )
            return None


class MCPClient:
    """Base client class for connecting to MCP servers."""

    @classmethod
    async def create(cls, *args: Any, **kwargs: Any) -> MCPClient:
        """Factory method to initialize and connect the MCP client."""
        self = cls(*args, **kwargs)
        self.closed = False
        await self.connect()

        tool_list = await self.list_tools()
        self.tools = {
            tool.name: MCPToolWrapper(
                tool_name=tool.name,
                tool_define={
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema or {},
                    "strict": True,
                },
                call_fn=lambda arguments, name=tool.name, meta=None: self.call_tool(
                    name=name, arguments=arguments, meta=meta
                ),
            )
            for tool in tool_list.tools
        }
        return self

    async def connect(self) -> None:
        raise NotImplementedError

    async def list_tools(self) -> Any:
        return await self._session.list_tools()

    async def call_tool(
        self, name: str, arguments: dict[str, Any], meta: dict[str, Any] | None = None
    ) -> str:
        forwarded_meta = {k: v for k, v in (meta or {}).items() if not k.startswith("_")}
        result = await self._session.call_tool(name, arguments, meta=forwarded_meta)
        if result.content and hasattr(result.content[0], "text"):
            return result.content[0].text
        return str(result.content)

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            if hasattr(self, "_session_cm") and self._session_cm:
                try:
                    await self._session_cm.__aexit__(None, None, None)
                except Exception as exc:
                    logger.debug("Exception closing session: %s", exc)
            if hasattr(self, "_client_cm") and self._client_cm:
                try:
                    await self._client_cm.__aexit__(None, None, None)
                except Exception as exc:
                    logger.debug("Exception closing transport: %s", exc)


class STDIOMCPClient(MCPClient):
    """MCP Client connecting over STDIO."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        timeout: float | None = None,
        allowed_commands: set[str] | list[str] | None = None,
    ) -> None:
        self.command = command
        self.args = args or []
        self.allowed_commands = allowed_commands
        validate_mcp_command(self.command, self.allowed_commands)

        self.server_params = StdioServerParameters(
            command=command,
            args=self.args,
            env=os.environ.copy(),
        )
        self.timeout = timedelta(seconds=timeout) if timeout is not None else None
        self._session = None
        self._read = None
        self._write = None
        self._client_cm = None
        self._session_cm = None

    async def connect(self) -> None:
        validate_mcp_command(self.command, self.allowed_commands)
        self._client_cm = stdio_client(self.server_params)
        self._read, self._write = await self._client_cm.__aenter__()
        self._session_cm = ClientSession(self._read, self._write, read_timeout_seconds=self.timeout)
        self._session = await self._session_cm.__aenter__()
        try:
            await self._session.initialize()
        except Exception as exc:
            await self.close()
            raise MCPConnectionError(
                f"Failed to connect to STDIO MCP server ({self.command}): {exc}"
            ) from exc


class SSEMCPClient(MCPClient):
    """MCP Client connecting over SSE (Server-Sent Events) with headers and auth support."""

    def __init__(
        self,
        mcp_server_url: str,
        headers: dict[str, Any] | None = None,
        auth_token: str | None = None,
        timeout: float | None = None,
        allowed_hosts: set[str] | list[str] | None = None,
    ) -> None:
        self.mcp_server_url = mcp_server_url
        self.headers = dict(headers or {})
        if auth_token and "Authorization" not in self.headers:
            self.headers["Authorization"] = f"Bearer {auth_token}"
        self.allowed_hosts = allowed_hosts
        validate_mcp_url(self.mcp_server_url, self.allowed_hosts)

        self.timeout_val = timeout if timeout is not None else 10.0
        self.timeout = timedelta(seconds=self.timeout_val)
        self._session = None
        self._read = None
        self._write = None
        self._client_cm = None
        self._session_cm = None

    async def connect(self) -> None:
        validate_mcp_url(self.mcp_server_url, self.allowed_hosts)
        self._client_cm = sse_client(
            self.mcp_server_url,
            headers=self.headers,
            timeout=self.timeout_val,
        )
        self._read, self._write = await self._client_cm.__aenter__()
        self._session_cm = ClientSession(self._read, self._write, read_timeout_seconds=self.timeout)
        self._session = await self._session_cm.__aenter__()
        try:
            await self._session.initialize()
        except Exception as exc:
            await self.close()
            raise MCPConnectionError(
                f"Failed to connect to SSE MCP server ({self.mcp_server_url}): {exc}"
            ) from exc


class StreamableHTTPMCPClient(MCPClient):
    """MCP Client connecting over Streamable HTTP with headers and auth support."""

    def __init__(
        self,
        mcp_server_url: str,
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        timeout: float | None = None,
        allowed_hosts: set[str] | list[str] | None = None,
    ) -> None:
        if streamablehttp_client is None:
            raise ImportError(
                "streamablehttp_client is not available in the installed mcp package."
            )
        self.mcp_server_url = mcp_server_url
        self.headers = dict(headers or {})
        if auth_token and "Authorization" not in self.headers:
            self.headers["Authorization"] = f"Bearer {auth_token}"
        self.allowed_hosts = allowed_hosts
        validate_mcp_url(self.mcp_server_url, self.allowed_hosts)

        self.timeout_val = timeout if timeout is not None else 30.0
        self.timeout = timedelta(seconds=self.timeout_val)
        self._session = None
        self._read = None
        self._write = None
        self._client_cm = None
        self._session_cm = None

    async def connect(self) -> None:
        validate_mcp_url(self.mcp_server_url, self.allowed_hosts)
        self._client_cm = streamablehttp_client(
            self.mcp_server_url,
            headers=self.headers,
            timeout=self.timeout_val,
        )
        self._read, self._write, _ = await self._client_cm.__aenter__()
        self._session_cm = ClientSession(self._read, self._write, read_timeout_seconds=self.timeout)
        self._session = await self._session_cm.__aenter__()
        try:
            await self._session.initialize()
        except Exception as exc:
            await self.close()
            raise MCPConnectionError(
                f"Failed to connect to HTTP MCP server ({self.mcp_server_url}): {exc}"
            ) from exc


class ExternalMCPManager:
    """Quản lý vòng đời (lifecycle), xác thực và allowlist các External MCP Client."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.clients: dict[str, MCPClient] = {}
        self.tools: dict[str, MCPToolWrapper] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Khởi tạo và kết nối an toàn tới danh sách external MCP servers."""
        if self._initialized:
            return
        self._initialized = True

        servers = getattr(self.settings, "external_mcp_servers", [])
        if not servers:
            return

        allowed_hosts = getattr(self.settings, "mcp_allowed_hosts", {"127.0.0.1", "localhost"})
        allowed_commands = getattr(
            self.settings, "mcp_allowed_commands", {"python", "python3", "uvx", "npx"}
        )

        for srv in servers:
            if not isinstance(srv, dict):
                continue
            name = srv.get("name") or f"mcp_{len(self.clients) + 1}"
            transport = srv.get("transport", "sse").lower()
            auth_token = srv.get("auth_token") or ""
            env_token_var = srv.get("auth_token_env")
            if env_token_var and os.environ.get(env_token_var):
                auth_token = os.environ[env_token_var]

            headers = dict(srv.get("headers") or {})
            if auth_token and "Authorization" not in headers:
                headers["Authorization"] = f"Bearer {auth_token}"

            try:
                client = None
                if transport == "sse":
                    url = srv.get("url", "")
                    validate_mcp_url(url, allowed_hosts)
                    client = await SSEMCPClient.create(
                        mcp_server_url=url,
                        headers=headers,
                        allowed_hosts=allowed_hosts,
                    )
                elif transport == "stdio":
                    cmd = srv.get("command", "")
                    args = srv.get("args", [])
                    validate_mcp_command(cmd, allowed_commands)
                    client = await STDIOMCPClient.create(
                        command=cmd,
                        args=args,
                        allowed_commands=allowed_commands,
                    )
                elif transport in {"http", "streamable_http"}:
                    url = srv.get("url", "")
                    validate_mcp_url(url, allowed_hosts)
                    client = await StreamableHTTPMCPClient.create(
                        mcp_server_url=url,
                        headers=headers,
                        allowed_hosts=allowed_hosts,
                    )
                else:
                    logger.warning(
                        "Giao thức MCP transport không được hỗ trợ: '%s' cho server '%s'",
                        transport,
                        name,
                    )
                    continue

                if client:
                    self.clients[name] = client
                    for tool_name, tool_wrapper in client.tools.items():
                        namespaced_name = (
                            f"{name}_{tool_name}" if tool_name in self.tools else tool_name
                        )
                        self.tools[namespaced_name] = tool_wrapper
                    logger.info(
                        "Đã kết nối external MCP server '%s' (%s) thành công với %d tools",
                        name,
                        transport,
                        len(client.tools),
                    )
            except Exception as exc:
                logger.warning(
                    "Không thể kết nối tới external MCP server '%s' (%s): %s",
                    name,
                    transport,
                    exc,
                )

    def get_tools(self) -> list[MCPToolWrapper]:
        """Trả về toàn bộ công cụ thu thập được từ external MCP servers."""
        return list(self.tools.values())

    def get_langchain_tools(self) -> list[Any]:
        """Chuyển đổi toàn bộ external MCP tools sang StructuredTool."""
        result = []
        for wrapper in self.tools.values():
            lc_tool = wrapper.to_langchain_tool()
            if lc_tool is not None:
                result.append(lc_tool)
        return result

    async def close(self) -> None:
        """Đóng toàn bộ session kết nối an toàn và giải phóng tài nguyên."""
        for name, client in list(self.clients.items()):
            try:
                await client.close()
                logger.debug("Đã đóng kết nối MCP client '%s'", name)
            except Exception as exc:
                logger.warning("Lỗi đóng MCP client '%s': %s", name, exc)
        self.clients.clear()
        self.tools.clear()
        self._initialized = False
