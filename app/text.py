import re
import unicodedata


def norm(text: str) -> str:
    """NFC + chữ thường + gộp khoảng trắng.
    
    Mọi so khớp regex và embedding chạy trên chuỗi này (tránh lỗi chữ tiếng Việt dạng tổ hợp NFD).
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "").lower()).strip()
