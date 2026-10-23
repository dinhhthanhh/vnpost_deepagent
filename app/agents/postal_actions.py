"""Module thực thi nghiệp vụ hành động bưu chính (Action Services):
1. booking-agent: Tạo đơn hàng, tính cước thể tích (chuẩn 6000) và phát hành mã vận đơn.
2. complaint-agent: Tiếp nhận khiếu nại, đối chiếu thời hiệu và bồi thường bưu gửi.
Hỗ trợ cơ chế Human-in-the-Loop (HITL) xác nhận trước khi thực thi chính thức.
"""

import json
import random
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import time

# Cơ sở dữ liệu bộ nhớ lưu trữ các bản ghi đơn hàng và khiếu nại (có thể đồng bộ DB)
_DRAFT_BOOKINGS: dict[str, dict[str, Any]] = {}
_DRAFT_COMPLAINTS: dict[str, dict[str, Any]] = {}
DEFAULT_DRAFT_TTL_SECONDS = 1800  # 30 phút hiệu lực cho bản nháp

_VERIFY_FAILS: dict[tuple[str, str], dict[str, Any]] = {}
_MAX_VERIFY_FAILS = 5
_VERIFY_LOCK_SECONDS = 15 * 60


def _verify_locked(tenant: str, target_id: str) -> int:
    rec = _VERIFY_FAILS.get((tenant, target_id))
    now = time.monotonic()
    return int(rec["until"] - now) if rec and float(rec.get("until", 0)) > now else 0


def _verify_register_fail(tenant: str, target_id: str) -> None:
    now = time.monotonic()
    rec = _VERIFY_FAILS.setdefault((tenant, target_id), {"n": 0, "until": 0.0})
    if rec["until"] and float(rec["until"]) <= now:
        rec["n"], rec["until"] = 0, 0.0
    rec["n"] = int(rec["n"]) + 1
    if int(rec["n"]) >= _MAX_VERIFY_FAILS:
        rec["until"] = now + _VERIFY_LOCK_SECONDS


def _verify_reset(tenant: str, target_id: str) -> None:
    _VERIFY_FAILS.pop((tenant, target_id), None)


def _normalize_vn_phone(raw: str) -> str | None:
    d = re.sub(r"[\s.\-()]", "", raw or "")
    if d.startswith("+84"):
        d = "0" + d[3:]
    elif d.startswith("84") and len(d) == 11:
        d = "0" + d[2:]
    return d if re.fullmatch(r"0\d{9}", d) else None


def _validate_booking_input(
    sender_phone: str | None,
    receiver_phone: str | None,
    weight_grams: float | None,
    length_cm: float | None,
    width_cm: float | None,
    height_cm: float | None,
    max_kg: float | None = None,
) -> list[str]:
    errs: list[str] = []
    if _normalize_vn_phone(sender_phone or "") is None:
        errs.append("số điện thoại người gửi phải gồm 10 chữ số")
    if _normalize_vn_phone(receiver_phone or "") is None:
        errs.append("số điện thoại người nhận phải gồm 10 chữ số")
    if weight_grams is None or weight_grams <= 0:
        errs.append("khối lượng phải lớn hơn 0")
    dims = [length_cm or 0.0, width_cm or 0.0, height_cm or 0.0]
    if any(x < 0 for x in dims):
        errs.append("kích thước không được âm")
    elif any(x > 0 for x in dims) and not all(x > 0 for x in dims):
        errs.append("cần đủ cả ba chiều dài, rộng, cao (đều lớn hơn 0)")
    if max_kg and weight_grams and (weight_grams / 1000 > max_kg):
        errs.append(f"khối lượng vượt giới hạn {max_kg} kg của dịch vụ")
    return errs


def _sync_booking_draft(draft_record: dict[str, Any]) -> None:
    """Đồng bộ bản ghi đơn hàng nháp vào PostgreSQL (nếu khả dụng)."""
    try:
        from app.core.postgres import persist_draft_booking_to_postgres

        persist_draft_booking_to_postgres(draft_record)
    except Exception:
        pass


def _sync_complaint_draft(claim_record: dict[str, Any]) -> None:
    """Đồng bộ bản ghi khiếu nại nháp vào PostgreSQL (nếu khả dụng)."""
    try:
        from app.core.postgres import persist_draft_complaint_to_postgres

        persist_draft_complaint_to_postgres(claim_record)
    except Exception:
        pass


def _get_current_session_context() -> tuple[str, str | None, str | None]:
    """Lấy an toàn tenant, session_id và request_id từ context hiện tại (nếu có)."""
    try:
        from app.mcp.server import current_mcp_tenant

        m_tenant = current_mcp_tenant.get()
        if m_tenant:
            return (m_tenant, None, None)
    except Exception:
        pass
    try:
        from app.core.context import current_run

        run = current_run.get()
        if not run:
            return ("default", None, None)
        return (
            getattr(run, "tenant", "default") or "default",
            getattr(run, "session_id", None),
            getattr(run, "request_id", None),
        )
    except Exception:
        return ("default", None, None)


_CONFIRM_RE = re.compile(
    r"(?<!\w)(xác nhận|xac nhan|đồng ý|dong y|đúng rồi|dung roi|chốt|chot|tạo đi|tao di|"
    r"nộp đi|nop di|gửi đi|gui di|tiến hành|tien hanh|duyệt|duyet|ok|oke|okay|vâng|dạ|"
    r"được rồi|duoc roi|confirm|yes)(?!\w)",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(
    r"\?|(?<!\w)(chưa|chua|hông|hong|ko|hả|ha|không|khong|bao nhiêu|bao nhieu|khi nào|khi nao|thế nào|the nao|sao|vậy hả)(?!\w)",
    re.IGNORECASE,
)
_CHANGE_RE = re.compile(
    r"(?<!\w)(hủy|huy|thôi|thoi|khoan|không|khong|sửa|sua|đổi|doi|thay|cập nhật|cap nhat)(?!\w)",
    re.IGNORECASE,
)
_FILLER_RE = re.compile(
    r"(?<!\w)(tôi|em|anh|chị|nhé|nha|ạ|đi|luôn|rồi|vậy|thì|mipo|tạo|đơn|hàng|phiếu|khiếu nại|nộp|đặt|gửi)(?!\w)",
    re.I,
)
_DRAFT_ID_RE = re.compile(r"\b(?:bk|kn)-draft-[\w-]+|\bdraft-[\w-]+", re.I)


def _is_pure_confirmation(msg: str) -> bool:
    rest = _DRAFT_ID_RE.sub(" ", msg)
    rest = _CONFIRM_RE.sub(" ", rest)
    rest = _FILLER_RE.sub(" ", rest)
    rest = re.sub(r"[\s,.!?…]+", " ", rest).strip()
    return len(rest.split()) <= 2 and not re.search(r"\d{4,}", rest)


def _hitl_gate(clean_id: str, record: dict) -> str | None:
    """Trả JSON lỗi nếu KHÔNG được phép xác nhận; None nếu được phép.

    - Không có RunContext (REST /api/actions/confirm, người dùng bấm nút) -> cho phép.
    - Có RunContext (agent gọi tool) -> bắt buộc tin nhắn gần nhất là xác nhận rõ ràng.
    """
    try:
        from app.core.context import current_run

        run = current_run.get()
    except LookupError:
        return None
    except Exception:
        return json.dumps(
            {
                "status": "error",
                "message": "Không thể xác thực ngữ cảnh thực thi để xác nhận bản nháp.",
            },
            ensure_ascii=False,
        )

    if clean_id in getattr(run, "created_draft_ids", []):
        return json.dumps(
            {
                "status": "hitl_required",
                "draft_id": clean_id,
                "message": (
                    "⚠️ Chốt chặn bảo vệ HITL: Bản nháp vừa tạo trong lượt này. "
                    "Hãy trình bày bảng tóm tắt và chờ khách xác nhận ở lượt sau. Tuyệt đối không tự ý gọi xác nhận!"
                ),
            },
            ensure_ascii=False,
        )

    rec_sid, run_sid = record.get("session_id"), getattr(run, "session_id", None)
    if rec_sid and run_sid and rec_sid != run_sid:
        return json.dumps(
            {
                "status": "error",
                "message": f"Không có quyền xác nhận bản nháp của phiên khác (phiên hiện tại: {run_sid}).",
            },
            ensure_ascii=False,
        )

    msg = (getattr(run, "user_message", "") or "").strip()
    if _CHANGE_RE.search(msg):
        return json.dumps(
            {
                "status": "hitl_rejected_or_modifying",
                "draft_id": clean_id,
                "message": (
                    f"Khách hàng chưa xác nhận hoặc đang yêu cầu sửa/hủy đơn nháp (nội dung: '{msg}'). "
                    "Hãy xử lý yêu cầu sửa/hủy của khách."
                ),
            },
            ensure_ascii=False,
        )

    if _QUESTION_RE.search(msg):
        return json.dumps(
            {
                "status": "hitl_required",
                "draft_id": clean_id,
                "message": f"Tin nhắn gần nhất là câu hỏi, chưa phải xác nhận (nội dung: '{msg}').",
            },
            ensure_ascii=False,
        )

    if not _CONFIRM_RE.search(msg) or len(msg.split()) > 12 or not _is_pure_confirmation(msg):
        return json.dumps(
            {
                "status": "hitl_required",
                "draft_id": clean_id,
                "message": (
                    f"Chưa có xác nhận rõ ràng từ khách ở tin nhắn gần nhất (nội dung: '{msg}'). "
                    "Hãy hỏi lại hoặc xử lý yêu cầu sửa/hủy của khách."
                ),
            },
            ensure_ascii=False,
        )
    return None


def _is_tenant_match(t1: str | None, t2: str | None) -> bool:
    """Kiểm tra xem 2 tenant có thuộc cùng một phạm vi bảo mật hay không.
    Hỗ trợ đồng nhất bí danh 'default' và 'vnpost' cho phiên đơn tenant / môi trường cục bộ."""
    if t1 is None or t2 is None:
        return True
    s1, s2 = (t1 or "").strip(), (t2 or "").strip()
    if s1 == s2:
        return True
    if {s1, s2} <= {"default", "vnpost"}:
        return True
    return False


def _set_current_session_context(
    tenant: str = "default", session_id: str | None = None, request_id: str | None = None
):
    """Thiết lập thủ công context cho test hoặc worker."""
    from app.core.context import RunContext, current_run

    run = RunContext(
        tenant=tenant,
        request_id=request_id or "req-manual",
        max_parallel=2,
        max_tasks=4,
        session_id=session_id,
    )
    return current_run.set(run)


def _reset_current_session_context(token=None):
    """Đặt lại context về mặc định."""
    from app.core.context import current_run

    if token:
        try:
            current_run.reset(token)
            return
        except Exception:
            pass
    try:
        run = current_run.get()
        if run and hasattr(run, "created_draft_ids"):
            run.created_draft_ids.clear()
        current_run.set(None)
    except Exception:
        pass


def _is_draft_expired(record: dict[str, Any], now: datetime | None = None) -> bool:
    """Kiểm tra bản nháp đã quá thời gian hiệu lực (TTL) hay chưa."""
    if record.get("status") == "EXPIRED":
        return True
    exp_str = record.get("expires_at")
    if not exp_str:
        return False
    try:
        exp_dt = datetime.fromisoformat(exp_str)
        curr = now or _get_vn_now()
        if curr.tzinfo is None and exp_dt.tzinfo is not None:
            curr = curr.replace(tzinfo=exp_dt.tzinfo)
        elif curr.tzinfo is not None and exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=curr.tzinfo)
        return curr > exp_dt
    except Exception:
        return False


