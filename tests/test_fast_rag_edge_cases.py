import pytest
from langchain_core.messages import SystemMessage

from app.core.context import RunContext, current_run
from app.core.prompts import FAST_RAG_SYSTEM_PROMPT
from app.rag.fast_rag import FastRAGExecutor


@pytest.mark.asyncio
async def test_greeting_no_name_error(settings):
    """Lỗi 1: Kiểm tra khi gặp câu chào hỏi, prepare() dùng FAST_RAG_SYSTEM_PROMPT an toàn, không bị NameError."""
    executor = FastRAGExecutor(settings, None, None)
    scope = RunContext("tenant_test", "req-1", 1, 1)
    token = current_run.set(scope)
    try:
        prep = await executor.prepare("tenant_test", "Xin chào bạn!", [], True)
        assert prep.greeting is True
        assert prep.source_count == 0
        assert len(prep.messages) >= 2
        assert isinstance(prep.messages[0], SystemMessage)
        assert prep.messages[0].content == FAST_RAG_SYSTEM_PROMPT
    finally:
        current_run.reset(token)


@pytest.mark.asyncio
async def test_direct_answer_math_no_orphan_aimessage(settings):
    """Lỗi 3: Kiểm tra try_evaluate_math trong prepare() trả về direct_answer, không gửi AIMessage đơn độc."""
    executor = FastRAGExecutor(settings, None, None)
    scope = RunContext("tenant_test", "req-2", 1, 1)
    token = current_run.set(scope)
    try:
        prep = await executor.prepare("tenant_test", "15000 + 35000", [], True)
        assert "50000" in prep.direct_answer
        assert prep.has_sufficient_evidence(1) is True
        # messages không chứa mảng lỗi đơn độc tới model
        assert prep.messages == []

        # execute() và stream() trả về ngay lập tức giá trị direct_answer
        ans = await executor.execute("tenant_test", "15000 + 35000", [], True, prepared=prep)
        assert ans == prep.direct_answer

        streamed = [delta async for delta in executor.stream("tenant_test", "15000 + 35000", [], True, prepared=prep)]
        assert "".join(streamed) == prep.direct_answer
    finally:
        current_run.reset(token)


@pytest.mark.asyncio
async def test_filter_relevant_hits_applied_in_both(settings):
    """Lỗi 2: Kiểm tra filter_relevant_hits lọc sạch hit lạc đề trong cả Fast RAG lẫn Deep Agent search_documents."""
    from app.service import ChatService
    svc = ChatService(settings)
    tenant = "tenant_filter_test"
    # Nạp văn bản về chuyển phát bưu phẩm
    svc.knowledge.for_tenant(tenant).ingest(
        "chuyen_phat.txt",
        "Dịch vụ bưu phẩm chuyển phát nhanh nội tỉnh có thời gian tối đa 24 giờ.".encode()
    )

    scope = RunContext(tenant, "req-3", 3, 8)
    token = current_run.set(scope)
    try:
        # Truy vấn hoàn toàn lạc đề không có từ khóa nào khớp với văn bản
        irrelevant_query = "công thức hóa học của nước cất và axit sunfuric"

        # 1. Kiểm tra trong fast_rag.prepare
        prep = await svc.fast_rag.prepare(tenant, irrelevant_query, [], True)
        # Vì không có từ khóa liên quan, hit lạc đề phải bị loại bỏ
        assert prep.source_count == 0

        # 2. Kiểm tra trong agents.search_documents
        agent_res = await svc.harness.search_documents.ainvoke({"query": irrelevant_query})
        import json
        data = json.loads(agent_res)
        assert len(data.get("sources", [])) == 0
    finally:
        current_run.reset(token)
        await svc.close()
