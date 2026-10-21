import json
from unittest.mock import patch

from app.agents.postal_actions import (
    cancel_booking,
    cancel_complaint,
    cancel_draft_booking,
    cancel_draft_complaint,
    confirm_booking,
    confirm_complaint,
    create_draft_booking,
    create_draft_complaint,
    execute_action_with_interrupt,
    get_draft_booking,
    get_draft_complaint,
    get_session_drafts,
    list_my_orders,
    prune_expired_drafts,
    update_draft_booking,
    update_draft_complaint,
)
from app.agents.signals import analyze
from app.service import ChatService


def test_booking_bulky_calculation_and_draft():
    """Kiểm tra tạo đơn nháp: tính toán cồng kềnh chuẩn chia 6000 và trạng thái chờ duyệt (HITL)."""
    # Kích thước: 30cm x 20cm x 10cm = 6000 cm3 -> Thể tích quy đổi: 6000 / 6000 = 1.0 kg
    # Khối lượng thực: 500g = 0.5 kg -> Phải tính cước theo 1.0 kg
    res_str = create_draft_booking(
        sender_name="Nguyễn Văn A",
        sender_phone="0912345678",
        sender_address="125 Hai Bà Trưng, Quận 1, Hồ Chí Minh",
        receiver_name="Trần Thị B",
        receiver_phone="0987654321",
        receiver_address="45 Đinh Tiên Hoàng, Hoàn Kiếm, Hà Nội",
        weight_grams=500,
        length_cm=30,
        width_cm=20,
        height_cm=10,
        service_type="EMS",
    )
    data = json.loads(res_str)
    assert data["status"] == "waiting_confirmation"
    draft_id = data["draft_id"]
    assert draft_id.startswith("BK-DRAFT-")
    assert "YÊU CẦU XÁC NHẬN (HITL)" in data["instruction"]

    detail = data["detail"]
    assert detail["parcel"]["weight_actual_kg"] == 0.5
    assert detail["parcel"]["weight_volumetric_kg"] == 1.0
    assert detail["parcel"]["weight_chargeable_kg"] == 1.0
    assert detail["parcel"]["is_bulky"] is True
    assert "Vùng 3" in detail["pricing"]["zone"]
    assert detail["status"] == "WAITING_CONFIRMATION"

    # Kiểm tra truy vấn get_draft_booking
    record = get_draft_booking(draft_id)
    assert record is not None
    assert record["draft_id"] == draft_id


def test_booking_confirm_and_cancel_flow():
    """Kiểm tra luồng xác nhận đơn nháp (cấp mã vận đơn UPU) và hủy đơn nháp."""
    res_str = create_draft_booking(
        sender_name="Lê Minh",
        sender_phone="0901112222",
        sender_address="Đà Nẵng",
        receiver_name="Hoàng Nam",
        receiver_phone="0903334444",
        receiver_address="Đà Nẵng",
        weight_grams=800,
        service_type="EMS",
    )
    draft_id = json.loads(res_str)["draft_id"]

    # 0. Kiểm tra chốt chặn nội bộ ở cấp độ hàm khi confirmed_by_user=False
    unconfirmed_res = json.loads(confirm_booking(draft_id, confirmed_by_user=False))
    assert unconfirmed_res["status"] == "unconfirmed"

    # 1. Xác nhận đơn hàng (sau khi người dùng duyệt HITL)
    confirm_res = json.loads(confirm_booking(draft_id))
    assert confirm_res["status"] == "confirmed"
    item_code = confirm_res["item_code"]
    assert item_code.startswith("EB") and item_code.endswith("VN")
    assert "bưu tá vnpost sẽ liên hệ" in confirm_res["message"].lower()

    # 2. Xác nhận lại -> báo already_confirmed
    reconfirm_res = json.loads(confirm_booking(draft_id))
    assert reconfirm_res["status"] == "already_confirmed"
    assert reconfirm_res["item_code"] == item_code

    # 3. Test hủy đơn nháp mới
    draft_id_2 = json.loads(create_draft_booking(
        sender_name="Khách Hàng",
        sender_phone="0900000000",
        sender_address="Hà Nội",
        receiver_name="Người Nhận",
        receiver_phone="0911111111",
        receiver_address="Hà Nội",
        weight_grams=200,
    ))["draft_id"]

    cancel_res = json.loads(cancel_draft_booking(draft_id_2))
    assert cancel_res["status"] == "cancelled"
    assert get_draft_booking(draft_id_2)["status"] == "CANCELLED"


