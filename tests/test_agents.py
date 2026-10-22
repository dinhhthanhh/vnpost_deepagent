import asyncio
import json
import uuid

import pytest
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain_core.messages import AIMessage, ToolMessage

from app.agents import validate_answer
from app.agents.calculator import safe_calculate
from app.api.schemas import ChatRequest, TaskSpec
from app.core.context import RunContext, current_run
from app.core.demo import DemoChatModel, message_text
from app.service import ChatService


async def test_real_harness_parallel_rag_and_citations(settings):
    svc = ChatService(settings)
    svc.knowledge.for_tenant("a").ingest("rules.txt", "Hoàn cước có thời hạn 7 ngày.".encode())
    result = await svc.chat("a", ChatRequest(message="Hoàn cước có thời hạn bao lâu?", mode="deep"))
    assert result.grounding_status == "cited" and result.sources
    assert "7 ngày" in result.answer and "[S1]" in result.answer
    assert any(e["type"] == "rag_prefetch_end" and e.get("status") == "ok" for e in result.events)
    assert sum(e["type"] == "retrieval" for e in result.events) == 1
    assert any(e["type"] == "retrieval_cache_hit" for e in result.events)
    starts = [e for e in result.events if e["type"] == "task_start"]
    ends = [e for e in result.events if e["type"] == "task_end"]
    assert len(starts) == 2 and max(e["elapsed_ms"] for e in starts) <= min(
        e["elapsed_ms"] for e in ends
    )
    assert svc.store.reply("a", result.request_id)["sources"]
    await svc.close()


async def test_native_deepagents_task_tool_also_runs_parallel(settings):
    class NativeTaskModel(DemoChatModel):
        def _response(self, messages):
            tools = [m for m in messages if isinstance(m, ToolMessage)]
            if tools:
                return AIMessage(content="\n".join(message_text(m) for m in tools))
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "subagent_type": "rag-agent",
                            "description": "Thời hạn hoàn cước?",
                        },
                        "id": "r",
                    },
                    {
                        "name": "task",
                        "args": {
                            "subagent_type": "analyst-agent",
                            "description": "Phân tích điều kiện",
                        },
                        "id": "w",
                    },
                ],
            )

    svc = ChatService(settings)
    svc.knowledge.for_tenant("a").ingest("x.txt", "Thời hạn hoàn cước là 7 ngày.".encode())
    graph = create_deep_agent(
        model=NativeTaskModel(),
        backend=StateBackend(),
        middleware=[FilesystemMiddleware(backend=StateBackend(), tools=["read_file"])],
        subagents=[
            {"name": name, "description": name, "runnable": agent}
            for name, agent in svc.harness.subagents.items()
        ],
    )
    scope = RunContext("a", "native", 3, 8)
    token = current_run.set(scope)
    try:
        result = await graph.ainvoke({"messages": [{"role": "user", "content": "Tra cứu"}]})
        assert "7 ngày" in message_text(result["messages"][-1])
        starts = [e for e in scope.events if e["type"] == "task_start"]
        ends = [e for e in scope.events if e["type"] == "task_end"]
        assert len(starts) == 2 and max(e["elapsed_ms"] for e in starts) <= min(
            e["elapsed_ms"] for e in ends
        )
    finally:
        current_run.reset(token)
        await svc.close()


async def test_task_budget_and_semaphore(settings):
    settings = settings.model_copy(update={"max_delegated_tasks": 1, "max_parallel_subagents": 1})
    svc = ChatService(settings)
    result = await svc.chat("a", ChatRequest(message="Tìm thời hạn hoàn cước", mode="deep"))
    assert sum(e["type"] == "task_start" for e in result.events) == 1
    assert any(e["type"] == "task_rejected" for e in result.events)
    await svc.close()


