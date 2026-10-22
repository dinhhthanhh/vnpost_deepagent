import io
import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.agents.postal_actions import (
    _DRAFT_BOOKINGS,
    _DRAFT_COMPLAINTS,
    create_draft_booking,
    create_draft_complaint,
)
from app.api.main import create_app
from app.core.postgres import (
    fetch_draft_booking_from_postgres,
    fetch_draft_complaint_from_postgres,
)

KEY_ALICE = "key-alice-1234567890"
KEY_BOB = "key-bob-1234567890"


def _make_app(settings, **kwargs):
    updates = {
        "api_keys_json": json.dumps({KEY_ALICE: "alice", KEY_BOB: "bob"}),
        "allow_anonymous_demo": False,
        "allowed_s3_buckets": "vnpost-official-bucket",
        "max_upload_bytes": 1024 * 1024,  # 1MB
    }
    updates.update(kwargs)
    return create_app(settings.model_copy(update=updates))


def test_cross_tenant_confirm_booking_forbidden(settings):
    with TestClient(_make_app(settings)) as client:
        headers_alice = {"X-API-Key": KEY_ALICE}
        headers_bob = {"X-API-Key": KEY_BOB}

        # Alice creates a booking draft
        res_str = create_draft_booking(
            sender_name="Alice Nguyen",
            sender_phone="0912345678",
            sender_address="125 Hai Ba Trung, Q1, HCM",
            receiver_name="Bob Tran",
            receiver_phone="0987654321",
            receiver_address="45 Dinh Tien Hoang, Hoan Kiem, Ha Noi",
            weight_grams=500,
            length_cm=20,
            width_cm=15,
            height_cm=10,
            service_type="EMS",
        )
        draft_data = json.loads(res_str)
        draft_id = draft_data["draft_id"]
        _DRAFT_BOOKINGS[draft_id]["tenant"] = "alice"

        # Bob attempts to confirm Alice's booking draft -> 403 Forbidden
        resp_bob = client.post(
            "/api/actions/confirm",
            headers=headers_bob,
            json={"action_type": "booking", "draft_id": draft_id},
        )
        assert resp_bob.status_code == 403
        assert "tenant khác" in resp_bob.text or "không có quyền" in resp_bob.text

        # Bob attempts to cancel Alice's booking draft -> 403 Forbidden
        resp_bob_cancel = client.post(
            "/api/actions/cancel",
            headers=headers_bob,
            json={
                "action_type": "booking",
                "target_id": draft_id,
                "reason": "Tự ý hủy của người khác",
            },
        )
        assert resp_bob_cancel.status_code == 403
        assert "tenant khác" in resp_bob_cancel.text or "không có quyền" in resp_bob_cancel.text

        # Alice confirms her own booking draft -> 200 OK
        resp_alice = client.post(
            "/api/actions/confirm",
            headers=headers_alice,
            json={"action_type": "booking", "draft_id": draft_id},
        )
        assert resp_alice.status_code == 200
        assert resp_alice.json()["status"] == "confirmed"
        item_code = resp_alice.json()["item_code"]

        # Bob attempts to cancel Alice's confirmed shipment via item_code -> 403 Forbidden
        resp_bob_cancel_order = client.post(
            "/api/actions/cancel",
            headers=headers_bob,
            json={
                "action_type": "booking",
                "target_id": item_code,
                "reason": "Phá hoại đơn đã phát hành",
            },
        )
        assert resp_bob_cancel_order.status_code == 403


def test_cross_tenant_complaint_forbidden(settings):
    with TestClient(_make_app(settings)) as client:
        headers_alice = {"X-API-Key": KEY_ALICE}
        headers_bob = {"X-API-Key": KEY_BOB}

        # Alice creates a complaint draft
        res_str = create_draft_complaint(
            item_code="EB123456789VN",
            customer_name="Alice Nguyen",
            customer_phone="0912345678",
            complaint_type="CHAM_CHI_TRA",
            description="Bưu gửi bị chậm 5 ngày chưa nhận được",
        )
        draft_data = json.loads(res_str)
        draft_ticket_id = draft_data["draft_ticket_id"]
        _DRAFT_COMPLAINTS[draft_ticket_id]["tenant"] = "alice"

        # Bob attempts to confirm Alice's complaint draft -> 403 Forbidden
        resp_bob = client.post(
            "/api/actions/confirm",
            headers=headers_bob,
            json={"action_type": "complaint", "draft_id": draft_ticket_id},
        )
        assert resp_bob.status_code == 403
        assert "tenant khác" in resp_bob.text or "không có quyền" in resp_bob.text

        # Bob attempts to cancel/withdraw Alice's complaint draft -> 403 Forbidden
        resp_bob_cancel = client.post(
            "/api/actions/cancel",
            headers=headers_bob,
            json={
                "action_type": "complaint",
                "target_id": draft_ticket_id,
                "reason": "Rút trái phép",
            },
        )
        assert resp_bob_cancel.status_code == 403

        # Alice confirms her own complaint -> 200 OK
        resp_alice = client.post(
            "/api/actions/confirm",
            headers=headers_alice,
            json={"action_type": "complaint", "draft_id": draft_ticket_id},
        )
        assert resp_alice.status_code == 200
        assert resp_alice.json()["status"] == "submitted"