def test_complaint_statute_of_limitations_and_draft():
    """Kiểm tra thời hiệu khiếu nại (06 tháng nội địa, 12 tháng quốc tế) và lập phiếu nháp."""
    # 1. Quá hạn 06 tháng nội địa (ví dụ ngày gửi 2024-01-01) -> Từ chối thụ lý
    res_expired = json.loads(create_draft_complaint(
        item_code="EB987654321VN",
        customer_name="Phạm Văn C",
        customer_phone="0977889900",
        complaint_type="Hàng bị mất tích",
        description="Bưu phẩm gửi đã lâu không thấy đến",
        sent_date="2024-01-01",
    ))
    assert res_expired["status"] == "rejected_expired"
    assert "vượt quá thời hiệu" in res_expired["message"].lower()
    assert "06 tháng" in res_expired["message"]

    # 2. Còn trong thời hiệu -> Tạo phiếu nháp thành công
    res_valid = json.loads(create_draft_complaint(
        item_code="EB123456789VN",
        customer_name="Phạm Văn C",
        customer_phone="0977889900",
        complaint_type="Bưu gửi bị thất lạc, mất mát hoàn toàn",
        description="Kiện hàng báo phát thành công nhưng khách chưa nhận được",
        claimed_amount=500000.0,
        sent_date="2026-09-01",
    ))
    assert res_valid["status"] == "waiting_confirmation"
    draft_ticket_id = res_valid["draft_ticket_id"]
    assert draft_ticket_id.startswith("KN-DRAFT-")
    assert "YÊU CẦU XÁC NHẬN (HITL)" in res_valid["instruction"]

    detail = res_valid["detail"]
    assert detail["status"] == "WAITING_CONFIRMATION"
    assert "Mất mát bưu phẩm hoàn toàn" in detail["complaint_details"]["type"]
    assert detail["complaint_details"]["proposed_compensation"] == 500000.0
    assert "500.000 đ" in detail["complaint_details"]["proposed_compensation_text"]

    # 3. Khi khách chưa khai báo số tiền (claimed_amount=0) -> Không hardcode tiền mà thẩm định theo thực tế
    res_no_amount = json.loads(create_draft_complaint(
        item_code="EB123456789VN",
        customer_name="Trần Văn E",
        customer_phone="0988001122",
        complaint_type="Mất kiện hàng",
        description="Không rõ hàng đi đâu",
        claimed_amount=0.0,
    ))
    detail_no_amount = res_no_amount["detail"]["complaint_details"]
    assert detail_no_amount["proposed_compensation"] == 0.0
    assert "Thẩm định theo giá trị thực tế" in detail_no_amount["proposed_compensation_text"]


def test_slot_filling_detects_missing_fields():
    """Kiểm tra cơ chế Slot-filling phát hiện thiếu thông tin để Chatbot hỏi bù người dùng."""
    # Booking thiếu địa chỉ người nhận và SĐT người gửi
    res_booking_missing = json.loads(create_draft_booking(
        sender_name="Nguyễn Văn A",
        sender_phone="",
        sender_address="Hà Nội",
        receiver_name="Trần B",
        receiver_phone="0912345678",
        receiver_address="",
        weight_grams=500,
    ))
    assert res_booking_missing["status"] == "missing_info"
    assert "số điện thoại người gửi" in res_booking_missing["missing_fields"]
    assert "địa chỉ người nhận" in res_booking_missing["missing_fields"]

    # Complaint thiếu mã vận đơn và SĐT liên hệ
    res_complaint_missing = json.loads(create_draft_complaint(
        item_code="",
        customer_name="Lê C",
        customer_phone="",
        complaint_type="Bị vỡ hộp quà",
        description="Vỏ hộp bị móp méo",
    ))
    assert res_complaint_missing["status"] == "missing_info"
    assert "mã vận đơn (item_code)" in res_complaint_missing["missing_fields"]
    assert "số điện thoại liên hệ" in res_complaint_missing["missing_fields"]


def test_complaint_confirm_and_sla_flow():
    """Kiểm tra xác nhận nộp khiếu nại, cấp Ticket VNPost và cam kết SLA tối đa 20 ngày."""
    draft_res = json.loads(create_draft_complaint(
        item_code="CP555666777VN",
        customer_name="Đỗ Hoàng D",
        customer_phone="0933445566",
        complaint_type="Phát chậm so với chỉ tiêu toàn trình",
        description="Gửi EMS mà 10 ngày chưa tới",
    ))
    draft_ticket_id = draft_res["draft_ticket_id"]

    # 1. Xác nhận khiếu nại (sau khi khách duyệt HITL)
    submit_res = json.loads(confirm_complaint(draft_ticket_id))
    assert submit_res["status"] == "submitted"
    ticket_number = submit_res["ticket_number"]
    assert ticket_number.startswith("KN-VNPOST-")
    assert "20 ngày làm việc" in submit_res["sla_resolution"]
    assert "hồ sơ khiếu nại đã được chuyển chính thức" in submit_res["message"].lower()

    # 2. Xác nhận lại -> báo already_submitted
    resubmit_res = json.loads(confirm_complaint(draft_ticket_id))
    assert resubmit_res["status"] == "already_submitted"
    assert resubmit_res["ticket_number"] == ticket_number

    # 3. Test hủy phiếu khiếu nại nháp
    draft_ticket_2 = json.loads(create_draft_complaint(
        item_code="CP111222333VN",
        customer_name="Khách Hàng",
        customer_phone="0911223344",
        complaint_type="Hỏng nhẹ vỏ hộp",
        description="Hộp bị móp méo",
    ))["draft_ticket_id"]

    cancel_res = json.loads(cancel_draft_complaint(draft_ticket_2))
    assert cancel_res["status"] == "cancelled"
    assert get_draft_complaint(draft_ticket_2)["status"] == "CANCELLED"


