import json

from fastapi.testclient import TestClient

from app.agents.postal_actions import (
    _DRAFT_BOOKINGS,
    cancel_booking,
    create_draft_booking,
)
from app.api.main import create_app
from app.core.config import Settings
from app.mcp.server import create_authenticated_sse_app, current_mcp_tenant
from app.mcp.tools import register_postal_mcp_tools

KEY_ALICE = "mcp-key-alice-1234567890"
KEY_BOB = "mcp-key-bob-1234567890"


def _make_test_settings():
    return Settings(
        api_keys_json=json.dumps({KEY_ALICE: "alice", KEY_BOB: "bob"}),
        allow_anonymous_demo=False,
    )


def test_mcp_sse_transport_authentication():
    settings = _make_test_settings()
    app = create_authenticated_sse_app(settings=settings)
    client = TestClient(app, base_url="http://127.0.0.1:8001")

    # 1. Kết nối không có API key -> 401 Unauthorized
    resp_no_auth = client.get("/sse")
    assert resp_no_auth.status_code == 401
    assert "X-API-Key" in resp_no_auth.text

    # 2. Kết nối với API key không hợp lệ -> 403 Forbidden
    resp_bad_auth = client.get("/sse", headers={"X-API-Key": "invalid-key-1234567890"})
    assert resp_bad_auth.status_code == 403
    assert "không hợp lệ" in resp_bad_auth.text

    # 3. Kết nối với API key hợp lệ qua header (dùng stream vì SSE là kết nối mở liên tục)
    with client.stream("GET", "/sse", headers={"X-API-Key": KEY_ALICE}) as resp_good:
        assert resp_good.status_code == 200
        assert "text/event-stream" in resp_good.headers.get("content-type", "")

    # 4. Hỗ trợ query parameter (?api_key=...) cho EventSource trình duyệt
    with client.stream("GET", f"/sse?api_key={KEY_ALICE}") as resp_query:
        assert resp_query.status_code == 200
        assert "text/event-stream" in resp_query.headers.get("content-type", "")


def test_mcp_tool_cannot_spoof_tenant_and_uses_server_identity():
    from mcp.server.fastmcp import FastMCP

    test_mcp = FastMCP("test-isolation")
    register_postal_mcp_tools(test_mcp)

    # Kiểm tra metadata công cụ danh_sach_don_va_khieu_nai không có tham số tenant do client truyền
    tool_func = None
    for tool_name, tool_obj in test_mcp._tool_manager._tools.items():
        if "danh_sach" in tool_name:
            tool_func = tool_obj.fn
            break

    assert tool_func is not None
    import inspect

    sig = inspect.signature(tool_func)
    assert "tenant" not in sig.parameters, (
        "Client MCP không được phép chỉ định tham số tenant để chống giả mạo tenant!"
    )

    # Alice tạo đơn nháp
    res_a = json.loads(
        create_draft_booking(
            sender_name="Alice Nguyen",
            sender_phone="0911223344",
            sender_address="Hà Nội",
            receiver_name="Target",
            receiver_phone="0988776655",
            receiver_address="Đà Nẵng",
            weight_grams=500,
        )
    )
    draft_a = res_a["draft_id"]
    _DRAFT_BOOKINGS[draft_a]["tenant"] = "alice"

    # Bob tạo đơn nháp
    res_b = json.loads(
        create_draft_booking(
            sender_name="Bob Tran",
            sender_phone="0933445566",
            sender_address="TP HCM",
            receiver_name="Target",
            receiver_phone="0988776655",
            receiver_address="Đà Nẵng",
            weight_grams=500,
        )
    )
    draft_b = res_b["draft_id"]
    _DRAFT_BOOKINGS[draft_b]["tenant"] = "bob"

    # Khi server xác thực Bob qua current_mcp_tenant
    tok = current_mcp_tenant.set("bob")
    try:
        orders_bob = json.loads(tool_func())
        detail = orders_bob.get("detail", {})
        bob_draft_ids = [b["draft_id"] for b in detail.get("active_draft_bookings", [])]
        assert draft_b in bob_draft_ids
        assert draft_a not in bob_draft_ids, "Bob không được phép nhìn thấy đơn hàng của Alice!"
    finally:
        current_mcp_tenant.reset(tok)


