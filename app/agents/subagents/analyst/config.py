"""Cấu hình tinh chỉnh chuyên biệt cho analyst-agent."""

ROLE = "analyst"
NAME = "analyst-agent"
DESCRIPTION = (
    "So sánh, phân tích bằng chứng được giao, tính toán số học và tính toán ngày tháng/lịch trình."
)
TEMPERATURE = 0.0
MAX_TOKENS = 1500
MODE = "isolated"
SKILLS = ["/skills/uoc_tinh_cuoc_phi/"]