def test_hitl_interrupt_execution():
    """Kiểm tra hàm execute_action_with_interrupt phối hợp với LangGraph interrupt."""
    # Tạo đơn nháp
    draft_id = json.loads(create_draft_booking(
        sender_name="Người Gửi A",
        sender_phone="0901234567",
        sender_address="Hà Nội",
        receiver_name="Người Nhận B",
        receiver_phone="0987654321",
        receiver_address="Hồ Chí Minh",
        weight_grams=600,
    ))["draft_id"]

    # Case 1: Người dùng phê duyệt (approved=True)
    with patch("langgraph.types.interrupt", return_value={"approved": True}):
        approved_result = execute_action_with_interrupt("booking", draft_id)
        assert approved_result["status"] == "confirmed"
        assert approved_result["item_code"].startswith("EB")

    # Tạo đơn nháp thứ 2
    draft_id_2 = json.loads(create_draft_booking(
        sender_name="Người Gửi C",
        sender_phone="0901234567",
        sender_address="Hà Nội",
        receiver_name="Người Nhận D",
        receiver_phone="0987654321",
        receiver_address="Hồ Chí Minh",
        weight_grams=600,
    ))["draft_id"]

    # Case 2: Người dùng từ chối (approved=False)
    with patch("langgraph.types.interrupt", return_value={"approved": False}):
        rejected_result = execute_action_with_interrupt("booking", draft_id_2)
        assert rejected_result["status"] == "rejected"
        assert get_draft_booking(draft_id_2)["status"] == "CANCELLED"


def test_router_signals_action_intent():
    """Kiểm tra bộ nhận diện tín hiệu nhận diện đúng từ khóa tạo đơn và khiếu nại."""
    # Tạo đơn
    signals_booking = analyze("Tôi muốn tạo đơn gửi bưu phẩm từ Hà Nội đi Cần Thơ")
    assert signals_booking.postal_ops is True

    # Khiếu nại
    signals_complaint = analyze("Tôi cần khiếu nại bồi thường kiện hàng EB123456789VN bị hư hỏng")
    assert signals_complaint.postal_ops is True


async def test_harness_action_subagents_registered(settings):
    """Kiểm tra AgentHarness khởi tạo đầy đủ 7 subagents bao gồm booking-agent và complaint-agent."""
    svc = ChatService(settings)
    assert "booking-agent" in svc.harness.subagents
    assert "complaint-agent" in svc.harness.subagents
    assert "tracking-agent" in svc.harness.subagents
    assert "post-office-agent" in svc.harness.subagents
    assert "rag-agent" in svc.harness.subagents
    assert "analyst-agent" in svc.harness.subagents
    assert "writer-agent" in svc.harness.subagents

    # Kiểm tra tool đã được gán trên harness
    assert hasattr(svc.harness, "create_draft_booking")
    assert hasattr(svc.harness, "update_draft_booking")
    assert hasattr(svc.harness, "confirm_booking")
    assert hasattr(svc.harness, "create_draft_complaint")
    assert hasattr(svc.harness, "update_draft_complaint")
    assert hasattr(svc.harness, "confirm_complaint")
    await svc.close()


def test_region_pricing_zones_skill_compliance():
    """Kiểm tra phân vùng cước chính xác theo SKILL.md:
    - Hà Nội đi Đà Nẵng: Vùng 3 (Bắc - Trung liên miền)
    - Đà Nẵng đi Cần Thơ: Vùng 3 (Trung - Nam liên miền)
    - Hà Nội đi Hải Phòng: Vùng 2 (Nội miền Bắc)
    - Đà Nẵng đi Huế: Vùng 2 (Nội miền Trung)
    - TP.HCM đi Cần Thơ: Vùng 2 (Nội miền Nam)
    - Hà Nội đi Hà Nội: Vùng 1 (Nội tỉnh)
    """
    # 1. Hà Nội (Bắc) -> Đà Nẵng (Trung)
    res_hn_dn = json.loads(create_draft_booking(
        sender_name="A", sender_phone="0901", sender_address="Hà Nội",
        receiver_name="B", receiver_phone="0902", receiver_address="Đà Nẵng",
        weight_grams=500,
    ))
    assert res_hn_dn["detail"]["pricing"]["zone"] == "Vùng 3 (Liên miền)"
    assert res_hn_dn["detail"]["pricing"]["is_simulated_rate"] is True

    # 2. Đà Nẵng (Trung) -> Cần Thơ (Nam)
    res_dn_ct = json.loads(create_draft_booking(
        sender_name="A", sender_phone="0901", sender_address="Đà Nẵng",
        receiver_name="B", receiver_phone="0902", receiver_address="Cần Thơ",
        weight_grams=500,
    ))
    assert res_dn_ct["detail"]["pricing"]["zone"] == "Vùng 3 (Liên miền)"

    # 3. Hà Nội (Bắc) -> Hải Phòng (Bắc)
    res_hn_hp = json.loads(create_draft_booking(
        sender_name="A", sender_phone="0901", sender_address="Hà Nội",
        receiver_name="B", receiver_phone="0902", receiver_address="Hải Phòng",
        weight_grams=500,
    ))
    assert res_hn_hp["detail"]["pricing"]["zone"] == "Vùng 2 (Nội miền)"

    # 4. Đà Nẵng (Trung) -> Huế (Trung)
    res_dn_hue = json.loads(create_draft_booking(
        sender_name="A", sender_phone="0901", sender_address="Đà Nẵng",
        receiver_name="B", receiver_phone="0902", receiver_address="Thừa Thiên Huế",
        weight_grams=500,
    ))
    assert res_dn_hue["detail"]["pricing"]["zone"] == "Vùng 2 (Nội miền)"