# Danh mục tỉnh/thành phố theo 3 miền địa lý (căn cứ theo /skills/bang-ma-buu-chinh-vung-cuoc/SKILL.md)
_PROVINCES_NORTH = [
    "hà giang",
    "cao bằng",
    "bắc kạn",
    "tuyên quang",
    "lào cai",
    "yên bái",
    "thái nguyên",
    "lạng sơn",
    "bắc giang",
    "phú thọ",
    "quảng ninh",
    "hà nội",
    "hải phòng",
    "bắc ninh",
    "hà nam",
    "hải dương",
    "hưng yên",
    "nam định",
    "ninh bình",
    "thái bình",
    "vĩnh phúc",
    "hòa bình",
    "sơn la",
    "điện biên",
    "lai châu",
]
_PROVINCES_CENTRAL = [
    "thanh hóa",
    "nghệ an",
    "hà tĩnh",
    "quảng bình",
    "quảng trị",
    "thừa thiên huế",
    "huế",
    "đà nẵng",
    "quảng nam",
    "quảng ngãi",
    "bình định",
]
_PROVINCES_SOUTH = [
    "phú yên",
    "khánh hòa",
    "ninh thuận",
    "bình thuận",
    "kon tum",
    "gia lai",
    "đắk lắk",
    "đắk nông",
    "lâm đồng",
    "hồ chí minh",
    "tp.hcm",
    "tp hcm",
    "hcm",
    "sài gòn",
    "bình dương",
    "bình phước",
    "tây ninh",
    "đồng nai",
    "bà rịa - vũng tàu",
    "bà rịa vũng tàu",
    "vũng tàu",
    "long an",
    "tiền giang",
    "bến tre",
    "trà vinh",
    "vĩnh long",
    "đồng tháp",
    "an giang",
    "kiên giang",
    "cần thơ",
    "hậu giang",
    "sóc trăng",
    "bạc liêu",
    "cà mau",
]


def _detect_province_and_region(address: str) -> tuple[str | None, str | None]:
    """Nhận diện tỉnh/thành phố và phân vùng miền (Bắc / Trung / Nam) theo SKILL.md."""
    addr_lower = (address or "").lower()
    for prov in _PROVINCES_SOUTH:
        if prov in addr_lower:
            canonical = "hồ chí minh" if prov in {"hcm", "tp hcm", "tp.hcm", "sài gòn"} else prov
            return canonical, "SOUTH"
    for prov in _PROVINCES_CENTRAL:
        if prov in addr_lower:
            canonical = "thừa thiên huế" if prov == "huế" else prov
            return canonical, "CENTRAL"
    for prov in _PROVINCES_NORTH:
        if prov in addr_lower:
            return prov, "NORTH"
    return None, None


def _get_vn_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Asia/Ho_Chi_Minh")
    except Exception:
        tz = timezone(timedelta(hours=7))
    return datetime.now(tz)


def _is_international_code(
    item_code: str,
    complaint_type: str = "",
    description: str = "",
    is_international: bool | None = None,
) -> bool:
    """Phân định bưu gửi nội địa hay quốc tế theo chuẩn UPU S10 và ngữ cảnh khiếu nại.

    - Chuẩn UPU S10: Mã gồm 2 chữ cái đầu + 9 số + 2 chữ cái mã quốc gia phát hành (ISO 3166-1).
    - Nếu 2 chữ cái cuối khác 'VN' (ví dụ CP...US, EE...JP, RK...CN): là bưu gửi quốc tế đến (Inbound).
    - Nếu kết thúc bằng 'VN' (ví dụ EB...VN, CP...VN, RK...VN): mặc định là bưu gửi nội địa Việt Nam
      (thời hiệu 06 tháng), trừ khi có chỉ định cờ is_international=True hoặc ngữ cảnh khiếu nại
      nêu rõ gửi đi nước ngoài (Outbound, thời hiệu 12 tháng).
    """
    if is_international is not None:
        return bool(is_international)

    clean_code = (item_code or "").strip().upper()
    if (
        len(clean_code) >= 2
        and not clean_code.endswith("VN")
        and re.match(r"^[A-Z]{2}\d{9}[A-Z]{2}$", clean_code)
    ):
        return True

    text_context = f"{complaint_type} {description}".lower()
    keywords = ["quốc tế", "nước ngoài", "ngoại quốc", "international", "outbound", "inbound"]
    if any(k in text_context for k in keywords):
        return True

    return False


def create_draft_booking(
    sender_name: str,
    sender_phone: str,
    sender_address: str,
    receiver_name: str,
    receiver_phone: str,
    receiver_address: str,
    weight_grams: int,
    length_cm: float = 0.0,
    width_cm: float = 0.0,
    height_cm: float = 0.0,
    service_type: str = "EMS",
    declared_value: float = 0.0,
) -> str:
    """Tạo bản nháp đơn gửi hàng VNPost và tính toán khối lượng quy đổi cồng kềnh (hệ số 6000),

    ước tính cước phí theo vùng. Đơn nháp cần người dùng xác nhận (HITL) trước khi phát hành mã vận đơn.
    """
    clean_sender_name = (sender_name or "").strip()
    clean_sender_phone = (sender_phone or "").strip()
    clean_sender_address = (sender_address or "").strip()
    clean_receiver_name = (receiver_name or "").strip()
    clean_receiver_phone = (receiver_phone or "").strip()
    clean_receiver_address = (receiver_address or "").strip()

    missing_fields = []
    if not clean_sender_name:
        missing_fields.append("họ tên người gửi")
    if not clean_sender_phone:
        missing_fields.append("số điện thoại người gửi")
    if not clean_sender_address:
        missing_fields.append("địa chỉ người gửi")
    if not clean_receiver_name:
        missing_fields.append("họ tên người nhận")
    if not clean_receiver_phone:
        missing_fields.append("số điện thoại người nhận")
    if not clean_receiver_address:
        missing_fields.append("địa chỉ người nhận")

    if missing_fields:
        return json.dumps(
            {
                "status": "missing_info",
                "missing_fields": missing_fields,
                "message": f"Để tạo đơn gửi hàng, vui lòng hỏi người dùng bổ sung các thông tin còn thiếu: {', '.join(missing_fields)}.",
            },
            ensure_ascii=False,
        )

    errs = _validate_booking_input(
        clean_sender_phone,
        clean_receiver_phone,
        weight_grams,
        length_cm,
        width_cm,
        height_cm,
        max_kg=None,
    )
    if errs:
        return json.dumps(
            {
                "status": "invalid_input",
                "errors": errs,
                "message": "Thông tin chưa hợp lệ: " + "; ".join(errs) + ". Vui lòng hỏi lại khách hàng.",
            },
            ensure_ascii=False,
        )

    clean_sender_phone = _normalize_vn_phone(clean_sender_phone) or clean_sender_phone
    clean_receiver_phone = _normalize_vn_phone(clean_receiver_phone) or clean_receiver_phone

    # 1. Tính toán khối lượng quy đổi thể tích theo chuẩn VNPost (hệ số 6000)
    actual_kg = round(weight_grams / 1000.0, 2)
    vol_kg = 0.0
    if length_cm > 0 and width_cm > 0 and height_cm > 0:
        vol_kg = round((length_cm * width_cm * height_cm) / 6000.0, 2)
    chargeable_kg = max(actual_kg, vol_kg)

    # 2. Xác định phân vùng cước chính xác theo 3 miền địa lý (SKILL.md)
    s_prov, s_reg = _detect_province_and_region(clean_sender_address)
    r_prov, r_reg = _detect_province_and_region(clean_receiver_address)

    if s_prov and r_prov and s_prov == r_prov:
        zone = "Vùng 1 (Nội tỉnh)"
        base_fee = 22000
        step_fee = 3500
    elif s_reg and r_reg and s_reg == r_reg:
        zone = "Vùng 2 (Nội miền)"
        base_fee = 32000
        step_fee = 5500
    else:
        zone = "Vùng 3 (Liên miền)"
        base_fee = 45000
        step_fee = 8500

    # 3. Tính cước lũy tiến (Mô phỏng ước tính để minh họa hệ thống)
    extra_kg = max(0.0, chargeable_kg - 0.5)
    est_shipping_fee = base_fee + int(extra_kg * 2 * step_fee)
    if declared_value > 0:
        # Phí khai giá 0.5%
        est_shipping_fee += int(declared_value * 0.005)

    now = _get_vn_now()
    expires_at = now + timedelta(seconds=DEFAULT_DRAFT_TTL_SECONDS)
    tenant, session_id, request_id = _get_current_session_context()
    entropy = secrets.token_hex(4).upper()
    draft_id = f"BK-DRAFT-{now.strftime('%Y%m%d')}-{entropy}"

    draft_record = {
        "draft_id": draft_id,
        "status": "WAITING_CONFIRMATION",
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "tenant": tenant,
        "session_id": session_id,
        "request_id": request_id,
        "sender": {
            "name": clean_sender_name,
            "phone": clean_sender_phone,
            "address": clean_sender_address,
            "detected_province": s_prov or "Không xác định",
            "detected_region": s_reg or "Không xác định",
        },
        "receiver": {
            "name": clean_receiver_name,
            "phone": clean_receiver_phone,
            "address": clean_receiver_address,
            "detected_province": r_prov or "Không xác định",
            "detected_region": r_reg or "Không xác định",
        },
        "parcel": {
            "weight_actual_kg": actual_kg,
            "dimensions_cm": f"{length_cm}x{width_cm}x{height_cm}"
            if vol_kg > 0
            else "Chưa đo kích thước",
            "weight_volumetric_kg": vol_kg,
            "weight_chargeable_kg": chargeable_kg,
            "is_bulky": vol_kg > actual_kg,
            "declared_value": declared_value,
        },
        "pricing": {
            "service_type": service_type.upper(),
            "zone": zone,
            "estimated_fee": est_shipping_fee,
            "estimated_fee_text": f"{est_shipping_fee:,} đ".replace(",", "."),
            "is_simulated_rate": True,
            "rate_note": "Cước phí 22.000 / 32.000 / 45.000 đ là biểu cước mô phỏng ước tính để minh họa hệ thống, không phải biểu cước chính thức của VNPost.",
        },
    }
    _DRAFT_BOOKINGS[draft_id] = draft_record
    _sync_booking_draft(draft_record)
    try:
        from app.core.context import current_run

        run = current_run.get()
        if hasattr(run, "created_draft_ids"):
            run.created_draft_ids.append(draft_id)
        run.event("draft_created", kind="booking", draft_id=draft_id, detail=draft_record)
    except Exception:
        pass

    return json.dumps(
        {
            "status": "waiting_confirmation",
            "draft_id": draft_id,
            "expires_at": expires_at.isoformat(),
            "detail": draft_record,
            "instruction": (
                f"Đã tạo bản nháp đơn hàng [{draft_id}]. Cước ước tính mô phỏng: {draft_record['pricing']['estimated_fee_text']} "
                f"(Khối lượng tính cước: {chargeable_kg} kg theo {zone}). "
                "YÊU CẦU XÁC NHẬN (HITL): Bản nháp đã lưu ở trạng thái WAITING_CONFIRMATION (hiệu lực trong 30 phút). Agent KHÔNG ĐƯỢC tự ý gọi confirm_booking trong cùng lượt này. "
                "Phải xuất trình tóm tắt thông tin cho người dùng và DỪNG LƯỢT để chờ người dùng phản hồi. "
                "Chỉ khi người dùng xác nhận/đồng ý ở lượt tiếp theo, mới gọi confirm_booking để phát hành mã vận đơn chính thức."
            ),
        },
        ensure_ascii=False,
    )


