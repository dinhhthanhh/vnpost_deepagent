import asyncio
import json
import uuid
import pytest
from starlette.testclient import TestClient

from app.api.main import create_app
from app.api.schemas import ChatRequest
from app.core.config import Settings
from app.core.context import RunContext, current_run
from app.service import ChatService, _SLOT_PROMPT, SafeStreamBuffer
from app.agents.postal_actions import (
    create_draft_booking,
    update_draft_booking,
    confirm_booking,
    cancel_booking,
    cancel_draft_booking,
    create_draft_complaint,
    update_draft_complaint,
    confirm_complaint,
    get_draft_booking,
    get_draft_complaint,
    _hitl_gate,
    _VERIFY_FAILS,
)


@pytest.fixture
def clean_settings():
    return Settings(
        checkpointer_enabled=False,
        demo_mode=True,
        postgres_url="",
    )


def make_ctx(tenant="default", session_id="sess-1", user_message="", request_id="req-1"):
    return RunContext(
        tenant=tenant,
        request_id=request_id,
        max_parallel=2,
        max_tasks=5,
        session_id=session_id,
        user_message=user_message,
    )


def test_confirm_keywords_and_hitl_gate():
    """Kiểm tra các từ khóa ngắn 'ok', 'dạ', 'đúng rồi' được HITL gate chấp nhận."""
    tok0 = current_run.set(make_ctx(session_id="sess-kw-1", user_message="Tạo đơn"))
    try:
        draft = json.loads(
            create_draft_booking(
                sender_name="Nguyễn Văn A",
                sender_phone="0912345678",
                sender_address="Hà Nội",
                receiver_name="Trần Thị B",
                receiver_phone="0987654321",
                receiver_address="Hồ Chí Minh",
                weight_grams=500,
            )
        )
        draft_id = draft["draft_id"]
    finally:
        current_run.reset(tok0)

    record = get_draft_booking(draft_id)

    # 1. Khách nhắn "ok" ở lượt tiếp theo
    tok = current_run.set(make_ctx(session_id="sess-kw-1", user_message="ok", request_id="req-ok"))
    try:
        assert _hitl_gate(draft_id, record) is None
    finally:
        current_run.reset(tok)

    # 2. Khách nhắn "dạ" ở lượt tiếp theo
    tok = current_run.set(make_ctx(session_id="sess-kw-1", user_message="dạ", request_id="req-da"))
    try:
        assert _hitl_gate(draft_id, record) is None
    finally:
        current_run.reset(tok)

    # 3. Khách nhắn "đúng rồi" ở lượt tiếp theo
    tok = current_run.set(make_ctx(session_id="sess-kw-1", user_message="đúng rồi", request_id="req-dung"))
    try:
        assert _hitl_gate(draft_id, record) is None
    finally:
        current_run.reset(tok)


def test_booking_multiturn_flow():
    """Kịch bản gửi hàng đa lượt: Tạo nháp -> Kiểm tra -> Sửa khối lượng -> Xác nhận -> Phát hành mã vận đơn."""
    sid = "sess-booking-multi"
    tok1 = current_run.set(make_ctx(session_id=sid, user_message="Tôi muốn gửi bưu phẩm EMS"))
    try:
        res1 = json.loads(
            create_draft_booking(
                sender_name="Lê Văn C",
                sender_phone="0901234567",
                sender_address="Đà Nẵng",
                receiver_name="Phạm Thị D",
                receiver_phone="0907654321",
                receiver_address="Cần Thơ",
                weight_grams=800,
                service_type="EMS",
            )
        )
        assert res1["status"] == "waiting_confirmation"
        draft_id = res1["draft_id"]
    finally:
        current_run.reset(tok1)

    # Sửa khối lượng trước khi xác nhận
    res_upd = json.loads(update_draft_booking(draft_id=draft_id, weight_grams=1500))
    assert res_upd["status"] == "updated"

    # Lượt 2: Khách nhắn "xác nhận gửi hàng"
    tok2 = current_run.set(make_ctx(session_id=sid, user_message="Tôi xác nhận tạo đơn hàng này", request_id="req-confirm"))
    try:
        res2 = json.loads(confirm_booking(draft_id))
        assert res2["status"] == "confirmed"
        assert res2["item_code"].startswith("EB")
        assert "phát hành mã vận đơn" in res2["message"].lower() or "thành công" in res2["message"].lower()
    finally:
        current_run.reset(tok2)