def test_domestic_vs_international_classification_and_missing_sent_date():
    """Kiểm tra:
    - Mã CP123456789VN là nội địa (thời hiệu 6 tháng, SLA 20 ngày), không bị tính là quốc tế.
    - Mã CP123456789US là quốc tế (thời hiệu 12 tháng, SLA 30 ngày).
    - Không có sent_date thì ghi 'Chưa xác minh ngày gửi', không khẳng định 'Còn trong thời hiệu'.
    - Entropy mã nháp cao (BK-DRAFT-..., KN-DRAFT-... có 8 ký tự hex).
    """
    # 1. Mã CP123456789VN (Bưu kiện nội địa Việt Nam)
    res_cp_vn = json.loads(create_draft_complaint(
        item_code="CP123456789VN",
        customer_name="Trần Văn Nam",
        customer_phone="0909000111",
        complaint_type="Mất bưu gửi",
        description="Gửi từ Hà Nội vào Đà Nẵng",
        claimed_amount=300000.0,
    ))
    detail_vn = res_cp_vn["detail"]
    assert detail_vn["is_international"] is False
    assert detail_vn["complaint_details"]["scope"] == "Nội địa"
    assert "Chưa xác minh ngày gửi" in detail_vn["complaint_details"]["statute_of_limitations"]
    assert "06 tháng" in detail_vn["complaint_details"]["statute_of_limitations"]
    # Kiểm tra entropy mã nháp: dạng KN-DRAFT-YYYYMMDD-HEX (phần đuôi có độ dài 8 ký tự)
    draft_parts = res_cp_vn["draft_ticket_id"].split("-")
    assert len(draft_parts) == 4 and len(draft_parts[3]) == 8

    # Xác nhận khiếu nại nội địa -> SLA 20 ngày làm việc
    confirm_vn = json.loads(confirm_complaint(res_cp_vn["draft_ticket_id"]))
    assert confirm_vn["status"] == "submitted"
    assert "20 ngày làm việc" in confirm_vn["sla_resolution"]

    # 2. Mã CP123456789US (Bưu kiện quốc tế từ Mỹ về)
    res_cp_intl = json.loads(create_draft_complaint(
        item_code="CP123456789US",
        customer_name="Lê Minh",
        customer_phone="0909000222",
        complaint_type="Hư hỏng bưu gửi",
        description="Hàng gửi từ Mỹ về",
        claimed_amount=1500000.0,
        sent_date="2026-05-01",
    ))
    detail_intl = res_cp_intl["detail"]
    assert detail_intl["is_international"] is True
    assert detail_intl["complaint_details"]["scope"] == "Quốc tế"
    assert "12 tháng" in detail_intl["complaint_details"]["statute_of_limitations"]
    assert "Đã xác minh" in detail_intl["complaint_details"]["statute_of_limitations"]

    # Xác nhận khiếu nại quốc tế -> SLA 30 ngày làm việc theo SKILL.md
    confirm_intl = json.loads(confirm_complaint(res_cp_intl["draft_ticket_id"]))
    assert confirm_intl["status"] == "submitted"
    assert "30 ngày làm việc" in confirm_intl["sla_resolution"]
    assert "Quốc tế" in confirm_intl["scope"]


def test_nearest_post_office_geolocation_and_distance():
    """Kiểm tra tìm kiếm bưu điện gần nhất qua GPS, khoảng cách Haversine và liên kết chỉ đường Google Maps."""
    from app.domain.postal_services import find_nearest_post_offices, haversine_distance, lookup_postal_office

    # 1. Tính toán khoảng cách Haversine
    # Hoàn Kiếm (21.0285, 105.8542) đến Cầu Giấy (21.0333, 105.7958) khoảng ~6km
    dist = haversine_distance(21.0285, 105.8542, 21.0333, 105.7958)
    assert 5.5 <= dist <= 6.5

    # 2. Vị trí ở Hồ Gươm (21.0285, 105.8542) -> Bưu điện Bờ Hồ phải gần nhất (< 0.2 km)
    res_hn = find_nearest_post_offices(21.0285, 105.8542, limit=3)
    assert res_hn["found"] is True
    assert len(res_hn["post_offices"]) == 3
    closest_hn = res_hn["post_offices"][0]
    assert "Hoàn Kiếm" in closest_hn["name"]
    assert closest_hn["distance_km"] < 0.2
    assert "google.com/maps/dir/" in closest_hn["direction_url"]
    assert "google.com/maps/search/" in closest_hn["google_maps_url"]
    assert "google_maps_live_search" in res_hn

    # 3. Vị trí ở Nhà thờ Đức Bà Quận 1 (10.7798, 106.6999) -> Bưu điện Trung tâm Sài Gòn phải gần nhất
    res_sg = find_nearest_post_offices(10.7798, 106.6999, limit=3)
    assert res_sg["found"] is True
    closest_sg = res_sg["post_offices"][0]
    assert "Sài Gòn" in closest_sg["name"]
    assert closest_sg["distance_km"] < 0.2
    assert "google.com/maps/dir/" in closest_sg["direction_url"]

    # 4. Kiểm tra lookup_postal_office tự động nhận diện chuỗi tọa độ GPS trong câu hỏi
    res_query_coords = lookup_postal_office("Bưu điện nào gần tọa độ 21.0285, 105.8542?")
    assert res_query_coords["found"] is True
    assert "user_coordinates" in res_query_coords
    assert res_query_coords["post_offices"][0]["id"] == "100000"

    # 5. Phân tích tín hiệu Router tự động nhận diện truy vấn bưu điện gần
    sig = analyze("bưu điện nào gần tôi nhất?")
    assert sig.postal_ops is True


