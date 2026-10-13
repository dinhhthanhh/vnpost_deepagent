import asyncio
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents import create_model
from app.config import Settings
from app.context import current_run
from app.demo import message_text
from app.providers import ProviderClients
from app.rag import KnowledgeBases

FAST_RAG_SYSTEM_PROMPT = """Bạn là chuyên viên tư vấn AI thông minh và tận tâm của Tổng công ty Bưu điện Việt Nam (VNPost).
Nhiệm vụ của bạn là giải đáp thắc mắc của khách hàng một cách chính xác, dựa trên các tài liệu trích dẫn được cung cấp dưới đây.

QUY TẮC BẮT BUỘC VỀ NGUỒN VÀ TRÍCH DẪN:
1. Khi sử dụng thông tin từ tài liệu, BẮT BUỘC phải ghi mã nguồn trích dẫn tương ứng (ví dụ [S1], [S2]) ngay sau thông tin đó.
2. Không tự bịa đặt hoặc suy diễn thông tin nghiệp vụ không có trong tài liệu.
3. Nếu tài liệu không đủ dữ liệu để trả lời câu hỏi, hãy nêu rõ tài liệu chưa đề cập và hướng dẫn khách hàng liên hệ hotline 1900 54 54 81 hoặc bưu cục gần nhất.
4. Trình bày ngắn gọn, rõ ràng, lịch sự, chuẩn tiếng Việt.

--- TÀI LIỆU THAM KHẢO ---
{evidence}
"""


class FastRAGExecutor:
    def __init__(self, settings: Settings, knowledge: KnowledgeBases, clients: ProviderClients | None = None):
        self.settings = settings
        self.knowledge = knowledge
        self.clients = clients
        self.model = create_model(settings, "fast_rag", clients)

    async def execute(self, tenant: str, message: str, history: list[dict], grounded: bool) -> str:
        run = current_run.get()
        kb = await asyncio.to_thread(self.knowledge.for_tenant, tenant)
        hits = await asyncio.to_thread(kb.retrieve, message, top_k=self.settings.retrieval_top_k, session_id=run.session_id, user_id=run.user_id)

        sources = [run.cite(hit) for hit in hits]
        run.event("retrieval", count=len(sources), revision=kb.snapshot.revision)

        evidence_blocks = []
        for hit, src in zip(hits, sources):
            evidence_blocks.append(
                f"[{src.citation_id}] (Tài liệu: {src.filename}, Vị trí: {src.location}):\n{src.excerpt}"
            )

        evidence_text = "\n\n".join(evidence_blocks) if evidence_blocks else "Không tìm thấy tài liệu phù hợp trong hệ thống."

        system_content = FAST_RAG_SYSTEM_PROMPT.format(evidence=evidence_text)
        if not grounded:
            system_content += "\n[Lưu ý: Chế độ câu hỏi mở, cho phép trả lời tổng quan nếu không có nguồn]"

        messages: list = [SystemMessage(content=system_content)]

        # Bổ sung một vài lượt hội thoại gần nhất nếu có
        for turn in history[-4:]:
            role = turn.get("role")
            content = turn.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))

        messages.append(HumanMessage(content=message))

        response = await self.model.ainvoke(messages)
        return message_text(response)
