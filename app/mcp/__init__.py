"""VNPost Model Context Protocol (MCP) Module.

Exposes postal actions and resources to standard MCP clients (Stdio & SSE/HTTP transports).
"""

from app.mcp.clients import (
    ExternalMCPManager,
    MCPClient,
    MCPConnectionError,
    MCPToolWrapper,
    SSEMCPClient,
    STDIOMCPClient,
    StreamableHTTPMCPClient,
    validate_mcp_command,
    validate_mcp_url,
)
from app.mcp.server import create_mcp_server, mcp

__all__ = [
    "ExternalMCPManager",
    "MCPClient",
    "MCPConnectionError",
    "MCPToolWrapper",
    "SSEMCPClient",
    "STDIOMCPClient",
    "StreamableHTTPMCPClient",
    "create_mcp_server",
    "mcp",
    "validate_mcp_command",
    "validate_mcp_url",
]
