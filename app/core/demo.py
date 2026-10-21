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
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(block.get("text", ""))
        return "\n".join(p for p in parts if p)
    return str(content or "")


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
            from app.agents.signals import analyze
            if analyze(user).temporal_calc:
                return AIMessage(content="", tool_calls=[{"name": "calculate_date", "args": {"query": user}, "id": "demo-date-calc"}])
            return AIMessage(content="MISSING_INPUT: Demo chỉ tính biểu thức số hoặc ngày tháng được nhập rõ ràng.")
        if self.role == "tracking":
            if results:
                return AIMessage(content="Kết quả định vị bưu gửi:\n" + message_text(results[-1]))
            m = re.search(r"\b[A-Za-z]{2}\d{9}[A-Za-z]{2}\b", user) or re.search(r"\b[A-Za-z0-9]{8,16}\b", user)
            code = m.group() if m else "EB123456789VN"
            return AIMessage(content="", tool_calls=[{"name": "track_item", "args": {"item_code": code}, "id": "demo-track"}])
        if self.role == "post_office":
            if results:
                return AIMessage(content="Kết quả tra cứu bưu cục:\n" + message_text(results[-1]))
            return AIMessage(content="", tool_calls=[{"name": "lookup_post_office", "args": {"query": user}, "id": "demo-po"}])
        if self.role == "writer":
            return AIMessage(content="Bố cục đề xuất: kết quả chính → bằng chứng → bước thực hiện. Chế độ demo chưa dùng LLM để soạn nội dung.")

        if self.role == "fast_rag":
            human_text = next((message_text(m) for m in reversed(messages) if isinstance(m, HumanMessage)), "")
            if "[TÀI LIỆU]" in human_text:
                evidence_part = human_text.split("[TÀI LIỆU]")[-1].split("[HẾT TÀI LIỆU]")[0]
            else:
                from langchain_core.messages import SystemMessage
                sys_text = next((message_text(m) for m in messages if isinstance(m, SystemMessage)), "")
                evidence_part = sys_text.split("--- TÀI LIỆU THAM KHẢO ---")[-1] if "--- TÀI LIỆU THAM KHẢO ---" in sys_text else sys_text
            cites = re.findall(r"\[(S\d+)\]", evidence_part)
            if cites:
                idx = evidence_part.find(f"[{cites[0]}]")
                block = evidence_part[idx:idx + 400]
                lines = [line.strip() for line in block.split("\n") if line.strip() and not line.strip().startswith(f"[{cites[0]}")]
                content_text = " ".join(lines) if lines else block
                return AIMessage(content=f"Dựa trên tài liệu, thông tin tìm thấy: {content_text} [{cites[0]}].")
            return AIMessage(content="Chưa tìm thấy bằng chứng phù hợp trong kho tài liệu.")
        if results:
            pieces = [message_text(m) for m in results if message_text(m)]
            return AIMessage(content="[DEMO — chưa dùng LLM thật]\n\n" + "\n\n".join(pieces))
        if user.lower().strip().strip("!.") in {"xin chào", "chào", "hello", "hi"}:
            return AIMessage(content="Xin chào! Đây là chế độ demo. Bạn có thể nhập tài liệu và thử tra cứu có trích nguồn.")
        is_tracking = bool(re.search(r"\b[A-Za-z]{2}\d{9}[A-Za-z]{2}\b", user) or any(k in user.lower() for k in ["định vị", "vận đơn", "bưu gửi", "tracking", "tra cứu đơn"]))
        is_po = any(k in user.lower() for k in ["bưu cục", "bưu điện", "điểm phục vụ", "vpostcode", "mã bưu chính", "giờ mở cửa", "chi nhánh"])

        if is_tracking and is_po:
            tool_calls = [
                {"name": "task", "args": {"subagent_type": "tracking-agent", "description": user}, "id": "t1"},
                {"name": "task", "args": {"subagent_type": "post-office-agent", "description": user}, "id": "t2"},
            ]
        elif is_tracking:
            tool_calls = [
                {"name": "task", "args": {"subagent_type": "tracking-agent", "description": user}, "id": "t1"},
            ]
        elif is_po:
            tool_calls = [
                {"name": "task", "args": {"subagent_type": "post-office-agent", "description": user}, "id": "t1"},
            ]
        else:
            # Two independent roles demonstrate true concurrent execution in the real harness.
            tool_calls = [
                {"name": "task", "args": {"subagent_type": "rag-agent", "description": user}, "id": "t1"},
            ]
            from app.agents.signals import analyze
            if re.search(r"\d+\s*[+*/-]\s*\d+", user) or analyze(user).temporal_calc:
                tool_calls.append({"name": "task", "args": {"subagent_type": "analyst-agent", "description": user}, "id": "t2"})
            else:
                tool_calls.append({"name": "task", "args": {"subagent_type": "analyst-agent", "description": "Phân tích và kiểm chứng: " + user}, "id": "t2"})
        return AIMessage(content="", tool_calls=tool_calls)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        return ChatResult(generations=[ChatGeneration(message=self._response(messages))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        await asyncio.sleep(self.latency_seconds)
        return self._generate(messages, stop, run_manager, **kwargs)
