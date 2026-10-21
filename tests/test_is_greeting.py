from app.agents import validate_answer
from app.rag.fast_rag import is_greeting


def test_greeting_not_swallowing_business_questions():
    assert not is_greeting("Hello, quy trình hoàn hàng thế nào?")
    assert not is_greeting("chào bạn cho mình hỏi về thủ tục nghỉ phép")
    assert not is_greeting("Chào bạn, cước EMS gửi đi Đà Nẵng là bao nhiêu?")

def test_greeting_true_for_pure_chitchat():
    assert is_greeting("Hello")
    assert is_greeting("Xin chào")
    assert is_greeting("Chào bạn")
    assert is_greeting("Mipo là ai?")
    assert is_greeting("Cảm ơn bạn")
    assert is_greeting("Tạm biệt")

def test_validate_answer_uses_same_greeting_logic():
    # Câu hỏi mở đầu bằng Hello nhưng có nội dung thì không được coi là greeting
    # Trả lời không nguồn cho câu nghiệp vụ mở đầu bằng Hello phải bị no_evidence/unverified
    _, _, status, _ = validate_answer("Tự bịa không nguồn", {}, True, "Hello, quy trình hoàn hàng thế nào?")
    assert status == "no_evidence"
