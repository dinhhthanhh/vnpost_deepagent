"""FastMCP Server Entrypoint for VNPost Enterprise Assistant.

Supports both Stdio Transport (local subprocess isolation) and SSE Transport (remote distributed AI networks).
"""
import argparse
import sys
from mcp.server.fastmcp import FastMCP

from app.mcp.tools import register_postal_mcp_tools

# Khởi tạo FastMCP Server với tên thương hiệu bưu chính
mcp = FastMCP(
    name="vnpost-enterprise-mcp-server",
    instructions="Máy chủ công cụ và ngữ cảnh bưu chính quốc gia VNPost (Tra cứu vận đơn, định giá cước, tìm bưu cục, tạo đơn hàng).",
)

# Đăng ký các công cụ bưu chính
register_postal_mcp_tools(mcp)

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
    parser.add_argument("--transport", default="stdio", choices=["stdio", "sse"], help="Phương thức truyền thông: stdio hoặc sse")
    parser.add_argument("--host", default="127.0.0.1", help="Địa chỉ host khi chạy SSE")
    parser.add_argument("--port", type=int, default=8001, help="Cổng mạng khi chạy SSE")
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
