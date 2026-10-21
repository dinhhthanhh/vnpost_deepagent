"""Agent-to-Agent (A2A) Client for remote agent invocation and federation."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

import httpx

try:
    from a2a.client import A2ACardResolver, Client, ClientConfig, create_client
    from a2a.types import AgentCard, Message, Part, Role, SendMessageRequest
    from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
    A2A_SDK_AVAILABLE = True
except ImportError:
    A2A_SDK_AVAILABLE = False
    AGENT_CARD_WELL_KNOWN_PATH = "/.well-known/agent.json"

logger = logging.getLogger(__name__)


class CustomA2AClient:
    """A2A client to discover and call remote agents over HTTP/SSE."""

    def __init__(self, default_timeout: float = 600.0) -> None:
        self.default_timeout = default_timeout
        self.agents: dict[str, Any] = {}
        self.agent_clients: dict[str, Any] = {}

    @classmethod
    async def create(cls, a2a_server_urls: list[str], default_timeout: float = 600.0) -> "CustomA2AClient":
        self = cls(default_timeout=default_timeout)
        if not A2A_SDK_AVAILABLE or not a2a_server_urls:
            return self

        async with httpx.AsyncClient(timeout=10.0) as http_client:
            for url in a2a_server_urls:
                cleaned_url = url.rstrip("/")
                try:
                    resolver = A2ACardResolver(httpx_client=http_client, base_url=cleaned_url)
                    card = await resolver.get_agent_card()
                    agent_name = getattr(card, "name", "") or cleaned_url
                    self.agents[agent_name] = card
                    client_cfg = ClientConfig(streaming=False)
                    self.agent_clients[agent_name] = await create_client(agent=card, client_config=client_cfg)
                    logger.info("Connected to remote A2A agent: %s at %s", agent_name, cleaned_url)
                except Exception as exc:
                    logger.warning("Failed to connect to remote A2A agent at %s: %s", cleaned_url, exc)
        return self

    async def call_remote_agent(
        self,
        agent_name: str,
        message: str,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """Call a registered remote agent by name."""
        if not A2A_SDK_AVAILABLE or agent_name not in self.agents:
            return f"Agent '{agent_name}' is not registered or unavailable."

        try:
            client = self.agent_clients.get(agent_name)
            if client is None:
                card = self.agents[agent_name]
                client = await create_client(agent=card)
                self.agent_clients[agent_name] = client

            msg = Message(
                message_id=uuid.uuid4().hex,
                role=Role.ROLE_USER,
                parts=[Part(text=message)],
            )
            req = SendMessageRequest(message=msg)

            parts_text = []
            async for stream_res in client.send_message(req):
                msg_obj = getattr(stream_res, "message", None)
                if msg_obj and getattr(msg_obj, "parts", None):
                    for part in msg_obj.parts:
                        txt = getattr(part, "text", "")
                        if txt:
                            parts_text.append(txt)

            if parts_text:
                return "".join(parts_text)
            return "Remote agent responded with empty content."
        except Exception as exc:
            logger.error("Error invoking remote agent '%s': %s", agent_name, exc)
            return f"Error invoking agent '{agent_name}': {exc}"