def confirm_booking(
    draft_id: str, confirmed_by_user: bool = True, tenant: str | None = None
) -> str:
    """Xác nhận đơn hàng sau khi có sự đồng ý của người dùng (HITL).

    Phát hành mã vận đơn chính thức chuẩn UPU của VNPost và lên lịch điều phối thu gom.
    """
    clean_id = (draft_id or "").strip()
    if tenant is None:
        ctx_tenant, _, _ = _get_current_session_context()
        tenant = ctx_tenant
    record = get_draft_booking(clean_id, tenant=tenant)
    if not record:
        cross_rec = _DRAFT_BOOKINGS.get(clean_id)
        if (
            cross_rec
            and tenant
            and not _is_tenant_match(cross_rec.get("tenant", "default"), tenant)
        ):
            return json.dumps(
                {
                    "status": "error",
                    "message": "Không có quyền xác nhận bản nháp đơn hàng của tenant khác.",
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "status": "error",
                "message": f"Không tìm thấy bản nháp đơn hàng với mã '{clean_id}'.",
            },
            ensure_ascii=False,
        )
    if tenant and not _is_tenant_match(record.get("tenant", "default"), tenant):
        return json.dumps(
            {
                "status": "error",
                "message": "Không có quyền xác nhận bản nháp đơn hàng của tenant khác.",
            },
            ensure_ascii=False,
        )

    # 1. Chốt chặn thuộc đúng tenant / phiên làm việc
    ctx_tenant, ctx_session_id, _ = _get_current_session_context()
    rec_session = record.get("session_id")
    if ctx_session_id and rec_session and rec_session != ctx_session_id:
        return json.dumps(
            {
                "status": "error",
                "message": f"Không có quyền xác nhận bản nháp đơn hàng của phiên khác (phiên hiện tại: {ctx_session_id}).",
            },
            ensure_ascii=False,
        )

    # 2. Chốt chặn Draft mới nhất trong phiên (chống xác nhận nhầm draft cũ)
    if ctx_session_id:
        waiting_drafts = get_session_drafts(
            session_id=ctx_session_id, tenant=tenant or ctx_tenant, status="WAITING_CONFIRMATION"
        )["bookings"]
        if waiting_drafts:
            latest_draft = max(waiting_drafts, key=lambda d: d.get("created_at", ""))
            if clean_id != latest_draft.get("draft_id"):
                return json.dumps(
                    {
                        "status": "not_latest_draft",
                        "draft_id": clean_id,
                        "message": (
                            f"Bản nháp [{clean_id}] không phải bản nháp mới nhất của phiên "
                            f"(bản nháp mới nhất là [{latest_draft.get('draft_id')}]). Vui lòng xác nhận bản nháp mới nhất."
                        ),
                    },
                    ensure_ascii=False,
                )

    now = _get_vn_now()

    # Kiểm tra hết hạn hiệu lực (TTL)
    if _is_draft_expired(record, now):
        record["status"] = "EXPIRED"
        return json.dumps(
            {
                "status": "expired",
                "message": f"Bản nháp đơn hàng {clean_id} đã hết hạn hiệu lực (quá thời hạn 30 phút). Vui lòng tạo đơn mới.",
            },
            ensure_ascii=False,
        )

    if record["status"] == "CONFIRMED":
        return json.dumps(
            {
                "status": "already_confirmed",
                "item_code": record.get("item_code"),
                "message": f"Đơn hàng {clean_id} đã được xác nhận trước đó với mã vận đơn {record.get('item_code')}.",
            },
            ensure_ascii=False,
        )

    if record["status"] in {"CANCELLED", "CANCELLED_BY_CUSTOMER"}:
        return json.dumps(
            {
                "status": "cancelled",
                "message": f"Đơn hàng {clean_id} đã bị hủy trước đó, không thể xác nhận.",
            },
            ensure_ascii=False,
        )

    if record["status"] != "WAITING_CONFIRMATION":
        return json.dumps(
            {
                "status": "error",
                "message": f"Đơn hàng {clean_id} đang ở trạng thái '{record['status']}', không thể xác nhận.",
            },
            ensure_ascii=False,
        )

    if not confirmed_by_user:
        return json.dumps(
            {
                "status": "unconfirmed",
                "message": "Chưa có sự xác nhận rõ ràng từ phía người dùng (HITL required).",
            },
            ensure_ascii=False,
        )

    # Chốt chặn vòng đời hội thoại đa tầng (Multi-layer HITL Guard)
    if (err := _hitl_gate(clean_id, record)):
        return err

    try:
        from app.core.context import current_run

        run = current_run.get()
        if hasattr(run, "actions_invoked"):
            run.actions_invoked.append("confirm_booking")
    except Exception:
        pass

    # Sinh mã vận đơn chuẩn UPU VNPost (EB...VN cho EMS, CP...VN cho Bưu kiện)
    prefix = "EB" if record["pricing"]["service_type"] == "EMS" else "CP"
    random_digits = "".join([str(random.randint(0, 9)) for _ in range(9)])
    item_code = f"{prefix}{random_digits}VN"

    pickup_time = (now + timedelta(hours=2)).strftime("%H:%M ngày %d/%m/%Y")
    record["status"] = "CONFIRMED"
    record["item_code"] = item_code
    record["confirmed_at"] = now.isoformat()
    record["pickup_schedule"] = pickup_time
    _DRAFT_BOOKINGS[clean_id] = record
    _sync_booking_draft(record)

    return json.dumps(
        {
            "status": "confirmed",
            "draft_id": clean_id,
            "item_code": item_code,
            "service_name": f"{record['pricing']['service_type']} - Bưu điện Việt Nam VNPost",
            "chargeable_weight": f"{record['parcel']['weight_chargeable_kg']} kg",
            "total_fee": record["pricing"]["estimated_fee_text"],
            "pickup_schedule": pickup_time,
            "sender": record["sender"],
            "receiver": record["receiver"],
            "message": (
                f"🎉 Tạo đơn gửi hàng thành công! Mã vận đơn chính thức: **{item_code}**. "
                f"Cước phí ước tính: **{record['pricing']['estimated_fee_text']}**. "
                f"Bưu tá VNPost sẽ liên hệ lấy hàng vào khoảng {pickup_time}."
            ),
        },
        ensure_ascii=False,
    )


def create_draft_complaint(
    item_code: str,
    customer_name: str,
    customer_phone: str,
    complaint_type: str,
    description: str,
    claimed_amount: float = 0.0,
    sent_date: str | None = None,
    is_international: bool | None = None,
) -> str:
    """Tiếp nhận yêu cầu khiếu nại bưu gửi VNPost.

    Kiểm tra thời hiệu (06 tháng nội địa, 12 tháng quốc tế theo quy trình bồi thường SKILL.md),
    tính định mức bồi thường trần và lập hồ sơ nháp chờ duyệt (HITL).
    """
    clean_code = (item_code or "").strip().upper()
    clean_customer_name = (customer_name or "").strip()
    clean_customer_phone = (customer_phone or "").strip()
    clean_complaint_type = (complaint_type or "").strip()

    missing_fields = []
    if not clean_code:
        missing_fields.append("mã vận đơn (item_code)")
    if not clean_customer_name:
        missing_fields.append("họ tên khách hàng")
    if not clean_customer_phone:
        missing_fields.append("số điện thoại liên hệ")
    if not clean_complaint_type:
        missing_fields.append("lý do khiếu nại (mất hàng, hư hỏng, phát chậm...)")

    if missing_fields:
        return json.dumps(
            {
                "status": "missing_info",
                "missing_fields": missing_fields,
                "message": f"Để mở phiếu khiếu nại, vui lòng hỏi khách hàng bổ sung các thông tin còn thiếu: {', '.join(missing_fields)}.",
            },
            ensure_ascii=False,
        )

    now = _get_vn_now()

    # Phân định nội địa / quốc tế chuẩn UPU S10
    is_intl = _is_international_code(
        clean_code,
        complaint_type=clean_complaint_type,
        description=description,
        is_international=is_international,
    )
    limit_months = 12 if is_intl else 6

    # 1. Kiểm tra thời hiệu khiếu nại bằng code (6 tháng nội địa, 12 tháng quốc tế) nếu có ngày gửi
    sent_dt = None
    if sent_date and sent_date.strip():
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
            try:
                sent_dt = datetime.strptime(sent_date.strip(), fmt).replace(tzinfo=now.tzinfo)
                break
            except ValueError:
                pass
        if sent_dt:
            delta_days = (now - sent_dt).days
            max_days = 366 if is_intl else 183
            if delta_days > max_days:
                scope_str = "quốc tế (12 tháng)" if is_intl else "nội địa (06 tháng)"
                return json.dumps(
                    {
                        "status": "rejected_expired",
                        "item_code": clean_code,
                        "scope": "Quốc tế" if is_intl else "Nội địa",
                        "sent_date": sent_date.strip(),
                        "elapsed_days": delta_days,
                        "limit_months": limit_months,
                        "message": (
                            f"Từ chối tiếp nhận khiếu nại cho bưu phẩm {clean_code}: "
                            f"Ngày gửi ({sent_date.strip()}, đã trôi qua {delta_days} ngày) vượt quá thời hiệu khiếu nại quy định của VNPost "
                            f"cho dịch vụ {scope_str} tính từ ngày gửi."
                        ),
                    },
                    ensure_ascii=False,
                )
            if sent_dt:
                statute_of_limitations_text = (
                    f"Đã xác minh bằng code: Còn trong thời hiệu ({limit_months:02d} tháng; đã gửi {delta_days} ngày trước, ngày gửi {sent_date.strip()})"
                )
            else:
                statute_of_limitations_text = (
                    f"Chưa thể xác thực định dạng ngày gửi ({sent_date.strip()}) - Thời hiệu quy định là {limit_months:02d} tháng"
                )
    else:
        statute_of_limitations_text = (
            f"Chưa xác minh ngày gửi (chưa cung cấp ngày gửi hàng; thời hiệu quy định là {limit_months:02d} tháng tính từ ngày gửi)"
        )

    # 2. Phân loại loại sự cố và tính toán định mức bồi thường
    ctype_lower = clean_complaint_type.lower()
    if any(k in ctype_lower for k in ["mất", "that lac", "lost"]):
        nature = "Mất mát bưu phẩm hoàn toàn"
        rule = "Khai giá bồi thường 100%; Không khai giá hoàn cước + tối đa 04 lần cước dịch vụ."
        if claimed_amount > 0:
            suggested_comp = float(claimed_amount)
            proposed_comp_text = f"{int(claimed_amount):,} đ (theo giá trị khai báo)".replace(
                ",", "."
            )
        else:
            suggested_comp = 0.0
            proposed_comp_text = (
                "Thẩm định theo giá trị thực tế (tối đa 04 lần cước nếu không khai giá)"
            )
    elif any(k in ctype_lower for k in ["hỏng", "vỡ", "rách", "damage"]):
        nature = "Hư hỏng bưu gửi"
        rule = "Bồi thường theo tỷ lệ hư hỏng thực tế căn cứ biên bản đồng kiểm."
        if claimed_amount > 0:
            suggested_comp = float(claimed_amount)
            proposed_comp_text = f"{int(claimed_amount):,} đ (ước tính theo khai báo)".replace(
                ",", "."
            )
        else:
            suggested_comp = 0.0
            proposed_comp_text = "Thẩm định theo tỷ lệ hư hại thực tế căn cứ biên bản đồng kiểm"
    elif any(k in ctype_lower for k in ["chậm", "trễ", "delay"]):
        nature = "Bưu phẩm phát chậm so với cam kết toàn trình"
        rule = "Hoàn trả 100% cước dịch vụ đã thu."
        suggested_comp = float(claimed_amount) if claimed_amount > 0 else 0.0
        proposed_comp_text = (
            f"{int(claimed_amount):,} đ (hoàn cước)".replace(",", ".")
            if claimed_amount > 0
            else "Hoàn trả 100% cước dịch vụ phát sinh thực tế"
        )
    else:
        nature = "Khiếu nại nghiệp vụ khác"
        rule = "Theo quy chế giải quyết khiếu nại khách hàng VNPost."
        suggested_comp = float(claimed_amount)
        proposed_comp_text = (
            f"{int(claimed_amount):,} đ".replace(",", ".")
            if claimed_amount > 0
            else "Thẩm định theo thực tế giải quyết khiếu nại"
        )

    entropy = secrets.token_hex(4).upper()
    draft_ticket_id = f"KN-DRAFT-{now.strftime('%Y%m%d')}-{entropy}"
    expires_at = now + timedelta(seconds=DEFAULT_DRAFT_TTL_SECONDS)
    tenant, session_id, request_id = _get_current_session_context()

    claim_record = {
        "draft_ticket_id": draft_ticket_id,
        "status": "WAITING_CONFIRMATION",
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "tenant": tenant,
        "session_id": session_id,
        "request_id": request_id,
        "item_code": clean_code,
        "is_international": is_intl,
        "customer": {
            "name": clean_customer_name,
            "phone": clean_customer_phone,
        },
        "complaint_details": {
            "type": nature,
            "description": description.strip(),
            "claimed_amount": claimed_amount,
            "sent_date": sent_date.strip() if sent_date else None,
            "is_international": is_intl,
            "scope": "Quốc tế" if is_intl else "Nội địa",
            "statute_of_limitations": statute_of_limitations_text,
            "compensation_policy": rule,
            "proposed_compensation": suggested_comp,
            "proposed_compensation_text": proposed_comp_text,
        },
    }
    _DRAFT_COMPLAINTS[draft_ticket_id] = claim_record
    _sync_complaint_draft(claim_record)
    try:
        from app.core.context import current_run

        run = current_run.get()
        if hasattr(run, "created_draft_ids"):
            run.created_draft_ids.append(draft_ticket_id)
        run.event("draft_created", kind="complaint", draft_id=draft_ticket_id, detail=claim_record)
    except Exception:
        pass

    return json.dumps(
        {
            "status": "waiting_confirmation",
            "draft_ticket_id": draft_ticket_id,
            "expires_at": expires_at.isoformat(),
            "detail": claim_record,
            "instruction": (
                f"Đã lập phiếu khiếu nại nháp [{draft_ticket_id}] cho bưu gửi {clean_code} ({claim_record['complaint_details']['scope']}). "
                f"Loại khiếu nại: {nature}. Mức bồi thường đề xuất: {claim_record['complaint_details']['proposed_compensation_text']}. "
                "YÊU CẦU XÁC NHẬN (HITL): Bản nháp đã lưu ở trạng thái WAITING_CONFIRMATION (hiệu lực trong 30 phút). Agent KHÔNG ĐƯỢC tự ý gọi confirm_complaint trong cùng lượt này. "
                "Hãy tóm tắt hồ sơ trên và hỏi người dùng có đồng ý gửi khiếu nại chính thức không, sau đó DỪNG LƯỢT. "
                "Khi người dùng xác nhận ở lượt tiếp theo, mới gọi confirm_complaint để cấp mã Ticket chính thức."
            ),
        },
        ensure_ascii=False,
    )


