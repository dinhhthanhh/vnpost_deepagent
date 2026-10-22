"""Cấu hình tinh chỉnh chuyên biệt cho tracking-agent."""

ROLE = "tracking"
NAME = "tracking-agent"
DESCRIPTION = "Tra cứu định vị hành trình, trạng thái bưu gửi VNPost theo mã vận đơn (ItemCode)."
TEMPERATURE = 0.0
MAX_TOKENS = 1500
MODE = "isolated"
SKILLS = ["/skills/tra-cuu-buu-gui/"]
