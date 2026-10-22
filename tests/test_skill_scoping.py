import json
from unittest.mock import MagicMock

from app.agents.orchestrator import AgentHarness, _resolve_skill_content
from app.core.config import Settings


def _create_test_harness() -> AgentHarness:
    settings = Settings(demo_mode=True, checkpointer_enabled=False)
    knowledge = MagicMock()
    return AgentHarness(settings=settings, knowledge=knowledge)


def test_resolve_skill_content():
    """Kiểm tra hàm trợ năng trích xuất chính xác nội dung kỹ năng theo nhiều biến thể đường dẫn."""
    harness = _create_test_harness()
    content_raw = _resolve_skill_content("/skills/uoc_tinh_cuoc_phi/", harness.enterprise_skills)
    assert len(content_raw) > 50
    assert "KỸ NĂNG TÍNH TOÁN CƯỚC PHÍ" in content_raw
    assert "6000" in content_raw

    content_complaint = _resolve_skill_content(
        "/skills/boi_thuong_khieu_nai/SKILL.md", harness.enterprise_skills
    )
    assert "BỒI THƯỜNG THIỆT HẠI" in content_complaint


def test_subagent_skill_injection_runtime_contract():
    """Kiểm tra từng subagent được inject đúng các kỹ năng đã khai báo vào system prompt (Prompt-level Runtime Contract),

    và cách ly không bị lẫn các kỹ năng của subagent khác.
    """
    harness = _create_test_harness()

    # 1. booking-agent: được cấp quy_chuan_dong_goi và uoc_tinh_cuoc_phi
    booking_prompt = harness.subagent_prompts["booking-agent"]
    assert "RUNTIME CONTRACT" in booking_prompt
    assert "quy_chuan_dong_goi" in booking_prompt
    assert "uoc_tinh_cuoc_phi" in booking_prompt
    assert "6000" in booking_prompt
    assert "Vùng 1 (Nội tỉnh)" in booking_prompt
    # Cách ly: không được chứa kỹ năng khiếu nại hoặc bưu cục
    assert "BỒI THƯỜNG THIỆT HẠI" not in booking_prompt
    assert "Vpostcode" not in booking_prompt
    assert "BCCP Event Codes" not in booking_prompt

    # 2. complaint-agent: được cấp boi_thuong_khieu_nai
    complaint_prompt = harness.subagent_prompts["complaint-agent"]
    assert "RUNTIME CONTRACT" in complaint_prompt
    assert "boi_thuong_khieu_nai" in complaint_prompt
    assert "06 tháng" in complaint_prompt or "Thời hiệu Khiếu nại" in complaint_prompt
    assert "20 ngày làm việc" in complaint_prompt
    # Cách ly: không chứa cước phí hoặc vpostcode
    assert "Vùng 1 (Nội tỉnh)" not in complaint_prompt
    assert "Vpostcode" not in complaint_prompt

    # 3. tracking-agent: được cấp tra_cuu_buu_gui
    tracking_prompt = harness.subagent_prompts["tracking-agent"]
    assert "RUNTIME CONTRACT" in tracking_prompt
    assert "tra_cuu_buu_gui" in tracking_prompt
    assert "BCCP Event Codes" in tracking_prompt
    assert "J06" in tracking_prompt
    assert "BỒI THƯỜNG THIỆT HẠI" not in tracking_prompt

    # 4. post-office-agent: được cấp ma_buu_chinh_vpostcode
    po_prompt = harness.subagent_prompts["post-office-agent"]
    assert "RUNTIME CONTRACT" in po_prompt
    assert "ma_buu_chinh_vpostcode" in po_prompt
    assert "5 chữ số" in po_prompt
    assert "Vpostcode" in po_prompt
    assert "6000" not in po_prompt

    # 5. analyst-agent: được cấp uoc_tinh_cuoc_phi
    analyst_prompt = harness.subagent_prompts["analyst-agent"]
    assert "RUNTIME CONTRACT" in analyst_prompt
    assert "uoc_tinh_cuoc_phi" in analyst_prompt

    # 6. rag-agent và writer-agent: không khai báo SKILLS -> không có khối inject
    rag_prompt = harness.subagent_prompts["rag-agent"]
    assert "RUNTIME CONTRACT" not in rag_prompt
    writer_prompt = harness.subagent_prompts["writer-agent"]
    assert "RUNTIME CONTRACT" not in writer_prompt


def test_scoped_read_file_tool_enforcement():
    """Kiểm tra scoped_read_file chặn truy cập kỹ năng trái quyền (Tool-level Scoping)."""
    harness = _create_test_harness()

    # Analyst agent chỉ có quyền đọc /skills/uoc_tinh_cuoc_phi/
    analyst_reader = harness.make_scoped_read_file("analyst-agent", ["/skills/uoc_tinh_cuoc_phi/"])

    # Đọc kỹ năng được cấp phép -> Thành công
    res_allowed = analyst_reader.invoke({"path": "/skills/uoc_tinh_cuoc_phi/SKILL.md"})
    assert "KỸ NĂNG TÍNH TOÁN CƯỚC PHÍ" in res_allowed

    # Cố tình đọc kỹ năng khiếu nại không được cấp quyền -> Bị từ chối
    res_denied = analyst_reader.invoke({"path": "/skills/boi_thuong_khieu_nai/SKILL.md"})
    data_denied = json.loads(res_denied)
    assert "error" in data_denied
    assert "Quyền truy cập bị từ chối" in data_denied["error"]
    assert "analyst-agent" in data_denied["error"]

    # Writer agent có danh sách skills rỗng -> Bị chặn khi đọc bất kỳ file nào trong /skills/
    writer_reader = harness.make_scoped_read_file("writer-agent", [])
    res_writer_denied = writer_reader.invoke({"path": "/skills/quy_chuan_dong_goi/SKILL.md"})
    data_w = json.loads(res_writer_denied)
    assert "Quyền truy cập bị từ chối" in data_w["error"]