async def test_single_subagent_failure_preserves_successful_results(settings):
    svc = ChatService(settings)
    svc.knowledge.for_tenant("a").ingest("x.txt", "Hoàn cước trong 7 ngày.".encode())

    class Failing:
        async def ainvoke(self, *args, **kwargs):
            raise RuntimeError("secret-provider-data")

    svc.harness.subagents["analyst-agent"] = svc.harness._tracked_agent("analyst-agent", Failing())
    result = await svc.chat("a", ChatRequest(message="Hoàn cước bao lâu?", mode="deep"))
    assert "7 ngày" in result.answer and "secret-provider-data" not in str(result)
    assert any(e.get("status") == "error" for e in result.events)
    await svc.close()


async def test_parallel_requests_do_not_mix_tenant_sources(settings):
    svc = ChatService(settings)
    svc.knowledge.for_tenant("a").ingest("a.txt", "Thời hạn hoàn cước là 7 ngày.".encode())
    svc.knowledge.for_tenant("b").ingest("b.txt", "Thời hạn hoàn cước là 9 ngày.".encode())
    a, b = await asyncio.gather(
        svc.chat("a", ChatRequest(message="Hoàn cước bao lâu?", mode="deep")),
        svc.chat("b", ChatRequest(message="Hoàn cước bao lâu?", mode="deep")),
    )
    assert {s.filename for s in a.sources} == {"a.txt"}
    assert {s.filename for s in b.sources} == {"b.txt"}
    assert "9 ngày" not in a.answer and "7 ngày" not in b.answer
    await svc.close()


async def test_session_serialization_preserves_both_turns(settings):
    svc = ChatService(settings)
    session_id = uuid.uuid4()
    await asyncio.gather(
        svc.chat(
            "a", ChatRequest(session_id=session_id, message="12 + 8", grounded=False, mode="deep")
        ),
        svc.chat(
            "a", ChatRequest(session_id=session_id, message="20 - 5", grounded=False, mode="deep")
        ),
    )
    history = svc.store.history("a", str(session_id))
    assert len(history) == 4 and "20" in history[1]["content"] and "15" in history[3]["content"]
    assert not svc.session_locks
    await svc.close()


async def test_timeout_cancels_run_and_does_not_commit_history(settings, monkeypatch):
    svc = ChatService(settings.model_copy(update={"request_timeout_seconds": 0.03}))

    async def slow(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(svc.harness, "invoke", slow)
    session = uuid.uuid4()
    with pytest.raises(TimeoutError):
        await svc.chat("a", ChatRequest(message="query", session_id=session, mode="deep"))
    assert not svc.store.history("a", str(session)) and not svc.session_locks
    await svc.close()


async def test_no_evidence_and_tts_failure_do_not_break_text(settings):
    svc = ChatService(settings)
    result = await svc.chat("a", ChatRequest(message="thời hạn hoàn cước", voice=True))
    assert result.grounding_status == "no_evidence" and not result.audio_url and result.warnings
    assert result.answer
    await svc.close()


def test_citation_gate_and_greetings():
    assert validate_answer("Nguồn [S99]", {}, True, "query")[2] == "invalid_citation"
    assert validate_answer("Tự đoán", {}, True, "query")[2] == "no_evidence"
    assert validate_answer("Xin chào", {}, True, "xin chào")[0] == "Xin chào"


@pytest.mark.parametrize(
    "expression,expected", [("(120-100)/100*100", 20), ("-5+2", -3), ("2**3", 8), ("9%4", 1)]
)
def test_calculator_correct(expression, expected):
    assert safe_calculate(expression) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('whoami')",
        "x+1",
        "2**1000000",
        "1/0",
        "True+1",
        "(1).__class__",
        "1e309",
        "(-1)**0.5",
    ],
)
def test_calculator_rejects_code_and_unbounded_work(expression):
    with pytest.raises((ValueError, SyntaxError)):
        safe_calculate(expression)


def test_task_spec_is_constrained():
    with pytest.raises(ValueError):
        TaskSpec(id="../bad", agent="shell", description="x")


