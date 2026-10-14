"""Scripted model for OFFLINE tests of the actual LangChain/Deep Agents tool loop.

This is deliberately not presented as real language-model reasoning.
"""
import asyncio
import json
import re
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def message_text(message) -> str:
    if isinstance(message.content, str):
        return message.content
    return "\n".join(block.get("text", "") for block in message.content if isinstance(block, dict))


class DemoChatModel(BaseChatModel):
    role: str = "supervisor"
    latency_seconds: float = 0.01

    @property
    def _llm_type(self) -> str:
        return "offline-scripted-demo"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self

    def _response(self, messages):
        user = next((message_text(m) for m in reversed(messages) if isinstance(m, HumanMessage)), "")
        user = user.split("\n\n[Chế độ hệ thống:")[0]
        # Tool outputs belong only to the most recent user turn in this isolated invocation.
        last_user = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
        results = [m for m in messages[last_user + 1:] if isinstance(m, ToolMessage)]
        if self.role == "rag":
            if not results:
                return AIMessage(content="", tool_calls=[{"name": "search_documents", "args": {"query": user}, "id": "demo-rag"}])
            data = json.loads(message_text(results[-1]))
            sources = data.get("sources", [])
            if not sources:
                return AIMessage(content="NO_EVIDENCE: Chưa tìm thấy bằng chứng phù hợp trong kho tài liệu.")
            # Verbatim evidence demonstrates provenance without inventing an LLM answer.
            lines = [f"[{s['citation_id']}] {s['excerpt']}" for s in sources[:3]]
            return AIMessage(content="Trích đoạn tìm được:\n\n" + "\n\n".join(lines))
        if self.role == "analyst":
            if results:
                return AIMessage(content="Kết quả phép tính: " + message_text(results[-1]))
            match = re.search(r"(?:\d+(?:\.\d+)?\s*[+*/-]\s*)+\d+(?:\.\d+)?", user)
            if match:
                return AIMessage(content="", tool_calls=[{"name": "calculate", "args": {"expression": match.group()}, "id": "demo-calc"}])
            return AIMessage(content="MISSING_INPUT: Demo chỉ tính biểu thức số được nhập rõ ràng.")
        if self.role == "writer":
            return AIMessage(content="Bố cục đề xuất: kết quả chính → bằng chứng → bước thực hiện. Chế độ demo chưa dùng LLM để soạn nội dung.")
        if self.role == "fast_rag":
            from langchain_core.messages import SystemMessage
            sys_text = next((message_text(m) for m in messages if isinstance(m, SystemMessage)), "")
            evidence_part = sys_text.split("--- TÀI LIỆU THAM KHẢO ---")[-1] if "--- TÀI LIỆU THAM KHẢO ---" in sys_text else sys_text
            cites = re.findall(r"\[(S\d+)\]", evidence_part)
            if cites:
                idx = evidence_part.find(f"[{cites[0]}]")
                block = evidence_part[idx:idx + 400]
                lines = [l.strip() for l in block.split("\n") if l.strip() and not l.strip().startswith(f"[{cites[0]}")]
                content_text = " ".join(lines) if lines else block
                return AIMessage(content=f"Dựa trên tài liệu, thông tin tìm thấy: {content_text} [{cites[0]}].")
            return AIMessage(content="Chưa tìm thấy bằng chứng phù hợp trong kho tài liệu.")
        if results:
            data = json.loads(message_text(results[-1]))
            pieces = [x["result"] for x in data.get("results", []) if x.get("status") == "ok" and x.get("agent") != "writer-agent"]
            return AIMessage(content="[DEMO — chưa dùng LLM thật]\n\n" + "\n\n".join(pieces))
        if user.lower().strip().strip("!.") in {"xin chào", "chào", "hello", "hi"}:
            return AIMessage(content="Xin chào! Đây là chế độ demo. Bạn có thể nhập tài liệu và thử tra cứu có trích nguồn.")
        # Two independent roles demonstrate true concurrent execution in the real harness.
        tasks = [{"id": "find-evidence", "agent": "rag-agent", "description": user},
                 {"id": "prepare-structure", "agent": "writer-agent", "description": "Chuẩn bị bố cục cho yêu cầu: " + user}]
        if re.search(r"\d+\s*[+*/-]\s*\d+", user):
            tasks[1] = {"id": "calculate", "agent": "analyst-agent", "description": user}
        return AIMessage(content="", tool_calls=[{"name": "parallel_tasks", "args": {"tasks": tasks}, "id": "demo-parallel"}])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        return ChatResult(generations=[ChatGeneration(message=self._response(messages))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        await asyncio.sleep(self.latency_seconds)
        return self._generate(messages, stop, run_manager, **kwargs)
