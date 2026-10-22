"""Cấu hình tinh chỉnh chuyên biệt cho post-office-agent."""

ROLE = "post_office"
NAME = "post-office-agent"
DESCRIPTION = "Tra cứu mạng lưới bưu cục, tìm bưu điện gần nhất qua GPS find_nearest_post_office hoặc địa chỉ lookup_post_office và chỉ đường Google Maps."
TEMPERATURE = 0.0
MAX_TOKENS = 1500
MODE = "isolated"
SKILLS = ["/skills/ma-buu-chinh-vpostcode/"]