def confirm_complaint(
    draft_ticket_id: str, confirmed_by_user: bool = True, tenant: str | None = None
) -> str:
    """Xác nhận nộp khiếu nại chính thức vào hệ thống CRM CSKH VNPost sau khi có sự đồng ý của khách hàng (HITL)."""
    clean_id = (draft_ticket_id or "").strip()
    if tenant is None:
        ctx_tenant, _, _ = _get_current_session_context()
        tenant = ctx_tenant
    record = get_draft_complaint(clean_id, tenant=tenant)
    if not record:
        cross_rec = _DRAFT_COMPLAINTS.get(clean_id)
        if (
            cross_rec
            and tenant
            and not _is_tenant_match(cross_rec.get("tenant", "default"), tenant)
        ):
            return json.dumps(
                {
                    "status": "error",
                    "message": "Không có quyền xác nhận phiếu khiếu nại của tenant khác.",
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "status": "error",
                "message": f"Không tìm thấy phiếu khiếu nại nháp '{clean_id}'.",
            },
            ensure_ascii=False,
        )
    if tenant and not _is_tenant_match(record.get("tenant", "default"), tenant):
        return json.dumps(
            {
                "status": "error",
                "message": "Không có quyền xác nhận phiếu khiếu nại của tenant khác.",
            },
            ensure_ascii=False,
        )

    # 1. Chốt chặn thuộc đúng tenant / phiên làm việc
    ctx_tenant, ctx_session_id, _ = _get_current_session_context()
    rec_session = record.get("session_id")
    if ctx_session_id and rec_session and rec_session != ctx_session_id:
        return json.dumps(
            {
                "status": "error",
                "message": f"Không có quyền xác nhận phiếu khiếu nại của phiên khác (phiên hiện tại: {ctx_session_id}).",
            },
            ensure_ascii=False,
        )

    # 2. Chốt chặn Draft mới nhất trong phiên (chống xác nhận nhầm draft cũ)
    if ctx_session_id:
        waiting_complaints = get_session_drafts(
            session_id=ctx_session_id, tenant=tenant or ctx_tenant, status="WAITING_CONFIRMATION"
        )["complaints"]
        if waiting_complaints:
            latest_complaint = max(waiting_complaints, key=lambda d: d.get("created_at", ""))
            if clean_id != latest_complaint.get("draft_ticket_id"):
                return json.dumps(
                    {
                        "status": "not_latest_draft",
                        "draft_ticket_id": clean_id,
                        "message": (
                            f"Phiếu khiếu nại [{clean_id}] không phải bản nháp mới nhất của phiên "
                            f"(bản nháp mới nhất là [{latest_complaint.get('draft_ticket_id')}]). Vui lòng xác nhận bản nháp mới nhất."
                        ),
                    },
                    ensure_ascii=False,
                )

    now = _get_vn_now()

    # Kiểm tra hết hạn hiệu lực (TTL)
    if _is_draft_expired(record, now):
        record["status"] = "EXPIRED"
        return json.dumps(
            {
                "status": "expired",
                "message": f"Phiếu khiếu nại nháp {clean_id} đã hết hạn hiệu lực (quá thời hạn 30 phút). Vui lòng lập phiếu mới.",
            },
            ensure_ascii=False,
        )

    if record["status"] == "SUBMITTED":
        return json.dumps(
            {
                "status": "already_submitted",
                "ticket_number": record.get("ticket_number"),
                "message": f"Phiếu khiếu nại {clean_id} đã được gửi trước đó với mã số {record.get('ticket_number')}.",
            },
            ensure_ascii=False,
        )

    if record["status"] in {"CANCELLED", "CANCELLED_BY_CUSTOMER"}:
        return json.dumps(
            {
                "status": "cancelled",
                "message": f"Phiếu khiếu nại {clean_id} đã bị hủy trước đó, không thể nộp chính thức.",
            },
            ensure_ascii=False,
        )

    if record["status"] != "WAITING_CONFIRMATION":
        return json.dumps(
            {
                "status": "error",
                "message": f"Phiếu khiếu nại {clean_id} đang ở trạng thái '{record['status']}', không thể xác nhận.",
            },
            ensure_ascii=False,
        )

    if not confirmed_by_user:
        return json.dumps(
            {
                "status": "unconfirmed",
                "message": "Chưa có sự xác nhận rõ ràng từ phía khách hàng (HITL required).",
            },
            ensure_ascii=False,
        )

    # Chốt chặn vòng đời hội thoại đa tầng (Multi-layer HITL Guard)
    if (err := _hitl_gate(clean_id, record)):
        return err

    try:
        from app.core.context import current_run

        run = current_run.get()
        if hasattr(run, "actions_invoked"):
            run.actions_invoked.append("confirm_complaint")
    except Exception:
        pass

    ticket_number = f"KN-VNPOST-{now.strftime('%Y')}-{random.randint(10000, 99999)}"

    # SLA theo SKILL.md: 20 ngày làm việc nội địa, 30 ngày làm việc quốc tế (EMS)
    is_intl = record.get("is_international") or record.get("complaint_details", {}).get(
        "is_international", False
    )
    sla_days = 30 if is_intl else 20
    deadline = (now + timedelta(days=int(sla_days * 1.4))).strftime("%d/%m/%Y")

    record["status"] = "SUBMITTED"
    record["ticket_number"] = ticket_number
    record["submitted_at"] = now.isoformat()
    record["sla_days"] = sla_days
    record["sla_deadline"] = deadline
    _DRAFT_COMPLAINTS[clean_id] = record
    _sync_complaint_draft(record)

    scope_name = "Quốc tế" if is_intl else "Nội địa"
    return json.dumps(
        {
            "status": "submitted",
            "draft_ticket_id": clean_id,
            "ticket_number": ticket_number,
            "item_code": record["item_code"],
            "scope": scope_name,
            "complaint_type": record["complaint_details"]["type"],
            "proposed_compensation": record["complaint_details"]["proposed_compensation_text"],
            "sla_resolution": f"Tối đa {sla_days} ngày làm việc (trước ngày {deadline})",
            "customer": record["customer"],
            "message": (
                f"✅ Hồ sơ khiếu nại đã được chuyển chính thức ({scope_name}) sang Tổng đài CSKH VNPost! "
                f"Mã tra cứu Ticket: **{ticket_number}** (bưu gửi: {record['item_code']}). "
                f"Thời hạn giải quyết cam kết: tối đa {sla_days} ngày làm việc (hạn chót: {deadline}). "
                "Chuyên viên bưu điện sẽ liên hệ trực tiếp qua số điện thoại của bạn để giải quyết chi trả bồi thường."
            ),
        },
        ensure_ascii=False,
    )


def update_draft_booking(
    draft_id: str,
    sender_name: str | None = None,
    sender_phone: str | None = None,
    sender_address: str | None = None,
    receiver_name: str | None = None,
    receiver_phone: str | None = None,
    receiver_address: str | None = None,
    weight_grams: int | None = None,
    length_cm: float | None = None,
    width_cm: float | None = None,
    height_cm: float | None = None,
    service_type: str | None = None,
    declared_value: float | None = None,
    tenant: str | None = None,
) -> str:
    """Cập nhật thông tin bản nháp đơn hàng trước khi người dùng xác nhận duyệt (HITL)."""
    clean_id = (draft_id or "").strip()
    if tenant is None:
        ctx_tenant, _, _ = _get_current_session_context()
        tenant = ctx_tenant
    record = get_draft_booking(clean_id, tenant=tenant)
    if not record:
        cross_rec = _DRAFT_BOOKINGS.get(clean_id)
        if (
            cross_rec
            and tenant
            and not _is_tenant_match(cross_rec.get("tenant", "default"), tenant)
        ):
            return json.dumps(
                {"status": "error", "message": "Không có quyền cập nhật bản nháp của tenant khác."},
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "status": "error",
                "message": f"Không tìm thấy bản nháp '{clean_id}'.",
            },
            ensure_ascii=False,
        )
    if tenant and not _is_tenant_match(record.get("tenant", "default"), tenant):
        return json.dumps(
            {"status": "error", "message": "Không có quyền cập nhật bản nháp của tenant khác."},
            ensure_ascii=False,
        )

    now = _get_vn_now()
    if _is_draft_expired(record, now):
        record["status"] = "EXPIRED"
        return json.dumps(
            {"status": "expired", "message": f"Bản nháp {clean_id} đã hết hạn hiệu lực."},
            ensure_ascii=False,
        )

    if record["status"] != "WAITING_CONFIRMATION":
        return json.dumps(
            {
                "status": "error",
                "message": f"Bản nháp {clean_id} ở trạng thái '{record['status']}', không thể sửa.",
            },
            ensure_ascii=False,
        )

    # Cập nhật thông tin người gửi nếu có
    if sender_name is not None and sender_name.strip():
        record["sender"]["name"] = sender_name.strip()
    if sender_phone is not None and sender_phone.strip():
        norm_s = _normalize_vn_phone(sender_phone)
        if not norm_s:
            return json.dumps(
                {
                    "status": "invalid_input",
                    "message": "Số điện thoại người gửi phải gồm 10 chữ số.",
                },
                ensure_ascii=False,
            )
        record["sender"]["phone"] = norm_s
    if sender_address is not None and sender_address.strip():
        record["sender"]["address"] = sender_address.strip()
        s_prov, s_reg = _detect_province_and_region(sender_address.strip())
        record["sender"]["detected_province"] = s_prov or "Không xác định"
        record["sender"]["detected_region"] = s_reg or "Không xác định"

    # Cập nhật thông tin người nhận nếu có
    if receiver_name is not None and receiver_name.strip():
        record["receiver"]["name"] = receiver_name.strip()
    if receiver_phone is not None and receiver_phone.strip():
        norm_r = _normalize_vn_phone(receiver_phone)
        if not norm_r:
            return json.dumps(
                {
                    "status": "invalid_input",
                    "message": "Số điện thoại người nhận phải gồm 10 chữ số.",
                },
                ensure_ascii=False,
            )
        record["receiver"]["phone"] = norm_r
    if receiver_address is not None and receiver_address.strip():
        record["receiver"]["address"] = receiver_address.strip()
        r_prov, r_reg = _detect_province_and_region(receiver_address.strip())
        record["receiver"]["detected_province"] = r_prov or "Không xác định"
        record["receiver"]["detected_region"] = r_reg or "Không xác định"

    # Cập nhật thông tin bưu kiện nếu có
    parcel = record["parcel"]
    recalc_needed = False
    if weight_grams is not None:
        if weight_grams <= 0:
            return json.dumps(
                {"status": "invalid_input", "message": "Khối lượng phải lớn hơn 0."},
                ensure_ascii=False,
            )
        parcel["weight_actual_kg"] = round(weight_grams / 1000.0, 2)
        recalc_needed = True

    dims_check = [length_cm, width_cm, height_cm]
    if any(x is not None and x < 0 for x in dims_check):
        return json.dumps(
            {"status": "invalid_input", "message": "Kích thước không được âm."},
            ensure_ascii=False,
        )

    dims_parts = [
        float(x) for x in re.findall(r"\d+(?:\.\d+)?", parcel.get("dimensions_cm", "")) or [0, 0, 0]
    ]
    cur_l = dims_parts[0] if len(dims_parts) > 0 else 0.0
    cur_w = dims_parts[1] if len(dims_parts) > 1 else 0.0
    cur_h = dims_parts[2] if len(dims_parts) > 2 else 0.0

    if length_cm is not None:
        cur_l = float(length_cm)
        recalc_needed = True
    if width_cm is not None:
        cur_w = float(width_cm)
        recalc_needed = True
    if height_cm is not None:
        cur_h = float(height_cm)
        recalc_needed = True

    if recalc_needed:
        vol_kg = 0.0
        if cur_l > 0 and cur_w > 0 and cur_h > 0:
            vol_kg = round((cur_l * cur_w * cur_h) / 6000.0, 2)
            parcel["dimensions_cm"] = f"{cur_l}x{cur_w}x{cur_h}"
        parcel["weight_volumetric_kg"] = vol_kg
        parcel["weight_chargeable_kg"] = max(parcel["weight_actual_kg"], vol_kg)
        parcel["is_bulky"] = vol_kg > parcel["weight_actual_kg"]

    if declared_value is not None and declared_value >= 0:
        parcel["declared_value"] = float(declared_value)

    if service_type is not None and service_type.strip():
        record["pricing"]["service_type"] = service_type.strip().upper()

    # Tính lại cước phí nếu có thay đổi vùng hoặc khối lượng
    s_prov = record["sender"].get("detected_province")
    s_reg = record["sender"].get("detected_region")
    r_prov = record["receiver"].get("detected_province")
    r_reg = record["receiver"].get("detected_region")

    if s_prov and r_prov and s_prov == r_prov and s_prov != "Không xác định":
        zone = "Vùng 1 (Nội tỉnh)"
        base_fee = 22000
        step_fee = 3500
    elif s_reg and r_reg and s_reg == r_reg and s_reg != "Không xác định":
        zone = "Vùng 2 (Nội miền)"
        base_fee = 32000
        step_fee = 5500
    else:
        zone = "Vùng 3 (Liên miền)"
        base_fee = 45000
        step_fee = 8500

    chargeable_kg = parcel["weight_chargeable_kg"]
    extra_kg = max(0.0, chargeable_kg - 0.5)
    est_fee = base_fee + int(extra_kg * 2 * step_fee)
    if parcel.get("declared_value", 0) > 0:
        est_fee += int(parcel["declared_value"] * 0.005)

    record["pricing"]["zone"] = zone
    record["pricing"]["estimated_fee"] = est_fee
    record["pricing"]["estimated_fee_text"] = f"{est_fee:,} đ".replace(",", ".")

    # Gia hạn thêm TTL kể từ thời điểm sửa đổi
    record["updated_at"] = now.isoformat()
    record["expires_at"] = (now + timedelta(seconds=DEFAULT_DRAFT_TTL_SECONDS)).isoformat()
    _DRAFT_BOOKINGS[clean_id] = record
    _sync_booking_draft(record)

    return json.dumps(
        {
            "status": "updated",
            "draft_id": clean_id,
            "detail": record,
            "message": f"Đã cập nhật bản nháp [{clean_id}]. Cước ước tính mới: {record['pricing']['estimated_fee_text']}.",
        },
        ensure_ascii=False,
    )


