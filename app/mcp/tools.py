"""FastMCP Tools Definition for VNPost Enterprise Assistant.

Standardizes postal operations into MCP Tools with full JSON Schema validation.
"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from app.domain.postal_services import (
    find_nearest_post_offices,
    lookup_postal_office,
    track_postal_item,
)
from app.agents.postal_actions import (
    cancel_booking,
    cancel_complaint,
    cancel_draft_booking,
    cancel_draft_complaint,
    confirm_booking,
    confirm_complaint,
    create_draft_booking,
    create_draft_complaint,
    list_my_orders,
    update_draft_booking,
    update_draft_complaint,
)


def register_postal_mcp_tools(mcp: FastMCP) -> None:
    """Đăng ký toàn bộ công cụ nghiệp vụ bưu chính vào máy chủ FastMCP."""

    @mcp.tool()
    def tra_cuu_buu_gui(item_code: str, ctx: Context | None = None) -> str:
        """Tra cứu hành trình và trạng thái bưu phẩm bưu kiện VNPost theo mã vận đơn 13 ký tự (UPU: EB...VN, CP...VN)."""
        res = track_postal_item(item_code)
        return json.dumps(res, ensure_ascii=False)

    @mcp.tool()
    def tra_cuu_buu_cuc(query: str, ctx: Context | None = None) -> str:
        """Tra cứu danh bạ bưu điện, mã bưu chính quốc gia Vpostcode, địa chỉ và giờ mở cửa."""
        res = lookup_postal_office(query)
        return json.dumps(res, ensure_ascii=False)

    @mcp.tool()
    def tim_buu_cuc_gan_nhat(latitude: float, longitude: float, ctx: Context | None = None) -> str:
        """Tìm kiếm các bưu cục VNPost gần nhất theo tọa độ vệ tinh GPS vĩ độ (latitude) và kinh độ (longitude)."""
        res = find_nearest_post_offices(latitude, longitude)
        return json.dumps(res, ensure_ascii=False)

    @mcp.tool()
    def tao_don_hang_nhap(
        sender_name: str,
        sender_phone: str,
        sender_address: str,
        receiver_name: str,
        receiver_phone: str,
        receiver_address: str,
        weight_grams: int,
        length_cm: float = 0.0,
        width_cm: float = 0.0,
        height_cm: float = 0.0,
        service_type: str = "EMS",
        declared_value: float = 0.0,
        ctx: Context | None = None,
    ) -> str:
        """Khởi tạo dự thảo đơn hàng gửi bưu chính VNPost với tính cước quy đổi thể tích cồng kềnh (chia 6000). Yêu cầu duyệt HITL."""
        return create_draft_booking(
            sender_name=sender_name,
            sender_phone=sender_phone,
            sender_address=sender_address,
            receiver_name=receiver_name,
            receiver_phone=receiver_phone,
            receiver_address=receiver_address,
            weight_grams=weight_grams,
            length_cm=length_cm,
            width_cm=width_cm,
            height_cm=height_cm,
            service_type=service_type,
            declared_value=declared_value,
        )

    @mcp.tool()
    def xac_nhan_don_hang(draft_id: str, ctx: Context | None = None) -> str:
        """Xác nhận đơn hàng nháp (HITL) và phát hành mã vận đơn chính thức chuẩn UPU của VNPost."""
        return confirm_booking(draft_id)

    @mcp.tool()
    def huy_don_hang(item_code_or_draft_id: str = "", reason: str = "", verification_phone: str = "", ctx: Context | None = None) -> str:
        """Hủy đơn gửi hàng bưu phẩm bưu kiện (cả đơn nháp lẫn đơn đã phát hành vận đơn trước khi bưu tá lấy hàng)."""
        return cancel_booking(item_code_or_draft_id=item_code_or_draft_id, reason=reason, verification_phone=verification_phone)

    @mcp.tool()
    def tao_phieu_khieu_nai_nhap(
        item_code: str,
        customer_name: str,
        customer_phone: str,
        complaint_type: str,
        description: str,
        claimed_amount: float = 0.0,
        sent_date: str | None = None,
        ctx: Context | None = None,
    ) -> str:
        """Tiếp nhận yêu cầu khiếu nại bưu gửi, thẩm định thời hiệu (06/12 tháng) và lập hồ sơ nháp."""
        return create_draft_complaint(
            item_code=item_code,
            customer_name=customer_name,
            customer_phone=customer_phone,
            complaint_type=complaint_type,
            description=description,
            claimed_amount=claimed_amount,
            sent_date=sent_date,
        )

    @mcp.tool()
    def xac_nhan_khieu_nai(draft_ticket_id: str, ctx: Context | None = None) -> str:
        """Xác nhận nộp khiếu nại chính thức vào hệ thống CRM CSKH VNPost và cấp mã Ticket."""
        return confirm_complaint(draft_ticket_id)

    @mcp.tool()
    def huy_khieu_nai(ticket_id_or_draft_id: str = "", reason: str = "", verification_phone: str = "", ctx: Context | None = None) -> str:
        """Hủy hoặc rút khiếu nại bưu gửi VNPost."""
        return cancel_complaint(ticket_id_or_draft_id=ticket_id_or_draft_id, reason=reason, verification_phone=verification_phone)

    @mcp.tool()
    def danh_sach_don_va_khieu_nai(session_id: str | None = None, tenant: str = "default", ctx: Context | None = None) -> str:
        """Tra cứu toàn bộ danh sách đơn hàng và khiếu nại trong phiên làm việc hiện tại."""
        return list_my_orders(session_id=session_id, tenant=tenant)
