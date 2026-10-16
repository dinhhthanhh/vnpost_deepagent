"""Dịch vụ nghiệp vụ bưu chính VNPost: Tra cứu hành trình bưu phẩm và mạng lưới bưu cục."""

import re
import unicodedata
from datetime import datetime, timedelta, timezone


def _fold_vn(text: str) -> str:
    """Chuẩn hóa chữ thường và bỏ dấu tiếng Việt để hỗ trợ tra cứu cả có dấu lẫn không dấu."""
    text = unicodedata.normalize("NFC", (text or "").strip().lower()).replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def track_postal_item(item_code: str) -> dict:
    """Tra cứu trạng thái và hành trình bưu phẩm theo mã vận đơn VNPost."""
    clean_code = (item_code or "").strip().upper()
    if not clean_code:
        return {"found": False, "error": "Mã vận đơn không được để trống."}

    # Kiểm tra định dạng mã vận đơn chuẩn UPU S10 (13 ký tự: 2 chữ + 9 số + 2 chữ quốc gia, VD: EB123456789VN)
    # hoặc mã bưu gửi nội địa VNPost (8-16 ký tự chữ/số)
    is_upu = bool(re.fullmatch(r"^[A-Z]{2}\d{9}[A-Z]{2}$", clean_code))
    is_domestic = bool(re.fullmatch(r"^[A-Z0-9]{8,16}$", clean_code))
    if not (is_upu or is_domestic):
        return {
            "found": False,
            "error": (
                f"Mã vận đơn '{clean_code}' không đúng định dạng. "
                "Mã vận đơn chuẩn UPU S10 của VNPost gồm 13 ký tự (ví dụ: EB123456789VN, CP123456789VN, "
                "RA123456789VN) hoặc mã bưu gửi nội địa từ 8–16 ký tự."
            ),
        }

    # Xác định loại dịch vụ theo dải đầu mã chuẩn UPU S10 và quy định VNPost
    prefix = clean_code[:2]
    first_char = clean_code[0]
    if prefix in {"EB", "EM", "EP", "EE", "EV", "EY", "EZ", "EA"} or first_char == "E":
        service_name = "EMS - Chuyển phát nhanh Bưu điện"
    elif prefix in {"CP", "CV", "CB", "CD", "CE", "CA"} or first_char == "C":
        service_name = "Bưu kiện Bưu điện (VNPost Parcel)"
    elif prefix in {"RA", "RR", "RD", "RB", "RC", "RF", "RT"} or first_char == "R":
        service_name = "Bưu phẩm bảo đảm (Registered Mail)"
    elif prefix in {"LP", "LK", "LC", "LA", "LB"} or first_char == "L":
        service_name = "Chuyển phát Thương mại điện tử (E-commerce)"
    else:
        service_name = "Chuyển phát tiêu chuẩn VNPost"

    # Tạo mốc thời gian thực chuẩn Việt Nam (UTC+7)
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Ho_Chi_Minh")
    except Exception:
        tz = timezone(timedelta(hours=7))
    now = datetime.now(tz)
    t0 = now - timedelta(days=2, hours=3)
    t1 = now - timedelta(days=1, hours=8)
    t2 = now - timedelta(hours=4)

    # Trích xuất chữ số cuối để tạo trạng thái xác định (deterministic) phục vụ kiểm thử ổn định
    digits = "".join(c for c in clean_code if c.isdigit())
    last_digit = int(digits[-1]) if digits else 0

    if last_digit in {0, 2, 4, 6, 8}:
        current_status = "Đã phát thành công"
        status_detail = "Phát thành công cho người nhận (Đã ký nhận)"
        events = [
            {
                "time": f"{t0:%d/%m/%Y %H:%M}",
                "location": "Bưu cục Giao dịch Bờ Hồ (100000) - Bưu điện TP. Hà Nội",
                "status": "Đã chấp nhận gửi (Chấp nhận tại bưu cục)",
            },
            {
                "time": f"{t1:%d/%m/%Y %H:%M}",
                "location": "Trung tâm Khai thác Vận chuyển Bưu điện Hà Nội (KTT1)",
                "status": "Đã đóng túi gói, rời trung tâm khai thác đi Đà Nẵng",
            },
            {
                "time": f"{t2:%d/%m/%Y %H:%M}",
                "location": "Bưu cục Phát Hải Châu (550001) - Bưu điện TP. Đà Nẵng",
                "status": "Đã đến bưu cục phát, phân công bưu tá đi phát",
            },
            {
                "time": f"{now:%d/%m/%Y %H:%M}",
                "location": "Quận Hải Châu, TP. Đà Nẵng",
                "status": "Đã phát thành công (Người nhận đã ký nhận)",
            },
        ]
    else:
        current_status = "Đang vận chuyển / Đang đi phát"
        status_detail = "Bưu gửi đã đến trung tâm khai thác đích, đang chuyển bưu cục phát"
        events = [
            {
                "time": f"{t0:%d/%m/%Y %H:%M}",
                "location": "Bưu cục Giao dịch Cầu Giấy (122000) - Bưu điện TP. Hà Nội",
                "status": "Đã chấp nhận gửi (Chấp nhận tại bưu cục)",
            },
            {
                "time": f"{t1:%d/%m/%Y %H:%M}",
                "location": "Trung tâm Khai thác Vận chuyển Nội Bài - Hà Nội",
                "status": "Đang kết nối vận chuyển đường hàng không đi TP. Hồ Chí Minh",
            },
            {
                "time": f"{now:%d/%m/%Y %H:%M}",
                "location": "Trung tâm Khai thác Vận chuyển Bưu điện TP. Hồ Chí Minh (KTT2 - Tân Sơn Nhất)",
                "status": "Đã đến trung tâm khai thác đích, chuẩn bị bàn giao cho bưu cục phát",
            },
        ]

    return {
        "found": True,
        "item_code": clean_code,
        "service": service_name,
        "status": current_status,
        "status_detail": status_detail,
        "weight": "450 gram",
        "last_updated": f"{now:%d/%m/%Y %H:%M}",
        "hotline_support": "1900 54 54 81",
        "events": events,
    }


