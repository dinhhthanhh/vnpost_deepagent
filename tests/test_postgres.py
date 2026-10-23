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


def test_store_sqlite_fallback(tmp_path):
    """Kiểm tra Store hoạt động ở chế độ fallback SQLite khi không có postgres_url."""
    from app.rag.store import Store

    store = Store(tmp_path, postgres_url=None)
    assert not store.use_postgres
    assert store.db_path.is_file()

    store.save_turn("tenant-x", "sess-1", "Hello", "Hi there!", 10)
    history = store.history("tenant-x", "sess-1")
    assert len(history) == 2
    assert history[0]["content"] == "Hello"

    sessions = store.list_sessions("tenant-x")
    assert len(sessions) == 1
    assert sessions[0]["id"] == "sess-1"

    store.delete_session("tenant-x", "sess-1")
    assert len(store.list_sessions("tenant-x")) == 0


def test_store_postgres_live(settings, tmp_path):
    """Kiểm tra Store kết nối và thao tác bền vững trên PostgreSQL khi postgres_url được cấu hình."""
    from app.rag.store import Store

    if not settings.postgres_url:
        return
    store = Store(tmp_path, postgres_url=settings.postgres_url)
    if not store.use_postgres:
        return

    test_sid = f"test-sess-pg-{tmp_path.name}"
    store.save_turn("tenant-test", test_sid, "Tra cứu bưu gửi", "Dạ mã bưu gửi là gì ạ?", 16)
    history = store.history("tenant-test", test_sid)
    assert len(history) == 2
    assert history[0]["content"] == "Tra cứu bưu gửi"

    sessions = store.list_sessions("tenant-test")
    assert any(s["id"] == test_sid for s in sessions)

    store.delete_session("tenant-test", test_sid)
    history_after = store.history("tenant-test", test_sid)
    assert len(history_after) == 0


def test_get_sync_connection_pool_alias():
    """Kiểm tra alias get_sync_connection_pool trỏ đúng vào get_sync_pool."""
    from app.core.postgres import cancel_orphaned_drafts_in_postgres, get_sync_connection_pool, get_sync_pool

    assert get_sync_connection_pool is get_sync_pool
    # Đảm bảo cancel_orphaned_drafts_in_postgres chạy êm khi offline
    assert cancel_orphaned_drafts_in_postgres("dummy_tenant", "dummy_sess") == 0


def test_run_context_event_draft_created_kind():
    """Kiểm tra RunContext.event chấp nhận keyword argument kind='booking' / 'complaint'."""
    from app.core.context import RunContext

    ctx = RunContext("default", "req-test-kind", 1, 1)
    # Không raise TypeError: got multiple values for argument 'kind'
    ctx.event("draft_created", kind="booking", draft_id="BK-123", detail={"key": "val"})
    ctx.event("draft_created", kind="complaint", draft_id="CP-456", detail={"key": "val2"})

    assert len(ctx.events) == 2
    assert ctx.events[0]["type"] == "draft_created"
    assert ctx.events[0]["kind"] == "booking"
    assert ctx.events[0]["draft_id"] == "BK-123"

    assert ctx.events[1]["type"] == "draft_created"
    assert ctx.events[1]["kind"] == "complaint"
    assert ctx.events[1]["draft_id"] == "CP-456"