def test_no_fake_upu_tracking_cancellation():
    """Mã vận đơn chuẩn UPU nhưng không có trong cơ sở dữ liệu phải trả về lỗi không tìm thấy, không được tạo trạng thái hủy giả."""
    fake_upu = "EB123456789VN"

    # 1. Gọi trực tiếp hàm nghiệp vụ
    res_str = cancel_booking(item_code_or_draft_id=fake_upu, reason="Hủy đơn lạ")
    res_data = json.loads(res_str)
    assert res_data["status"] == "error"
    assert "Không tìm thấy" in res_data["message"]
    assert "đã tiếp nhận yêu cầu hủy lấy hàng" not in res_data.get("message", "").lower()

    # 2. Gọi qua REST API -> Phải trả về 404 Not Found
    settings = Settings(checkpointer_enabled=False)
    with TestClient(create_app(settings)) as client:
        resp = client.post(
            "/api/actions/cancel",
            json={"action_type": "booking", "target_id": fake_upu, "reason": "Hủy đơn giả"},
        )
        assert resp.status_code == 404
        assert "Không tìm thấy" in resp.text


def test_rest_api_cancel_enforces_phone_verification_across_sessions():
    """REST API /api/actions/cancel bắt buộc kiểm tra số điện thoại người gửi nếu không nằm trong phiên gốc."""
    settings = Settings(
        api_keys_json=json.dumps({KEY_ALICE: "alice"}),
        allow_anonymous_demo=False,
    )
    with TestClient(create_app(settings)) as client:
        # Tạo đơn nháp gắn với session gốc 'session-alice-origin'
        res_a = json.loads(
            create_draft_booking(
                sender_name="Alice Nguyen",
                sender_phone="0912345678",
                sender_address="125 Hai Bà Trưng, Q1, HCM",
                receiver_name="Bob Tran",
                receiver_phone="0987654321",
                receiver_address="45 Đinh Tiên Hoàng, Hoàn Kiếm, Hà Nội",
                weight_grams=500,
            )
        )
        draft_id = res_a["draft_id"]
        _DRAFT_BOOKINGS[draft_id]["tenant"] = "alice"
        _DRAFT_BOOKINGS[draft_id]["session_id"] = "session-alice-origin"

        # 1. Gọi cancel qua REST không có session_id và không có verification_phone -> 400 BẢO VỆ CHÍNH CHỦ
        resp_unauth = client.post(
            "/api/actions/cancel",
            headers={"X-API-Key": KEY_ALICE},
            json={"action_type": "booking", "target_id": draft_id, "reason": "Tự ý hủy"},
        )
        assert resp_unauth.status_code == 400
        assert "BẢO VỆ CHÍNH CHỦ" in resp_unauth.text
        assert "...5678" in resp_unauth.text

        # 2. Gọi cancel với SĐT sai -> 400 XÁC THỰC THẤT BẠI
        resp_wrong = client.post(
            "/api/actions/cancel",
            headers={"X-API-Key": KEY_ALICE},
            json={
                "action_type": "booking",
                "target_id": draft_id,
                "reason": "Đoán mò SĐT",
                "verification_phone": "1234",
            },
        )
        assert resp_wrong.status_code == 400
        assert "XÁC THỰC THẤT BẠI" in resp_wrong.text

        # 3. Gọi cancel với đúng 4 số cuối SĐT người gửi -> 200 OK thành công
        resp_ok_phone = client.post(
            "/api/actions/cancel",
            headers={"X-API-Key": KEY_ALICE},
            json={
                "action_type": "booking",
                "target_id": draft_id,
                "reason": "Chính chủ hủy",
                "verification_phone": "5678",
            },
        )
        assert resp_ok_phone.status_code == 200
        assert resp_ok_phone.json()["status"] == "cancelled"