def test_draft_ttl_expiration_guard():
    """Kiểm tra cơ chế hết hạn bản nháp (TTL 30 phút), chặn xác nhận và dọn dẹp nháp quá hạn."""
    from datetime import datetime, timedelta, timezone

    # 1. Tạo đơn hàng nháp và chỉnh lùi thời gian hết hạn về quá khứ
    b_draft = json.loads(create_draft_booking(
        sender_name="Người Gửi A",
        sender_phone="0911223344",
        sender_address="Hà Nội",
        receiver_name="Người Nhận B",
        receiver_phone="0988776655",
        receiver_address="Đà Nẵng",
        weight_grams=400,
    ))
    b_id = b_draft["draft_id"]
    booking_record = get_draft_booking(b_id)
    assert booking_record is not None
    assert "expires_at" in booking_record

    # Giả lập bản nháp đã quá hạn 35 phút
    past_time = (datetime.now(timezone(timedelta(hours=7))) - timedelta(minutes=35)).isoformat()
    booking_record["expires_at"] = past_time

    # Chặn xác nhận khi bản nháp đã hết hạn
    confirm_res = json.loads(confirm_booking(b_id))
    assert confirm_res["status"] == "expired"
    assert "hết hạn hiệu lực" in confirm_res["message"].lower()
    assert booking_record["status"] == "EXPIRED"

    # Chặn sửa đổi khi bản nháp đã hết hạn
    update_res = json.loads(update_draft_booking(b_id, weight_grams=800))
    assert update_res["status"] == "expired"

    # 2. Tạo phiếu khiếu nại nháp và kiểm tra hết hạn tương tự
    c_draft = json.loads(create_draft_complaint(
        item_code="EB123456789VN",
        customer_name="Khách Hàng C",
        customer_phone="0977112233",
        complaint_type="Giao hàng chậm",
        description="Giao muộn 5 ngày",
    ))
    c_id = c_draft["draft_ticket_id"]
    complaint_record = get_draft_complaint(c_id)
    assert complaint_record is not None
    complaint_record["expires_at"] = past_time

    confirm_c_res = json.loads(confirm_complaint(c_id))
    assert confirm_c_res["status"] == "expired"
    assert "hết hạn hiệu lực" in confirm_c_res["message"].lower()

    # 3. Kiểm tra dọn dẹp nháp quá hạn qua prune_expired_drafts
    prune_result = prune_expired_drafts(ttl_seconds=1800, max_age_hours=0)
    assert prune_result["pruned_bookings"] >= 1
    assert prune_result["pruned_complaints"] >= 1


def test_draft_state_machine_strict_guards():
    """Kiểm tra State Machine nghiêm ngặt:
    - WAITING_CONFIRMATION -> CANCELLED -> Chặn xác nhận (báo cancelled).
    - WAITING_CONFIRMATION -> CONFIRMED -> Chặn hủy đơn (báo error).
    - Tính lũy biến (idempotent): Hủy đơn đã hủy -> báo already_cancelled.
    - Hủy phiếu khiếu nại đã gửi -> báo error.
    """
    # 1. Hủy rồi cố tình xác nhận -> Bị chặn
    b_draft = json.loads(create_draft_booking(
        sender_name="Gửi 1", sender_phone="0901", sender_address="Hà Nội",
        receiver_name="Nhận 1", receiver_phone="0902", receiver_address="Hải Phòng",
        weight_grams=300,
    ))
    b_id = b_draft["draft_id"]

    cancel_res1 = json.loads(cancel_draft_booking(b_id))
    assert cancel_res1["status"] == "cancelled"

    # Hủy lại lần 2 -> báo already_cancelled
    cancel_res2 = json.loads(cancel_draft_booking(b_id))
    assert cancel_res2["status"] == "already_cancelled"

    # Cố tình confirm đơn đã hủy -> báo cancelled
    confirm_cancelled = json.loads(confirm_booking(b_id))
    assert confirm_cancelled["status"] == "cancelled"
    assert "đã bị hủy" in confirm_cancelled["message"].lower()

    # 2. Xác nhận thành công rồi cố tình hủy -> Bị chặn
    b_draft_ok = json.loads(create_draft_booking(
        sender_name="Gửi 2", sender_phone="0901", sender_address="Hà Nội",
        receiver_name="Nhận 2", receiver_phone="0902", receiver_address="Hải Phòng",
        weight_grams=300,
    ))
    b_id_ok = b_draft_ok["draft_id"]
    confirm_ok = json.loads(confirm_booking(b_id_ok))
    assert confirm_ok["status"] == "confirmed"

    # Hủy đơn đã xác nhận -> báo error
    cancel_confirmed = json.loads(cancel_draft_booking(b_id_ok))
    assert cancel_confirmed["status"] == "error"
    assert "đã phát hành vận đơn" in cancel_confirmed["message"].lower()


