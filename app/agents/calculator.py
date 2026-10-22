import ast
import calendar
import datetime
import math
import operator
import re
import unicodedata

OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}


def _vn_numbers(expr: str) -> str:
    # 125.000 -> 125000, 1.500.000 -> 1500000 (bảo tồn số thập phân 0.xxx vì bắt đầu bằng [1-9])
    while re.search(r"\b([1-9]\d*)\.(\d{3}(?!\d))", expr):
        expr = re.sub(r"\b([1-9]\d*)\.(\d{3}(?!\d))", r"\1\2", expr)
    return re.sub(r"(?<=\d),(?=\d)", ".", expr)  # 2,5 -> 2.5


def safe_calculate(expression: str) -> float | int:
    """A bounded numerical AST evaluator. Never eval, exec, imports or attributes."""
    if len(expression) > 200:
        raise ValueError("Biểu thức quá dài")
    expression = _vn_numbers(expression.strip())
    tree = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 60:
        raise ValueError("Biểu thức quá phức tạp")

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = node.value
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in OPS:
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > 10 or abs(left) > 1e6):
                raise ValueError("Lũy thừa vượt giới hạn")
            value = OPS[type(node.op)](left, right)
        else:
            raise ValueError("Chỉ cho phép phép tính số học")
        if isinstance(value, complex) or not math.isfinite(value) or abs(value) > 1e15:
            raise ValueError("Kết quả vượt giới hạn")
        return value

    try:
        res = evaluate(tree)
        if isinstance(res, float):
            res = round(res, 10)
            if res.is_integer():
                res = int(res)
        return res
    except (ZeroDivisionError, OverflowError) as exc:
        raise ValueError("Phép tính không hợp lệ") from exc


_WEEKDAYS_VN = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
_WEEKDAY_MAP = {
    "thứ hai": 0,
    "thứ 2": 0,
    "thu hai": 0,
    "thu 2": 0,
    "t2": 0,
    "thứ ba": 1,
    "thứ 3": 1,
    "thu ba": 1,
    "thu 3": 1,
    "t3": 1,
    "thứ tư": 2,
    "thứ 4": 2,
    "thu tư": 2,
    "thu 4": 2,
    "t4": 2,
    "thứ năm": 3,
    "thứ 5": 3,
    "thu năm": 3,
    "thu 5": 3,
    "t5": 3,
    "thứ sáu": 4,
    "thứ 6": 4,
    "thu sáu": 4,
    "thu 6": 4,
    "t6": 4,
    "thứ bảy": 5,
    "thứ 7": 5,
    "thu bảy": 5,
    "thu 7": 5,
    "t7": 5,
    "chủ nhật": 6,
    "chu nhat": 6,
    "cn": 6,
}


