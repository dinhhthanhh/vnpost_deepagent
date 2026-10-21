"""MCP Client module supporting STDIO, SSE, and Streamable HTTP transports.

Enables VNPost Deep Agent or its subagents to connect to external MCP servers
and dynamically fetch and execute tools.
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Any, Callable

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
try:
    from mcp.client.streamable_http import streamablehttp_client
except ImportError:
    streamablehttp_client = None

from app.core.telemetry import add_request_baggage

logger = logging.getLogger(__name__)


class MCPConnectionError(Exception):
    """Raised when connection to an MCP server fails."""
    pass


class MCPToolWrapper:
    """Wrapper encapsulating MCP tool schema and callable invocation."""

    def __init__(self, tool_name: str, tool_define: dict[str, Any], call_fn: Callable) -> None:
        self.tool_name = tool_name
        self.tool_define = tool_define
        self.call_fn = call_fn

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.call_fn(*args, **kwargs)


class MCPClient:
    """Base client class for connecting to MCP servers."""

    @classmethod
    async def create(cls, *args: Any, **kwargs: Any) -> "MCPClient":
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

    async def call_tool(self, name: str, arguments: dict[str, Any], meta: dict[str, Any] | None = None) -> str:
        forwarded_meta = {k: v for k, v in (meta or {}).items() if not k.startswith("_")}
        result = await self._session.call_tool(name, arguments, meta=forwarded_meta)
        if result.content and hasattr(result.content[0], "text"):
            return result.content[0].text
        return str(result.content)

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            if hasattr(self, "_session_cm") and self._session_cm:
                await self._session_cm.__aexit__(None, None, None)
            if hasattr(self, "_client_cm") and self._client_cm:
                await self._client_cm.__aexit__(None, None, None)


class STDIOMCPClient(MCPClient):
    """MCP Client connecting over STDIO."""

    def __init__(self, command: str, args: list[str], timeout: float | None = None) -> None:
        self.command = command
        self.args = args
        self.server_params = StdioServerParameters(
            command=command,
            args=args,
            env=os.environ.copy(),
        )
        self.timeout = timedelta(seconds=timeout) if timeout is not None else None
        self._session = None
        self._read = None
        self._write = None
        self._client_cm = None
        self._session_cm = None

    async def connect(self) -> None:
        self._client_cm = stdio_client(self.server_params)
        self._read, self._write = await self._client_cm.__aenter__()
        self._session_cm = ClientSession(self._read, self._write, read_timeout_seconds=self.timeout)
        self._session = await self._session_cm.__aenter__()
        try:
            await self._session.initialize()
        except Exception as exc:
            await self.close()
            raise MCPConnectionError(f"Failed to connect to STDIO MCP server ({self.command}): {exc}") from exc


class SSEMCPClient(MCPClient):
    """MCP Client connecting over SSE (Server-Sent Events)."""

    def __init__(self, mcp_server_url: str, timeout: float | None = None) -> None:
        self.mcp_server_url = mcp_server_url
        self.timeout = timedelta(seconds=timeout) if timeout is not None else None
        self._session = None
        self._read = None
        self._write = None
        self._client_cm = None
        self._session_cm = None

    async def connect(self) -> None:
        self._client_cm = sse_client(self.mcp_server_url)
        self._read, self._write = await self._client_cm.__aenter__()
        self._session_cm = ClientSession(self._read, self._write, read_timeout_seconds=self.timeout)
        self._session = await self._session_cm.__aenter__()
        try:
            await self._session.initialize()
        except Exception as exc:
            await self.close()
            raise MCPConnectionError(f"Failed to connect to SSE MCP server ({self.mcp_server_url}): {exc}") from exc


class StreamableHTTPMCPClient(MCPClient):
    """MCP Client connecting over Streamable HTTP."""

    def __init__(self, mcp_server_url: str, timeout: float | None = None) -> None:
        if streamablehttp_client is None:
            raise ImportError("streamablehttp_client is not available in the installed mcp package.")
        self.mcp_server_url = mcp_server_url
        self.timeout = timedelta(seconds=timeout) if timeout is not None else None
        self._session = None
        self._read = None
        self._write = None
        self._client_cm = None
        self._session_cm = None

    async def connect(self) -> None:
        self._client_cm = streamablehttp_client(self.mcp_server_url)
        self._read, self._write, _ = await self._client_cm.__aenter__()
        self._session_cm = ClientSession(self._read, self._write, read_timeout_seconds=self.timeout)
        self._session = await self._session_cm.__aenter__()
        try:
            await self._session.initialize()
        except Exception as exc:
            await self.close()
            raise MCPConnectionError(f"Failed to connect to HTTP MCP server ({self.mcp_server_url}): {exc}") from exc