def update_draft_complaint(
    draft_ticket_id: str,
    complaint_type: str | None = None,
    description: str | None = None,
    claimed_amount: float | None = None,
    sent_date: str | None = None,
    tenant: str | None = None,
) -> str:
    """Cập nhật thông tin phiếu khiếu nại nháp trước khi duyệt chính thức (HITL)."""
    clean_id = (draft_ticket_id or "").strip()
    if tenant is None:
        ctx_tenant, _, _ = _get_current_session_context()
        tenant = ctx_tenant
    record = get_draft_complaint(clean_id, tenant=tenant)
    if not record:
        cross_rec = _DRAFT_COMPLAINTS.get(clean_id)
        if (
            cross_rec
            and tenant
            and not _is_tenant_match(cross_rec.get("tenant", "default"), tenant)
        ):
            return json.dumps(
                {
                    "status": "error",
                    "message": "Không có quyền cập nhật phiếu khiếu nại của tenant khác.",
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "status": "error",
                "message": f"Không tìm thấy phiếu khiếu nại nháp '{clean_id}'.",
            },
            ensure_ascii=False,
        )
    if tenant and not _is_tenant_match(record.get("tenant", "default"), tenant):
        return json.dumps(
            {
                "status": "error",
                "message": "Không có quyền cập nhật phiếu khiếu nại của tenant khác.",
            },
            ensure_ascii=False,
        )

    now = _get_vn_now()
    if _is_draft_expired(record, now):
        record["status"] = "EXPIRED"
        return json.dumps(
            {
                "status": "expired",
                "message": f"Phiếu khiếu nại nháp {clean_id} đã hết hạn hiệu lực.",
            },
            ensure_ascii=False,
        )

    if record["status"] != "WAITING_CONFIRMATION":
        return json.dumps(
            {
                "status": "error",
                "message": f"Phiếu khiếu nại nháp {clean_id} ở trạng thái '{record['status']}', không thể sửa.",
            },
            ensure_ascii=False,
        )

    details = record["complaint_details"]
    if complaint_type is not None and complaint_type.strip():
        details["type"] = complaint_type.strip()
    if description is not None and description.strip():
        details["description"] = description.strip()
    if claimed_amount is not None and claimed_amount >= 0:
        details["claimed_amount"] = float(claimed_amount)
        details["proposed_compensation"] = float(claimed_amount)
        details["proposed_compensation_text"] = f"{int(claimed_amount):,} đ".replace(",", ".")
    if sent_date is not None and sent_date.strip():
        details["sent_date"] = sent_date.strip()
        # Đối chiếu lại thời hiệu
        is_intl = record.get("is_international", False)
        limit_months = 12 if is_intl else 6
        sent_dt = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                sent_dt = datetime.strptime(sent_date.strip(), fmt).replace(tzinfo=now.tzinfo)
                break
            except ValueError:
                pass
        if sent_dt:
            delta_days = (now - sent_dt).days
            max_days = limit_months * 30.5
            if delta_days > max_days:
                return json.dumps(
                    {
                        "status": "rejected_expired",
                        "draft_ticket_id": clean_id,
                        "message": f"Ngày gửi mới ({sent_date.strip()}) đã vượt quá thời hiệu khiếu nại quy định ({limit_months} tháng).",
                    },
                    ensure_ascii=False,
                )
            details["statute_of_limitations"] = (
                f"Đã xác minh: Còn trong thời hiệu ({limit_months:02d} tháng kể từ ngày gửi {sent_date.strip()})"
            )

    record["updated_at"] = now.isoformat()
    record["expires_at"] = (now + timedelta(seconds=DEFAULT_DRAFT_TTL_SECONDS)).isoformat()
    _DRAFT_COMPLAINTS[clean_id] = record
    _sync_complaint_draft(record)

    return json.dumps(
        {
            "status": "updated",
            "draft_ticket_id": clean_id,
            "detail": record,
            "message": f"Đã cập nhật phiếu khiếu nại nháp [{clean_id}].",
        },
        ensure_ascii=False,
    )


def cancel_draft_booking(
    draft_id: str = "",
    verification_phone: str = "",
    tenant: str | None = None,
    session_id: str | None = None,
    is_rest: bool = False,
) -> str:
    """Hủy đơn hàng nháp theo yêu cầu của người dùng.

    Tham số:
    - draft_id: Mã đơn nháp (BK-DRAFT-...).
    - verification_phone: 4 số cuối hoặc toàn bộ số điện thoại người gửi (bắt buộc khi hủy từ session khác hoặc REST API).
    - tenant: Định danh tenant của người dùng yêu cầu hủy (chống IDOR xuyên tenant).
    - session_id: Mã phiên hội thoại yêu cầu hủy.
    - is_rest: Đánh dấu yêu cầu xuất phát từ REST API công khai.
    """
    clean_id = (draft_id or "").strip()
    if tenant is None:
        ctx_tenant, _, _ = _get_current_session_context()
        tenant = ctx_tenant
    if not clean_id:
        _, s_id, _ = _get_current_session_context()
        caller_sid = session_id or s_id
        drafts = get_session_drafts(
            session_id=caller_sid, tenant=tenant, status="WAITING_CONFIRMATION"
        )["bookings"]
        if drafts:
            clean_id = drafts[-1]["draft_id"]
        else:
            return json.dumps(
                {
                    "status": "error",
                    "message": "Không tìm thấy đơn nháp nào trong phiên hiện tại để hủy.",
                },
                ensure_ascii=False,
            )

    record = get_draft_booking(clean_id, tenant=tenant)
    if not record:
        cross_rec = _DRAFT_BOOKINGS.get(clean_id)
        if (
            cross_rec
            and tenant
            and not _is_tenant_match(cross_rec.get("tenant", "default"), tenant)
        ):
            return json.dumps(
                {"status": "error", "message": "Không có quyền hủy đơn nháp của tenant khác."},
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "status": "error",
                "message": f"Không tìm thấy đơn nháp '{clean_id}'.",
            },
            ensure_ascii=False,
        )
    if tenant and not _is_tenant_match(record.get("tenant", "default"), tenant):
        return json.dumps(
            {"status": "error", "message": "Không có quyền hủy đơn nháp của tenant khác."},
            ensure_ascii=False,
        )
    if record["status"] == "CONFIRMED":
        return json.dumps(
            {
                "status": "error",
                "message": f"Đơn hàng '{clean_id}' đã phát hành vận đơn ({record.get('item_code')}). Vui lòng sử dụng công cụ cancel_booking để hủy lấy hàng.",
            },
            ensure_ascii=False,
        )
    if record["status"] in {"CANCELLED", "CANCELLED_BY_CUSTOMER"}:
        return json.dumps(
            {
                "status": "already_cancelled",
                "draft_id": clean_id,
                "message": f"Đơn nháp {clean_id} đã ở trạng thái đã hủy.",
            },
            ensure_ascii=False,
        )

    # BẢO VỆ CHÍNH CHỦ (Phone Identity Verification):
    # Yêu cầu xác thực SĐT nếu gọi ngoài phiên tạo ban đầu hoặc qua REST API không gắn session gốc
    orig_session_id = record.get("session_id")
    _, current_session_id, _ = _get_current_session_context()
    caller_session_id = session_id or current_session_id
    needs_verification = False
    if orig_session_id and orig_session_id != caller_session_id:
        needs_verification = True
    elif is_rest and not (
        orig_session_id and caller_session_id and orig_session_id == caller_session_id
    ):
        needs_verification = True

    if needs_verification:
        lock_key = clean_id
        left = _verify_locked(tenant or "default", lock_key)
        if left > 0:
            return json.dumps(
                {
                    "status": "verification_locked",
                    "draft_id": clean_id,
                    "message": f"Đã nhập sai quá nhiều lần. Vui lòng thử lại sau {left // 60 + 1} phút hoặc liên hệ tổng đài/bưu cục để được hỗ trợ.",
                },
                ensure_ascii=False,
            )

        sender_phone = (
            record.get("sender", {}).get("phone")
            or record.get("sender_phone")
            or (record.get("detail", {}).get("sender", {}).get("phone"))
            or ""
        )
        clean_sender = re.sub(r"\D", "", sender_phone or "")
        if not clean_sender:
            return json.dumps(
                {
                    "status": "verification_unavailable",
                    "draft_id": clean_id,
                    "message": "Đơn này chưa có SĐT người gửi để xác minh. Vui lòng liên hệ bưu cục hoặc tổng đài để hủy đơn.",
                },
                ensure_ascii=False,
            )

        clean_verif = re.sub(r"\D", "", verification_phone or "")
        if not clean_verif:
            masked = f"...{clean_sender[-4:]}" if len(clean_sender) >= 4 else "***"
            return json.dumps(
                {
                    "status": "requires_verification",
                    "draft_id": clean_id,
                    "masked_phone": masked,
                    "message": (
                        f"🔒 BẢO VỆ CHÍNH CHỦ: Yêu cầu hủy đơn nháp [{clean_id}] thực hiện ngoài phiên tạo ban đầu. "
                        f"Để đảm bảo an toàn, vui lòng cung cấp 4 số cuối của Số điện thoại người gửi "
                        f"(SĐT đuôi {masked}) để xác nhận hủy đơn."
                    ),
                },
                ensure_ascii=False,
            )
        is_matched = clean_verif == clean_sender or (
            len(clean_verif) >= 4 and clean_sender.endswith(clean_verif)
        )
        if not is_matched:
            _verify_register_fail(tenant or "default", lock_key)
            return json.dumps(
                {
                    "status": "verification_failed",
                    "draft_id": clean_id,
                    "message": "❌ XÁC THỰC THẤT BẠI: Số điện thoại xác minh không khớp với thông tin người gửi của đơn này. Yêu cầu hủy bị từ chối.",
                },
                ensure_ascii=False,
            )
        _verify_reset(tenant or "default", lock_key)

    record["status"] = "CANCELLED"
    _DRAFT_BOOKINGS[clean_id] = record
    _sync_booking_draft(record)
    return json.dumps(
        {
            "status": "cancelled",
            "draft_id": clean_id,
            "message": f"Đã hủy đơn nháp {clean_id} thành công.",
        },
        ensure_ascii=False,
    )


