import pytest
from app.router import classify_query
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
