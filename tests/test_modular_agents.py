import json
import pathlib

from app.agents.orchestrator import _get_supervisor_prompt, _load_enterprise_skills
from app.agents.subagents import SUBAGENT_NAMES, get_subagents_registry
from app.mcp.server import mcp


def test_subagents_registry_complete():
    """Kiểm tra toàn bộ 7 subagents được cấu hình độc lập với prompt, config và mode riêng."""
    reg = get_subagents_registry()
    assert len(reg) == 7
    for name in SUBAGENT_NAMES:
        assert name in reg
        meta = reg[name]
        assert "role" in meta
        assert "description" in meta
        assert "prompt" in meta and len(meta["prompt"]) > 50
        assert "temperature" in meta
        assert "max_tokens" in meta
        assert "mode" in meta
    # Kiểm tra tinh chỉnh riêng cho writer-agent (fork mode & higher temperature)
    assert reg["writer-agent"]["mode"] == "fork"
    assert reg["writer-agent"]["temperature"] == 0.3
    assert reg["analyst-agent"]["temperature"] == 0.0


def test_supervisor_modular_prompt():
    """Kiểm tra prompt của supervisor được tải thành công từ file hoặc fallback."""
    prompt = _get_supervisor_prompt()
    assert "ROLE: supervisor" in prompt
    assert "vnpost" in prompt.lower() or "bưu" in prompt.lower()


def test_enterprise_skills_loading():
    """Kiểm tra hệ thống nạp các kỹ năng SKILL.md chuẩn hóa từ skills/."""
    skills = _load_enterprise_skills()
    assert len(skills) > 0
    # Kiểm tra sự tồn tại của các kỹ năng cốt lõi
    keys = list(skills.keys())
    assert any("tra_cuu_buu_gui" in k or "tra-cuu-buu-gui" in k for k in keys)
    assert any("uoc_tinh_cuoc_phi" in k or "uoc-tinh-cuoc-phi" in k for k in keys)
    assert any("quy_chuan_dong_goi" in k or "quy-chuan-dong-goi" in k for k in keys)


def test_fastmcp_server_tools_and_resources():
    """Kiểm tra máy chủ FastMCP chuẩn hóa đã đăng ký đầy đủ tools và resources bưu chính."""
    assert mcp.name == "vnpost-enterprise-mcp-server"
    tool_names = [t.name for t in mcp._tool_manager.list_tools()]
    assert "tra_cuu_buu_gui" in tool_names
    assert "tra_cuu_buu_cuc" in tool_names
    assert "tim_buu_cuc_gan_nhat" in tool_names
    assert "tao_don_hang_nhap" in tool_names
    assert "xac_nhan_don_hang" in tool_names
    assert "huy_don_hang" in tool_names
    assert "tao_phieu_khieu_nai_nhap" in tool_names
    assert "xac_nhan_khieu_nai" in tool_names
    assert "huy_khieu_nai" in tool_names
    assert "danh_sach_don_va_khieu_nai" in tool_names

    # Kiểm tra resources
    res_uris = [str(r.uri) for r in mcp._resource_manager.list_resources()]
    assert any("tariffs/domestic-2026" in u for u in res_uris)


def test_agent_card_json_valid():
    """Kiểm tra thẻ định danh A2A agent_card.json đúng chuẩn."""
    card_path = pathlib.Path("agent_card.json")
    assert card_path.exists()
    data = json.loads(card_path.read_text(encoding="utf-8"))
    assert data["name"] == "vnpost-mipo-agent"
    assert data["version"] == "1.1.0"
    assert "capabilities" in data
    assert data["capabilities"].get("streaming") is True
    assert "skills" in data
    assert len(data["skills"]) >= 3


def test_subagent_evaluation_benchmarks():
    """Kiểm tra toàn bộ bộ eval benchmarks của các subagent hoạt động chính xác."""
    from app.agents.eval_runner import run_all_benchmarks

    summary = run_all_benchmarks()
    assert summary["total_agents"] == 7
    assert summary["passed_agents"] == 7
    assert summary["overall_health"] == "healthy"


def test_k8s_manifests_exist_and_valid():
    """Kiểm tra sự tồn tại và tính hợp lệ của các k8s manifests."""
    k8s_base = pathlib.Path("k8s/base")
    assert (k8s_base / "deployment.yaml").is_file()
    assert (k8s_base / "service.yaml").is_file()
    assert (k8s_base / "hpa.yaml").is_file()
    assert (k8s_base / "configmap.yaml").is_file()
    assert (k8s_base / "ingress.yaml").is_file()
    assert (k8s_base / "kustomization.yaml").is_file()


def test_healthz_and_agent_card_routes():
    """Kiểm tra endpoint /healthz và /.well-known/agent.json."""
    from fastapi.testclient import TestClient

    from app.api.main import create_app
    from app.core.config import Settings

    settings = Settings(allow_anonymous=True)
    app = create_app(settings)
    with TestClient(app) as client:
        res = client.get("/healthz")
        assert res.status_code == 200
        assert res.json().get("status") == "ok"

        card_res = client.get("/.well-known/agent.json")
        assert card_res.status_code == 200
        assert "name" in card_res.json()
