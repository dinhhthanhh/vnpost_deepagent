"""FastMCP Server Entrypoint for VNPost Enterprise Assistant.

Supports both Stdio Transport (local subprocess isolation) and SSE Transport (remote distributed AI networks).
Enforces strict authentication and server-side tenant binding for SSE transport.
"""

import argparse
import hmac
import logging
from contextvars import ContextVar
from urllib.parse import parse_qs

from mcp.server.fastmcp import FastMCP
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings
from app.mcp.tools import register_postal_mcp_tools

logger = logging.getLogger(__name__)

# ContextVar lưu trữ tenant được xác thực từ tầng transport của MCP Server
current_mcp_tenant: ContextVar[str | None] = ContextVar("current_mcp_tenant", default=None)

# Khởi tạo FastMCP Server với tên thương hiệu bưu chính
mcp = FastMCP(
    name="vnpost-enterprise-mcp-server",
    instructions="Máy chủ công cụ và ngữ cảnh bưu chính quốc gia VNPost (Tra cứu vận đơn, định giá cước, tìm bưu cục, tạo đơn hàng).",
)

# Đăng ký các công cụ bưu chính
register_postal_mcp_tools(mcp)


class MCPServerAuthMiddleware:
    """Middleware xác thực định danh và ràng buộc tenant trên transport SSE của MCP Server."""

    def __init__(self, app: ASGIApp, settings: Settings | None = None):
        self.app = app
        self.settings = settings or Settings()

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        query_string = scope.get("query_string", b"").decode("utf-8")
        query_params = parse_qs(query_string)

        # Trích xuất API Key từ header hoặc query param (dành cho browser EventSource)
        api_key = (
            headers.get("x-api-key")
            or headers.get("authorization", "").replace("Bearer ", "").strip()
            or (query_params.get("api_key", [None])[0])
            or (query_params.get("token", [None])[0])
        )

        resolved_tenant: str | None = None
        if self.settings.api_keys:
            if not api_key:
                resp = JSONResponse(
                    {
                        "error": "Unauthorized: Yêu cầu cung cấp X-API-Key hoặc Bearer token cho kết nối MCP SSE"
                    },
                    status_code=401,
                )
                await resp(scope, receive, send)
                return

            for key, tenant in self.settings.api_keys.items():
                if hmac.compare_digest(key, api_key):
                    resolved_tenant = tenant
                    break

            if not resolved_tenant:
                resp = JSONResponse(
                    {
                        "error": "Forbidden: API key không hợp lệ hoặc không có quyền truy cập MCP SSE"
                    },
                    status_code=403,
                )
                await resp(scope, receive, send)
                return
        else:
            # Nếu chưa cấu hình api_keys, chỉ cho phép truy cập qua loopback/localhost
            client_host = scope.get("client", [""])[0] if scope.get("client") else ""
            if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
                resp = JSONResponse(
                    {
                        "error": "Forbidden: MCP SSE khi chưa cấu hình api_keys chỉ được phép chạy trên mạng cục bộ (127.0.0.1/localhost)."
                    },
                    status_code=403,
                )
                await resp(scope, receive, send)
                return
            resolved_tenant = "default"

        token = current_mcp_tenant.set(resolved_tenant)
        try:
            await self.app(scope, receive, send)
        finally:
            current_mcp_tenant.reset(token)


def create_authenticated_sse_app(
    mcp_instance: FastMCP | None = None, settings: Settings | None = None
) -> ASGIApp:
    """Tạo Starlette ASGI app cho MCP SSE có tích hợp middleware xác thực."""
    target_mcp = mcp_instance or mcp
    base_sse_app = target_mcp.sse_app()
    return MCPServerAuthMiddleware(base_sse_app, settings=settings)


# Đăng ký các tài nguyên ngữ cảnh tĩnh (MCP Resources)
@mcp.resource("vnpost://tariffs/domestic-2026")
def get_domestic_tariffs() -> str:
    """Biểu giá cước chuyển phát nhanh EMS và bưu kiện nội địa cơ bản năm 2026."""
    return (
        "Biểu cước VNPost 2026:\n"
        "- Vùng 1 (Nội tỉnh): 22.000 đ nấc 500g đầu, +3.500 đ mỗi 500g tiếp theo.\n"
        "- Vùng 2 (Nội miền): 32.000 đ nấc 500g đầu, +5.500 đ mỗi 500g tiếp theo.\n"
        "- Vùng 3 (Liên miền): 45.000 đ nấc 500g đầu, +8.500 đ mỗi 500g tiếp theo.\n"
        "Công thức thể tích cồng kềnh: (Dài x Rộng x Cao) / 6000."
    )


@mcp.resource("vnpost://contacts/hotline")
def get_postal_hotline() -> str:
    """Thông tin liên hệ đường dây nóng hỗ trợ khách hàng của VNPost."""
    return (
        "Tổng công ty Bưu điện Việt Nam (VNPost)\n"
        "Hotline Chăm sóc Khách hàng: 1900 54 54 81\n"
        "Website chính thức: https://vietnampost.vn\n"
        "Cổng tra cứu bưu gửi: https://vietnampost.vn/tra-cuu-hanh-trinh"
    )


def create_mcp_server() -> FastMCP:
    """Trả về phiên bản máy chủ FastMCP đã sẵn sàng."""
    return mcp


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chạy VNPost MCP Server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse"],
        help="Phương thức truyền thông: stdio (mặc định) hoặc sse",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Địa chỉ host khi chạy SSE (mặc định 127.0.0.1 - loopback an toàn)",
    )
    parser.add_argument("--port", type=int, default=8001, help="Cổng mạng khi chạy SSE")
    args = parser.parse_args()

    if args.transport == "sse":
        import uvicorn

        app = create_authenticated_sse_app(mcp)
        logger.info("Khởi chạy authenticated MCP SSE Server tại %s:%s", args.host, args.port)
        uvicorn.run(app, host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")
