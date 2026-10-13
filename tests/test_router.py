import app.router as router
import app.service as service_module
from app.router import (
    RouterDecision,
    _parse_semantic_response,
    classify_query,
    classify_query_adaptive,
    rule_based_decision,
)
from app.schemas import ChatRequest
from app.service import ChatService


def test_router_classification_heuristics():
    # Câu hỏi tra cứu đơn giản -> fast
    assert classify_query("Thời hạn hoàn cước là bao lâu?")[0] == "fast"
    assert classify_query("Địa chỉ bưu cục gần nhất ở đâu?")[0] == "fast"
    assert classify_query("Quy định gửi hàng chuyển phát tiêu chuẩn")[0] == "fast"

    # Câu hỏi kèm ảnh -> deep
    assert classify_query("Bưu phẩm này gửi được không?", image="data:image/png;base64,abc")[0] == "deep"

    # Câu hỏi so sánh -> deep
    assert classify_query("Hãy so sánh dịch vụ EMS và bưu phẩm thường")[0] == "deep"
    assert classify_query("Hai dịch vụ này khác nhau thế nào?")[0] == "deep"

    # Câu hỏi tính toán hoặc nhiều câu hỏi -> deep
    assert classify_query("Tính giúp tôi cước phí gửi 5kg đi Đà Nẵng")[0] == "deep"
    assert classify_query("Thời gian gửi là bao lâu? Cước phí hết bao nhiêu?")[0] == "deep"


def test_rule_router_marks_unfamiliar_intent_for_semantic_classification():
    decision = rule_based_decision("Nếu bưu gửi bị chậm, tôi cần làm gì tiếp theo?")

    assert decision.route == "deep"
    assert decision.needs_semantic is True
    assert decision.strategy == "fallback"


def test_semantic_router_response_parser_rejects_free_text_and_bad_confidence():
    assert _parse_semantic_response('{"route":"fast","confidence":0.91}') == ("fast", 0.91)
    assert _parse_semantic_response('```json\n{"confidence":0.91,"route":"fast"}\n```') == ("fast", 0.91)
    assert _parse_semantic_response("route: fast") is None
    assert _parse_semantic_response('{"route":"fast","confidence":1.2}') is None


async def test_adaptive_router_uses_semantic_result_for_ambiguous_request(settings, monkeypatch):
    async def semantic_fast(*_args):
        return "fast", 0.93

    monkeypatch.setattr(router, "_semantic_route", semantic_fast)
    decision = await classify_query_adaptive(
        settings, None, "Tôi muốn hỏi về việc nhận bưu gửi của mình."
    )

    assert decision.route == "fast"
    assert decision.strategy == "semantic"
    assert decision.confidence == 0.93


async def test_adaptive_router_falls_back_to_deep_when_semantic_router_fails(settings, monkeypatch):
    async def broken_router(*_args):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(router, "_semantic_route", broken_router)
    decision = await classify_query_adaptive(
        settings, None, "Tôi muốn hỏi về việc nhận bưu gửi của mình."
    )

    assert decision.route == "deep"
    assert decision.strategy == "fallback"


async def test_service_records_adaptive_router_metadata(settings, monkeypatch):
    settings = settings.model_copy(update={"router_enabled": True})

    async def semantic_decision(*_args):
        return RouterDecision("fast", "Phân loại ngữ nghĩa với độ tin cậy 91%", "semantic", 0.91)

    monkeypatch.setattr(service_module, "classify_query_adaptive", semantic_decision)
    svc = ChatService(settings)
    try:
        svc.knowledge.for_tenant("a").ingest("rule.txt", "Thời gian khiếu nại là 30 ngày.".encode())
        result = await svc.chat("a", ChatRequest(message="Tôi muốn hỏi về việc khiếu nại."))

        assert result.route == "fast"
        event = next(e for e in result.events if e["type"] == "router_decision")
        assert event["strategy"] == "semantic"
        assert event["confidence"] == 0.91
    finally:
        await svc.close()


async def test_fast_rag_execution_in_service(settings):
    # Test service using explicit mode='fast'
    svc = ChatService(settings)
    svc.knowledge.for_tenant("a").ingest("rule.txt", "Thời gian khiếu nại là 30 ngày.".encode())
    
    req = ChatRequest(message="Thời gian khiếu nại là bao lâu?", mode="fast")
    result = await svc.chat("a", req)
    
    assert result.route == "fast"
    assert result.grounding_status == "cited"
    assert len(result.sources) >= 1
    assert any(e["type"] == "router_decision" and e["route"] == "fast" for e in result.events)
    await svc.close()
