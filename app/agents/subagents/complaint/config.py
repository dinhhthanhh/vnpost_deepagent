"""Cấu hình tinh chỉnh chuyên biệt cho complaint-agent."""

ROLE = "complaint"
NAME = "complaint-agent"
DESCRIPTION = "Tiếp nhận khiếu nại, đối chiếu thời hiệu 06/12 tháng, bồi thường, sửa đổi, nộp Ticket (HITL), hủy/rút khiếu nại (cancel_complaint/cancel_draft_complaint) và tra cứu đơn (list_my_orders)."
TEMPERATURE = 0.0
MAX_TOKENS = 2500
MODE = "isolated"
SKILLS = ["/skills/boi_thuong_khieu_nai/"]