def test_complaint_multiturn_flow():
    """Kịch bản khiếu nại đa lượt: Tạo nháp phiếu -> Sửa số tiền bồi thường -> Xác nhận -> Nộp hồ sơ."""
    sid = "sess-complaint-multi"
    tok1 = current_run.set(make_ctx(session_id=sid, user_message="Tôi muốn khiếu nại đơn EB123456789VN"))
    try:
        res1 = json.loads(
            create_draft_complaint(
                item_code="EB123456789VN",
                customer_name="Trần Văn Khiếu",
                customer_phone="0912345678",
                complaint_type="Hàng bị móp méo",
                description="Bưu phẩm bị móp méo vỏ hộp khi nhận",
                sent_date="2026-09-01",
            )
        )
        assert res1["status"] == "waiting_confirmation"
        draft_id = res1["draft_ticket_id"]
    finally:
        current_run.reset(tok1)

    # Lượt 2: Khách sửa bổ sung số tiền yêu cầu bồi thường
    res2 = json.loads(
        update_draft_complaint(
            draft_ticket_id=draft_id,
            description="Hàng bị móp méo nặng và vỡ niêm phong hộp quà bên trong",
            claimed_amount=500000.0,
        )
    )
    assert res2["status"] == "updated"

    # Lượt 3: Khách nhắn "ok nộp đi em"
    tok2 = current_run.set(make_ctx(session_id=sid, user_message="ok nộp đi em", request_id="req-sub"))
    try:
        res3 = json.loads(confirm_complaint(draft_id))
        assert res3["status"] in {"submitted", "confirmed"}
        assert res3["ticket_number"].startswith("KN-")
    finally:
        current_run.reset(tok2)


def test_two_drafts_old_card_blocked_by_not_latest_draft():
    """Hai nháp cùng một phiên: bấm thẻ cũ bị backend chặn bằng not_latest_draft."""
    sid = "sess-two-drafts"
    tok1 = current_run.set(make_ctx(session_id=sid, user_message="Tạo đơn 1", request_id="req-d1"))
    try:
        d1 = json.loads(
            create_draft_booking(
                sender_name="Người Gửi 1",
                sender_phone="0911111111",
                sender_address="Hà Nội",
                receiver_name="Người Nhận 1",
                receiver_phone="0922222222",
                receiver_address="Hồ Chí Minh",
                weight_grams=500,
            )
        )
        draft_id_1 = d1["draft_id"]
    finally:
        current_run.reset(tok1)

    # Nháp 2 (mới hơn)
    tok2 = current_run.set(make_ctx(session_id=sid, user_message="Tạo đơn 2", request_id="req-d2"))
    try:
        d2 = json.loads(
            create_draft_booking(
                sender_name="Người Gửi 2",
                sender_phone="0933333333",
                sender_address="Hải Phòng",
                receiver_name="Người Nhận 2",
                receiver_phone="0944444444",
                receiver_address="Đà Nẵng",
                weight_grams=1200,
            )
        )
        draft_id_2 = d2["draft_id"]
    finally:
        current_run.reset(tok2)

    # Bấm thẻ cũ (nháp 1) -> Bị chặn
    tok3 = current_run.set(make_ctx(session_id=sid, user_message="xác nhận", request_id="req-conf-old"))
    try:
        conf_old = json.loads(confirm_booking(draft_id_1))
        assert conf_old["status"] == "not_latest_draft"
        assert "không phải bản nháp mới nhất" in conf_old["message"]

        # Bấm thẻ mới (nháp 2) -> Thành công
        conf_new = json.loads(confirm_booking(draft_id_2))
        assert conf_new["status"] == "confirmed"
        assert conf_new["item_code"].startswith("EB")
    finally:
        current_run.reset(tok3)


