import re
from typing import Literal

# Danh sách mẫu biểu thức nhận diện câu hỏi phức tạp (cần Deep Agent suy luận/đa tác vụ)
COMPLEX_PATTERNS = [
    # So sánh, đối chiếu
    r"\b(so sánh|đối chiếu|khác nhau|phân biệt|ưu nhược điểm|giống nhau)\b",
    # Tính toán số học hoặc ước tính chi phí nhiều bước
    r"\b(tính toán|tính giúp|tính cước|tổng cước|chi phí gửi|cộng lại|bảng tính)\b",
    # Quy trình nhiều bước, lập kế hoạch
    r"\b(lập kế hoạch|các bước|quy trình chi tiết|hướng dẫn từng bước|kế hoạch gửi)\b",
    # Phân tích nguyên nhân, đánh giá tổng thể
    r"\b(phân tích|đánh giá|tại sao|nguyên nhân và giải pháp|tổng hợp ý kiến)\b",
    # Nhiều yêu cầu kết hợp
    r"\b(đồng thời|vừa.*vừa|cả hai|cả 2|tiện thể|cho biết thêm)\b",
]


def classify_query(message: str, image: str | None = None) -> tuple[Literal["fast", "deep"], str]:
    """Phân loại truy vấn người dùng theo kiến trúc Hybrid Router:
    - fast: Câu hỏi tra cứu 1 ý, tìm định nghĩa, thủ tục thông thường -> 1-step Direct RAG (1.5 - 2.5s)
    - deep: Câu hỏi phức tạp, so sánh, tính toán, đa bước hoặc kèm hình ảnh -> Deep Agent Harness (Multi-agent)

    Returns:
        tuple[route, reason]
    """
    if image:
        return "deep", "Yêu cầu xử lý hình ảnh đa phương thức (Multimodal Vision)"

    text = message.lower().strip()

    # Kiểm tra nhiều câu hỏi lồng nhau (>= 2 dấu chấm hỏi)
    if text.count("?") >= 2:
        return "deep", "Nhiều câu hỏi kết hợp cần chia task cho các sub-agents"

    # Kiểm tra các mẫu phức tạp
    for pattern in COMPLEX_PATTERNS:
        match = re.search(pattern, text)
        if match:
            matched_phrase = match.group(1)
            return "deep", f"Yêu cầu suy luận chuyên sâu ({matched_phrase})"

    # Mặc định: câu hỏi tra cứu thông tin trực tiếp
    return "fast", "Tra cứu thông tin nghiệp vụ trực tiếp (Fast Direct RAG)"
