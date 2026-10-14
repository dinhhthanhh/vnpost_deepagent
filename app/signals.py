"""Tín hiệu rẻ từ câu hỏi (Zero-LLM Signal Detection).

Chỉ dùng để LEO THANG hoặc bỏ qua truy xuất; không dùng để chọn 'fast' (mặc định đã là fast).
"""
import re
from dataclasses import asdict, dataclass

from app.text import norm

_CW = (r"(?:xin chào|chào|hello|hi|hey|alo|cảm ơn|cám ơn|thanks|thank you|tạm biệt|bye|ok|oke|okay|vâng|dạ|được rồi"
       r"|bạn|mipo|nhé|nha|ạ|anh|chị|em|rất nhiều|nhiều|chao|xin chao|chao ban|cam on|tam biet)")
_CHITCHAT = re.compile(rf"{_CW}(?: {_CW})*")
_COMPARE = re.compile(r"so sánh|đối chiếu|khác nhau|khác gì|khác biệt|giống nhau|phân biệt|ưu nhược|hơn kém")
# Chỉ các cách nói "hãy tính cho tôi" và biểu thức số. KHÔNG gồm "tính phí/cước ... như thế nào" (đó là câu tra cứu).
_CALC = re.compile(r"tính (toán|giúp|hộ|cho tôi|cho mình|tổng)|tổng cộng|cộng lại|\d\s*[x×*+]\s*\d|\d\s*/\s*\d")
_DATE = re.compile(r"\b\d{1,2}\s*/\s*\d{1,2}(?:\s*/\s*\d{2,4})?\b")
_MULTISTEP = re.compile(
    r"(?:sau đó|tiếp theo)\s+(?:tính|so sánh|lập|soạn|tổng hợp|gửi|làm bước)|đồng thời|rồi (?:tính|so sánh|lập|soạn|tổng hợp|gửi)|và (?:so sánh|tính|lập|soạn|tổng hợp)"
    r"|lập kế hoạch|kế hoạch chi tiết|từng bước một|trước hết"
)
_LIST = re.compile(r"\n\s*([-*•]|\d+[.)])\s")


@dataclass(frozen=True)
class Signals:
    chitchat: bool = False
    compare: bool = False
    calc: bool = False
    multistep: bool = False
    multi_question: bool = False

    def hit(self) -> list[str]:
        return [k for k, v in asdict(self).items() if v]


def analyze(raw: str) -> Signals:
    t = norm(raw)
    plain = re.sub(r"[!?.,;:…]+", " ", t).strip()
    plain = re.sub(r"\s+", " ", plain)
    # Loại bỏ ngày tháng (8/3, 20/10, 30/4/1975) để không bị nhận nhầm dấu gạch chéo là phép chia
    t_no_dates = _DATE.sub(" ", t)
    return Signals(
        chitchat=bool(plain) and len(plain) <= 50 and bool(_CHITCHAT.fullmatch(plain)),
        compare=bool(_COMPARE.search(t)),
        calc=bool(_CALC.search(t_no_dates)),
        multistep=bool(_MULTISTEP.search(t)),
        multi_question=t.count("?") >= 2 or bool(_LIST.search(raw or "")),
    )
