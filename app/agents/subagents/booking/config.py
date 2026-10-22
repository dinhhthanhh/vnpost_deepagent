"""Cấu hình tinh chỉnh chuyên biệt cho booking-agent."""

ROLE = "booking"
NAME = "booking-agent"
DESCRIPTION = "Tạo đơn gửi hàng, tính cước theo vùng và thể tích chia 6000, tạo nháp, sửa đổi, xác nhận (HITL), hủy đơn (cancel_booking/cancel_draft_booking) và tra cứu danh sách đơn (list_my_orders)."
TEMPERATURE = 0.0
MAX_TOKENS = 2500
MODE = "isolated"
SKILLS = ["/skills/quy-chuan-dong-goi/", "/skills/uoc-tinh-cuoc-phi/"]
