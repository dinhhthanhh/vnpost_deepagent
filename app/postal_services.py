"""Dịch vụ nghiệp vụ bưu chính VNPost: Tra cứu hành trình bưu phẩm và mạng lưới bưu cục."""

import re
from datetime import datetime, timedelta, timezone


def track_postal_item(item_code: str) -> dict:
    """Tra cứu trạng thái và hành trình bưu phẩm theo mã vận đơn VNPost."""
    clean_code = (item_code or "").strip().upper()
    if not clean_code:
        return {"found": False, "error": "Mã vận đơn không được để trống."}

    # Kiểm tra định dạng mã vận đơn chuẩn UPU S10 (ví dụ EB123456789VN) hoặc mã số quốc nội 8-15 ký tự
    is_upu = bool(re.fullmatch(r"^[A-Z]{2}\d{9}[A-Z]{2}$", clean_code))
    is_domestic = bool(re.fullmatch(r"^[A-Z0-9]{8,16}$", clean_code))
    if not (is_upu or is_domestic):
        return {
            "found": False,
            "error": f"Mã vận đơn '{clean_code}' không hợp lệ. Mã vận đơn chuẩn của VNPost gồm 13 ký tự (ví dụ: EB123456789VN, CP123456789VN) hoặc chuỗi ký tự bưu phẩm 8-15 ký tự.",
        }

    # Xác định loại dịch vụ
    prefix = clean_code[:2]
    if prefix in {"EB", "EM", "EP"}:
        service_name = "EMS - Chuyển phát nhanh bưu chính"
    elif prefix in {"CP", "CV"}:
        service_name = "Bưu phẩm bưu kiện trong nước"
    elif prefix in {"RA", "RR", "RD"}:
        service_name = "Thư bảo đảm / Bưu phẩm chuyển tiền"
    else:
        service_name = "Chuyển phát tiêu chuẩn VNPost"

    # Tạo mốc thời gian thực chuẩn VN (UTC+7)
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Ho_Chi_Minh")
    except Exception:
        tz = timezone(timedelta(hours=7))
    now = datetime.now(tz)
    t0 = now - timedelta(days=2, hours=3)
    t1 = now - timedelta(days=1, hours=8)
    t2 = now - timedelta(hours=4)

    # Trích xuất số cuối để tạo trạng thái xác định (deterministic)
    digits = "".join(c for c in clean_code if c.isdigit())
    last_digit = int(digits[-1]) if digits else 0

    if last_digit in {0, 2, 4, 6, 8}:
        current_status = "Đã phát thành công"
        status_detail = "Người nhận đã ký nhận bưu gửi"
        events = [
            {"time": f"{t0:%d/%m/%Y %H:%M}", "location": "Bưu cục Giao dịch Trung tâm Hà Nội", "status": "Chấp nhận gửi bưu phẩm"},
            {"time": f"{t1:%d/%m/%Y %H:%M}", "location": "Trung tâm Khai thác Vận chuyển Liên tỉnh Hà Nội - Đà Nẵng", "status": "Rời bưu cục trung chuyển"},
            {"time": f"{t2:%d/%m/%Y %H:%M}", "location": "Bưu cục Phát Hải Châu - Đà Nẵng", "status": "Đang phân bưu tá đi phát"},
            {"time": f"{now:%d/%m/%Y %H:%M}", "location": "Đà Nẵng", "status": "Đã phát thành công (Người nhận ký nhận)"},
        ]
    else:
        current_status = "Đang vận chuyển / Đang đi phát"
        status_detail = "Bưu gửi đang trên đường vận chuyển tới bưu cục phát"
        events = [
            {"time": f"{t0:%d/%m/%Y %H:%M}", "location": "Bưu cục Chấp nhận Cầu Giấy - Hà Nội", "status": "Chấp nhận gửi bưu phẩm"},
            {"time": f"{t1:%d/%m/%Y %H:%M}", "location": "Trung tâm Khai thác Vận chuyển Nội Bài", "status": "Đang trung chuyển qua đường hàng không"},
            {"time": f"{now:%d/%m/%Y %H:%M}", "location": "Trung tâm Khai thác Tân Sơn Nhất - TP.HCM", "status": "Đã nhập bưu cục phát, chuẩn bị chia tuyến giao"},
        ]

    return {
        "found": True,
        "item_code": clean_code,
        "service": service_name,
        "status": current_status,
        "status_detail": status_detail,
        "weight": "450 gram",
        "last_updated": f"{now:%d/%m/%Y %H:%M}",
        "events": events,
    }