def cancel_booking(
    item_code_or_draft_id: str = "",
    reason: str = "",
    verification_phone: str = "",
    tenant: str | None = None,
    session_id: str | None = None,
    is_rest: bool = False,
) -> str:
    """Hủy đơn hàng gửi bưu phẩm VNPost (hỗ trợ cả đơn nháp lẫn đơn hàng đã xác nhận phát hành mã vận đơn trước khi bưu phẩm được bưu tá thu gom).

    Tham số:
    - item_code_or_draft_id: Mã vận đơn chuẩn UPU (EB...VN, CP...VN) hoặc mã đơn nháp (BK-DRAFT-...). Nếu để trống, tự động tìm đơn hàng gần nhất trong phiên.
    - reason: Lý do hủy đơn hàng (ví dụ: 'Khách đổi ý', 'Gửi kênh khác', 'Sai địa chỉ').
    - verification_phone: 4 số cuối hoặc toàn bộ số điện thoại người gửi (bắt buộc khi hủy từ session khác hoặc REST API).
    - tenant: Định danh tenant của người dùng yêu cầu hủy (chống IDOR).
    - session_id: Mã phiên hội thoại yêu cầu hủy.
    - is_rest: Đánh dấu yêu cầu xuất phát từ REST API công khai.
    """
    clean_id = (item_code_or_draft_id or "").strip()
    now = _get_vn_now()
    target_record = None
    if tenant is None:
        ctx_tenant, _, _ = _get_current_session_context()
        tenant = ctx_tenant

    if clean_id:
        target_record = get_draft_booking(clean_id, tenant=tenant)
        if not target_record:
            for rec in _DRAFT_BOOKINGS.values():
                if rec.get("item_code") == clean_id.upper() and (
                    tenant is None or _is_tenant_match(rec.get("tenant", "default"), tenant)
                ):
                    target_record = rec
                    break
        if not target_record and tenant:
            cross_rec = _DRAFT_BOOKINGS.get(clean_id)
            if not cross_rec:
                for rec in _DRAFT_BOOKINGS.values():
                    if rec.get("item_code") == clean_id.upper():
                        cross_rec = rec
                        break
            if cross_rec and not _is_tenant_match(cross_rec.get("tenant", "default"), tenant):
                return json.dumps(
                    {"status": "error", "message": "Không có quyền hủy đơn hàng của tenant khác."},
                    ensure_ascii=False,
                )
    else:
        _, s_id, _ = _get_current_session_context()
        caller_sid = session_id or s_id
        data = get_session_drafts(session_id=caller_sid, tenant=tenant)
        active = [
            b for b in data["bookings"] if b.get("status") in {"WAITING_CONFIRMATION", "CONFIRMED"}
        ]
        if active:
            target_record = active[-1]
        else:
            return json.dumps(
                {
                    "status": "error",
                    "message": "Không tìm thấy đơn hàng nào trong phiên hội thoại hiện tại để hủy.",
                },
                ensure_ascii=False,
            )

    if target_record:
        if tenant and not _is_tenant_match(target_record.get("tenant", "default"), tenant):
            return json.dumps(
                {"status": "error", "message": "Không có quyền hủy đơn hàng của tenant khác."},
                ensure_ascii=False,
            )
        status = target_record.get("status")
        draft_id = target_record.get("draft_id")
        item_code = target_record.get("item_code")
        orig_session_id = target_record.get("session_id")
        _, current_session_id, _ = _get_current_session_context()
        caller_session_id = session_id or current_session_id

        # BẢO VỆ CHÍNH CHỦ (Phone Identity Verification):
        # Yêu cầu xác thực SĐT nếu gọi ngoài phiên tạo ban đầu hoặc qua REST API không gắn session gốc
        needs_verification = False
        if orig_session_id and orig_session_id != caller_session_id:
            needs_verification = True
        elif is_rest and not (
            orig_session_id and caller_session_id and orig_session_id == caller_session_id
        ):
            needs_verification = True

        if needs_verification:
            lock_key = (item_code or draft_id or clean_id or "unknown")
            left = _verify_locked(tenant or "default", lock_key)
            if left > 0:
                return json.dumps(
                    {
                        "status": "verification_locked",
                        "draft_id": draft_id,
                        "item_code": item_code,
                        "message": f"Đã nhập sai quá nhiều lần. Vui lòng thử lại sau {left // 60 + 1} phút hoặc liên hệ tổng đài/bưu cục để được hỗ trợ.",
                    },
                    ensure_ascii=False,
                )

            sender_phone = (
                target_record.get("sender", {}).get("phone")
                or target_record.get("sender_phone")
                or (target_record.get("detail", {}).get("sender", {}).get("phone"))
                or ""
            )
            clean_sender = re.sub(r"\D", "", sender_phone or "")
            if not clean_sender:
                return json.dumps(
                    {
                        "status": "verification_unavailable",
                        "draft_id": draft_id,
                        "item_code": item_code,
                        "message": "Đơn này chưa có SĐT người gửi để xác minh. Vui lòng liên hệ bưu cục hoặc tổng đài để hủy đơn.",
                    },
                    ensure_ascii=False,
                )

            clean_verif = re.sub(r"\D", "", verification_phone or "")
            if not clean_verif:
                masked = f"...{clean_sender[-4:]}" if len(clean_sender) >= 4 else "***"
                return json.dumps(
                    {
                        "status": "requires_verification",
                        "draft_id": draft_id,
                        "item_code": item_code,
                        "masked_phone": masked,
                        "message": (
                            f"🔒 BẢO VỆ CHÍNH CHỦ: Yêu cầu hủy đơn hàng [{item_code or draft_id}] thực hiện ngoài phiên tạo ban đầu. "
                            f"Để ngăn chặn người lạ hủy nhầm hoặc phá hoại đơn hàng, vui lòng cung cấp 4 số cuối của "
                            f"Số điện thoại người gửi (SĐT đuôi {masked}) để xác nhận hủy đơn."
                        ),
                    },
                    ensure_ascii=False,
                )
            is_matched = clean_verif == clean_sender or (
                len(clean_verif) >= 4 and clean_sender.endswith(clean_verif)
            )
            if not is_matched:
                _verify_register_fail(tenant or "default", lock_key)
                return json.dumps(
                    {
                        "status": "verification_failed",
                        "draft_id": draft_id,
                        "item_code": item_code,
                        "message": "❌ XÁC THỰC THẤT BẠI: Số điện thoại xác minh không khớp với thông tin người gửi của đơn này. Yêu cầu hủy đơn bị từ chối vì lý do an toàn bảo mật.",
                    },
                    ensure_ascii=False,
                )
            _verify_reset(tenant or "default", lock_key)

        if status == "WAITING_CONFIRMATION":
            target_record["status"] = "CANCELLED"
            target_record["cancellation_reason"] = reason or "Khách hàng yêu cầu hủy đơn nháp"
            target_record["cancelled_at"] = now.isoformat()
            if draft_id:
                _DRAFT_BOOKINGS[draft_id] = target_record
            _sync_booking_draft(target_record)
            return json.dumps(
                {
                    "status": "cancelled",
                    "cancellation_type": "draft",
                    "draft_id": draft_id,
                    "message": f"Đã hủy đơn nháp {draft_id} thành công theo yêu cầu của quý khách.",
                },
                ensure_ascii=False,
            )

        elif status == "CONFIRMED":
            target_record["status"] = "CANCELLED_BY_CUSTOMER"
            target_record["cancellation_reason"] = reason or "Khách hàng yêu cầu hủy gửi hàng"
            target_record["cancelled_at"] = now.isoformat()
            if draft_id:
                _DRAFT_BOOKINGS[draft_id] = target_record
            _sync_booking_draft(target_record)
            return json.dumps(
                {
                    "status": "cancelled",
                    "cancellation_type": "confirmed_order",
                    "draft_id": draft_id,
                    "item_code": item_code,
                    "reason": target_record["cancellation_reason"],
                    "message": (
                        f"Đã hủy đơn hàng {item_code or draft_id} thành công theo yêu cầu của quý khách. "
                        "Hệ thống điều phối bưu tá VNPost đã được cập nhật (bưu tá sẽ không đến thu gom bưu phẩm này)."
                    ),
                },
                ensure_ascii=False,
            )

        elif status in {"CANCELLED", "CANCELLED_BY_CUSTOMER"}:
            return json.dumps(
                {
                    "status": "already_cancelled",
                    "draft_id": draft_id,
                    "item_code": item_code,
                    "message": f"Đơn hàng {item_code or draft_id} đã ở trạng thái hủy trước đó.",
                },
                ensure_ascii=False,
            )

        elif status == "EXPIRED":
            return json.dumps(
                {
                    "status": "expired",
                    "draft_id": draft_id,
                    "message": f"Đơn nháp {draft_id} đã hết hạn hiệu lực.",
                },
                ensure_ascii=False,
            )

    return json.dumps(
        {
            "status": "error",
            "message": f"Không tìm thấy đơn hàng hoặc mã vận đơn '{clean_id}' trong hệ thống để thực hiện hủy.",
        },
        ensure_ascii=False,
    )


def cancel_draft_complaint(
    draft_ticket_id: str = "",
    verification_phone: str = "",
    tenant: str | None = None,
    session_id: str | None = None,
    is_rest: bool = False,
) -> str:
    """Hủy phiếu khiếu nại nháp theo yêu cầu của khách hàng."""
    clean_id = (draft_ticket_id or "").strip()
    if tenant is None:
        ctx_tenant, _, _ = _get_current_session_context()
        tenant = ctx_tenant
    if not clean_id:
        _, s_id, _ = _get_current_session_context()
        caller_sid = session_id or s_id
        drafts = get_session_drafts(
            session_id=caller_sid, tenant=tenant, status="WAITING_CONFIRMATION"
        )["complaints"]
        if drafts:
            clean_id = drafts[-1]["draft_ticket_id"]
        else:
            return json.dumps(
                {
                    "status": "error",
                    "message": "Không tìm thấy phiếu khiếu nại nháp nào trong phiên hiện tại để hủy.",
                },
                ensure_ascii=False,
            )

    record = get_draft_complaint(clean_id, tenant=tenant)
    if not record:
        cross_rec = _DRAFT_COMPLAINTS.get(clean_id)
        if (
            cross_rec
            and tenant
            and not _is_tenant_match(cross_rec.get("tenant", "default"), tenant)
        ):
            return json.dumps(
                {
                    "status": "error",
                    "message": "Không có quyền hủy phiếu khiếu nại của tenant khác.",
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "status": "error",
                "message": f"Không tìm thấy phiếu khiếu nại nháp '{clean_id}'.",
            },
            ensure_ascii=False,
        )
    if tenant and not _is_tenant_match(record.get("tenant", "default"), tenant):
        return json.dumps(
            {"status": "error", "message": "Không có quyền hủy phiếu khiếu nại của tenant khác."},
            ensure_ascii=False,
        )
    if record["status"] == "SUBMITTED":
        return json.dumps(
            {
                "status": "error",
                "message": f"Phiếu khiếu nại '{clean_id}' đã nộp chính thức ({record.get('ticket_number')}). Vui lòng sử dụng cancel_complaint để rút khiếu nại.",
            },
            ensure_ascii=False,
        )
    if record["status"] in {"CANCELLED", "CANCELLED_BY_CUSTOMER"}:
        return json.dumps(
            {
                "status": "already_cancelled",
                "draft_ticket_id": clean_id,
                "message": f"Phiếu khiếu nại nháp {clean_id} đã ở trạng thái đã hủy.",
            },
            ensure_ascii=False,
        )

    # BẢO VỆ CHÍNH CHỦ (Phone Identity Verification):
    # Yêu cầu xác thực SĐT nếu gọi ngoài phiên tạo ban đầu hoặc qua REST API không gắn session gốc
    orig_session_id = record.get("session_id")
    _, current_session_id, _ = _get_current_session_context()
    caller_session_id = session_id or current_session_id
    needs_verification = False
    if orig_session_id and orig_session_id != caller_session_id:
        needs_verification = True
    elif is_rest and not (
        orig_session_id and caller_session_id and orig_session_id == caller_session_id
    ):
        needs_verification = True

    if needs_verification:
        lock_key = clean_id
        left = _verify_locked(tenant or "default", lock_key)
        if left > 0:
            return json.dumps(
                {
                    "status": "verification_locked",
                    "draft_ticket_id": clean_id,
                    "message": f"Đã nhập sai quá nhiều lần. Vui lòng thử lại sau {left // 60 + 1} phút hoặc liên hệ tổng đài/bưu cục để được hỗ trợ.",
                },
                ensure_ascii=False,
            )

        cust_phone = (
            record.get("customer", {}).get("phone")
            or record.get("customer_phone")
            or (record.get("detail", {}).get("customer", {}).get("phone"))
            or ""
        )
        clean_cust = re.sub(r"\D", "", cust_phone or "")
        if not clean_cust:
            return json.dumps(
                {
                    "status": "verification_unavailable",
                    "draft_ticket_id": clean_id,
                    "message": "Phiếu này chưa có SĐT người khiếu nại để xác minh. Vui lòng liên hệ bưu cục hoặc tổng đài để hủy khiếu nại.",
                },
                ensure_ascii=False,
            )

        clean_verif = re.sub(r"\D", "", verification_phone or "")
        if not clean_verif:
            masked = f"...{clean_cust[-4:]}" if len(clean_cust) >= 4 else "***"
            return json.dumps(
                {
                    "status": "requires_verification",
                    "draft_ticket_id": clean_id,
                    "masked_phone": masked,
                    "message": (
                        f"🔒 BẢO VỆ CHÍNH CHỦ: Phiếu khiếu nại [{clean_id}] được lập ở một phiên làm việc khác. "
                        f"Để đảm bảo an toàn, vui lòng cung cấp 4 số cuối của SĐT người khiếu nại "
                        f"(SĐT đuôi {masked}) để xác nhận hủy."
                    ),
                },
                ensure_ascii=False,
            )
        is_matched = clean_verif == clean_cust or (
            len(clean_verif) >= 4 and clean_cust.endswith(clean_verif)
        )
        if not is_matched:
            _verify_register_fail(tenant or "default", lock_key)
            return json.dumps(
                {
                    "status": "verification_failed",
                    "draft_ticket_id": clean_id,
                    "message": "❌ XÁC THỰC THẤT BẠI: Số điện thoại xác minh không khớp với thông tin người khiếu nại. Yêu cầu hủy bị từ chối.",
                },
                ensure_ascii=False,
            )
        _verify_reset(tenant or "default", lock_key)

    record["status"] = "CANCELLED"
    _DRAFT_COMPLAINTS[clean_id] = record
    _sync_complaint_draft(record)
    return json.dumps(
        {
            "status": "cancelled",
            "draft_ticket_id": clean_id,
            "message": f"Đã hủy phiếu khiếu nại nháp {clean_id}.",
        },
        ensure_ascii=False,
    )