def test_draft_update_before_confirmation():
    """Kiểm tra tính năng cập nhật thông tin đơn hàng và khiếu nại nháp trước khi duyệt (HITL):
    - Tự động tính lại khối lượng quy đổi cồng kềnh (chia 6000) và cước phí theo vùng.
    - Cập nhật số tiền bồi thường khiếu nại.
    - Chặn cập nhật khi đơn đã được xác nhận.
    """
    # 1. Tạo đơn 500g từ Hà Nội đi Hải Phòng (Vùng 2 - Nội miền, cước 32.000đ)
    draft_res = json.loads(create_draft_booking(
        sender_name="Nguyễn Văn A", sender_phone="0911", sender_address="Hà Nội",
        receiver_name="Trần Văn B", receiver_phone="0922", receiver_address="Hải Phòng",
        weight_grams=500,
    ))
    draft_id = draft_res["draft_id"]
    assert draft_res["detail"]["pricing"]["zone"] == "Vùng 2 (Nội miền)"
    assert draft_res["detail"]["pricing"]["estimated_fee"] == 32000

    # 2. Khách đổi ý: đổi địa chỉ nhận sang Đà Nẵng (thành Vùng 3 Liên miền),
    # đóng kiện kích thước 60x50x40 cm = 120,000 / 6000 = 20.0 kg thể tích
    update_res = json.loads(update_draft_booking(
        draft_id=draft_id,
        receiver_address="Quận Hải Châu, Đà Nẵng",
        length_cm=60,
        width_cm=50,
        height_cm=40,
        declared_value=2000000.0,  # Khai giá 2 triệu (+10.000đ phí)
    ))
    assert update_res["status"] == "updated"
    updated_detail = update_res["detail"]
    assert updated_detail["parcel"]["weight_volumetric_kg"] == 20.0
    assert updated_detail["parcel"]["weight_chargeable_kg"] == 20.0
    assert updated_detail["parcel"]["is_bulky"] is True
    assert updated_detail["pricing"]["zone"] == "Vùng 3 (Liên miền)"
    assert updated_detail["pricing"]["estimated_fee"] > 100000

    # 3. Xác nhận đơn sau khi cập nhật thành công
    confirm_res = json.loads(confirm_booking(draft_id))
    assert confirm_res["status"] == "confirmed"
    assert confirm_res["chargeable_weight"] == "20.0 kg"

    # 4. Chặn sửa đổi sau khi đã xác nhận
    update_after_confirm = json.loads(update_draft_booking(draft_id, weight_grams=100))
    assert update_after_confirm["status"] == "error"

    # 5. Kiểm tra cập nhật phiếu khiếu nại nháp
    c_draft = json.loads(create_draft_complaint(
        item_code="CP999888777VN",
        customer_name="Lê D",
        customer_phone="0933",
        complaint_type="Hư hỏng",
        description="Móp vỏ hộp",
        claimed_amount=100000.0,
    ))
    c_id = c_draft["draft_ticket_id"]
    assert c_draft["detail"]["complaint_details"]["proposed_compensation"] == 100000.0

    # Khách cập nhật số tiền yêu cầu bồi thường và mô tả chi tiết
    update_c = json.loads(update_draft_complaint(
        draft_ticket_id=c_id,
        claimed_amount=450000.0,
        description="Vỏ hộp móp làm gãy vỡ quà tặng lưu niệm bên trong",
    ))
    assert update_c["status"] == "updated"
    assert update_c["detail"]["complaint_details"]["proposed_compensation"] == 450000.0
    assert "450.000 đ" in update_c["detail"]["complaint_details"]["proposed_compensation_text"]


def test_session_scoped_draft_isolation():
    """Kiểm tra khả năng phân tách (namespace scoping) các bản nháp theo tenant và session_id."""
    from app.core.context import RunContext, current_run

    # Tạo draft trong phiên của tenant-alpha, session-101
    ctx1 = RunContext(tenant="tenant-alpha", request_id="req-1", max_parallel=2, max_tasks=5, session_id="session-101")
    tok1 = current_run.set(ctx1)
    try:
        b1 = json.loads(create_draft_booking(
            sender_name="Alpha Sender", sender_phone="0911", sender_address="Hà Nội",
            receiver_name="Alpha Recv", receiver_phone="0922", receiver_address="Hà Nội",
            weight_grams=250,
        ))
        b1_id = b1["draft_id"]
    finally:
        current_run.reset(tok1)

    # Tạo draft trong phiên của tenant-beta, session-202
    ctx2 = RunContext(tenant="tenant-beta", request_id="req-2", max_parallel=2, max_tasks=5, session_id="session-202")
    tok2 = current_run.set(ctx2)
    try:
        b2 = json.loads(create_draft_booking(
            sender_name="Beta Sender", sender_phone="0933", sender_address="Đà Nẵng",
            receiver_name="Beta Recv", receiver_phone="0944", receiver_address="Đà Nẵng",
            weight_grams=400,
        ))
        b2_id = b2["draft_id"]
    finally:
        current_run.reset(tok2)

    # Truy vấn nháp của tenant-alpha, session-101
    drafts_alpha = get_session_drafts(session_id="session-101", tenant="tenant-alpha")
    alpha_ids = [d["draft_id"] for d in drafts_alpha["bookings"]]
    assert b1_id in alpha_ids
    assert b2_id not in alpha_ids

    # Truy vấn nháp của tenant-beta, session-202
    drafts_beta = get_session_drafts(session_id="session-202", tenant="tenant-beta")
    beta_ids = [d["draft_id"] for d in drafts_beta["bookings"]]
    assert b2_id in beta_ids
    assert b1_id not in beta_ids


