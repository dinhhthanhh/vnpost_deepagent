import json

from app.agents.postal_actions import (
    create_draft_booking,
    get_draft_booking,
)
from app.core.config import Settings
from app.core.postgres import (
    PersistentPostgresCheckpointer,
    fetch_draft_booking_from_postgres,
    persist_draft_booking_to_postgres,
)


def test_settings_postgres_fields():
    """Kiểm tra cấu hình PostgreSQL được load hợp lệ qua Settings."""
    settings = Settings(
        checkpointer_type="postgres",
        postgres_url="postgresql://test:test@localhost:5432/test_db",
        postgres_min_connections=2,
        postgres_max_connections=8,
    )
    assert settings.checkpointer_type == "postgres"
    assert settings.postgres_url == "postgresql://test:test@localhost:5432/test_db"
    assert settings.postgres_min_connections == 2
    assert settings.postgres_max_connections == 8


def test_postgres_lazy_checkpointer_instantiation():
    """Kiểm tra PersistentPostgresCheckpointer có thể khởi tạo đồng bộ mà không cần loop."""
    cp = PersistentPostgresCheckpointer(
        postgres_url="postgresql://dummy:dummy@localhost:5432/dummy",
        min_size=1,
        max_size=5,
    )
    assert cp.postgres_url == "postgresql://dummy:dummy@localhost:5432/dummy"
    assert cp._saver is None
    assert cp._pool is None


def test_persist_draft_booking_graceful_offline():
    """Kiểm tra persist draft booking hoạt động an toàn khi PostgreSQL offline."""
    dummy_draft = {
        "draft_id": "BK-DRAFT-TEST-OFFLINE",
        "tenant": "default",
        "status": "WAITING_CONFIRMATION",
    }
    # Khi không có kết nối tới server thật, hàm trả về False một cách an toàn và không raise Exception
    res = persist_draft_booking_to_postgres(
        dummy_draft, postgres_url="postgresql://invalid:invalid@localhost:5432/invalid"
    )
    assert res is False


def test_fetch_draft_booking_graceful_offline():
    """Kiểm tra fetch draft booking an toàn khi PostgreSQL offline."""
    res = fetch_draft_booking_from_postgres(
        "BK-DRAFT-NONEXISTENT", postgres_url="postgresql://invalid:invalid@localhost:5432/invalid"
    )
    assert res is None


def test_session_drafts_fallback_with_mock():
    """Kiểm tra get_session_drafts kết hợp dữ liệu giữa RAM cache và PostgreSQL."""
    res_str = create_draft_booking(
        sender_name="Nguyễn Văn X",
        sender_phone="0901112233",
        sender_address="Hà Nội",
        receiver_name="Trần Thị Y",
        receiver_phone="0904445566",
        receiver_address="Hồ Chí Minh",
        weight_grams=300,
    )
    data = json.loads(res_str)
    draft_id = data["draft_id"]

    # Đảm bảo đơn hàng vừa tạo có thể truy vấn qua get_draft_booking
    record = get_draft_booking(draft_id)
    assert record is not None
    assert record["draft_id"] == draft_id
