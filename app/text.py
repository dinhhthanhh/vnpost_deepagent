import re
import unicodedata


def norm(text: str) -> str:
    """NFC + chữ thường + gộp khoảng trắng.
    
    Mọi so khớp regex và embedding chạy trên chuỗi này (tránh lỗi chữ tiếng Việt dạng tổ hợp NFD).
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "").lower()).strip()


def sanitize_llm_delimiters(text: str) -> str:
    """Thoát các ký tự và thẻ phân cách đặc biệt nhằm ngăn chặn Indirect Prompt Injection."""
    if not text:
        return ""
    replacements = (
        ("[HẾT TÀI LIỆU]", "&#91;HẾT TÀI LIỆU&#93;"),
        ("[TÀI LIỆU]", "&#91;TÀI LIỆU&#93;"),
        ("</tai_lieu_tham_khao>", "&lt;/tai_lieu_tham_khao&gt;"),
        ("<tai_lieu_tham_khao>", "&lt;tai_lieu_tham_khao&gt;"),
        ("</context>", "&lt;/context&gt;"),
        ("<context>", "&lt;context&gt;"),
        ("[INSTRUCTION]", "&#91;INSTRUCTION&#93;"),
        ("[/INSTRUCTION]", "&#91;/INSTRUCTION&#93;"),
        ("[INST]", "&#91;INST&#93;"),
        ("[/INST]", "&#91;/INST&#93;"),
        ("<|im_start|>", "&lt;|im_start|&gt;"),
        ("<|im_end|>", "&lt;|im_end|&gt;"),
        ("<|system|>", "&lt;|system|&gt;"),
        ("<|user|>", "&lt;|user|&gt;"),
        ("<|assistant|>", "&lt;|assistant|&gt;"),
        ("[SYSTEM]", "&#91;SYSTEM&#93;"),
        ("[/SYSTEM]", "&#91;/SYSTEM&#93;"),
        ("<s>", "&lt;s&gt;"),
        ("</s>", "&lt;/s&gt;"),
    )
    for target, rep in replacements:
        text = text.replace(target, rep)
    return text