POST_OFFICES = [
    {
        "id": "100000",
        "name": "Bưu điện Trung tâm Hoàn Kiếm (Bưu điện Bờ Hồ - Hà Nội)",
        "address": "Số 75 Đinh Tiên Hoàng, Phường Tràng Tiền, Quận Hoàn Kiếm, TP. Hà Nội",
        "district": "Quận Hoàn Kiếm",
        "province": "Hà Nội",
        "phone": "024.38254403",
        "hotline": "1900 54 54 81",
        "opening_hours": "07:00 - 20:00 (Thứ 2 đến Chủ Nhật, mở cửa cả ngày lễ)",
        "vpostcode": "100000",
        "postcode": "10000",
        "services": [
            "EMS Chuyển phát nhanh trong nước & quốc tế",
            "Bưu kiện - Bưu phẩm bảo đảm",
            "Tài chính Bưu chính (Chuyển tiền, Thu hộ/Chi hộ, Tiết kiệm Bưu điện)",
            "Tiếp nhận hồ sơ & trả kết quả giải quyết thủ tục hành chính công",
        ],
    },
    {
        "id": "122000",
        "name": "Bưu điện Cầu Giấy (Bưu cục Giao dịch Cầu Giấy)",
        "address": "Số 165 Cầu Giấy, Phường Quan Hoa (giáp Phường Dịch Vọng), Quận Cầu Giấy, TP. Hà Nội",
        "district": "Quận Cầu Giấy",
        "province": "Hà Nội",
        "phone": "024.38330363 / 024.38332155",
        "hotline": "1900 54 54 81",
        "opening_hours": "07:30 - 19:30 (Thứ 2 đến Thứ 7), 08:00 - 17:00 (Chủ Nhật)",
        "vpostcode": "122000",
        "postcode": "11300",
        "services": [
            "EMS Chuyển phát nhanh",
            "Chuyển phát Thương mại điện tử & Thu hộ COD",
            "Bưu phẩm - Bưu kiện trong nước và quốc tế",
            "Dịch vụ Logistics & Chuyển tiền Bưu điện",
        ],
    },
    {
        "id": "115000",
        "name": "Bưu điện Trung tâm Đống Đa (Bưu cục Giao dịch Hàng Bột)",
        "address": "Số 107 Tôn Đức Thắng, Phường Hàng Bột, Quận Đống Đa, TP. Hà Nội",
        "district": "Quận Đống Đa",
        "province": "Hà Nội",
        "phone": "024.38512400",
        "hotline": "1900 54 54 81",
        "opening_hours": "07:30 - 19:00 (Thứ 2 đến Thứ 7), Chủ Nhật nghỉ",
        "vpostcode": "115000",
        "postcode": "11500",
        "services": [
            "EMS Chuyển phát nhanh",
            "Bưu kiện - Bưu phẩm bảo đảm",
            "Thu hộ COD & Phát hành báo chí",
            "Tài chính Bưu chính & Hành chính công",
        ],
    },
    {
        "id": "700000",
        "name": "Bưu điện Trung tâm Sài Gòn (Bưu điện TP. Hồ Chí Minh)",
        "address": "Số 02 Công xã Paris, Phường Bến Nghé, Quận 1, TP. Hồ Chí Minh",
        "district": "Quận 1",
        "province": "TP. Hồ Chí Minh",
        "phone": "028.38221677 / 028.38296555",
        "hotline": "1900 54 54 81",
        "opening_hours": "07:00 - 19:00 (Thứ 2 đến Thứ 7), 07:30 - 18:00 (Chủ Nhật)",
        "vpostcode": "700000",
        "postcode": "70000",
        "services": [
            "EMS Trong nước & Quốc tế",
            "Bưu kiện - Bưu phẩm quốc tế và nội địa",
            "Thu hộ COD & Logistics",
            "Tài chính Bưu chính, Du lịch & Tem Bưu chính",
        ],
    },
    {
        "id": "725000",
        "name": "Bưu điện Tân Bình (Bưu cục Giao dịch Hoàng Văn Thụ)",
        "address": "Số 455 Hoàng Văn Thụ, Phường 4, Quận Tân Bình, TP. Hồ Chí Minh",
        "district": "Quận Tân Bình",
        "province": "TP. Hồ Chí Minh",
        "phone": "028.38440262",
        "hotline": "1900 54 54 81",
        "opening_hours": "07:30 - 19:00 (Thứ 2 đến Thứ 7), Chủ Nhật 08:00 - 12:00",
        "vpostcode": "725000",
        "postcode": "72100",
        "services": [
            "EMS Chuyển phát nhanh",
            "Bưu kiện trong nước & quốc tế",
            "Thu hộ COD & Chuyển tiền nhanh",
        ],
    },
    {
        "id": "550000",
        "name": "Bưu điện Trung tâm Đà Nẵng (Bưu cục Giao dịch Nguyễn Văn Linh)",
        "address": "Số 271 Nguyễn Văn Linh, Phường Vĩnh Trung, Quận Thanh Khê, TP. Đà Nẵng",
        "district": "Quận Thanh Khê",
        "province": "Đà Nẵng",
        "phone": "0236.3655222",
        "hotline": "1900 54 54 81",
        "opening_hours": "07:00 - 19:30 (Thứ 2 đến Chủ Nhật)",
        "vpostcode": "550000",
        "postcode": "50000",
        "services": [
            "EMS Chuyển phát nhanh",
            "Bưu chính trong nước & quốc tế",
            "Tiếp nhận hồ sơ hành chính công",
            "Tài chính Bưu chính & Thu hộ COD",
        ],
    },
    {
        "id": "550001",
        "name": "Bưu điện Bạch Đằng (Bưu cục Giao dịch Hải Châu - Đà Nẵng)",
        "address": "Số 64 Bạch Đằng, Phường Hải Châu 1, Quận Hải Châu, TP. Đà Nẵng",
        "district": "Quận Hải Châu",
        "province": "Đà Nẵng",
        "phone": "0236.3821235",
        "hotline": "1900 54 54 81",
        "opening_hours": "07:30 - 18:30 (Thứ 2 đến Thứ 7), Chủ Nhật 07:30 - 11:30",
        "vpostcode": "550001",
        "postcode": "50000",
        "services": [
            "EMS Chuyển phát nhanh",
            "Bưu kiện - Bưu phẩm",
            "Dịch vụ Bưu chính công ích & Tài chính Bưu chính",
        ],
    },
    {
        "id": "900000",
        "name": "Bưu điện Trung tâm Cần Thơ (Bưu cục Giao dịch Ninh Kiều)",
        "address": "Số 02 Hòa Bình, Phường Tân An, Quận Ninh Kiều, TP. Cần Thơ",
        "district": "Quận Ninh Kiều",
        "province": "Cần Thơ",
        "phone": "0292.3820832 / 0292.3815666",
        "hotline": "1900 54 54 81",
        "opening_hours": "07:00 - 19:00 (Thứ 2 đến Thứ 7), 07:30 - 17:00 (Chủ Nhật)",
        "vpostcode": "900000",
        "postcode": "90000",
        "services": [
            "EMS Chuyển phát nhanh",
            "Bưu kiện - Bưu phẩm",
            "Tài chính Bưu chính & Hành chính công",
        ],
    },
]