POST_OFFICES = [
    {
        "id": "100000",
        "name": "Bưu điện Trung tâm Hà Nội (Bưu điện Bờ Hồ)",
        "address": "Số 75 Đinh Tiên Hoàng, Phường Tràng Tiền, Quận Hoàn Kiếm, Hà Nội",
        "district": "Quận Hoàn Kiếm",
        "province": "Hà Nội",
        "phone": "024.38254403",
        "opening_hours": "07:00 - 20:00 (Thứ 2 đến Chủ Nhật, mở cửa cả ngày lễ)",
        "vpostcode": "100000",
        "services": ["EMS Chuyển phát nhanh", "Bưu kiện", "Chuyển tiền nhanh", "Tiết kiệm Bưu điện", "Bảo hiểm bưu chính"],
    },
    {
        "id": "122000",
        "name": "Bưu điện Cầu Giấy",
        "address": "Số 165 Cầu Giấy, Phường Dịch Vọng, Quận Cầu Giấy, Hà Nội",
        "district": "Quận Cầu Giấy",
        "province": "Hà Nội",
        "phone": "024.38332155",
        "opening_hours": "07:30 - 19:30 (Thứ 2 đến Thứ 7), 08:00 - 17:00 (Chủ Nhật)",
        "vpostcode": "122000",
        "services": ["EMS", "Logistics", "Thu hộ COD", "Bưu phẩm trong nước và quốc tế"],
    },
    {
        "id": "115000",
        "name": "Bưu điện Trung tâm Đống Đa",
        "address": "Số 13 Nguyễn Du, Phường Hàng Bột, Quận Đống Đa, Hà Nội",
        "district": "Quận Đống Đa",
        "province": "Hà Nội",
        "phone": "024.38512400",
        "opening_hours": "07:30 - 19:00 (Thứ 2 đến Thứ 7), Chủ Nhật nghỉ",
        "vpostcode": "115000",
        "services": ["EMS", "Bưu kiện", "Phát hành báo chí"],
    },
    {
        "id": "700000",
        "name": "Bưu điện Trung tâm Sài Gòn",
        "address": "Số 02 Công xã Paris, Phường Bến Nghé, Quận 1, TP. Hồ Chí Minh",
        "district": "Quận 1",
        "province": "TP. Hồ Chí Minh",
        "phone": "028.38221677",
        "opening_hours": "07:00 - 19:00 (Thứ 2 đến Thứ 7), 08:00 - 18:00 (Chủ Nhật)",
        "vpostcode": "700000",
        "services": ["EMS Quốc tế", "EMS Trong nước", "Logistics", "Thu hộ COD", "Quà lưu niệm & Du lịch"],
    },
    {
        "id": "725000",
        "name": "Bưu điện Tân Bình",
        "address": "Số 288 Hoàng Văn Thụ, Phường 4, Quận Tân Bình, TP. Hồ Chí Minh",
        "district": "Quận Tân Bình",
        "province": "TP. Hồ Chí Minh",
        "phone": "028.38442000",
        "opening_hours": "07:30 - 19:00 (Thứ 2 đến Thứ 7), Chủ Nhật 08:00 - 12:00",
        "vpostcode": "725000",
        "services": ["EMS", "Bưu kiện", "Chuyển tiền nhanh PayPost"],
    },
    {
        "id": "550000",
        "name": "Bưu điện Trung tâm Đà Nẵng",
        "address": "Số 271 Nguyễn Văn Linh, Phường Vĩnh Trung, Quận Thanh Khê, TP. Đà Nẵng",
        "district": "Quận Thanh Khê",
        "province": "Đà Nẵng",
        "phone": "0236.3822222",
        "opening_hours": "07:30 - 19:00 (Thứ 2 đến Chủ Nhật)",
        "vpostcode": "550000",
        "services": ["EMS", "Bưu chính quốc tế", "Dịch vụ hành chính công", "Thu hộ"],
    },
    {
        "id": "550001",
        "name": "Bưu điện Bạch Đằng (Hải Châu - Đà Nẵng)",
        "address": "Số 60 Bạch Đằng, Phường Hải Châu 1, Quận Hải Châu, TP. Đà Nẵng",
        "district": "Quận Hải Châu",
        "province": "Đà Nẵng",
        "phone": "0236.3821000",
        "opening_hours": "07:30 - 18:30 (Thứ 2 đến Thứ 7), Chủ Nhật mở buổi sáng",
        "vpostcode": "550001",
        "services": ["EMS", "Bưu kiện", "Dịch vụ bưu chính công ích"],
    },
    {
        "id": "900000",
        "name": "Bưu điện Trung tâm Cần Thơ",
        "address": "Số 02 Hòa Bình, Phường Tân An, Quận Ninh Kiều, TP. Cần Thơ",
        "district": "Quận Ninh Kiều",
        "province": "Cần Thơ",
        "phone": "0292.3820000",
        "opening_hours": "07:30 - 18:30 (Thứ 2 đến Thứ 7), 08:00 - 17:00 (Chủ Nhật)",
        "vpostcode": "900000",
        "services": ["EMS", "Bưu kiện", "Tài chính bưu chính"],
    },
]


def lookup_postal_office(query: str, province: str = "", district: str = "") -> dict:
    """Tra cứu bưu cục, mạng lưới phục vụ và mã bưu chính quốc gia theo từ khóa, quận/huyện hoặc tỉnh/thành."""
    clean_q = (query or "").strip().lower()
    clean_prov = (province or "").strip().lower()
    clean_dist = (district or "").strip().lower()

    matches = []
    for po in POST_OFFICES:
        searchable_text = f"{po['name']} {po['address']} {po['district']} {po['province']} {po['vpostcode']} {po['id']}".lower()

        # Kiểm tra khớp từ khóa
        score = 0
        if clean_q and clean_q in searchable_text:
            score += 2
        if clean_prov and clean_prov in po["province"].lower():
            score += 2
        if clean_dist and clean_dist in po["district"].lower():
            score += 3

        # Tìm kiếm theo từng từ đơn lẻ nếu query có nhiều từ
        tokens = [t for t in clean_q.split() if len(t) > 1]
        for token in tokens:
            if token in searchable_text:
                score += 1

        if score > 0 or not (clean_q or clean_prov or clean_dist):
            matches.append((score, po))

    # Sắp xếp theo độ phù hợp
    matches.sort(key=lambda x: x[0], reverse=True)
    results = [item[1] for item in matches[:5]]

    if not results:
        # Nếu không khớp chính xác, trả về các bưu cục trung tâm chính
        results = POST_OFFICES[:3]
        return {
            "found": False,
            "message": f"Không tìm thấy bưu cục chính xác với từ khóa '{query}'. Dưới đây là các bưu điện trung tâm tiêu biểu của VNPost.",
            "post_offices": results,
        }

    return {
        "found": True,
        "total": len(results),
        "post_offices": results,
    }
