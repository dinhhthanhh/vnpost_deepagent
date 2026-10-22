import asyncio
import json

import pytest

from app.api.schemas import ChatRequest
from app.core.context import RunContext, current_run
from app.service import ChatService


@pytest.mark.asyncio
async def test_search_documents_expanded(settings):
    svc = ChatService(settings)
    tenant = "test_sd"
    svc.knowledge.for_tenant(tenant).ingest(
        "bang_gia_ems.txt", "Giá cước bưu kiện EMS từ 500g là 35000đ.".encode()
    )
    svc.knowledge.for_tenant(tenant).ingest(
        "quy_trinh_khieunai.txt", "Thời gian khiếu nại EMS là 30 ngày.".encode()
    )

    scope = RunContext(tenant, "req-sd", 3, 8)
    token = current_run.set(scope)
    try:
        # 1. Search with filename_filter
        res_filtered = await svc.harness.search_documents.ainvoke(
            {"query": "EMS", "top_k": 5, "filename_filter": "bang_gia"}
        )
        data_filtered = json.loads(res_filtered)
        assert len(data_filtered["sources"]) == 1
        assert "bang_gia_ems" in data_filtered["sources"][0]["filename"]

        # 2. Search without filename_filter but higher top_k
        res_all = await svc.harness.search_documents.ainvoke(
            {"query": "EMS", "top_k": 8, "filename_filter": None}
        )
        data_all = json.loads(res_all)
        assert len(data_all["sources"]) >= 2
    finally:
        current_run.reset(token)
        await svc.close()


@pytest.mark.asyncio
async def test_context_offloading_and_read_file(settings):
    svc = ChatService(settings)
    tenant = "test_co"
    svc.knowledge.for_tenant(tenant).ingest(
        "bang_cuoc.txt",
        "Chi tiết cước chuyển phát nhanh EMS: Nấc 100g giá 15.000đ, nấc 250g giá 22.000đ, nấc 500g giá 32.000đ.".encode(),
    )

    result = await svc.chat(
        tenant, ChatRequest(message="Chi tiết cước EMS nấc 500g là bao nhiêu?", mode="deep")
    )
    assert result.grounding_status == "cited"
    assert result.sources

    # Test read_file tool can read virtual /evidence/prefetched_sources.json
    scope = RunContext(tenant, "req-rf", 3, 8)
    token = current_run.set(scope)
    try:
        scope.retrieval_cache["/evidence/prefetched_sources.json"] = json.dumps(
            {"sources": [{"citation_id": "S1", "excerpt": "Sample"}]}
        )
        content = svc.harness.read_file.invoke({"path": "/evidence/prefetched_sources.json"})
        assert "sources" in content
    finally:
        current_run.reset(token)
        await svc.close()


@pytest.mark.asyncio
async def test_streaming_tts_segments(settings):
    svc = ChatService(settings)
    tenant = "test_tts_stream"
    svc.knowledge.for_tenant(tenant).ingest(
        "chinh_sach.txt", "Quy định hoàn tiền bưu phẩm mất mát trong vòng 7 ngày làm việc.".encode()
    )

    queue = asyncio.Queue()
    request = ChatRequest(
        message="Quy định hoàn tiền trong bao lâu?",
        mode="fast",
        voice=True,
        stream_voice=True,
        voice_name="maichi",
    )

    res = await svc.chat(tenant, request, queue=queue)
    assert res.answer

    items = []
    while not queue.empty():
        items.append(await queue.get())

    tts_events = [it for it in items if it.get("type") == "tts_segment"]
    assert len(tts_events) >= 1
    for seg in tts_events:
        assert "text" in seg
        assert "index" in seg
        assert "total" in seg
        assert seg["voice"] == "maichi"
    await svc.close()


@pytest.mark.asyncio
async def test_deep_agent_streaming_tts_segments(settings):
    svc = ChatService(settings)
    tenant = "test_tts_deep"
    svc.knowledge.for_tenant(tenant).ingest(
        "chinh_sach_deep.txt",
        "Quy định bưu phẩm quốc tế EMS được hoàn tiền trong vòng 14 ngày.".encode(),
    )

    queue = asyncio.Queue()
    request = ChatRequest(
        message="Quy định bưu phẩm quốc tế EMS được xử lý như thế nào?",
        mode="deep",
        voice=True,
        stream_voice=True,
        voice_name="maichi",
    )

    res = await svc.chat(tenant, request, queue=queue)
    assert res.answer

    items = []
    while not queue.empty():
        items.append(await queue.get())

    # Kiểm tra cả token và tts_segment được sinh ra trong nhánh deep
    tokens = [it for it in items if it.get("type") == "token"]
    assert len(tokens) >= 1
    tts_events = [it for it in items if it.get("type") == "tts_segment"]
    assert len(tts_events) >= 1
    for seg in tts_events:
        assert "text" in seg
        assert "index" in seg
        assert "total" in seg
        assert seg["voice"] == "maichi"
    await svc.close()
