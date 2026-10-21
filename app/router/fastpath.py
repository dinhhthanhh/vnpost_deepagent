
"""Đường tắt không dùng LLM: phép tính thuần và xã giao.

Chạy trước router, tốn dưới 1 ms. Chỉ trả lời khi CHẮC CHẮN:
  * câu chỉ gồm một biểu thức số học (+ vài từ đệm như "tính giúp", "bằng mấy", "đồng");
  * hoặc là câu xã giao (cờ do app.signals.analyze(...).chitchat quyết định).
Mọi trường hợp còn lại trả None để đi router như cũ.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    _VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:
    _VN_TZ = timezone(timedelta(hours=7))

from app.agents.calculator import _vn_numbers, safe_calculate, safe_date_calculate


@dataclass(frozen=True)
class LocalAnswer:
    kind: str   # "calc" | "chitchat"
    text: str


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


# Từ đệm được phép đứng cạnh biểu thức (đã bỏ dấu).
_FILLER = {
    "tinh", "giup", "ho", "gium", "dum", "toi", "minh", "cho", "bang", "may", "bao", "nhieu",
    "la", "ket", "qua", "cua", "phep", "dong", "vnd", "vn", "d", "va", "neu", "cach",
    "hay", "vui", "long", "oi", "nhe", "a", "xin", "ban", "mipo", "giai", "thich",
    "calculate", "what", "is", "please", "bằng", "mod",
}
_SPAN = re.compile(r"[\d(][\d\s+\-*/%().,]*")
_DATE = re.compile(
    r"\b\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4}\b"
    r"|\b\d{1,4}\s*/\s*(?:19\d{2}|20\d{2})\b"
    r"|\b\d+/\d+/[A-Za-zĐđ\-_]+"
)
_OPERATOR = re.compile(r"(?<=[\d)])\s*(?:\*\*|[+\-*/%])\s*(?=[\d(])")


def _prepare(message: str) -> str:
    t = message.strip().lower()
    t = t.replace("×", "*").replace("÷", "/").replace("**", "^")
    t = re.sub(r"(?<=[\d)])\s*x\s*(?=[\d(])", "*", t)          # 3002x2, 3 x 4
    t = re.sub(r"(?<=\d)\s*:\s*(?=\d)", "/", t)                  # 10:2
    t = re.sub(r"(?<=\d)\s*mod\s*(?=\d)", "%", t)               # 10 mod 3
    t = t.replace("^", "**")
    return t


def _fmt(value: float | int) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        return str(value)
    return f"{value:.10g}".replace(".", ",")


_WEEKDAYS_VN = {
    0: "Thứ Hai",
    1: "Thứ Ba",
    2: "Thứ Tư",
    3: "Thứ Năm",
    4: "Thứ Sáu",
    5: "Thứ Bảy",
    6: "Chủ Nhật",
}

_SPECIAL_DATES = {
    "01/01": "Tết Dương lịch",
    "14/02": "Ngày lễ Tình nhân (Valentine)",
    "08/03": "Ngày Quốc tế Phụ nữ",
    "26/03": "Ngày thành lập Đoàn TNCS Hồ Chí Minh",
    "30/04": "Ngày Giải phóng miền Nam, Thống nhất đất nước",
    "01/05": "Ngày Quốc tế Lao động",
    "01/06": "Ngày Quốc tế Thiếu nhi",
    "28/06": "Ngày Gia đình Việt Nam",
    "27/07": "Ngày Thương binh Liệt sĩ",
    "19/08": "Ngày truyền thống Công an nhân dân",
    "02/09": "Ngày Quốc khánh Việt Nam",
    "10/10": "Ngày Giải phóng Thủ đô / Ngày Chuyển đổi số quốc gia",
    "13/10": "Ngày Doanh nhân Việt Nam",
    "20/10": "Ngày Phụ nữ Việt Nam",
    "20/11": "Ngày Nhà giáo Việt Nam",
    "22/12": "Ngày thành lập Quân đội nhân dân Việt Nam",
}


def today_answer(message: str) -> LocalAnswer | None:
    """Trả lời câu hỏi thời gian (hôm nay, ngày mai, hôm qua, ngày mốt, giờ hiện tại) bằng đồng hồ server Việt Nam."""
    if len(message) > 120:
        return None
    folded = _fold(message)
    plain = re.sub(r"[^a-z0-9 ]+", " ", folded)
    plain = re.sub(r"\s+", " ", plain).strip()

    # 1. Các câu hỏi về NGÀY MAI / MAI
    tomorrow_matches = {
        "ngay mai la ngay bao nhieu", "ngay mai ngay bao nhieu", "ngay mai la ngay may", "ngay mai ngay may",
        "ngay mai la ngay gi", "ngay mai la thu may", "ngay mai thu may", "mai la ngay bao nhieu",
        "mai la ngay may", "mai ngay may", "mai la thu may", "mai thu may", "mai la ngay gi",
        "ngay mai la ngay nao", "ngay mai", "mai la ngay gi", "mai ngay bao nhieu",
    }
    is_tomorrow = plain in tomorrow_matches or (
        ("ngay mai" in plain or plain.startswith("mai "))
        and any(k in plain for k in ["ngay bao nhieu", "ngay may", "thu may", "ngay gi", "ngay nao"])
    )
    if is_tomorrow:
        now = datetime.now(_VN_TZ)
        tomorrow = now + timedelta(days=1)
        special = _SPECIAL_DATES.get(tomorrow.strftime("%d/%m"))
        suffix = f" — {special}" if special else ""
        return LocalAnswer("date", f"Ngày mai là ngày **{tomorrow:%d/%m/%Y}** ({_WEEKDAYS_VN[tomorrow.weekday()]}){suffix}.")

    # 2. Các câu hỏi về HÔM QUA
    yesterday_matches = {
        "hom qua la ngay bao nhieu", "hom qua ngay bao nhieu", "hom qua la ngay may", "hom qua ngay may",
        "hom qua la ngay gi", "hom qua la thu may", "hom qua thu may", "hom qua la ngay nao", "hom qua",
    }
    is_yesterday = plain in yesterday_matches or (
        "hom qua" in plain and any(k in plain for k in ["ngay bao nhieu", "ngay may", "thu may", "ngay gi", "ngay nao"])
    )
    if is_yesterday:
        now = datetime.now(_VN_TZ)
        yesterday = now - timedelta(days=1)
        special = _SPECIAL_DATES.get(yesterday.strftime("%d/%m"))
        suffix = f" — {special}" if special else ""
        return LocalAnswer("date", f"Hôm qua là ngày **{yesterday:%d/%m/%Y}** ({_WEEKDAYS_VN[yesterday.weekday()]}){suffix}.")

    # 3. Các câu hỏi về NGÀY KIA / NGÀY MỐT
    after_tomorrow_matches = {
        "ngay kia la ngay bao nhieu", "ngay kia ngay bao nhieu", "ngay kia la ngay may", "ngay kia ngay may",
        "ngay kia la thu may", "ngay kia thu may", "ngay mot la ngay bao nhieu", "ngay mot ngay may", "ngay mot", "ngay kia",
    }
    if plain in after_tomorrow_matches:
        now = datetime.now(_VN_TZ)
        target = now + timedelta(days=2)
        special = _SPECIAL_DATES.get(target.strftime("%d/%m"))
        suffix = f" — {special}" if special else ""
        return LocalAnswer("date", f"Ngày kia (ngày mốt) là ngày **{target:%d/%m/%Y}** ({_WEEKDAYS_VN[target.weekday()]}){suffix}.")

    # 4. Các câu hỏi về GIỜ HIỆN TẠI
    time_matches = {
        "bay gio la may gio", "bay gio may gio", "may gio roi", "may gio", "hien tai la may gio",
        "thoi gian hien tai", "xem gio", "bay gio la may gio roi",
    }
    if plain in time_matches:
        now = datetime.now(_VN_TZ)
        return LocalAnswer("date", f"Bây giờ là **{now:%H:%M}**, ngày **{now:%d/%m/%Y}** ({_WEEKDAYS_VN[now.weekday()]}).")

    # 5. Các câu hỏi về HÔM NAY
    today_matches = {
        "hom nay la ngay bao nhieu", "hom nay ngay bao nhieu", "hom nay la ngay may", "hom nay ngay may",
        "ngay hom nay la ngay bao nhieu", "ngay hom nay la ngay may", "hom nay la ngay may",
        "hom nay la ngay gi", "ngay hom nay la ngay gi", "hom nay la ngay nao",
        "hom nay la thu may", "hom nay thu may", "thu may hom nay", "ngay may hom nay",
        "hom nay", "ngay hom nay",
    }
    is_today = plain in today_matches or (
        ("hom nay" in plain or "ngay nay" in plain)
        and any(k in plain for k in ["ngay bao nhieu", "ngay may", "thu may", "ngay gi", "ngay nao"])
    )
    if is_today:
        now = datetime.now(_VN_TZ)
        special = _SPECIAL_DATES.get(now.strftime("%d/%m"))
        suffix = f" — {special}" if special else ""
        return LocalAnswer("date", f"Hôm nay là ngày **{now:%d/%m/%Y}** ({_WEEKDAYS_VN[now.weekday()]}){suffix}.")

    return None


def try_modulo(message: str) -> LocalAnswer | None:
    """Xử lý phép chia có dư và câu hỏi số dư bằng ngôn ngữ tự nhiên."""
    if len(message) > 120:
        return None
    f = _fold(message)

    # 1. Mẫu: "tìm số dư khi chia A cho B"
    m1 = re.search(r"(?:tim\s+)?so\s+du\s+(?:khi\s+)?chia\s+(\d+(?:[.,]\d+)?)\s+cho\s+(\d+(?:[.,]\d+)?)", f)
    # 2. Mẫu: "số dư của / khi A chia (cho) B"
    m2 = re.search(r"(?:tim\s+)?so\s+du\s+(?:khi|cua)?\s*(\d+(?:[.,]\d+)?)\s*chia\s*(?:cho)?\s*(\d+(?:[.,]\d+)?)", f)
    # 3. Mẫu: "A chia (cho) B (thì) dư mấy / dư bao nhiêu"
    m3 = re.search(r"\b(\d+(?:[.,]\d+)?)\s*chia\s*(?:cho)?\s*(\d+(?:[.,]\d+)?)\s*(?:thi\s+)?du\s*(?:may|bao\s+nhieu|\?)?", f)
    # 4. Mẫu: "A mod B" hoặc "A % B"
    m4 = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(?:mod|%)\s*(\d+(?:[.,]\d+)?)\b", f)

    m = m1 or m2 or m3 or m4
    if not m:
        return None

    words = re.findall(r"[a-z]+", f)
    allowed_mod_words = _FILLER | {"so", "du", "chia", "khi", "mod", "tim", "thi"}
    if any(w not in allowed_mod_words for w in words):
        return None

    try:
        a_str = _vn_numbers(m.group(1))
        b_str = _vn_numbers(m.group(2))
        a = safe_calculate(a_str)
        b = safe_calculate(b_str)
        if b == 0:
            return None
        if isinstance(a, int) and isinstance(b, int):
            quotient = a // b
            remainder = a % b
            if remainder == 0:
                text = f"{a} ÷ {b} = **{quotient}** (chia hết, số dư là **0**)."
            else:
                text = f"{a} ÷ {b} = **{quotient}**, dư **{remainder}** ({a} = {b} × {quotient} + {remainder})."
            return LocalAnswer("calc", text)
        else:
            remainder = a % b
            return LocalAnswer("calc", f"Số dư của {a_str} chia {b_str} là **{_fmt(remainder)}**.")
    except Exception:
        return None


def try_date_query(message: str) -> LocalAnswer | None:
    """Trả lời các câu hỏi tính toán ngày tháng độc lập bằng safe_date_calculate mà không cần gọi LLM."""
    if len(message) > 150:
        return None

    # Không nhận nếu chứa các từ khóa nghiệp vụ bưu chính
    business_keywords = (
        "bưu phẩm", "bưu gửi", "bưu kiện", "vận đơn", "kiện hàng", "gửi hàng",
        "khiếu nại", "bồi thường", "hoàn cước", "cước", "giá", "phí", "bưu cục",
        "bưu điện", "vpostcode", "quy định", "thời hiệu", "thời hạn", "sla",
        "eb", "cp", "ee", "rk",
    )
    clean = message.lower()
    if any(k in clean for k in business_keywords):
        return None

    # Phải có tín hiệu câu hỏi hoặc ý định tính toán thời gian rõ ràng (tránh nhầm văn bản hành chính)
    temporal_question_markers = (
        "thứ mấy", "ngày mấy", "ngày bao nhiêu", "ngày gì", "ngày nào",
        "tuần sau", "tuần tới", "tuần trước", "tuần này", "tuần nữa",
        "năm sau", "năm tới", "năm ngoái", "năm trước",
        "ngày nữa", "ngày trước", "bao nhiêu ngày", "mấy ngày", "mấy ngày nữa",
    )
    if not any(k in clean for k in temporal_question_markers):
        return None

    try:
        res = safe_date_calculate(message)
        if isinstance(res, dict) and "explanation" in res:
            return LocalAnswer("date", res["explanation"])
    except Exception:
        pass
    return None


def try_arithmetic(message: str) -> LocalAnswer | None:
    if len(message) > 200 or _DATE.search(message):
        return None
    t = _prepare(message)
    spans = [s for s in _SPAN.findall(t) if re.search(r"\d", s)]
    if len(spans) != 1 or not _OPERATOR.search(spans[0]):
        return None
    span = spans[0]
    rest = _fold(t.replace(span, " "))
    words = re.findall(r"[a-z]+", rest)
    if any(w not in _FILLER for w in words):
        return None                      # còn từ nghiệp vụ -> không phải phép tính thuần
    expr = _vn_numbers(span.strip())
    try:
        value = safe_calculate(expr)
    except (SyntaxError, ValueError):
        return None                      # vd "1+!" -> để LLM xử lý
    shown = re.sub(r"\s*(\*\*|[+\-*/%])\s*", r" \1 ", span.strip()).replace("**", "^")
    shown = shown.replace("*", "×").replace("/", "÷").replace("%", " mod ")
    text = f"{shown} = **{_fmt(value)}**"
    if "cach" in words:
        text += "\n\nCách tính: nhân/chia trước, cộng/trừ sau; các phép cùng cấp tính từ trái sang phải."
    return LocalAnswer("calc", text)


def chitchat_reply(message: str) -> LocalAnswer | None:
    f = _fold(message)
    if re.search(r"\b(cam on|thanks|thank you)\b", f):
        text = "Không có gì ạ! Bạn cần tra cứu thêm gì cứ hỏi Mipo nhé."
    elif re.search(r"\b(tam biet|bye|goodbye|hen gap lai)\b", f):
        text = "Tạm biệt bạn! Cần gì cứ quay lại hỏi Mipo nhé."
    elif re.search(r"\b(ban la ai|ban ten gi|mipo la ai)\b", f):
        text = "Mình là Mipo, trợ lý ảo của VNPost. Mình có thể giúp bạn tra cứu tài liệu nội bộ và trả lời kèm nguồn."
    else:
        text = "Xin chào! Mình là Mipo, trợ lý của VNPost. Bạn cần tra cứu nội dung gì?"
    return LocalAnswer("chitchat", text)


def local_answer(message: str, *, chitchat: bool = False) -> LocalAnswer | None:
    """chitchat: cờ từ app.signals.analyze(message).chitchat (một định nghĩa duy nhất)."""
    if chitchat:
        return chitchat_reply(message)
    return today_answer(message) or try_date_query(message) or try_modulo(message) or try_arithmetic(message)
