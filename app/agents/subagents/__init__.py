"""Modular Subagents Package for Mipo VNPost Deep Agent.

Provides per-agent prompts, configurations, and tuning parameters.
"""
from __future__ import annotations

import pathlib
from typing import Any

from app.core import prompts

# Danh mục các sub-agents chuyên trách
SUBAGENT_NAMES = [
    "rag-agent",
    "analyst-agent",
    "tracking-agent",
    "post-office-agent",
    "booking-agent",
    "complaint-agent",
    "writer-agent",
]

_DIR = pathlib.Path(__file__).parent


def _read_prompt_or_fallback(agent_dir_name: str, fallback_prompt: str) -> str:
    """Đọc tệp prompt.md của subagent nếu có, hoặc dùng fallback từ app.core.prompts."""
    prompt_file = _DIR / agent_dir_name / "prompt.md"
    if prompt_file.exists():
        try:
            return prompt_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return fallback_prompt.strip()


def get_subagents_registry() -> dict[str, dict[str, Any]]:
    """Tải danh mục và cấu hình tinh chỉnh riêng cho toàn bộ 7 subagents."""
    from .analyst import config as analyst_cfg
    from .booking import config as booking_cfg
    from .complaint import config as complaint_cfg
    from .post_office import config as post_office_cfg
    from .rag import config as rag_cfg
    from .tracking import config as tracking_cfg
    from .writer import config as writer_cfg

    registry = {
        "rag-agent": {
            "role": rag_cfg.ROLE,
            "name": rag_cfg.NAME,
            "description": rag_cfg.DESCRIPTION,
            "prompt": _read_prompt_or_fallback("rag", prompts.RAG),
            "temperature": rag_cfg.TEMPERATURE,
            "max_tokens": rag_cfg.MAX_TOKENS,
            "mode": rag_cfg.MODE,
            "skills": rag_cfg.SKILLS,
        },
        "analyst-agent": {
            "role": analyst_cfg.ROLE,
            "name": analyst_cfg.NAME,
            "description": analyst_cfg.DESCRIPTION,
            "prompt": _read_prompt_or_fallback("analyst", prompts.ANALYST),
            "temperature": analyst_cfg.TEMPERATURE,
            "max_tokens": analyst_cfg.MAX_TOKENS,
            "mode": analyst_cfg.MODE,
            "skills": analyst_cfg.SKILLS,
        },
        "tracking-agent": {
            "role": tracking_cfg.ROLE,
            "name": tracking_cfg.NAME,
            "description": tracking_cfg.DESCRIPTION,
            "prompt": _read_prompt_or_fallback("tracking", prompts.TRACKING),
            "temperature": tracking_cfg.TEMPERATURE,
            "max_tokens": tracking_cfg.MAX_TOKENS,
            "mode": tracking_cfg.MODE,
            "skills": tracking_cfg.SKILLS,
        },
        "post-office-agent": {
            "role": post_office_cfg.ROLE,
            "name": post_office_cfg.NAME,
            "description": post_office_cfg.DESCRIPTION,
            "prompt": _read_prompt_or_fallback("post_office", prompts.POST_OFFICE),
            "temperature": post_office_cfg.TEMPERATURE,
            "max_tokens": post_office_cfg.MAX_TOKENS,
            "mode": post_office_cfg.MODE,
            "skills": post_office_cfg.SKILLS,
        },
        "booking-agent": {
            "role": booking_cfg.ROLE,
            "name": booking_cfg.NAME,
            "description": booking_cfg.DESCRIPTION,
            "prompt": _read_prompt_or_fallback("booking", prompts.BOOKING),
            "temperature": booking_cfg.TEMPERATURE,
            "max_tokens": booking_cfg.MAX_TOKENS,
            "mode": booking_cfg.MODE,
            "skills": booking_cfg.SKILLS,
        },
        "complaint-agent": {
            "role": complaint_cfg.ROLE,
            "name": complaint_cfg.NAME,
            "description": complaint_cfg.DESCRIPTION,
            "prompt": _read_prompt_or_fallback("complaint", prompts.COMPLAINT),
            "temperature": complaint_cfg.TEMPERATURE,
            "max_tokens": complaint_cfg.MAX_TOKENS,
            "mode": complaint_cfg.MODE,
            "skills": complaint_cfg.SKILLS,
        },
        "writer-agent": {
            "role": writer_cfg.ROLE,
            "name": writer_cfg.NAME,
            "description": writer_cfg.DESCRIPTION,
            "prompt": _read_prompt_or_fallback("writer", prompts.WRITER),
            "temperature": writer_cfg.TEMPERATURE,
            "max_tokens": writer_cfg.MAX_TOKENS,
            "mode": writer_cfg.MODE,
            "skills": writer_cfg.SKILLS,
        },
    }
    return registry