def test_confirm_cancel_nonexistent_returns_404(settings):
    with TestClient(_make_app(settings)) as client:
        headers_alice = {"X-API-Key": KEY_ALICE}

        resp_confirm = client.post(
            "/api/actions/confirm",
            headers=headers_alice,
            json={"action_type": "booking", "draft_id": "BK-DRAFT-DOESNOTEXIST"},
        )
        assert resp_confirm.status_code == 404

        resp_cancel = client.post(
            "/api/actions/cancel",
            headers=headers_alice,
            json={"action_type": "booking", "target_id": "BK-DRAFT-DOESNOTEXIST"},
        )
        assert resp_cancel.status_code == 404


def test_postgres_draft_query_enforces_tenant():
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = None

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.execute.return_value = mock_cur

    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn

    with patch("app.core.postgres.get_sync_pool", return_value=mock_pool):
        # Query with tenant="tenant_alice"
        fetch_draft_booking_from_postgres("BK-DRAFT-123", tenant="tenant_alice")
        query_sql, query_params = mock_conn.execute.call_args[0]
        assert "AND tenant = %s" in query_sql
        assert query_params == ("BK-DRAFT-123", "tenant_alice")

        # Query complaint draft with tenant="tenant_alice"
        fetch_draft_complaint_from_postgres("KN-DRAFT-456", tenant="tenant_alice")
        c_query_sql, c_query_params = mock_conn.execute.call_args[0]
        assert "AND tenant = %s" in c_query_sql
        assert c_query_params == ("KN-DRAFT-456", "tenant_alice")


def test_s3_bucket_allowlist_enforcement(settings):
    with TestClient(_make_app(settings)) as client:
        # Bucket not in allowed_s3_buckets ("vnpost-official-bucket")
        resp = client.post(
            "/api/documents/s3",
            headers={"X-API-Key": KEY_ALICE},
            json={"bucket": "unauthorized-bucket", "key": "test.pdf"},
        )
        assert resp.status_code == 403
        assert "danh sách được phép" in resp.text


def test_s3_bucket_unconfigured_allowlist_returns_403(settings):
    with TestClient(_make_app(settings, allowed_s3_buckets="")) as client:
        resp = client.post(
            "/api/documents/s3",
            headers={"X-API-Key": KEY_ALICE},
            json={"bucket": "any-bucket", "key": "test.pdf"},
        )
        assert resp.status_code == 403
        assert "chưa được cấu hình" in resp.text


def test_s3_content_length_exceeds_max_upload_bytes(settings):
    with TestClient(_make_app(settings)) as client:
        mock_body = MagicMock()
        mock_s3 = MagicMock()
        # ContentLength = 5MB, while max_upload_bytes is 1MB
        mock_s3.get_object.return_value = {
            "ContentLength": 5 * 1024 * 1024,
            "Body": mock_body,
        }
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            resp = client.post(
                "/api/documents/s3",
                headers={"X-API-Key": KEY_ALICE},
                json={"bucket": "vnpost-official-bucket", "key": "large.pdf"},
            )
            assert resp.status_code == 413
            assert "vượt quá dung lượng tối đa" in resp.text
            # Body stream should not even be read
            mock_body.read.assert_not_called()


def test_s3_chunked_streaming_exceeds_max_upload_bytes(settings):
    with TestClient(_make_app(settings)) as client:
        # S3 object reports unknown or None ContentLength, but stream yields 2MB (exceeding 1MB limit)
        oversized_data = b"x" * (2 * 1024 * 1024)
        stream_body = io.BytesIO(oversized_data)

        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "ContentLength": None,
            "Body": stream_body,
        }
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            resp = client.post(
                "/api/documents/s3",
                headers={"X-API-Key": KEY_ALICE},
                json={"bucket": "vnpost-official-bucket", "key": "stream_large.txt"},
            )
            assert resp.status_code == 413
            assert "vượt quá dung lượng tối đa" in resp.text