def cancel_complaint(
    ticket_id_or_draft_id: str = "",
    reason: str = "",
    verification_phone: str = "",
    tenant: str | None = None,
    session_id: str | None = None,
    is_rest: bool = False,
) -> str:
    """Hủy hoặc rút phiếu khiếu nại VNPost (hỗ trợ cả phiếu nháp lẫn khiếu nại đã gửi chính thức).

    Tham số:
    - ticket_id_or_draft_id: Mã phiếu khiếu nại (TK-...) hoặc mã nháp (KN-DRAFT-...).
    - reason: Lý do rút khiếu nại.
    - verification_phone: 4 số cuối hoặc toàn bộ số điện thoại người khiếu nại (bắt buộc khi hủy từ session khác hoặc REST API).
    - tenant: Định danh tenant của người dùng yêu cầu hủy (chống IDOR).
    - session_id: Mã phiên hội thoại yêu cầu hủy.
    - is_rest: Đánh dấu yêu cầu xuất phát từ REST API công khai.
    """
    clean_id = (ticket_id_or_draft_id or "").strip()
    now = _get_vn_now()
    target_record = None
    if tenant is None:
        ctx_tenant, _, _ = _get_current_session_context()
        tenant = ctx_tenant

    if clean_id:
        target_record = get_draft_complaint(clean_id, tenant=tenant)
        if not target_record:
            for rec in _DRAFT_COMPLAINTS.values():
                if rec.get("ticket_number") == clean_id.upper() and (
                    tenant is None or _is_tenant_match(rec.get("tenant", "default"), tenant)
                ):
                    target_record = rec
                    break
        if not target_record and tenant:
            cross_rec = _DRAFT_COMPLAINTS.get(clean_id)
            if not cross_rec:
                for rec in _DRAFT_COMPLAINTS.values():
                    if rec.get("ticket_number") == clean_id.upper():
                        cross_rec = rec
                        break
            if cross_rec and not _is_tenant_match(cross_rec.get("tenant", "default"), tenant):
                return json.dumps(
                    {
                        "status": "error",
                        "message": "Không có quyền rút phiếu khiếu nại của tenant khác.",
                    },
                    ensure_ascii=False,
                )
    else:
        _, s_id, _ = _get_current_session_context()
        caller_sid = session_id or s_id
        data = get_session_drafts(session_id=caller_sid, tenant=tenant)
        active = [
            c
            for c in data["complaints"]
            if c.get("status") in {"WAITING_CONFIRMATION", "SUBMITTED"}
        ]
        if active:
            target_record = active[-1]
        else:
            return json.dumps(
                {
                    "status": "error",
                    "message": "Không tìm thấy phiếu khiếu nại nào trong phiên hiện tại để hủy.",
                },
                ensure_ascii=False,
            )

    if target_record:
        if tenant and not _is_tenant_match(target_record.get("tenant", "default"), tenant):
            return json.dumps(
                {
                    "status": "error",
                    "message": "Không có quyền rút phiếu khiếu nại của tenant khác.",
                },
                ensure_ascii=False,
            )
        status = target_record.get("status")
        draft_id = target_record.get("draft_ticket_id")
        ticket_number = target_record.get("ticket_number")
        orig_session_id = target_record.get("session_id")
        _, current_session_id, _ = _get_current_session_context()
        caller_session_id = session_id or current_session_id

        # BẢO VỆ CHÍNH CHỦ (Phone Identity Verification):
        # Yêu cầu xác thực SĐT nếu gọi ngoài phiên tạo ban đầu hoặc qua REST API không gắn session gốc
        needs_verification = False
        if orig_session_id and orig_session_id != caller_session_id:
            needs_verification = True
        elif is_rest and not (
            orig_session_id and caller_session_id and orig_session_id == caller_session_id
        ):
            needs_verification = True

        if needs_verification:
            lock_key = (ticket_number or draft_id or clean_id or "unknown")
            left = _verify_locked(tenant or "default", lock_key)
            if left > 0:
                return json.dumps(
                    {
                        "status": "verification_locked",
                        "ticket_number": ticket_number,
                        "draft_ticket_id": draft_id,
                        "message": f"Đã nhập sai quá nhiều lần. Vui lòng thử lại sau {left // 60 + 1} phút hoặc liên hệ tổng đài/bưu cục để được hỗ trợ.",
                    },
                    ensure_ascii=False,
                )

            cust_phone = (
                target_record.get("customer", {}).get("phone")
                or target_record.get("customer_phone")
                or (target_record.get("detail", {}).get("customer", {}).get("phone"))
                or ""
            )
            clean_cust = re.sub(r"\D", "", cust_phone or "")
            if not clean_cust:
                return json.dumps(
                    {
                        "status": "verification_unavailable",
                        "ticket_number": ticket_number,
                        "draft_ticket_id": draft_id,
                        "message": "Phiếu này chưa có SĐT người khiếu nại để xác minh. Vui lòng liên hệ bưu cục hoặc tổng đài để rút khiếu nại.",
                    },
                    ensure_ascii=False,
                )

            clean_verif = re.sub(r"\D", "", verification_phone or "")
            if not clean_verif:
                masked = f"...{clean_cust[-4:]}" if len(clean_cust) >= 4 else "***"
                return json.dumps(
                    {
                        "status": "requires_verification",
                        "ticket_number": ticket_number,
                        "draft_ticket_id": draft_id,
                        "masked_phone": masked,
                        "message": (
                            f"🔒 BẢO VỆ CHÍNH CHỦ: Yêu cầu rút phiếu khiếu nại [{ticket_number or draft_id}] thực hiện ngoài phiên tạo ban đầu. "
                            f"Để đảm bảo an toàn, vui lòng cung cấp 4 số cuối của SĐT người khiếu nại "
                            f"(SĐT đuôi {masked}) để xác nhận rút khiếu nại."
                        ),
                    },
                    ensure_ascii=False,
                )
            is_matched = clean_verif == clean_cust or (
                len(clean_verif) >= 4 and clean_cust.endswith(clean_verif)
            )
            if not is_matched:
                _verify_register_fail(tenant or "default", lock_key)
                return json.dumps(
                    {
                        "status": "verification_failed",
                        "ticket_number": ticket_number,
                        "draft_ticket_id": draft_id,
                        "message": "❌ XÁC THỰC THẤT BẠI: Số điện thoại xác minh không khớp với thông tin người khiếu nại. Yêu cầu rút khiếu nại bị từ chối vì lý do an toàn bảo mật.",
                    },
                    ensure_ascii=False,
                )
            _verify_reset(tenant or "default", lock_key)

        if status == "WAITING_CONFIRMATION":
            target_record["status"] = "CANCELLED"
            target_record["cancellation_reason"] = (
                reason or "Khách hàng yêu cầu hủy phiếu khiếu nại nháp"
            )
            target_record["cancelled_at"] = now.isoformat()
            if draft_id:
                _DRAFT_COMPLAINTS[draft_id] = target_record
            _sync_complaint_draft(target_record)
            return json.dumps(
                {
                    "status": "cancelled",
                    "cancellation_type": "draft",
                    "draft_ticket_id": draft_id,
                    "message": f"Đã hủy phiếu khiếu nại nháp {draft_id} thành công.",
                },
                ensure_ascii=False,
            )

        elif status == "SUBMITTED":
            target_record["status"] = "CANCELLED_BY_CUSTOMER"
            target_record["cancellation_reason"] = reason or "Khách hàng yêu cầu rút khiếu nại"
            target_record["cancelled_at"] = now.isoformat()
            if draft_id:
                _DRAFT_COMPLAINTS[draft_id] = target_record
            _sync_complaint_draft(target_record)
            return json.dumps(
                {
                    "status": "cancelled",
                    "cancellation_type": "submitted_ticket",
                    "ticket_number": ticket_number,
                    "draft_ticket_id": draft_id,
                    "reason": target_record["cancellation_reason"],
                    "message": f"Đã rút phiếu khiếu nại {ticket_number or draft_id} thành công theo yêu cầu của quý khách.",
                },
                ensure_ascii=False,
            )

        elif status in {"CANCELLED", "CANCELLED_BY_CUSTOMER"}:
            return json.dumps(
                {
                    "status": "already_cancelled",
                    "draft_ticket_id": draft_id,
                    "ticket_number": ticket_number,
                    "message": f"Phiếu khiếu nại {ticket_number or draft_id} đã ở trạng thái hủy trước đó.",
                },
                ensure_ascii=False,
            )

    return json.dumps(
        {"status": "error", "message": f"Không tìm thấy phiếu khiếu nại '{clean_id}' để hủy."},
        ensure_ascii=False,
    )


