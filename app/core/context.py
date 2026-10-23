import asyncio
import time
from contextvars import ContextVar
from dataclasses import dataclass, field

from app.api.schemas import Source


@dataclass
class RunContext:
    tenant: str
    request_id: str
    max_parallel: int
    max_tasks: int
    session_id: str | None = None
    user_id: str | None = None
    events: list[dict] = field(default_factory=list)
    sources: dict[str, Source] = field(default_factory=dict)
    chunk_citations: dict[str, str] = field(default_factory=dict)
    # One request can invoke RAG from a prefetch, a supervisor and a specialist.
    # Exact query reuse must not hit the index again.
    retrieval_cache: dict[str, str] = field(default_factory=dict)
    tasks_started: int = 0
    queue: asyncio.Queue | None = None
    start: float = field(default_factory=time.monotonic)
    slots: asyncio.Semaphore = field(init=False)
    # The service emits final, validated TTS segments after validation.
    stream_voice: bool = False
    voice_name: str | None = None
    voice_input: bool = False
    user_message: str | None = None
    created_draft_ids: list[str] = field(default_factory=list)
    skills_accessed: list[str] = field(default_factory=list)
    actions_invoked: list[str] = field(default_factory=list)
    computed_agents: set[str] = field(default_factory=set)

    def __post_init__(self):
        self.slots = asyncio.Semaphore(self.max_parallel)

    def event(self, event_type: str, /, **data):
        item = {"type": event_type, "elapsed_ms": round((time.monotonic() - self.start) * 1000), **data}
        self.events.append(item)
        if self.queue is not None:
            self.queue.put_nowait(item)

    def cite(self, data: dict) -> Source:
        # All calls occur on the same event loop (never in a worker thread).
        chunk_id = data["chunk_id"]
        existing = self.chunk_citations.get(chunk_id)
        if existing:
            return self.sources[existing]
        citation_id = f"S{len(self.sources) + 1}"
        source = Source(citation_id=citation_id, **data)
        self.sources[citation_id] = source
        self.chunk_citations[chunk_id] = citation_id
        return source

    def emit_token(self, delta: str):
        """Phát token chữ ra SSE, không phát marker nội bộ của mô hình."""
        if not delta or "[[NO_EVIDENCE]]" in delta:
            return
        self.event("token", delta=delta)


current_run: ContextVar[RunContext] = ContextVar("current_run")
