import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from app.agents import AgentHarness, validate_answer
from app.config import Settings
from app.context import RunContext, current_run
from app.fast_rag import FastRAGExecutor
from app.providers import ProviderClients
from app.rag import KnowledgeBases
from app.router import classify_query
from app.schemas import ChatRequest, ChatResponse
from app.store import Store
from app.tts import TTSError, ZeroTTS

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = Store(settings.data_dir)
        self.providers = ProviderClients(settings)
        self.knowledge = KnowledgeBases(settings, self.providers)
        self.harness = AgentHarness(settings, self.knowledge, self.providers)
        self.fast_rag = FastRAGExecutor(settings, self.knowledge, self.providers)
        self.tts = ZeroTTS(settings)
        self.active = asyncio.Semaphore(settings.max_active_requests)
        self.ingest_slots = asyncio.Semaphore(2)
        self.session_locks: dict[tuple[str, str], tuple[asyncio.Lock, int]] = {}

    @asynccontextmanager
    async def session_lock(self, tenant, session_id):
        key = (tenant, session_id)
        lock, users = self.session_locks.get(key, (asyncio.Lock(), 0))
        self.session_locks[key] = (lock, users + 1)
        try:
            async with lock:
                yield
        finally:
            _, users = self.session_locks[key]
            if users == 1:
                del self.session_locks[key]
            else:
                self.session_locks[key] = (lock, users - 1)

    async def save_speech(self, tenant: str, text: str, voice=None, mode=None) -> str:
        data = await self.tts.synthesize(text, voice, mode)
        audio_id = uuid.uuid4().hex
        folder = self.settings.data_dir.resolve() / "audio" / tenant
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (audio_id + ".wav")
        await asyncio.to_thread(path.write_bytes, data)
        await asyncio.to_thread(self.store.save_audio, tenant, audio_id, path)
        await asyncio.to_thread(self.store.prune_audio, self.settings.audio_ttl_seconds)
        return "/api/audio/" + audio_id

    async def chat(self, tenant: str, request: ChatRequest, queue: asyncio.Queue | None = None) -> ChatResponse:
        started = time.monotonic()
        request_id, session_id = uuid.uuid4().hex, str(request.session_id or uuid.uuid4())
        run = RunContext(tenant, request_id, self.settings.max_subagents,
                         self.settings.max_tasks, session_id=session_id, queue=queue)
        run.event("start", request_id=request_id, session_id=session_id)
        token = current_run.set(run)
        try:
            # Xác định tuyến xử lý: Fast Path (Direct RAG) vs Deep Agent Path
            if request.mode == "fast":
                route, route_reason = "fast", "Đường nhanh (Fast Direct RAG) do người dùng yêu cầu"
            elif request.mode == "deep":
                route, route_reason = "deep", "Đường sâu (Deep Multi-Agent) do người dùng yêu cầu"
            elif not self.settings.router_enabled:
                route, route_reason = "deep", "Đường sâu (Deep Agent Harness)"
            else:
                route, route_reason = classify_query(request.message, request.image)

            run.event("router_decision", route=route, reason=route_reason)

            # Covers capacity queue, session queue and the complete reasoning run.
            async with asyncio.timeout(self.settings.request_timeout):
                async with self.active, self.session_lock(tenant, session_id):
                    history = await asyncio.to_thread(self.store.history, tenant, session_id)
                    if route == "fast":
                        run.event("planning", message=f"Đường nhanh (Direct RAG): {route_reason}")
                        raw = await self.fast_rag.execute(tenant, request.message.strip(), history, request.grounded)
                    else:
                        run.event("planning", message=f"Đường sâu (Deep Agent): {route_reason}")
                        raw = await self.harness.invoke(request.message.strip(), history, request.grounded, request.image)
                    answer, sources, status, warnings = validate_answer(raw, run.sources, request.grounded, request.message)
                    await asyncio.to_thread(self.store.save_turn, tenant, session_id,
                                            request.message, answer, self.settings.max_history,
                                            {"request_id": request_id, "sources": [s.model_dump() for s in sources],
                                             "grounding_status": status, "route": route, "route_reason": route_reason,
                                             "elapsed_ms": round((time.monotonic() - started) * 1000)})
            result = ChatResponse(request_id=request_id, session_id=session_id, answer=answer,
                                  sources=sources, grounding_status=status,
                                  route=route, route_reason=route_reason,
                                  elapsed_ms=round((time.monotonic() - started) * 1000),
                                  events=run.events, warnings=warnings)
            # Save and deliver validated text BEFORE awaiting TTS.
            await asyncio.to_thread(self.store.save_reply, tenant, request_id, result.model_dump())
            if queue is not None:
                queue.put_nowait({"type": "answer", "data": result.model_dump()})
            if request.voice:
                run.event("speech_start")
                try:
                    result.audio_url = await self.save_speech(tenant, answer, request.voice_name)
                    run.event("speech_ready", audio_url=result.audio_url)
                except (TTSError, OSError) as exc:
                    warning = str(exc) if isinstance(exc, TTSError) else "Không lưu được âm thanh; câu trả lời chữ vẫn khả dụng."
                    result.warnings.append(warning)
                    run.event("speech_error", message=warning)
            result.elapsed_ms = round((time.monotonic() - started) * 1000)
            result.events = list(run.events)
            await asyncio.to_thread(self.store.save_reply, tenant, request_id, result.model_dump())
            logger.info("chat_complete request_id=%s tenant=%s ms=%s sources=%s tasks=%s route=%s",
                        request_id, tenant, result.elapsed_ms, len(sources), run.tasks_started, route)
            if queue is not None:
                queue.put_nowait({"type": "done", "data": result.model_dump()})
            return result
        finally:
            current_run.reset(token)

    async def close(self):
        await self.tts.close()
        await self.providers.close()