async def test_valid_json_array_from_subagent_is_not_treated_as_failure(settings):
    svc = ChatService(settings)

    class ArrayOutput:
        async def ainvoke(self, *args, **kwargs):
            return {"messages": [AIMessage(content='["item one", "item two"]')]}

    svc.harness.subagents["writer-agent"] = svc.harness._tracked_agent(
        "writer-agent", ArrayOutput()
    )
    scope = RunContext("a", "json-output", 2, 8)
    token = current_run.set(scope)
    try:
        raw = await svc.harness.parallel_tasks.ainvoke(
            {
                "tasks": [
                    {"id": "draft", "agent": "writer-agent", "description": "Return a JSON array"}
                ]
            }
        )
        result = json.loads(raw)["results"][0]
        assert result["status"] == "ok" and json.loads(result["result"]) == ["item one", "item two"]
    finally:
        current_run.reset(token)
        await svc.close()


def test_date_calculator_reasoning():
    import datetime

    from app.agents.calculator import safe_date_calculate

    fixed_now = datetime.datetime(
        2026, 10, 15, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=7))
    )

    res1 = safe_date_calculate("12/3 năm sau là ngày thứ mấy", now=fixed_now)
    assert res1["weekday"] == "Thứ Sáu"
    assert res1["target_date"] == "12/03/2027"

    res2 = safe_date_calculate("thứ 4 tuần sau nữa nữa là ngày thứ mấy", now=fixed_now)
    assert res2["target_weekday"] == "Thứ Tư"
    assert res2["target_date"] == "04/11/2026"
    assert res2["weeks_ahead"] == 3

    res3 = safe_date_calculate("30 ngày nữa là ngày mấy", now=fixed_now)
    assert res3["target_date"] == "14/11/2026"
    assert res3["weekday"] == "Thứ Bảy"

    res4 = safe_date_calculate(
        "21 tháng sau là ngày thứ mấy",
        now=datetime.datetime(
            2026, 10, 21, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=7))
        ),
    )
    assert res4["target_date"] == "21/11/2026"
    assert res4["weekday"] == "Thứ Bảy"

    from app.agents.signals import analyze

    assert analyze("21 tháng sau là ngày thứ mấy").temporal_calc is True


async def test_tracking_and_post_office_subagents(settings):
    svc = ChatService(settings)
    scope = RunContext("a", "postal-subagents-test", 4, 8)
    token = current_run.set(scope)
    try:
        raw = await svc.harness.parallel_tasks.ainvoke(
            {
                "tasks": [
                    {
                        "id": "trk-1",
                        "agent": "tracking-agent",
                        "description": "Kiểm tra mã vận đơn EB123456789VN",
                    },
                    {
                        "id": "po-1",
                        "agent": "post-office-agent",
                        "description": "Tìm bưu cục gần Cầu Giấy Hà Nội",
                    },
                ]
            }
        )
        data = json.loads(raw)
        results = data["results"]
        assert len(results) == 2
        assert results[0]["id"] == "trk-1" and results[0]["status"] == "ok"
        assert "EB123456789VN" in results[0]["result"]
        assert results[1]["id"] == "po-1" and results[1]["status"] == "ok"
        assert "Cầu Giấy" in results[1]["result"]
    finally:
        current_run.reset(token)
        await svc.close()


async def test_chat_postal_tracking_and_office_end_to_end(settings):
    svc = ChatService(settings)
    try:
        res1 = await svc.chat(
            "a", ChatRequest(message="Kiểm tra bưu gửi EB123456789VN hiện đang ở đâu?", mode="deep")
        )
        assert res1.grounding_status in ("computed", "verified")
        assert (
            "EB123456789VN" in res1.answer or "Đang phát" in res1.answer or "Hà Nội" in res1.answer
        )

        res2 = await svc.chat(
            "a", ChatRequest(message="Tìm bưu cục giao dịch gần Hoàn Kiếm Hà Nội", mode="deep")
        )
        assert res2.grounding_status in ("computed", "verified")
        assert (
            "Hoàn Kiếm" in res2.answer
            or "Đinh Tiên Hoàng" in res2.answer
            or "Bưu điện" in res2.answer
        )
    finally:
        await svc.close()


