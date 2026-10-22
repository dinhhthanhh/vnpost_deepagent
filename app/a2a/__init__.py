"""Agent-to-Agent (A2A) protocol package for VNPost Deep Agent."""

from .server import VNPostA2AExecutor, load_agent_card_proto, mount_a2a_server

__all__ = [
    "VNPostA2AExecutor",
    "load_agent_card_proto",
    "mount_a2a_server",
]