def lookup_postal_office(query: str, province: str = "", district: str = "") -> dict:
    """Tra cứu bưu cục, mạng lưới phục vụ và mã bưu chính quốc gia theo từ khóa, quận/huyện hoặc tỉnh/thành."""
    clean_q = unicodedata.normalize("NFC", (query or "").strip().lower())
    clean_prov = unicodedata.normalize("NFC", (province or "").strip().lower())
    clean_dist = unicodedata.normalize("NFC", (district or "").strip().lower())

    fold_q = _fold_vn(clean_q)
    fold_prov = _fold_vn(clean_prov)
    fold_dist = _fold_vn(clean_dist)

    matches = []
    for po in POST_OFFICES:
        raw_text = (
            f"{po['name']} {po['address']} {po['district']} {po['province']} "
            f"{po['vpostcode']} {po.get('postcode', '')} {po['id']}"
        )
        searchable_text = unicodedata.normalize("NFC", raw_text.lower())
        folded_text = _fold_vn(raw_text)

        score = 0
        if clean_q and (clean_q in searchable_text or fold_q in folded_text):
            score += 3
        if clean_prov and (clean_prov in po["province"].lower() or fold_prov in _fold_vn(po["province"])):
            score += 2
        if clean_dist and (clean_dist in po["district"].lower() or fold_dist in _fold_vn(po["district"])):
            score += 3

        # Tìm kiếm theo từng từ đơn lẻ (cả có dấu và không dấu)
        q_tokens = [t for t in fold_q.split() if len(t) > 1 and t not in {"buu", "dien", "cuc", "tim", "o", "dau"}]
        for token in q_tokens:
            if token in folded_text:
                score += 1

        if score > 0 or not (clean_q or clean_prov or clean_dist):
            matches.append((score, po))

    matches.sort(key=lambda x: x[0], reverse=True)
    results = [item[1] for item in matches[:5]]

    if not results:
        results = POST_OFFICES[:3]
        return {
            "found": False,
            "message": (
                f"Không tìm thấy bưu cục khớp chính xác với từ khóa '{query}'. "
                "Dưới đây là các Bưu điện Trung tâm tiêu biểu của VNPost (Tổng đài hỗ trợ: 1900 54 54 81)."
            ),
            "post_offices": results,
        }

    return {
        "found": True,
        "total": len(results),
        "post_offices": results,
    }
