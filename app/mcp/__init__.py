"""VNPost Model Context Protocol (MCP) Module.

Exposes postal actions and resources to standard MCP clients (Stdio & SSE/HTTP transports).
"""
from app.mcp.server import mcp, create_mcp_server

__all__ = ["mcp", "create_mcp_server"]
