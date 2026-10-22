"""A2A Server Integration for VNPost Deep Agent."""

from __future__ import annotations

import json
import logging
import pathlib
import uuid
from collections.abc import Callable
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue_v2 import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, Message, Part, Role
from fastapi import FastAPI
from google.protobuf.json_format import Parse

logger = logging.getLogger(__name__)


def load_agent_card_proto(card_path: str | pathlib.Path | None = None) -> AgentCard:
    """Tải và phân giải agent_card.json thành protobuf AgentCard chuẩn hóa tuân thủ A2A spec."""
    if card_path is None:
        root_dir = pathlib.Path(__file__).resolve().parents[2]
        card_path = root_dir / "agent_card.json"
    card_path = pathlib.Path(card_path)
    if not card_path.exists():
        card = AgentCard()
        card.name = "vnpost-mipo-agent"
        card.description = "Trợ lý Trí tuệ Nhân tạo VNPost"
        card.version = "1.1.0"
        return card

    card_data = json.loads(card_path.read_text(encoding="utf-8"))
    card = AgentCard()
    Parse(json.dumps(card_data), card, ignore_unknown_fields=True)
    return card


class VNPostA2AExecutor(AgentExecutor):
    """A2A AgentExecutor kết nối trực tiếp với ChatService của VNPost Deep Agent."""

    def __init__(self, service_provider: Callable[[], Any] | Any = None) -> None:
        self.service_provider = service_provider

    def _get_service(self) -> Any:
        if callable(self.service_provider):
            return self.service_provider()
        return self.service_provider

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Thực thi thông điệp từ A2A client, gọi ChatService và gửi phản hồi ROLE_AGENT."""
        user_input = context.get_user_input() or ""
        tenant = getattr(context, "tenant", None) or "vnpost"
        session_id = context.context_id or f"a2a-{uuid.uuid4().hex[:8]}"

        svc = self._get_service()
        reply_text = ""
        if svc is not None:
            try:
                from app.api.schemas import ChatRequest

                req = ChatRequest(message=user_input, session_id=session_id)
                chat_res = await svc.chat(tenant=tenant, request=req)
                reply_text = (
                    getattr(chat_res, "reply", "")
                    or getattr(chat_res, "answer", "")
                    or str(chat_res)
                )
            except Exception as exc:
                logger.error("VNPost A2A execution failed: %s", exc, exc_info=True)
                reply_text = f"Mipo VNPost (A2A) gặp sự cố khi xử lý yêu cầu: {exc}"
        else:
            reply_text = f"Mipo VNPost (A2A): Đã tiếp nhận yêu cầu: {user_input}"

        msg = Message(
            message_id=str(uuid.uuid4()),
            role=Role.ROLE_AGENT,
            parts=[Part(text=reply_text or "VNPost đã xử lý thông điệp của bạn.")],
        )
        await event_queue.enqueue_event(msg)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Hủy tác vụ A2A theo yêu cầu."""
        logger.info("A2A cancellation requested for task %s", context.task_id)


def mount_a2a_server(
    app: FastAPI,
    service_provider: Callable[[], Any] | Any = None,
    agent_card: AgentCard | None = None,
    rpc_url: str = "/a2a",
) -> None:
    """Mount endpoint A2A chuẩn hóa lên FastAPI application."""
    if agent_card is None:
        agent_card = load_agent_card_proto()

    executor = VNPostA2AExecutor(service_provider=service_provider)
    task_store = InMemoryTaskStore()
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
        agent_card=agent_card,
    )

    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(agent_card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url=rpc_url, enable_v0_3_compat=True),
    )
    logger.info("A2A Server routes mounted at %s and /.well-known/agent-card.json", rpc_url)