def test_voice_readback_slot_prompt_matching():
    """Kiểm tra _SLOT_PROMPT khớp câu hỏi đọc lại mã/SĐT khi khách đáp 'đúng rồi'."""
    assistant_readback_1 = "Mipo xin đọc lại mã vận đơn của anh/chị là EB123456789VN, có phải không ạ?"
    assistant_readback_2 = "Anh/chị vui lòng xác nhận lại số điện thoại 0912345678 đã đúng chưa ạ?"
    assistant_readback_3 = "Mã bưu gửi anh/chị vừa đọc là CP987654321VN đúng không ạ?"

    assert bool(_SLOT_PROMPT.search(assistant_readback_1))
    assert bool(_SLOT_PROMPT.search(assistant_readback_2))
    assert bool(_SLOT_PROMPT.search(assistant_readback_3))

    # Khi trợ lý vừa hỏi đọc lại, _open_flow trả về True để lượt kế tiếp (khách nói 'đúng rồi') đi Deep Agent
    svc = ChatService(Settings(checkpointer_enabled=False, demo_mode=True, postgres_url=""))
    sid = "sess-voice-test"
    svc.store.save_turn("default", sid, "Tôi muốn tra cứu EB123456789VN", assistant_readback_3, 10)
    assert svc._open_flow("default", sid) is True


