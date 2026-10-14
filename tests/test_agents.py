import asyncio
import json
import uuid

import pytest
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain_core.messages import AIMessage, ToolMessage

from app.agents import validate_answer
from app.calculator import safe_calculate
from app.context import RunContext, current_run
from app.demo import DemoChatModel, message_text
from app.schemas import ChatRequest, TaskSpec
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
    assert len(starts) == 2 and max(e["elapsed_ms"] for e in starts) < min(e["elapsed_ms"] for e in ends)
    assert svc.store.reply("a", result.request_id)["sources"]
    await svc.close()


async def test_native_deepagents_task_tool_also_runs_parallel(settings):
    class NativeTaskModel(DemoChatModel):
        def _response(self, messages):
            tools = [m for m in messages if isinstance(m, ToolMessage)]
            if tools:
                return AIMessage(content="\n".join(message_text(m) for m in tools))
            return AIMessage(content="", tool_calls=[
                {"name": "task", "args": {"subagent_type": "rag-agent", "description": "Thời hạn hoàn cước?"}, "id": "r"},
                {"name": "task", "args": {"subagent_type": "writer-agent", "description": "Chuẩn bị bố cục"}, "id": "w"},
            ])
    svc = ChatService(settings)
    svc.knowledge.for_tenant("a").ingest("x.txt", "Thời hạn hoàn cước là 7 ngày.".encode())
    graph = create_deep_agent(model=NativeTaskModel(), backend=StateBackend(),
                             middleware=[FilesystemMiddleware(backend=StateBackend(), tools=["read_file"])],
                             subagents=[{"name": name, "description": name, "runnable": agent}
                                        for name, agent in svc.harness.subagents.items()])
    scope = RunContext("a", "native", 3, 8)
    token = current_run.set(scope)
    try:
        result = await graph.ainvoke({"messages": [{"role": "user", "content": "Tra cứu"}]})
        assert "7 ngày" in message_text(result["messages"][-1])
        starts = [e for e in scope.events if e["type"] == "task_start"]
        ends = [e for e in scope.events if e["type"] == "task_end"]
        assert len(starts) == 2 and max(e["elapsed_ms"] for e in starts) <= min(e["elapsed_ms"] for e in ends)
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
    svc.harness.subagents["writer-agent"] = svc.harness._tracked_agent("writer-agent", Failing())
    result = await svc.chat("a", ChatRequest(message="Hoàn cước bao lâu?", mode="deep"))
    assert "7 ngày" in result.answer and "secret-provider-data" not in str(result)
    assert any(e.get("status") == "error" for e in result.events)
    await svc.close()


async def test_parallel_requests_do_not_mix_tenant_sources(settings):
    svc = ChatService(settings)
    svc.knowledge.for_tenant("a").ingest("a.txt", "Thời hạn hoàn cước là 7 ngày.".encode())
    svc.knowledge.for_tenant("b").ingest("b.txt", "Thời hạn hoàn cước là 9 ngày.".encode())
    a, b = await asyncio.gather(svc.chat("a", ChatRequest(message="Hoàn cước bao lâu?", mode="deep")),
                               svc.chat("b", ChatRequest(message="Hoàn cước bao lâu?", mode="deep")))
    assert {s.filename for s in a.sources} == {"a.txt"}
    assert {s.filename for s in b.sources} == {"b.txt"}
    assert "9 ngày" not in a.answer and "7 ngày" not in b.answer
    await svc.close()


async def test_session_serialization_preserves_both_turns(settings):
    svc = ChatService(settings)
    session_id = uuid.uuid4()
    await asyncio.gather(svc.chat("a", ChatRequest(session_id=session_id, message="12 + 8", grounded=False, mode="deep")),
                         svc.chat("a", ChatRequest(session_id=session_id, message="20 - 5", grounded=False, mode="deep")))
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


@pytest.mark.parametrize("expression,expected", [("(120-100)/100*100", 20), ("-5+2", -3), ("2**3", 8), ("9%4", 1)])
def test_calculator_correct(expression, expected):
    assert safe_calculate(expression) == expected


@pytest.mark.parametrize("expression", ["__import__('os').system('whoami')", "x+1", "2**1000000", "1/0", "True+1", "(1).__class__", "1e309", "(-1)**0.5"])
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
    svc.harness.subagents["writer-agent"] = svc.harness._tracked_agent("writer-agent", ArrayOutput())
    scope = RunContext("a", "json-output", 2, 8)
    token = current_run.set(scope)
    try:
        raw = await svc.harness.parallel_tasks.ainvoke({"tasks": [{"id": "draft", "agent": "writer-agent", "description": "Return a JSON array"}]})
        result = json.loads(raw)["results"][0]
        assert result["status"] == "ok" and json.loads(result["result"]) == ["item one", "item two"]
    finally:
        current_run.reset(token)
        await svc.close()
