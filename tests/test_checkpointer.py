import os
import tempfile
import uuid

from app.api.schemas import ChatRequest
from app.core.checkpointer import PersistentSqliteCheckpointer
from app.service import ChatService


async def test_persistent_sqlite_checkpointer_unit():
    tmp_path = os.path.join(tempfile.gettempdir(), f"test_ckpt_{uuid.uuid4().hex}.sqlite3")
    checkpointer = PersistentSqliteCheckpointer(tmp_path)
    try:
        t1 = await checkpointer.aget_tuple({"configurable": {"thread_id": "thread-1"}})
        assert t1 is None

        # Verify put and get
        checkpoint = {
            "v": 1,
            "id": "cp1",
            "ts": "2026-10-15T12:00:00Z",
            "channel_values": {"messages": [{"role": "user", "content": "hello"}]},
            "channel_versions": {"messages": 1},
            "versions_seen": {},
        }
        config = {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}
        await checkpointer.aput(config, checkpoint, {}, {})

        t2 = await checkpointer.aget_tuple({"configurable": {"thread_id": "thread-1"}})
        assert t2 is not None
        assert t2.checkpoint["channel_values"]["messages"][0]["content"] == "hello"

        # Check another thread is isolated
        t3 = await checkpointer.aget_tuple({"configurable": {"thread_id": "thread-2"}})
        assert t3 is None
    finally:
        await checkpointer.aclose()
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


async def test_harness_with_checkpointer_multi_turn_state(settings):
    svc = ChatService(settings)
    svc.knowledge.for_tenant("tenant-a").ingest("rules.txt", "Thời hạn hoàn cước bưu gửi là 7 ngày kể từ ngày nhận khiếu nại.".encode())
    session_id = uuid.uuid4()
    try:
        res1 = await svc.chat("tenant-a", ChatRequest(session_id=session_id, message="Hoàn cước có thời hạn bao lâu?", mode="deep"))
        assert "7 ngày" in res1.answer

        # Conversation history is supplied by Store across turns, while each
        # checkpoint is isolated to one request for audit/resume.
        res2 = await svc.chat("tenant-a", ChatRequest(session_id=session_id, message="Cho biết thêm chi tiết", mode="deep"))
        assert res2.answer


        # Check that checkpointer saved the thread
        tid = f"tenant-a:{session_id}:{res2.request_id}"
        state = await svc.harness.graph.aget_state({"configurable": {"thread_id": tid}})
        assert state is not None and len(state.values.get("messages", [])) >= 2
    finally:
        await svc.close()


async def test_memory_checkpointer_storage_behavior():
    from langgraph.checkpoint.memory import MemorySaver
    saver = MemorySaver()
    config1 = {"configurable": {"thread_id": "req-1", "checkpoint_ns": ""}}
    config2 = {"configurable": {"thread_id": "req-2", "checkpoint_ns": ""}}
    cp1 = {"v": 1, "id": "1", "ts": "2026-10-15", "channel_values": {}, "channel_versions": {}, "versions_seen": {}}
    cp2 = {"v": 1, "id": "2", "ts": "2026-10-15", "channel_values": {}, "channel_versions": {}, "versions_seen": {}}
    await saver.aput(config1, cp1, {}, {})
    await saver.aput(config2, cp2, {}, {})
    assert await saver.aget_tuple(config1) is not None
    assert await saver.aget_tuple(config2) is not None