def test_rest_confirm_saves_turn_visible_to_next_chat(clean_settings):
    """Sau khi bấm xác nhận bằng REST /api/actions/confirm, store lưu lượt hội thoại và có mã đơn."""
    svc = ChatService(clean_settings)
    app = create_app(clean_settings, service=svc)
    with TestClient(app) as client:
        sid = "sess-rest-chat-flow"

        # 1. Tạo đơn nháp gắn với session và tenant vnpost (tenant mặc định của anonymous testclient)
        tok = current_run.set(make_ctx(tenant="vnpost", session_id=sid, user_message="Tạo đơn"))
        try:
            draft = json.loads(
                create_draft_booking(
                    sender_name="Trần Văn Minh",
                    sender_phone="0918888999",
                    sender_address="Hà Nội",
                    receiver_name="Võ Thị Hoa",
                    receiver_phone="0987777666",
                    receiver_address="Hồ Chí Minh",
                    weight_grams=600,
                )
            )
            draft_id = draft["draft_id"]
        finally:
            current_run.reset(tok)

        # 2. Người dùng bấm nút 'Xác nhận' trên giao diện gọi REST API
        resp = client.post(
            "/api/actions/confirm",
            json={"action_type": "booking", "draft_id": draft_id, "session_id": sid},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in {"confirmed", "already_confirmed"}
        item_code = data["item_code"]

        # 3. Kiểm tra store.history của session đã chứa lượt save_turn với item_code
        history = svc.store.history("vnpost", sid)
        assert len(history) >= 2
        last_user_turn = [t for t in history if t.get("role") == "user"][-1]
        assert draft_id in last_user_turn["content"]
        last_assistant_turn = [t for t in history if t.get("role") == "assistant"][-1]
        assert item_code in last_assistant_turn["content"]


def test_confirm_with_data_is_blocked():
    """Các câu 'dạ 0912345678 nhé', 'ok nhưng đổi địa chỉ thành…', 'đúng rồi, mã là EB123456789VN'
    phải bị HITL gate chặn, không được xác nhận phát hành mã."""
    sid = "sess-block-data"
    tok0 = current_run.set(make_ctx(session_id=sid, user_message="Tạo đơn"))
    try:
        draft = json.loads(
            create_draft_booking(
                sender_name="Nguyễn Văn A",
                sender_phone="0912345678",
                sender_address="Hà Nội",
                receiver_name="Trần Thị B",
                receiver_phone="0987654321",
                receiver_address="Hồ Chí Minh",
                weight_grams=500,
            )
        )
        draft_id = draft["draft_id"]
    finally:
        current_run.reset(tok0)

    record = get_draft_booking(draft_id)

    # 1. Khách gửi: "dạ 0912345678 nhé" (khách đang đưa SĐT khi nháp đang chờ) -> Bị gate chặn
    tok1 = current_run.set(make_ctx(session_id=sid, user_message="dạ 0912345678 nhé"))
    try:
        res1 = _hitl_gate(draft_id, record)
        assert res1 is not None
        assert json.loads(res1)["status"] == "hitl_required"
    finally:
        current_run.reset(tok1)

    # 2. Khách gửi: "ok nhưng đổi địa chỉ thành…" -> Bị gate chặn
    tok2 = current_run.set(make_ctx(session_id=sid, user_message="ok nhưng đổi địa chỉ thành số 10 Cầu Giấy"))
    try:
        res2 = _hitl_gate(draft_id, record)
        assert res2 is not None
        assert json.loads(res2)["status"] in {"hitl_rejected_or_modifying", "hitl_required"}
    finally:
        current_run.reset(tok2)

    # 3. Khách gửi: "đúng rồi, mã là EB123456789VN" -> Bị gate chặn
    tok3 = current_run.set(make_ctx(session_id=sid, user_message="đúng rồi, mã là EB123456789VN"))
    try:
        res3 = _hitl_gate(draft_id, record)
        assert res3 is not None
        assert json.loads(res3)["status"] == "hitl_required"
    finally:
        current_run.reset(tok3)

    # 4. Xác nhận chuẩn: "Tôi xác nhận đồng ý tạo đơn hàng BK-DRAFT-XXX" -> Cho qua
    tok4 = current_run.set(make_ctx(session_id=sid, user_message=f"Tôi xác nhận đồng ý tạo đơn hàng {draft_id}"))
    try:
        assert _hitl_gate(draft_id, record) is None
    finally:
        current_run.reset(tok4)


@pytest.mark.asyncio
async def test_need_agent_not_leaked(clean_settings):
    """Khi Fast RAG trả cờ [[NEED_AGENT]], bộ đệm SafeStreamBuffer không làm rò rỉ token marker ra SSE
    và ChatService tự động leo thang định tuyến sang Deep Agent."""
    # 1. Kiểm tra SafeStreamBuffer chặn sạch token [[NEED_AGENT]] khi stream từng phần
    emitted = []
    buf = SafeStreamBuffer(lambda tok: emitted.append(tok))
    for chunk in ["[", "[", "NEED_", "AGENT", "]]"]:
        buf.push(chunk)
    buf.flush()
    streamed = "".join(emitted)
    assert "[[NEED_AGENT]]" not in streamed
    assert streamed == ""

    # 2. Kiểm tra ChatService leo thang sang Deep Agent khi Fast RAG stream trả [[NEED_AGENT]]
    svc = ChatService(clean_settings)

    async def mock_stream(*args, **kwargs):
        yield "[[NEED_"
        yield "AGENT]]"

    svc.fast_rag.stream = mock_stream

    queue = asyncio.Queue()
    req = ChatRequest(
        message="Thời gian chuyển phát thư bưu phẩm tiêu chuẩn là bao lâu?",
        session_id=uuid.uuid4(),
        grounded=False,
    )
    resp = await svc.chat("default", req, queue=queue)

    assert "[[NEED_AGENT]]" not in resp.answer
    assert resp.route == "deep"
    assert any(e.get("reason") == "need_agent_marker" for e in resp.events)

    # Kiểm tra các token bắn qua SSE queue không chứa [[NEED_AGENT]]
    sse_tokens = []
    while not queue.empty():
        item = queue.get_nowait()
        if item.get("type") == "token":
            sse_tokens.append(item.get("content", ""))
    assert "[[NEED_AGENT]]" not in "".join(sse_tokens)
    await svc.close()


@pytest.mark.asyncio
async def test_stt_production_no_simulated():
    """Giả lập demo_mode=False mà không có upstream STT thì bắt buộc raise STTError,
    tuyệt đối không trả về câu mô phỏng 'Tôi muốn kiểm tra bưu phẩm VNPost'."""
    from app.tts.stt import SpeechTranscriber, STTError

    prod_settings = Settings(
        demo_mode=False,
        api_keys_json='{"key1234567890123456": "vnpost"}',
        llm_api_key="real-api-key-12345",
        llm_model="gpt-4o",
        allow_hash=True,
        checkpointer_enabled=False,
        postgres_url="",
    )
    assert prod_settings.is_production is True
    transcriber = SpeechTranscriber(prod_settings)
    with pytest.raises(STTError) as exc_info:
        await transcriber.transcribe(b"fake_audio_bytes_content_for_test")
    assert "Hệ thống STT trực tuyến hiện không khả dụng" in str(exc_info.value)


def test_spoken_text_phone_and_code():
    """Kiểm tra spoken_text đọc tách từng chữ số cho SĐT và mã vận đơn UPU."""
    from app.tts.service import spoken_text

    text_phone = "Số điện thoại người nhận: 0912.345.678"
    spoken_phone = spoken_text(text_phone)
    assert "0 9 1 2 3 4 5 6 7 8" in spoken_phone

    text_code = "Mã bưu phẩm của quý khách là EB123456789VN"
    spoken_code = spoken_text(text_code)
    # Format mới: phiên âm từng ký tự với dấu phẩy để TTS đọc rõ hơn
    assert "ê, bê" in spoken_code            # chữ E và B đọc từng ký tự
    assert "một, hai, ba" in spoken_code     # chữ số đọc bằng tên tiếng Việt
    assert "vê, en" in spoken_code           # ký tự kết VN


def test_computed_not_from_code_pattern():
    """Câu trả lời có mã EB123456789VN nhưng computed_agents và computed rỗng
    thì validate_answer phải trả về status no_evidence thay vì tự động chuyển thành computed."""
    from app.agents.orchestrator import validate_answer

    # Tin nhắn người dùng không chứa tín hiệu hành động hay bưu điện
    cleaned, selected, status, warnings = validate_answer(
        "Bưu phẩm của bạn mang mã EB123456789VN đã được tiếp nhận.",
        sources={},
        grounded=True,
        message="Xin cho biết thông tin",
        computed=False,
    )
    assert status == "no_evidence"


@pytest.mark.asyncio
async def test_voice_readback_full_turn_calls_track_item(clean_settings):
    """Test 5 hoàn chỉnh: Trợ lý đọc lại mã ở lượt trước, khách đáp 'đúng rồi' (voice_input=True) ở lượt sau:
    - _open_flow bật True (bỏ qua Fast RAG, định tuyến thẳng Deep Agent).
    - Supervisor nhận diện được xác nhận và gọi track_item ngay lập tức.
    - Không đọc lại lần thứ hai."""
    svc = ChatService(clean_settings)
    session_uuid = uuid.uuid4()
    sid = str(session_uuid)

    # Lượt 1: Giả lập trợ lý vừa đọc lại mã vận đơn và hỏi khách xác nhận
    assistant_readback = "Mipo xin đọc lại mã vận đơn của anh/chị là EB123456789VN, có phải không ạ?"
    svc.store.save_turn("default", sid, "Tôi muốn tra cứu EB123456789VN", assistant_readback, 15)

    # Kiểm tra _open_flow nhận diện câu hỏi đọc lại mã
    assert svc._open_flow("default", sid) is True

    # Mock harness.invoke để tránh gọi LLM thật (kiểm tra định tuyến và hành vi, không phải LLM output)
    _harness_called = []

    async def mock_harness_invoke(message, history, grounded, image=None, **kwargs):
        _harness_called.append({"message": message, "voice_input": kwargs.get("voice_input")})
        return "Mipo đã tra cứu mã vận đơn EB123456789VN cho anh/chị. Bưu phẩm đang được vận chuyển."

    svc.harness.invoke = mock_harness_invoke

    # Lượt 2: Khách hàng đáp giọng nói 'đúng rồi'
    req = ChatRequest(
        message="đúng rồi",
        session_id=session_uuid,
        voice_input=True,
    )
    resp = await svc.chat("default", req)

    # Định tuyến phải là deep do _open_flow kích hoạt
    assert resp.route == "deep"

    # Kiểm tra harness được gọi với voice_input=True
    assert len(_harness_called) == 1
    assert _harness_called[0]["voice_input"] is True

    # Kiểm tra response chứa mã và không lặp lại câu hỏi đọc lại
    assert "EB123456789VN" in resp.answer
    assert "có phải không ạ" not in resp.answer
    assert "đúng không ạ" not in resp.answer
    await svc.close()


def test_question_not_confirmation():
    """B13: Các câu hỏi như 'tạo đơn được chưa?', 'gửi được hông', 'khi nào gửi', 'ok?' bị _hitl_gate chặn."""
    sid = "sess-q-test"
    tok1 = current_run.set(make_ctx(session_id=sid, user_message="Tạo đơn"))
    try:
        d = json.loads(
            create_draft_booking(
                sender_name="Người Gửi",
                sender_phone="0912345678",
                sender_address="Hà Nội",
                receiver_name="Người Nhận",
                receiver_phone="0987654321",
                receiver_address="Đà Nẵng",
                weight_grams=1000,
            )
        )
        draft_id = d["draft_id"]
    finally:
        current_run.reset(tok1)

    question_queries = [
        "tạo đơn được chưa?",
        "gửi được hông",
        "khi nào gửi",
        "ok?",
        "ok bao nhiêu tiền vậy",
        "được không?",
    ]
    for q in question_queries:
        tok = current_run.set(make_ctx(session_id=sid, user_message=q))
        try:
            res = json.loads(confirm_booking(draft_id))
            assert res.get("status") in {"hitl_required", "hitl_rejected_or_modifying"}, f"Truy vấn '{q}' không được phép duyệt đơn, kết quả: {res}"
        finally:
            current_run.reset(tok)

    # Tin nhắn xác nhận hợp lệ vẫn duyệt thành công
    tok_ok = current_run.set(make_ctx(session_id=sid, user_message="xác nhận"))
    try:
        res_ok = json.loads(confirm_booking(draft_id))
        assert res_ok.get("status") == "confirmed"
    finally:
        current_run.reset(tok_ok)


def test_booking_invalid_input():
    """B02, B03: SĐT 9 số, khối lượng âm, kích thước thiếu chiều trả invalid_input."""
    # SĐT người gửi 9 số
    res1 = json.loads(
        create_draft_booking(
            sender_name="A",
            sender_phone="091234567",
            sender_address="Hà Nội",
            receiver_name="B",
            receiver_phone="0987654321",
            receiver_address="Đà Nẵng",
            weight_grams=500,
        )
    )
    assert res1.get("status") == "invalid_input"
    assert any("người gửi" in e for e in res1.get("errors", []))

    # Khối lượng âm (-3000g)
    res2 = json.loads(
        create_draft_booking(
            sender_name="A",
            sender_phone="0912345678",
            sender_address="Hà Nội",
            receiver_name="B",
            receiver_phone="0987654321",
            receiver_address="Đà Nẵng",
            weight_grams=-3000,
        )
    )
    assert res2.get("status") == "invalid_input"
    assert any("khối lượng" in e for e in res2.get("errors", []))

    # Kích thước thiếu chiều (dài > 0 nhưng rộng = 0, cao = 0)
    res3 = json.loads(
        create_draft_booking(
            sender_name="A",
            sender_phone="0912345678",
            sender_address="Hà Nội",
            receiver_name="B",
            receiver_phone="0987654321",
            receiver_address="Đà Nẵng",
            weight_grams=500,
            length_cm=30,
            width_cm=0,
            height_cm=0,
        )
    )
    assert res3.get("status") == "invalid_input"


def test_cancel_lockout():
    """E15: Sai SĐT 5 lần liên tiếp -> verification_locked; đơn khác không bị khóa."""
    _VERIFY_FAILS.clear()
    sid = "sess-lockout-1"
    tok = current_run.set(make_ctx(session_id=sid, user_message="Tạo đơn"))
    try:
        d1 = json.loads(
            create_draft_booking(
                sender_name="A",
                sender_phone="0912345678",
                sender_address="Hà Nội",
                receiver_name="B",
                receiver_phone="0987654321",
                receiver_address="Đà Nẵng",
                weight_grams=500,
            )
        )
        draft1 = d1["draft_id"]

        d2 = json.loads(
            create_draft_booking(
                sender_name="C",
                sender_phone="0933333333",
                sender_address="Hải Phòng",
                receiver_name="D",
                receiver_phone="0944444444",
                receiver_address="Huế",
                weight_grams=500,
            )
        )
        draft2 = d2["draft_id"]
    finally:
        current_run.reset(tok)

    # Gọi ngoài phiên (session khác) để kích hoạt needs_verification
    other_sid = "sess-lockout-attacker"
    # Thử sai 5 lần với draft1
    for _ in range(5):
        r = json.loads(cancel_booking(draft1, session_id=other_sid, verification_phone="0000"))
        assert r.get("status") == "verification_failed"

    # Lần 6: Kể cả nhập đúng số cuối (5678), hệ thống vẫn khóa verification_locked
    r6 = json.loads(cancel_booking(draft1, session_id=other_sid, verification_phone="5678"))
    assert r6.get("status") == "verification_locked"
    assert "quá nhiều lần" in r6.get("message", "")

    # Đơn khác (draft2) không bị khóa
    r_draft2 = json.loads(cancel_booking(draft2, session_id=other_sid, verification_phone="3333"))
    assert r_draft2.get("status") == "cancelled"


def test_cancel_no_sender_phone_fail_closed():
    """E15: Đơn không có SĐT khi cần xác thực -> fail-closed trả verification_unavailable."""
    sid = "sess-fail-closed"
    tok = current_run.set(make_ctx(session_id=sid, user_message="Tạo đơn"))
    try:
        d = json.loads(
            create_draft_booking(
                sender_name="A",
                sender_phone="0912345678",
                sender_address="Hà Nội",
                receiver_name="B",
                receiver_phone="0987654321",
                receiver_address="Đà Nẵng",
                weight_grams=500,
            )
        )
        draft_id = d["draft_id"]
    finally:
        current_run.reset(tok)

    # Giả lập xóa SĐT người gửi
    rec = get_draft_booking(draft_id)
    rec["sender"]["phone"] = ""
    rec["sender_phone"] = ""

    # Gọi ngoài phiên
    res = json.loads(cancel_booking(draft_id, session_id="other-sess", verification_phone="5678"))
    assert res.get("status") == "verification_unavailable"
    assert "chưa có SĐT người gửi" in res.get("message", "")


def test_signals_unaccented():
    """A06: Câu gõ hoàn toàn không dấu được nhận là thao tác bưu chính; có dấu 'bảo mật' không bị nhận nhầm."""
    from app.agents.signals import analyze

    s1 = analyze("toi muon gui hang tu ha noi di da nang")
    assert s1.postal_ops is True

    s2 = analyze("tim buu cuc gan toi")
    assert s2.postal_ops is True

    s3 = analyze("toi muon khieu nai buu pham")
    assert s3.postal_ops is True

    s4 = analyze("Chính sách bảo mật của VNPost")
    assert s4.postal_ops is False


def test_spoken_text_draft_codes():
    """Voice: Đọc mã đơn hàng/nháp BK-DRAFT-20261023-EDD0A3A1 phiên âm từng ký tự (bê, ca, hai, không, hai, sáu...)."""
    from app.tts.service import spoken_text

    spoken1 = spoken_text("Mã nháp: BK-DRAFT-20261023-EDD0A3A1")
    # Format mới: "bê, ca, hai, không, hai, sáu, một, không, hai, ba"
    assert "bê, ca" in spoken1               # tiền tố BK đọc từng chữ cái
    assert "hai, không, hai, sáu" in spoken1 # chữ số đọc bằng tên tiếng Việt
    assert "bách khoa" not in spoken1.lower()
    assert "triệu" not in spoken1.lower()

    spoken2 = spoken_text("Phiếu khiếu nại KN-DRAFT-20261023-1A2B3C4D")
    # KN -> ca, en (format mới: phiên âm từng chữ cái + tên số tiếng Việt)
    assert "ca, en" in spoken2
    assert "hai, không, hai, sáu" in spoken2