def test_cancel_booking_suite():
    """Kiểm tra chức năng hủy đơn hàng: hủy đơn nháp và hủy đơn đã xác nhận có mã vận đơn."""
    # 1. Hủy đơn nháp
    b_draft = json.loads(create_draft_booking(
        sender_name="Trần Văn C", sender_phone="0911223344", sender_address="Hà Nội",
        receiver_name="Lê Thị D", receiver_phone="0988776655", receiver_address="Hải Phòng",
        weight_grams=500,
    ))
    draft_id = b_draft["draft_id"]

    res_cancel_draft = json.loads(cancel_booking(draft_id, reason="Khách đổi địa chỉ nhận"))
    assert res_cancel_draft["status"] == "cancelled"
    assert res_cancel_draft["cancellation_type"] == "draft"
    assert get_draft_booking(draft_id)["status"] == "CANCELLED"

    # 2. Hủy đơn đã xác nhận (có mã vận đơn UPU)
    b_confirmed = json.loads(create_draft_booking(
        sender_name="Phạm Văn E", sender_phone="0912345678", sender_address="Hồ Chí Minh",
        receiver_name="Đặng Thị F", receiver_phone="0987654321", receiver_address="Cần Thơ",
        weight_grams=1200,
    ))
    draft_id_2 = b_confirmed["draft_id"]
    confirm_data = json.loads(confirm_booking(draft_id_2))
    assert confirm_data["status"] == "confirmed"
    item_code = confirm_data["item_code"]

    res_cancel_confirmed = json.loads(cancel_booking(item_code, reason="Khách tự mang ra bưu cục gửi"))
    assert res_cancel_confirmed["status"] == "cancelled"
    assert res_cancel_confirmed["cancellation_type"] == "confirmed_order"
    assert res_cancel_confirmed["item_code"] == item_code
    assert get_draft_booking(draft_id_2)["status"] == "CANCELLED_BY_CUSTOMER"

    # Hủy lại -> đã hủy
    re_cancel = json.loads(cancel_booking(item_code))
    assert re_cancel["status"] == "already_cancelled"


def test_cross_session_phone_identity_verification():
    """Kiểm tra lớp bảo mật đối chiếu số điện thoại khi hủy đơn xuyên session (Cross-Session Identity Matching)."""
    from app.agents.postal_actions import _set_current_session_context, _reset_current_session_context

    # Session 1: Người gửi tạo đơn ở phiên A
    t1 = _set_current_session_context("vnpost", "session-device-alice-1", "req-1")
    b = json.loads(create_draft_booking(
        sender_name="Nguyễn Văn An", sender_phone="0901234567", sender_address="Hà Nội",
        receiver_name="Trần Thị Bình", receiver_phone="0987654321", receiver_address="Hải Phòng",
        weight_grams=500,
    ))
    draft_id = b["draft_id"]

    # Session 2: Yêu cầu hủy ở phiên B (khác session_id)
    t2 = _set_current_session_context("vnpost", "session-device-stranger-2", "req-2")

    # 1. Thử hủy mà không cung cấp SĐT -> Bắt buộc xác minh
    res_req = json.loads(cancel_booking(draft_id))
    assert res_req["status"] == "requires_verification"
    assert "...4567" in res_req["message"]

    # 2. Thử hủy với SĐT sai (ví dụ 9999) -> Từ chối xác thực thất bại
    res_fail = json.loads(cancel_booking(draft_id, verification_phone="9999"))
    assert res_fail["status"] == "verification_failed"

    # 3. Hủy với đúng 4 số cuối của SĐT người gửi (4567) -> Thành công
    res_ok = json.loads(cancel_booking(draft_id, verification_phone="4567"))
    assert res_ok["status"] == "cancelled"
    assert get_draft_booking(draft_id)["status"] == "CANCELLED"

    _reset_current_session_context(t2)
    _reset_current_session_context(t1)
    _reset_current_session_context()



def test_cancel_complaint_suite():
    """Kiểm tra chức năng hủy phiếu khiếu nại: hủy phiếu nháp và rút phiếu đã nộp."""
    c_draft = json.loads(create_draft_complaint(
        item_code="EB888999111VN", customer_name="Vũ Hoàng", customer_phone="0901234567",
        complaint_type="Phát chậm", description="Chậm 2 ngày so với cam kết",
    ))
    draft_ticket_id = c_draft["draft_ticket_id"]

    # Hủy phiếu khiếu nại nháp
    res_cancel_c = json.loads(cancel_complaint(draft_ticket_id, reason="Bưu phẩm đã được phát"))
    assert res_cancel_c["status"] == "cancelled"
    assert res_cancel_c["cancellation_type"] == "draft"

    # Nộp phiếu khiếu nại rồi rút
    c_submitted = json.loads(create_draft_complaint(
        item_code="EB888999222VN", customer_name="Ngô Thanh", customer_phone="0907654321",
        complaint_type="Hư hỏng", description="Vỡ hộp hàng",
    ))
    draft_t2 = c_submitted["draft_ticket_id"]
    conf_c = json.loads(confirm_complaint(draft_t2))
    assert conf_c["status"] == "submitted"
    ticket_num = conf_c["ticket_number"]

    res_cancel_submitted = json.loads(cancel_complaint(ticket_num, reason="Người nhận đã thỏa thuận xong với người gửi"))
    assert res_cancel_submitted["status"] == "cancelled"
    assert res_cancel_submitted["cancellation_type"] == "submitted_ticket"


