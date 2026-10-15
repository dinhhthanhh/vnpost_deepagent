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
    assert classify_query("Thời hạn hoàn cước là bao lâu?")[0] == "fast"
    assert classify_query("Nghỉ phép năm được mấy ngày?")[0] == "fast"
    assert classify_query("Tóm tắt quy định gửi hàng chuyển phát tiêu chuẩn")[0] == "fast"
    assert classify_query("Bưu phẩm này gửi được không?", image="data:image/png;base64,abc")[0] == "deep"
    assert classify_query("Hãy so sánh dịch vụ EMS và bưu phẩm thường")[0] == "deep"
    assert classify_query("Tính giúp tôi cước phí gửi 5kg đi Đà Nẵng")[0] == "deep"
    assert classify_query("Thời gian gửi là bao lâu? Cước phí hết bao nhiêu?")[0] == "deep"
    assert classify_query("Tôi cần giấy tờ gì khi chuyển tiền, và cách tra cứu giao dịch như thế nào?")[0] == "deep"


def test_router_normalizes_vietnamese_unicode_and_defaults_to_retrieval_first():
    decision = rule_based_decision("Cha\u0300o bạn")
    assert decision.route == "fast"
    assert decision.tier == 0

    decision = rule_based_decision("Nếu bưu gửi bị chậm, tôi cần làm gì tiếp theo?")
    assert decision.route == "fast"
    assert decision.strategy == "retrieval_first"
    assert decision.needs_semantic is False


def test_semantic_router_response_parser_rejects_free_text_and_bad_confidence():
    assert _parse_semantic_response('{"route":"fast","confidence":0.91}') == ("fast", 0.91)
    assert _parse_semantic_response('```json\n{"confidence":0.91,"route":"fast"}\n```') == ("fast", 0.91)
    assert _parse_semantic_response("route: fast") is None
    assert _parse_semantic_response('{"route":"fast","confidence":1.2}') is None


async def test_adaptive_router_does_not_call_llm_by_default(settings, monkeypatch):
    async def forbidden(*_args):
        raise AssertionError("LLM router must stay off by default")

    monkeypatch.setattr(router, "_semantic_route", forbidden)
    decision = await classify_query_adaptive(settings, None, "Tôi muốn hỏi về việc nhận bưu gửi của mình.")
    assert decision.route == "fast"
    assert decision.strategy == "retrieval_first"


async def test_experimental_semantic_router_is_opt_in(settings, monkeypatch):
    async def semantic_deep(*_args):
        return "deep", 0.93

    monkeypatch.setattr(router, "_semantic_route", semantic_deep)
    settings = settings.model_copy(update={"llm_router_enabled": True})
    decision = await classify_query_adaptive(settings, None, "Tôi muốn hỏi về việc nhận bưu gửi của mình.")
    assert decision.route == "deep"
    assert decision.strategy == "semantic"


async def test_semantic_router_failure_keeps_fast_path(settings, monkeypatch):
    async def broken_router(*_args):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(router, "_semantic_route", broken_router)
    settings = settings.model_copy(update={"llm_router_enabled": True})
    decision = await classify_query_adaptive(settings, None, "Tôi muốn hỏi về việc nhận bưu gửi của mình.")
    assert decision.route == "fast"
    assert decision.strategy == "retrieval_first"


async def test_service_records_router_metadata(settings, monkeypatch):
    settings = settings.model_copy(update={"router_enabled": True, "llm_router_enabled": True})

    async def semantic_decision(*_args):
        return RouterDecision("fast", "Phân loại thử nghiệm", "semantic", 0.91)

    monkeypatch.setattr(service_module, "classify_query_adaptive", semantic_decision)
    svc = ChatService(settings)
    try:
        svc.knowledge.for_tenant("a").ingest("rule.txt", "Thời gian khiếu nại là 30 ngày.".encode())
        result = await svc.chat("a", ChatRequest(message="Tôi muốn hỏi về việc khiếu nại."))
        event = next(e for e in result.events if e["type"] == "router_decision")
        assert event["strategy"] == "semantic"
        assert event["confidence"] == 0.91
    finally:
        await svc.close()


async def test_fast_rag_execution_in_service(settings):
    svc = ChatService(settings)
    svc.knowledge.for_tenant("a").ingest("rule.txt", "Thời gian khiếu nại là 30 ngày.".encode())
    try:
        result = await svc.chat("a", ChatRequest(message="Thời gian khiếu nại là bao lâu?", mode="fast"))
        assert result.route == "fast"
        assert result.grounding_status == "cited"
        assert len(result.sources) >= 1
        assert any(e["type"] == "source_gate" and e["status"] == "pass" for e in result.events)
    finally:
        await svc.close()


async def test_service_uses_local_shortcuts_without_llm(settings):
    svc = ChatService(settings)
    try:
        calculation = await svc.chat("a", ChatRequest(message="125.000 + 35.000"))
        assert calculation.route == "calculator"
        assert calculation.grounding_status == "computed"
        assert "160000" in calculation.answer

        today = await svc.chat("a", ChatRequest(message="hôm nay là ngày bao nhiêu"))
        assert today.route == "local"
        assert today.grounding_status == "computed"
        assert "Hôm nay là ngày" in today.answer
    finally:
        await svc.close()


def test_router_temporal_calculation():
    decision1 = rule_based_decision("12/3 năm sau là ngày thứ mấy")
    assert decision1.route == "deep"
    assert decision1.tier == 2

    decision2 = rule_based_decision("thứ 4 tuần sau nữa nữa là ngày thứ mấy")
    assert decision2.route == "deep"
    assert decision2.tier == 2

def test_router_postal_operations_use_specialist_route():
    for question in (
        "Tra cứu đơn EB123456789VN",
        "Bưu cục gần tôi mở cửa lúc mấy giờ?",
        "Mã bưu chính của quận Hoàn Kiếm là gì?",
    ):
        decision = rule_based_decision(question)
        assert decision.route == "deep"
        assert decision.tier == 2
        assert "postal_ops" in decision.signals
