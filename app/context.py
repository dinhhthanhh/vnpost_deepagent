import asyncio
import time
from contextvars import ContextVar
from dataclasses import dataclass, field

from app.schemas import Source


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
    tasks_started: int = 0
    queue: asyncio.Queue | None = None
    start: float = field(default_factory=time.monotonic)
    slots: asyncio.Semaphore = field(init=False)

    def __post_init__(self):
        self.slots = asyncio.Semaphore(self.max_parallel)

    def event(self, kind: str, **data):
        item = {"type": kind, "elapsed_ms": round((time.monotonic() - self.start) * 1000), **data}
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


current_run: ContextVar[RunContext] = ContextVar("current_run")