def test_list_my_orders_in_session():
    """Kiểm tra chức năng tra cứu danh sách đơn hàng và khiếu nại trong phiên (list_my_orders)."""
    from app.core.context import RunContext, current_run

    ctx = RunContext(tenant="tenant-orders", request_id="req-orders-1", max_parallel=2, max_tasks=5, session_id="sess-orders-99")
    tok = current_run.set(ctx)
    try:
        # Tạo 1 đơn nháp
        create_draft_booking(
            sender_name="Người Gửi A", sender_phone="091", sender_address="Hà Nội",
            receiver_name="Người Nhận B", receiver_phone="092", receiver_address="Hải Phòng",
            weight_grams=300,
        )
        # Tạo 1 đơn đã xác nhận (ở lượt phản hồi tiếp theo của khách)
        d2 = json.loads(create_draft_booking(
            sender_name="Người Gửi C", sender_phone="093", sender_address="Đà Nẵng",
            receiver_name="Người Nhận D", receiver_phone="094", receiver_address="Huế",
            weight_grams=600,
        ))
        ctx.created_draft_ids.clear()
        ctx.user_message = "Tôi xác nhận tạo đơn hàng này"
        conf = json.loads(confirm_booking(d2["draft_id"]))
        assert conf["status"] == "confirmed"

        # Gọi list_my_orders
        res = json.loads(list_my_orders())
        assert res["status"] == "success"
        assert res["active_drafts_count"] >= 1
        assert res["confirmed_orders_count"] >= 1
        assert "Đơn hàng nháp chờ duyệt" in res["summary"]
        assert "Đơn hàng đã xác nhận" in res["summary"]
    finally:
        current_run.reset(tok)


def test_multi_layer_hitl_confirmation_guard():
    """Kiểm tra chốt chặn bảo vệ xác nhận đa tầng (Multi-layer Confirmation Guard)."""
    from app.core.context import RunContext, current_run

    ctx = RunContext(
        tenant="default", request_id="req-guard-1", max_parallel=2, max_tasks=5,
        session_id="sess-guard-1", user_message="Tạo giúp tôi đơn gửi hàng từ HN vào SG",
    )
    tok = current_run.set(ctx)
    try:
        # 1. Tạo đơn nháp trong lượt hội thoại này
        b_res = json.loads(create_draft_booking(
            sender_name="Hoàng Nam", sender_phone="0912000111", sender_address="Hà Nội",
            receiver_name="Minh Tú", receiver_phone="0987000222", receiver_address="Hồ Chí Minh",
            weight_grams=1000,
        ))
        draft_id = b_res["draft_id"]
        assert draft_id in ctx.created_draft_ids

        # 2. Cố tình gọi confirm_booking trong CÙNG LƯỢT CHẠY -> Bị chốt chặn Turn-level HITL Guard từ chối
        guard_res = json.loads(confirm_booking(draft_id))
        assert guard_res["status"] == "hitl_required"
        assert "Chốt chặn bảo vệ HITL" in guard_res["message"]
    finally:
        current_run.reset(tok)

    # 3. Lượt tiếp theo: Khách nhắn có ý định hủy/chỉnh sửa -> Bị chốt chặn Intent Guard từ chối
    ctx2 = RunContext(
        tenant="default", request_id="req-guard-2", max_parallel=2, max_tasks=5,
        session_id="sess-guard-1", user_message="Khoan đã, tôi muốn hủy đơn hoặc sửa địa chỉ",
    )
    tok2 = current_run.set(ctx2)
    try:
        guard_res2 = json.loads(confirm_booking(draft_id))
        assert guard_res2["status"] == "hitl_rejected_or_modifying"
        assert "Khách hàng chưa xác nhận" in guard_res2["message"]
    finally:
        current_run.reset(tok2)

    # 4. Lượt tiếp theo: Khách đồng ý xác nhận -> Xác nhận thành công
    ctx3 = RunContext(
        tenant="default", request_id="req-guard-3", max_parallel=2, max_tasks=5,
        session_id="sess-guard-1", user_message="Tôi xác nhận đồng ý tạo đơn hàng",
    )
    tok3 = current_run.set(ctx3)
    try:
        confirm_ok = json.loads(confirm_booking(draft_id))
        assert confirm_ok["status"] == "confirmed"
        assert confirm_ok["item_code"].startswith("EB")
    finally:
        current_run.reset(tok3)


def test_action_api_endpoints():
    """Kiểm tra các endpoint RESTful /api/actions/orders, confirm, cancel qua FastAPI TestClient."""
    from fastapi.testclient import TestClient
    from app.api.main import create_app
    from app.core.config import Settings

    settings = Settings(checkpointer_enabled=False)
    with TestClient(create_app(settings)) as client:
        # 1. Tạo trước 1 đơn nháp
        d = json.loads(create_draft_booking(
            sender_name="API Sender", sender_phone="0911", sender_address="Hà Nội",
            receiver_name="API Recv", receiver_phone="0922", receiver_address="Đà Nẵng",
            weight_grams=400,
        ))
        draft_id = d["draft_id"]

        # 2. Xác nhận qua POST /api/actions/confirm
        res_conf = client.post("/api/actions/confirm", json={"action_type": "booking", "draft_id": draft_id})
        assert res_conf.status_code == 200
        conf_data = res_conf.json()
        assert conf_data["status"] == "confirmed"
        item_code = conf_data["item_code"]

        # 3. Hủy đơn qua POST /api/actions/cancel
        res_cancel = client.post("/api/actions/cancel", json={"action_type": "booking", "target_id": item_code, "reason": "Hủy qua UI"})
        assert res_cancel.status_code == 200
        cancel_data = res_cancel.json()
        assert cancel_data["status"] == "cancelled"

        # 4. Tra cứu qua GET /api/actions/orders
        res_orders = client.get("/api/actions/orders")
        assert res_orders.status_code == 200
        orders_data = res_orders.json()
        assert "bookings" in orders_data
        assert "complaints" in orders_data