def list_my_orders(session_id: str | None = None, tenant: str | None = None) -> str:
    """Truy vấn danh sách đơn hàng, đơn nháp và khiếu nại của khách hàng trong phiên hội thoại hiện tại."""
    ctx_tenant, ctx_session_id, _ = _get_current_session_context()
    target_tenant = tenant or ctx_tenant
    target_session_id = session_id or ctx_session_id
    data = get_session_drafts(session_id=target_session_id, tenant=target_tenant)
    bookings = data.get("bookings", [])
    complaints = data.get("complaints", [])

    active_drafts = [b for b in bookings if b.get("status") == "WAITING_CONFIRMATION"]
    confirmed_orders = [b for b in bookings if b.get("status") == "CONFIRMED"]
    cancelled_orders = [
        b for b in bookings if b.get("status") in {"CANCELLED", "CANCELLED_BY_CUSTOMER"}
    ]

    draft_complaints = [c for c in complaints if c.get("status") == "WAITING_CONFIRMATION"]
    submitted_complaints = [c for c in complaints if c.get("status") == "SUBMITTED"]

    summary_lines = []
    if active_drafts:
        summary_lines.append(f"📦 **Đơn hàng nháp chờ duyệt ({len(active_drafts)}):**")
        for b in active_drafts:
            summary_lines.append(
                f"  • Mã nháp: `{b['draft_id']}` | Gửi từ: {b['sender']['address']} ➜ {b['receiver']['address']} | Cước ước tính: {b['pricing']['estimated_fee_text']}"
            )
    if confirmed_orders:
        summary_lines.append(f"🚚 **Đơn hàng đã xác nhận ({len(confirmed_orders)}):**")
        for b in confirmed_orders:
            summary_lines.append(
                f"  • Mã vận đơn: `{b.get('item_code')}` | Lấy hàng dự kiến: {b.get('pickup_schedule', 'Hôm nay')} | Cước: {b['pricing']['estimated_fee_text']}"
            )
    if cancelled_orders:
        summary_lines.append(f"❌ **Đơn hàng đã hủy ({len(cancelled_orders)}):**")
        for b in cancelled_orders:
            summary_lines.append(f"  • Mã: `{b.get('item_code', b['draft_id'])}`")
    if draft_complaints:
        summary_lines.append(f"📝 **Phiếu khiếu nại nháp chờ duyệt ({len(draft_complaints)}):**")
        for c in draft_complaints:
            summary_lines.append(
                f"  • Mã nháp: `{c['draft_ticket_id']}` | Mã bưu gửi: `{c['item_code']}`"
            )
    if submitted_complaints:
        summary_lines.append(f"📬 **Phiếu khiếu nại đã tiếp nhận ({len(submitted_complaints)}):**")
        for c in submitted_complaints:
            summary_lines.append(
                f"  • Mã Ticket: `{c.get('ticket_number')}` | Hạn xử lý: {c.get('sla_deadline')}"
            )

    summary_text = (
        "\n".join(summary_lines)
        if summary_lines
        else "Hiện tại chưa có đơn hàng hoặc phiếu khiếu nại nào được tạo trong phiên này."
    )
    return json.dumps(
        {
            "status": "success",
            "active_drafts_count": len(active_drafts),
            "confirmed_orders_count": len(confirmed_orders),
            "summary": summary_text,
            "detail": {
                "active_draft_bookings": active_drafts,
                "confirmed_bookings": confirmed_orders,
                "cancelled_bookings": cancelled_orders,
                "draft_complaints": draft_complaints,
                "submitted_complaints": submitted_complaints,
            },
        },
        ensure_ascii=False,
    )


def prune_expired_drafts(
    ttl_seconds: int = DEFAULT_DRAFT_TTL_SECONDS, max_age_hours: int = 24
) -> dict[str, int]:
    """Dọn dẹp các bản ghi nháp đã hết hạn hiệu lực hoặc vượt quá thời gian lưu trữ."""
    now = _get_vn_now()
    pruned_bookings = 0
    pruned_complaints = 0

    to_delete_b = []
    for bid, rec in list(_DRAFT_BOOKINGS.items()):
        if _is_draft_expired(rec, now):
            rec["status"] = "EXPIRED"
        try:
            created_dt = datetime.fromisoformat(rec["created_at"])
            if (now - created_dt).total_seconds() > max_age_hours * 3600:
                to_delete_b.append(bid)
        except Exception:
            pass
    for bid in to_delete_b:
        _DRAFT_BOOKINGS.pop(bid, None)
        pruned_bookings += 1

    to_delete_c = []
    for cid, rec in list(_DRAFT_COMPLAINTS.items()):
        if _is_draft_expired(rec, now):
            rec["status"] = "EXPIRED"
        try:
            created_dt = datetime.fromisoformat(rec["created_at"])
            if (now - created_dt).total_seconds() > max_age_hours * 3600:
                to_delete_c.append(cid)
        except Exception:
            pass
    for cid in to_delete_c:
        _DRAFT_COMPLAINTS.pop(cid, None)
        pruned_complaints += 1

    return {"pruned_bookings": pruned_bookings, "pruned_complaints": pruned_complaints}


def get_session_drafts(
    session_id: str | None = None, tenant: str = "default", status: str | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Truy vấn các bản nháp theo phạm vi session và tenant của người dùng (kết hợp RAM và PostgreSQL)."""
    bookings_map: dict[str, dict[str, Any]] = {}
    complaints_map: dict[str, dict[str, Any]] = {}

    # 1. Truy xuất từ PostgreSQL trước (nếu có kết nối)
    try:
        from app.core.postgres import fetch_session_drafts_from_postgres

        pg_drafts = fetch_session_drafts_from_postgres(tenant=tenant, session_id=session_id)
        for b in pg_drafts.get("bookings", []):
            bid = b.get("draft_id")
            if bid:
                bookings_map[bid] = b
        for c in pg_drafts.get("complaints", []):
            cid = c.get("draft_ticket_id")
            if cid:
                complaints_map[cid] = c
    except Exception:
        pass

    # 2. Ghi đè bằng trạng thái mới nhất trong RAM
    for rec in _DRAFT_BOOKINGS.values():
        if _is_tenant_match(rec.get("tenant", "default"), tenant):
            if session_id is None or rec.get("session_id") == session_id:
                bid = rec.get("draft_id")
                if bid:
                    bookings_map[bid] = rec

    for rec in _DRAFT_COMPLAINTS.values():
        if _is_tenant_match(rec.get("tenant", "default"), tenant):
            if session_id is None or rec.get("session_id") == session_id:
                cid = rec.get("draft_ticket_id")
                if cid:
                    complaints_map[cid] = rec

    bookings = [b for b in bookings_map.values() if status is None or b.get("status") == status]
    complaints = [c for c in complaints_map.values() if status is None or c.get("status") == status]

    return {"bookings": bookings, "complaints": complaints}


def get_draft_booking(draft_id: str, tenant: str | None = None) -> dict[str, Any] | None:
    """Lấy dữ liệu chi tiết của một đơn hàng nháp (có kiểm tra tenant chống IDOR)."""
    clean_id = (draft_id or "").strip()
    rec = _DRAFT_BOOKINGS.get(clean_id)
    if rec is not None:
        if tenant is not None and not _is_tenant_match(rec.get("tenant", "default"), tenant):
            return None
        return rec
    try:
        from app.core.postgres import fetch_draft_booking_from_postgres

        pg_rec = fetch_draft_booking_from_postgres(clean_id, tenant=tenant)
        if pg_rec is not None:
            if tenant is not None and not _is_tenant_match(pg_rec.get("tenant", "default"), tenant):
                return None
            _DRAFT_BOOKINGS[clean_id] = pg_rec
            return pg_rec
    except Exception:
        pass
    return None


def get_draft_complaint(draft_ticket_id: str, tenant: str | None = None) -> dict[str, Any] | None:
    """Lấy dữ liệu chi tiết của một phiếu khiếu nại nháp (có kiểm tra tenant chống IDOR)."""
    clean_id = (draft_ticket_id or "").strip()
    rec = _DRAFT_COMPLAINTS.get(clean_id)
    if rec is not None:
        if tenant is not None and not _is_tenant_match(rec.get("tenant", "default"), tenant):
            return None
        return rec
    try:
        from app.core.postgres import fetch_draft_complaint_from_postgres

        pg_rec = fetch_draft_complaint_from_postgres(clean_id, tenant=tenant)
        if pg_rec is not None:
            if tenant is not None and not _is_tenant_match(pg_rec.get("tenant", "default"), tenant):
                return None
            _DRAFT_COMPLAINTS[clean_id] = pg_rec
            return pg_rec
    except Exception:
        pass
    return None


def execute_action_with_interrupt(action_type: str, draft_id: str) -> dict[str, Any]:
    """Cơ chế Human-in-the-Loop (HITL) sử dụng LangGraph interrupt.

    Khi được gọi trong luồng Graph có Checkpointer, hàm sẽ tạm dừng (interrupt)
    để người dùng xác nhận thông tin trên giao diện trước khi gọi confirm_booking hoặc confirm_complaint.
    """
    from langgraph.types import interrupt

    if action_type == "booking":
        draft = get_draft_booking(draft_id)
        if not draft:
            return {"status": "error", "message": f"Không tìm thấy đơn nháp {draft_id}"}
        if _is_draft_expired(draft):
            draft["status"] = "EXPIRED"
            return {"status": "expired", "message": f"Đơn nháp {draft_id} đã hết hạn hiệu lực."}
        if draft["status"] != "WAITING_CONFIRMATION":
            return {
                "status": "error",
                "message": f"Đơn nháp {draft_id} không ở trạng thái chờ duyệt (trạng thái: {draft['status']})",
            }

        human_decision = interrupt(
            {
                "action_type": "confirm_booking",
                "draft_id": draft_id,
                "summary": f"Tạo đơn gửi bưu phẩm từ {draft['sender']['address']} đến {draft['receiver']['address']}",
                "chargeable_weight": draft["parcel"]["weight_chargeable_kg"],
                "fee": draft["pricing"]["estimated_fee_text"],
                "prompt": "Quý khách có xác nhận tạo đơn hàng và phát hành mã vận đơn này không?",
            }
        )
        if human_decision and human_decision.get("approved"):
            return json.loads(confirm_booking(draft_id))
        else:
            cancel_draft_booking(draft_id)
            return {"status": "rejected", "message": "Người dùng đã từ chối tạo đơn hàng."}

    elif action_type == "complaint":
        draft = get_draft_complaint(draft_id)
        if not draft:
            return {"status": "error", "message": f"Không tìm thấy phiếu khiếu nại nháp {draft_id}"}
        if _is_draft_expired(draft):
            draft["status"] = "EXPIRED"
            return {
                "status": "expired",
                "message": f"Phiếu khiếu nại {draft_id} đã hết hạn hiệu lực.",
            }
        if draft["status"] != "WAITING_CONFIRMATION":
            return {
                "status": "error",
                "message": f"Phiếu khiếu nại {draft_id} không ở trạng thái chờ duyệt (trạng thái: {draft['status']})",
            }

        human_decision = interrupt(
            {
                "action_type": "confirm_complaint",
                "draft_ticket_id": draft_id,
                "item_code": draft["item_code"],
                "type": draft["complaint_details"]["type"],
                "compensation": draft["complaint_details"]["proposed_compensation_text"],
                "prompt": "Quý khách có xác nhận gửi phiếu khiếu nại này tới tổng đài CSKH VNPost không?",
            }
        )
        if human_decision and human_decision.get("approved"):
            return json.loads(confirm_complaint(draft_id))
        else:
            cancel_complaint(ticket_id_or_draft_id=draft_id, reason="Người dùng từ chối xác nhận")
            return {"status": "rejected", "message": "Người dùng đã từ chối xác nhận khiếu nại."}
    return {"status": "error", "message": f"Loại hành động không hợp lệ: {action_type}"}


def has_active_draft_for_session(tenant: str, session_id: str | None) -> bool:
    """Kiểm tra xem phiên có bản nháp đơn hàng hoặc khiếu nại đang chờ xác nhận (WAITING_CONFIRMATION) hay không."""
    if not session_id:
        return False
    drafts = get_session_drafts(session_id=session_id, tenant=tenant, status="WAITING_CONFIRMATION")
    now = _get_vn_now()
    active_b = [b for b in drafts.get("bookings", []) if not _is_draft_expired(b, now)]
    active_c = [c for c in drafts.get("complaints", []) if not _is_draft_expired(c, now)]
    return bool(active_b or active_c)


def cancel_orphaned_drafts(tenant: str, session_id: str | None) -> int:
    """Hủy toàn bộ các bản nháp mồ côi đang chờ xác nhận trong phiên khi người dùng sửa câu hỏi / re-ask."""
    if not session_id:
        return 0
    cancelled_count = 0
    now = _get_vn_now()

    # 1. In-memory bookings
    for rec in _DRAFT_BOOKINGS.values():
        if _is_tenant_match(rec.get("tenant", "default"), tenant) and rec.get("session_id") == session_id:
            if rec.get("status") == "WAITING_CONFIRMATION":
                rec["status"] = "CANCELLED_ORPHANED"
                rec["cancelled_at"] = now.isoformat()
                cancelled_count += 1
                _sync_booking_draft(rec)

    # 2. In-memory complaints
    for rec in _DRAFT_COMPLAINTS.values():
        if _is_tenant_match(rec.get("tenant", "default"), tenant) and rec.get("session_id") == session_id:
            if rec.get("status") == "WAITING_CONFIRMATION":
                rec["status"] = "CANCELLED_ORPHANED"
                rec["cancelled_at"] = now.isoformat()
                cancelled_count += 1
                _sync_complaint_draft(rec)

    # 3. PostgreSQL
    try:
        from app.core.postgres import cancel_orphaned_drafts_in_postgres

        cancelled_count += cancel_orphaned_drafts_in_postgres(tenant=tenant, session_id=session_id)
    except Exception:
        pass

    return cancelled_count

