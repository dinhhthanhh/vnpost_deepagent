"""Module thuật ngữ nghiệp vụ bưu điện (terminology) và hậu xử lý văn bản (postprocess).

Kế thừa và chuẩn hóa từ agent.template của VNPost:
1. Tự động nhận diện từ viết tắt nghiệp vụ trong câu hỏi và bổ sung gợi ý vào prompt lúc runtime.
2. Hậu xử lý văn bản (postprocess_func) chuẩn hóa định dạng số/tiền tệ Việt Nam và công thức LaTeX sang Markdown.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TERMINOLOGY: dict[str, str] = {
    "đkcl": "Đo kiểm chất lượng",
    "ems": "Dịch vụ chuyển phát nhanh Express Mail Service",
    "cod": "Dịch vụ phát hàng thu tiền hộ (Cash On Delivery)",
    "kt1": "Hệ thống bưu gửi phục vụ cơ quan Đảng, Nhà nước",
    "bcp": "Bưu cục phát",
    "ktt": "Khai thác trung tâm",
    "vnp": "Tổng công ty Bưu điện Việt Nam (Vietnam Post)",
    "gdv": "Giao dịch viên",
    "bdt": "Bưu điện tỉnh / thành phố",
    "bdh": "Bưu điện huyện / thị xã",
    "kpi": "Chỉ số đánh giá hiệu quả công việc (Key Performance Indicator)",
    "slt": "Sản lượng / Số lượng",
    "tlk": "Trọng lượng quy đổi",
    "vpt": "Vận chuyển phát chuyển tiếp",
}


def normalize_for_match(text: str) -> str:
    """Chuẩn hóa văn bản: lowercase, đ->d, bỏ dấu tiếng Việt (NFD decomposition)."""
    text = text.lower().replace("đ", "d")
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


def load_terminology(file_path: str = "terminology.json") -> dict[str, str]:
    """Tải từ điển thuật ngữ từ file json nếu có, kết hợp với bộ mặc định."""
    terms = dict(DEFAULT_TERMINOLOGY)
    p = Path(file_path)
    if not p.is_file():
        # Kiểm tra thử trong data/ nếu root không có
        alt = Path("data") / file_path
        if alt.is_file():
            p = alt

    if p.is_file():
        try:
            with open(p, encoding="utf-8") as f:
                custom = json.load(f)
                if isinstance(custom, dict):
                    terms.update({str(k).lower(): str(v) for k, v in custom.items()})
        except Exception as e:
            logger.warning("Không thể tải file thuật ngữ %s: %s", p, e)
    return terms


def find_matched_terminology(
    text: str | list[dict], terms: dict[str, str] | None = None
) -> dict[str, str]:
    """Tìm các từ viết tắt xuất hiện trong văn bản câu hỏi (chuẩn hóa tiếng Việt, khớp ranh giới từ)."""
    if terms is None:
        terms = load_terminology()
    if not terms:
        return {}

    if isinstance(text, list):
        text_str = " ".join(
            m.get("content", "") or "" for m in text if isinstance(m, dict) and isinstance(m.get("content"), str)
        )
    else:
        text_str = str(text or "")

    normalized_text = normalize_for_match(text_str)
    matched: dict[str, str] = {}
    for key, value in terms.items():
        norm_key = normalize_for_match(key)
        if not norm_key:
            continue
        # Khớp nguyên từ \b
        pattern = r"\b" + re.escape(norm_key) + r"\b"
        if re.search(pattern, normalized_text):
            matched[key] = value
    return matched


def build_terminology_hint(matched: dict[str, str]) -> str:
    """Tạo chuỗi gợi ý thuật ngữ để bổ sung vào prompt."""
    if not matched:
        return ""
    lines = "\n".join(f"- {k.upper()}: {v}" for k, v in matched.items())
    return f"Một số từ viết tắt, thuật ngữ nghiệp vụ bưu điện cần lưu ý:\n{lines}"


def postprocess_func(s: str) -> str:
    """Hậu xử lý chuỗi văn bản trả về từ LLM (chuẩn từ agent.template của VNPost).

    1. Thay thế ký tự khoảng trắng hẹp `\\u202f` và khoảng trắng phân cách hàng nghìn bằng dấu chấm.
       (Bảo vệ số điện thoại / hotline không bị đổi khoảng trắng thành dấu chấm).
    2. Chuyển đổi công thức toán dạng LaTeX:
       - Khối công thức `\\[...\\]` -> `$$...$$` (block math).
       - Công thức nội dòng `\\(...\\)` -> `$...$` (inline math).
    """
    if not s:
        return s

    # 1. Bảo vệ số điện thoại / hotline bằng token tạm thời
    phone_tokens: list[str] = []

    def _save_phone(m: re.Match) -> str:
        phone_tokens.append(m.group(0))
        return f"__PHONE_TOKEN_{len(phone_tokens) - 1}__"

    phone_pattern = re.compile(
        r"(?i)\b(?:hotline|tổng đài|sđt|số điện thoại|điện thoại|tel|phone|liên hệ)\s*[:]?\s*(?:1900|1800|0\d{1,3})[\s.]\d{2,4}[\s.]\d{2,4}"
        r"|\b(?:1900|1800)[\s.]\d{2,4}[\s.]\d{2,4}\b"
        r"|\b0\d{1,3}[\s.]\d{3}[\s.]\d{3,4}\b"
    )
    s_protected = phone_pattern.sub(_save_phone, s)

    # 2. Chuẩn hóa khoảng trắng phân cách hàng nghìn sang dấu chấm
    pattern = re.compile(r"\d{1,3}(?:[\u202f ]\d{3})+(?:[.,]\d+)?")

    def repl(match: re.Match) -> str:
        num = match.group(0)
        num = re.sub(r"\.", ",", num)
        num = re.sub(r"[\u202f ]", ".", num)
        return num

    s_processed = pattern.sub(repl, s_protected)

    # 3. Phục hồi số điện thoại / hotline nguyên bản
    for idx, token in enumerate(phone_tokens):
        s_processed = s_processed.replace(f"__PHONE_TOKEN_{idx}__", token)

    # 4. Block math: \[ ... \] -> $$ ... $$
    s_processed = re.sub(r"\\\[(.*?)\\\]", r"$$\1$$", s_processed, flags=re.DOTALL)

    # 5. Inline math: \( ... \) -> $ ... $
    s_processed = re.sub(r"\\\((.*?)\\\)", r"$\1$", s_processed, flags=re.DOTALL)

    return s_processed