def safe_date_calculate(query: str, now: datetime.datetime | None = None) -> dict:
    """Tính toán thời gian, lịch, thứ trong tuần và khoảng cách ngày an toàn."""
    if now is None:
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7)))
    today = now.date()
    q = unicodedata.normalize("NFC", query or "").lower().strip()
    q = re.sub(r"\s+", " ", q)

    # 1. 'thứ X tuần sau nữa nữa...' hoặc 'thứ X tuần tới/này'
    wd_match = None
    for name, wd_idx in _WEEKDAY_MAP.items():
        if re.search(r"\b" + re.escape(name) + r"\b", q):
            wd_match = (name, wd_idx)
            break

    if wd_match and ("tuần" in q or "tới" in q):
        target_wd = wd_match[1]
        weeks_ahead = 1
        if "tuần này" in q:
            weeks_ahead = 0
        elif "tuần trước" in q:
            weeks_ahead = -1
        else:
            nua_count = len(re.findall(r"\bnữa\b", q))
            if nua_count > 0:
                weeks_ahead = 1 + nua_count
            elif "tuần sau" in q or "tuần tới" in q:
                weeks_ahead = 1

        curr_monday = today - datetime.timedelta(days=today.weekday())
        target_date = curr_monday + datetime.timedelta(weeks=weeks_ahead, days=target_wd)
        diff_days = (target_date - today).days
        return {
            "type": "relative_weekday",
            "target_weekday": _WEEKDAYS_VN[target_wd],
            "target_date": target_date.strftime("%d/%m/%Y"),
            "iso_date": target_date.isoformat(),
            "weeks_ahead": weeks_ahead,
            "days_from_today": diff_days,
            "explanation": (
                f"{_WEEKDAYS_VN[target_wd]} sau {weeks_ahead} tuần "
                f"(kể từ tuần hiện tại chứa ngày {today.strftime('%d/%m/%Y')}) là ngày **{target_date.strftime('%d/%m/%Y')}**."
            ),
        }

    # 2. Ngày cụ thể kèm năm sau / năm nay / năm trước (ví dụ: 12/3 năm sau, 20/10 năm nay, 29/02/2028)
    date_match = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{4}))?\b", q)
    if date_match:
        d = int(date_match.group(1))
        m = int(date_match.group(2))
        y = int(date_match.group(3)) if date_match.group(3) else None

        if y is None:
            if "năm sau" in q or "năm tới" in q:
                y = today.year + 1
            elif "năm trước" in q or "năm ngoái" in q:
                y = today.year - 1
            else:
                y = today.year

        try:
            target_date = datetime.date(y, m, d)
        except ValueError as exc:
            return {"error": f"Ngày {d}/{m}/{y} không hợp lệ trên lịch: {exc}"}

        wd = target_date.weekday()
        days_from_today = (target_date - today).days
        exp = f"Ngày **{target_date.strftime('%d/%m/%Y')}** là **{_WEEKDAYS_VN[wd]}**."
        if "bao nhiêu ngày" in q or "mấy ngày" in q or "còn" in q:
            exp += f" (còn {days_from_today} ngày kể từ hôm nay {today.strftime('%d/%m/%Y')})"
        return {
            "type": "specific_date",
            "target_date": target_date.strftime("%d/%m/%Y"),
            "iso_date": target_date.isoformat(),
            "weekday": _WEEKDAYS_VN[wd],
            "days_from_today": days_from_today,
            "explanation": exp,
        }

    # 3. 'N ngày nữa', 'sau N ngày', 'N ngày trước'
    add_days_match = re.search(r"(?:sau\s+)?(\d+)\s+ngày(?:\s+(nữa|trước))?", q)
    if add_days_match:
        days = int(add_days_match.group(1))
        direction = add_days_match.group(2) or ("sau" if "sau" in q else "nữa")
        if direction == "trước":
            target_date = today - datetime.timedelta(days=days)
            wd = target_date.weekday()
            return {
                "type": "sub_days",
                "days_subtracted": days,
                "target_date": target_date.strftime("%d/%m/%Y"),
                "weekday": _WEEKDAYS_VN[wd],
                "explanation": f"{days} ngày trước (tính từ {today.strftime('%d/%m/%Y')}) là ngày **{target_date.strftime('%d/%m/%Y')}** ({_WEEKDAYS_VN[wd]}).",
            }
        else:
            target_date = today + datetime.timedelta(days=days)
            wd = target_date.weekday()
            return {
                "type": "add_days",
                "days_added": days,
                "target_date": target_date.strftime("%d/%m/%Y"),
                "weekday": _WEEKDAYS_VN[wd],
                "explanation": f"{days} ngày nữa kể từ {today.strftime('%d/%m/%Y')} là ngày **{target_date.strftime('%d/%m/%Y')}** ({_WEEKDAYS_VN[wd]}).",
            }

    # 4. 'N tuần nữa', 'sau N tuần'
    add_weeks_match = re.search(r"(?:sau\s+)?(\d+)\s+tuần(?:\s+(nữa|trước))?", q)
    if add_weeks_match:
        weeks = int(add_weeks_match.group(1))
        direction = add_weeks_match.group(2) or ("sau" if "sau" in q else "nữa")
        if direction == "trước":
            target_date = today - datetime.timedelta(weeks=weeks)
            wd = target_date.weekday()
            return {
                "type": "sub_weeks",
                "weeks_subtracted": weeks,
                "target_date": target_date.strftime("%d/%m/%Y"),
                "weekday": _WEEKDAYS_VN[wd],
                "explanation": f"{weeks} tuần trước (tính từ {today.strftime('%d/%m/%Y')}) là ngày **{target_date.strftime('%d/%m/%Y')}** ({_WEEKDAYS_VN[wd]}).",
            }
        else:
            target_date = today + datetime.timedelta(weeks=weeks)
            wd = target_date.weekday()
            return {
                "type": "add_weeks",
                "weeks_added": weeks,
                "target_date": target_date.strftime("%d/%m/%Y"),
                "weekday": _WEEKDAYS_VN[wd],
                "explanation": f"{weeks} tuần nữa kể từ {today.strftime('%d/%m/%Y')} là ngày **{target_date.strftime('%d/%m/%Y')}** ({_WEEKDAYS_VN[wd]}).",
            }

    # 5. Nhận diện 'ngày X tháng sau/tới/trước' hoặc 'X tháng sau/tới/trước' (X là ngày 1..31 trong tháng)
    # Ví dụ: '21 tháng sau là ngày thứ mấy', 'ngày 15 tháng tới', '20 tháng trước'
    day_rel_month = re.search(
        r"(?:ngày\s+)?\b([1-9]|[12]\d|3[01])\s+tháng\s+(sau|tới|tiếp\s+theo|trước|này)\b", q
    )
    if day_rel_month:
        day = int(day_rel_month.group(1))
        rel = day_rel_month.group(2)
        if rel in ("sau", "tới", "tiếp theo"):
            target_year = today.year + (1 if today.month == 12 else 0)
            target_month = 1 if today.month == 12 else today.month + 1
        elif rel in ("trước",):
            target_year = today.year - (1 if today.month == 1 else 0)
            target_month = 12 if today.month == 1 else today.month - 1
        else:
            target_year = today.year
            target_month = today.month
        max_d = calendar.monthrange(target_year, target_month)[1]
        target_date = datetime.date(target_year, target_month, min(day, max_d))
        wd = _WEEKDAYS_VN[target_date.weekday()]

        d_str = target_date.strftime("%d/%m/%Y")
        rel_text = (
            "tháng sau"
            if rel in ("sau", "tới", "tiếp theo")
            else ("tháng trước" if rel == "trước" else "tháng này")
        )
        return {
            "type": "day_of_relative_month",
            "target_date": d_str,
            "weekday": wd,
            "explanation": f"Ngày **{day} {rel_text}** (ngày {d_str}) là ngày **{wd}**.",
        }

    # Hoặc người dùng chỉnh sửa: 'tháng sau chứ không phải năm sau'
    if "tháng sau" in q and (
        "không phải năm sau" in q or "chứ không phải" in q or "không phải năm" in q
    ):
        target_year = today.year + (1 if today.month == 12 else 0)
        target_month = 1 if today.month == 12 else today.month + 1
        target_date = datetime.date(
            target_year,
            target_month,
            min(today.day, calendar.monthrange(target_year, target_month)[1]),
        )
        wd = _WEEKDAYS_VN[target_date.weekday()]
        return {
            "type": "clarification_next_month",
            "target_date": target_date.strftime("%d/%m/%Y"),
            "weekday": wd,
            "explanation": f"Dạ hiểu rồi ạ! Tính theo **tháng sau** (tháng {target_month:02d}/{target_year}), ngày {today.day} tháng sau là ngày **{target_date.strftime('%d/%m/%Y')}** (**{wd}**).",
        }

    # 6. 'N tháng nữa', 'sau N tháng', 'N tháng sau', 'N tháng trước' (khoảng thời gian)
    add_months_match = re.search(r"(?:sau\s+)?(\d+)\s+tháng(?:\s+(nữa|trước|sau))?", q)
    if add_months_match:
        months = int(add_months_match.group(1))
        direction = add_months_match.group(2) or ("sau" if "sau" in q else "nữa")
        if direction == "trước":
            m_total = today.month - 1 - months
            new_year = today.year + m_total // 12
            new_month = m_total % 12 + 1
            max_day = calendar.monthrange(new_year, new_month)[1]
            target_date = datetime.date(new_year, new_month, min(today.day, max_day))
            wd = target_date.weekday()
            return {
                "type": "sub_months",
                "months_subtracted": months,
                "target_date": target_date.strftime("%d/%m/%Y"),
                "weekday": _WEEKDAYS_VN[wd],
                "explanation": f"{months} tháng trước (tính từ {today.strftime('%d/%m/%Y')}) là ngày **{target_date.strftime('%d/%m/%Y')}** ({_WEEKDAYS_VN[wd]}).",
            }
        else:
            m_total = today.month - 1 + months
            new_year = today.year + m_total // 12
            new_month = m_total % 12 + 1
            max_day = calendar.monthrange(new_year, new_month)[1]
            target_date = datetime.date(new_year, new_month, min(today.day, max_day))
            wd = target_date.weekday()
            return {
                "type": "add_months",
                "months_added": months,
                "target_date": target_date.strftime("%d/%m/%Y"),
                "weekday": _WEEKDAYS_VN[wd],
                "explanation": f"{months} tháng sau (ngày **{target_date.strftime('%d/%m/%Y')}**) là ngày **{_WEEKDAYS_VN[wd]}**.",
            }

    # 6. 'N năm nữa', 'sau N năm', 'N năm sau', 'N năm trước'
    add_years_match = re.search(r"(?:sau\s+)?(\d+)\s+năm(?:\s+(nữa|trước|sau))?", q)
    if add_years_match:
        years = int(add_years_match.group(1))
        direction = add_years_match.group(2) or ("sau" if "sau" in q else "nữa")
        if direction == "trước":
            new_year = today.year - years
            max_day = calendar.monthrange(new_year, today.month)[1]
            target_date = datetime.date(new_year, today.month, min(today.day, max_day))
            wd = target_date.weekday()
            return {
                "type": "sub_years",
                "years_subtracted": years,
                "target_date": target_date.strftime("%d/%m/%Y"),
                "weekday": _WEEKDAYS_VN[wd],
                "explanation": f"{years} năm trước (tính từ {today.strftime('%d/%m/%Y')}) là ngày **{target_date.strftime('%d/%m/%Y')}** ({_WEEKDAYS_VN[wd]}).",
            }
        else:
            new_year = today.year + years
            max_day = calendar.monthrange(new_year, today.month)[1]
            target_date = datetime.date(new_year, today.month, min(today.day, max_day))
            wd = target_date.weekday()
            return {
                "type": "add_years",
                "years_added": years,
                "target_date": target_date.strftime("%d/%m/%Y"),
                "weekday": _WEEKDAYS_VN[wd],
                "explanation": f"{years} năm sau (ngày **{target_date.strftime('%d/%m/%Y')}**) là ngày **{_WEEKDAYS_VN[wd]}**.",
            }

    return {"error": "Không nhận diện được biểu thức ngày tháng cần tính."}