def test_citation_claim_mismatch_warning():
    from app.agents import validate_answer

    # S1 excerpt is about tariff fees
    sources = {
        "S1": {"excerpt": "Cước chuyển phát nhanh EMS là 50000 đồng.", "filename": "cuoc.txt"}
    }
    # Answer cites [S1] for an unsupported claim without keyword overlap
    answer = "Quy định nghỉ phép hàng năm của nhân viên là 12 ngày [S1]."
    cleaned, selected, status, warnings = validate_answer(
        answer, sources, True, "Thời gian giao hàng là bao lâu?"
    )
    # The unsupported citation should be removed from valid selections
    assert len(selected) == 0
    assert status == "no_evidence"
    assert any("không có đủ từ khóa hỗ trợ" in w for w in warnings)


def test_create_model_thinking_configuration():
    from app.agents.orchestrator import create_model
    from app.core.config import Settings

    # 1. When thinking is True and custom proxy base_url
    s1 = Settings(
        llm_api_key="sk-test", llm_thinking=True, llm_base_url="https://api.deepseek.com/v1"
    )
    model1 = create_model(s1, "supervisor")
    assert model1.extra_body is not None
    assert model1.extra_body.get("thinking") is True

    # 2. When thinking is True but googleapis.com endpoint
    s2 = Settings(
        llm_api_key="sk-test",
        llm_thinking=True,
        llm_base_url="https://generativelanguage.googleapis.com/v1",
    )
    model2 = create_model(s2, "supervisor")
    assert model2.extra_body is None


async def test_chat_nearest_post_office_with_geolocation(settings):
    from app.api.schemas import LocationInfo

    svc = ChatService(settings)
    try:
        req = ChatRequest(
            message="Tìm bưu điện gần tôi nhất",
            location=LocationInfo(latitude=21.0285, longitude=105.8542),
            mode="deep",
        )
        res = await svc.chat("a", req)
        assert res.grounding_status in ("computed", "verified")
        assert (
            "Hoàn Kiếm" in res.answer
            or "Đinh Tiên Hoàng" in res.answer
            or "Google Maps" in res.answer
        )
    finally:
        await svc.close()


def test_safe_stream_buffer_prevents_no_evidence_leak():
    from app.core.prompts import NO_EVIDENCE_TEMPLATE
    from app.service import SafeStreamBuffer

    emitted = []
    buf = SafeStreamBuffer(lambda t: emitted.append(t))

    # Case 1: Streamed in fragments of [[NO_EVIDENCE]]
    buf.push("[")
    assert len(emitted) == 0  # Held in buffer
    buf.push("[")
    assert len(emitted) == 0  # Held in buffer
    buf.push("NO_")
    assert len(emitted) == 0  # Held in buffer
    buf.push("EVIDENCE]]")
    buf.flush()

    assert len(emitted) == 1
    assert emitted[0] == NO_EVIDENCE_TEMPLATE
    assert "[[NO_EVIDENCE]]" not in "".join(emitted)

    # Case 2: Normal response with citation bracket [S1]
    emitted_normal = []
    buf_normal = SafeStreamBuffer(lambda t: emitted_normal.append(t))
    buf_normal.push("Theo quy định ")
    buf_normal.push("[S1]")
    buf_normal.push(" thời hạn là 7 ngày.")
    buf_normal.flush()
    assert "".join(emitted_normal) == "Theo quy định [S1] thời hạn là 7 ngày."


async def test_supervisor_has_parallel_tasks_registered(settings):
    svc = ChatService(settings)
    try:
        assert hasattr(svc.harness, "parallel_tasks")
        assert svc.harness.parallel_tasks is not None
        assert svc.harness.parallel_tasks.name == "parallel_tasks"
    finally:
        await svc.close()


async def test_pure_tracking_skips_rag_prefetch(settings):
    svc = ChatService(settings)
    try:
        req = ChatRequest(message="Kiểm tra trạng thái bưu gửi EB123456789VN", mode="deep")
        res = await svc.chat("a", req)
        # Should not have executed rag_prefetch_start because it's a pure tracking query
        assert not any(e["type"] == "rag_prefetch_start" for e in res.events)
        assert res.answer
    finally:
        await svc.close()
