import json
import httpx

from app.config import Settings


def _sanitize_chat_messages(data: dict) -> bool:
    modified = False
    for m in data.get("messages", []):
        if isinstance(m, dict) and m.get("content") is None:
            m["content"] = ""
            modified = True
    return modified


def _patch_request_sync(request: httpx.Request):
    if request.content and request.url.path.endswith("/chat/completions"):
        try:
            data = json.loads(request.content)
            if _sanitize_chat_messages(data):
                new_b = json.dumps(data).encode("utf-8")
                request.stream = httpx.ByteStream(new_b)
                request.headers["content-length"] = str(len(new_b))
        except Exception:
            pass


async def _patch_request_async(request: httpx.Request):
    _patch_request_sync(request)


class ProviderClients:
    """Shared explicit HTTP clients for LLM and embedding SDKs, closed on shutdown.

    This also keeps transport tests independent of SDK changes to default clients.
    """
    def __init__(self, settings: Settings):
        limit = settings.max_active_requests * (settings.max_parallel_subagents + 1) + 2
        options = {"timeout": settings.llm_timeout_seconds,
                   "limits": httpx.Limits(max_connections=limit, max_keepalive_connections=limit)}
        self.sync = httpx.Client(**options, event_hooks={"request": [_patch_request_sync]})
        self.async_ = httpx.AsyncClient(**options, event_hooks={"request": [_patch_request_async]})

    async def close(self):
        await self.async_.aclose()
        self.sync.close()
