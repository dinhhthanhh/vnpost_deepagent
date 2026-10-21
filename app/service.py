import asyncio
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from app.agents import AgentHarness, validate_answer
from app.agents.signals import analyze
from app.api.schemas import ChatRequest, ChatResponse
from app.core.config import Settings
from app.core.context import RunContext, current_run
from app.core.prompts import NO_EVIDENCE_MARKER, NO_EVIDENCE_TEMPLATE
from app.core.providers import ProviderClients
from app.domain.terminology import postprocess_func
from app.rag import KnowledgeBases
from app.rag.fast_rag import FastRAGExecutor, PreparedRAG
from app.rag.store import Store
from app.router import RouterDecision, classify_query_adaptive, rule_based_decision
from app.router.fastpath import local_answer
from app.tts import STTError, SpeechTranscriber, TTSError, ZeroTTS

logger = logging.getLogger(__name__)


class SafeStreamBuffer:
    """Bộ đệm token streaming giữ lại và chuyển đổi cờ [[NO_EVIDENCE]] tránh rò rỉ ra giao diện."""

    def __init__(self, emit_fn, target_marker: str = NO_EVIDENCE_MARKER, replacement: str = NO_EVIDENCE_TEMPLATE):
        self.emit_fn = emit_fn
        self.target = target_marker
        self.replacement = replacement
        self.buffer = ""
        self.matched = False

    def push(self, delta: str):
        if self.matched:
            return
        self.buffer += delta
        # Nếu buffer đang là tiền tố của [[NO_EVIDENCE]] (như "[", "[[", "[[NO", ...)
        if self.target.startswith(self.buffer):
            if self.buffer == self.target:
                self.matched = True
                self.emit_fn(self.replacement)
                self.buffer = ""
            return
        # Nếu buffer không khớp tiền tố, xả toàn bộ buffer ra giao diện
        self.emit_fn(self.buffer)
        self.buffer = ""

    def flush(self):
        if self.buffer and not self.matched:
            self.emit_fn(self.buffer)
            self.buffer = ""



class ChatService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = Store(settings.data_dir)
        self.providers = ProviderClients(settings)
        self.knowledge = KnowledgeBases(settings, self.providers)
        self.harness = AgentHarness(settings, self.knowledge, self.providers)
        self.fast_rag = FastRAGExecutor(settings, self.knowledge, self.providers)
        self.tts = ZeroTTS(settings)
        self.stt = SpeechTranscriber(settings)
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

    async def save_speech(self, tenant: str, text: str, voice=None, mode=None, **kwargs) -> str:
        data = await self.tts.synthesize(text, voice, mode, **kwargs)
        audio_id = uuid.uuid4().hex
        folder = self.settings.data_dir.resolve() / "audio" / tenant
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (audio_id + ".wav")
        await asyncio.to_thread(path.write_bytes, data)
        await asyncio.to_thread(self.store.save_audio, tenant, audio_id, path)
        await asyncio.to_thread(self.store.prune_audio, self.settings.audio_ttl_seconds)
        return "/api/audio/" + audio_id

    async def transcribe_speech(
        self,
        audio_bytes: bytes,
        filename: str = "audio.webm",
        content_type: str = "audio/webm",
        language: str = "vi",
    ) -> dict[str, Any]:
        """Chuyển đổi âm thanh ghi âm thành văn bản tiếng Việt qua STT."""
        return await self.stt.transcribe(
            audio_bytes,
            filename=filename,
            content_type=content_type,
            language=language,
        )

    async def _deep_or_fallback(
        self,
        request: ChatRequest,
        history: list[dict],
        prepared: PreparedRAG | None,
        route_reason: str,
    ) -> tuple[str, str, str]:
        """Bound Deep Agent to one budget and return Tier 1 on timeout.

        ``prepared`` is populated when a Tier-1 source gate escalates, avoiding
        a second identical retrieval before the deep graph starts.
        """
        run = current_run.get()
        try:
            async with asyncio.timeout(self.settings.deep_timeout):
                raw = await self.harness.invoke(
                    request.message.strip(), history, request.grounded, request.image,
                    prefetched_evidence=prepared.evidence_json if prepared and request.grounded else None,
                    thread_id=f"{run.tenant}:{run.session_id}:{run.request_id}",
                    location=request.location,
                )
            return raw, "deep", route_reason
        except TimeoutError:
            run.event("deep_timeout", timeout_seconds=self.settings.deep_timeout, fallback="fast")
            if prepared is None:
                prepared = await self.fast_rag.prepare(
                    run.tenant, request.message.strip(), history, request.grounded,
                )
            raw = await self.fast_rag.execute(
                run.tenant, request.message.strip(), history, request.grounded, prepared=prepared,
            )
            return raw, "fast_fallback", route_reason + "; hết ngân sách deep, trả lời theo Tier 1"

    async def chat(self, tenant: str, request: ChatRequest, queue: asyncio.Queue | None = None) -> ChatResponse:
        started = time.monotonic()
        request_id, session_id = uuid.uuid4().hex, str(request.session_id or uuid.uuid4())
        run = RunContext(
            tenant,
            request_id,
            self.settings.max_subagents,
            self.settings.max_tasks,
            session_id=session_id,
            queue=queue,
            stream_voice=bool(request.voice and request.stream_voice),
            voice_name=request.voice_name or self.settings.tts_voice,
        )
        run.event("start", request_id=request_id, session_id=session_id)
        token = current_run.set(run)
        try:
            shortcut = local_answer(request.message, chitchat=analyze(request.message).chitchat) if not request.image else None
            if request.image and not self.settings.supports_vision:
                from app.router.fastpath import LocalAnswer
                shortcut = LocalAnswer(
                    kind="chitchat",
                    text=(
                        f"Mô hình ngôn ngữ hiện tại ({self.settings.llm_model}) là mô hình chuyên xử lý văn bản, "
                        "chưa hỗ trợ nhận diện hình ảnh trực tiếp (Vision/OCR). "
                        "Vui lòng nhập nội dung câu hỏi hoặc mã vận đơn bằng văn bản để tôi hỗ trợ bạn tốt nhất nhé!"
                    ),
                )
            if shortcut is not None:
                decision = RouterDecision("fast", "Đường tắt cục bộ không gọi LLM", "rule", 1.0, tier=0)
            elif request.mode == "fast":
                decision = RouterDecision("fast", "Đường nhanh do người dùng yêu cầu", "rule", 1.0, tier=1)
            elif request.mode == "deep":
                decision = RouterDecision("deep", "Đường sâu do người dùng yêu cầu", "rule", 1.0, tier=2)
            elif self.settings.router_enabled:
                # This is rules/retrieval-first by default; its optional LLM experiment
                # remains disabled unless LLM_ROUTER_ENABLED=true.
                decision = await classify_query_adaptive(
                    self.settings, self.providers, request.message, request.image,
                )
            else:
                decision = rule_based_decision(
                    request.message, request.image, max_characters=self.settings.router_max_characters,
                )

            if shortcut is not None:
                route = "calculator" if shortcut.kind == "calc" else "local"
                route_reason = f"local {shortcut.kind}"
            else:
                route, route_reason = decision.route, decision.reason
            run.event("router_decision", route=route, tier=decision.tier, reason=route_reason,
                      strategy=decision.strategy, confidence=decision.confidence)

            async with asyncio.timeout(self.settings.request_timeout):
                async with self.active, self.session_lock(tenant, session_id):
                    history = await asyncio.to_thread(self.store.history, tenant, session_id)
                    prepared: PreparedRAG | None = None
                    # Tier 1 is the default. Its evidence is what decides a low-evidence
                    # escalation, instead of an LLM classifier guessing from wording.
                    if route == "fast":
                        run.event("planning", message=f"Tier 1 — Direct RAG: {route_reason}")
                        prepared = await self.fast_rag.prepare(
                            tenant, request.message.strip(), history, request.grounded,
                        )
                        if request.mode == "auto" and request.grounded and not prepared.has_sufficient_evidence(self.settings.fast_min_sources, self.settings.fast_min_retrieval_score):
                            route = "deep"
                            route_reason += "; cổng nguồn Tier 1 không đủ bằng chứng"
                            run.event("source_gate", status="escalate", source_count=prepared.source_count,
                                      required=self.settings.fast_min_sources, top_retrieval_score=prepared.top_retrieval_score, min_retrieval_score=self.settings.fast_min_retrieval_score)
                            run.event("route_escalated", from_tier=1, to_tier=2, reason="insufficient_evidence")
                        else:
                            run.event("source_gate", status="pass", source_count=prepared.source_count,
                                      required=self.settings.fast_min_sources, top_retrieval_score=prepared.top_retrieval_score, min_retrieval_score=self.settings.fast_min_retrieval_score)

                    if route in {"calculator", "local"}:
                        raw = shortcut.text
                        status = "computed" if shortcut.kind in {"calc", "date"} else "unverified"
                        answer, sources, warnings = raw, [], []
                        if queue is not None:
                            for chunk in re.findall(r"\S+\s*|\s+", raw):
                                run.emit_token(chunk)
                    elif route == "fast":
                        if queue is not None:
                            parts = []
                            safe_buf = SafeStreamBuffer(run.emit_token)
                            async for delta in self.fast_rag.stream(
                                tenant, request.message.strip(), history, request.grounded, prepared=prepared,
                            ):
                                parts.append(delta)
                                safe_buf.push(delta)
                            safe_buf.flush()
                            raw = "".join(parts)
                        else:
                            raw = await self.fast_rag.execute(
                                tenant, request.message.strip(), history, request.grounded, prepared=prepared,
                            )
                    elif route not in {"calculator", "local"}:
                        run.event("planning", message=f"Tier {decision.tier if decision.tier > 1 else 2} — Deep Agent: {route_reason}")
                        raw, route, route_reason = await self._deep_or_fallback(
                            request, history, prepared, route_reason,
                        )
                        if queue is not None:
                            safe_buf = SafeStreamBuffer(run.emit_token)
                            for chunk in re.findall(r"\S+\s*|\s+", raw):
                                safe_buf.push(chunk)
                            safe_buf.flush()

                    if route not in {"calculator", "local"}:
                        answer, sources, status, warnings = validate_answer(
                            raw, run.sources, request.grounded, request.message,
                        )
                    answer = postprocess_func(answer)
                    await asyncio.to_thread(
                        self.store.save_turn, tenant, session_id, request.message, answer,
                        self.settings.max_history,
                        {"request_id": request_id, "sources": [s.model_dump() for s in sources],
                         "grounding_status": status, "route": route, "route_reason": route_reason,
                         "elapsed_ms": round((time.monotonic() - started) * 1000)},
                    )
            result = ChatResponse(request_id=request_id, session_id=session_id, answer=answer,
                                  sources=sources, grounding_status=status,
                                  route=route, route_reason=route_reason,
                                  elapsed_ms=round((time.monotonic() - started) * 1000),
                                  events=run.events, warnings=warnings)
            # Deliver validated text before awaiting an optional, slow TTS synthesis.
            await asyncio.to_thread(self.store.save_reply, tenant, request_id, result.model_dump())
            if queue is not None:
                queue.put_nowait({"type": "answer", "data": result.model_dump()})
            if request.voice and request.stream_voice and queue is not None:
                from app.tts import spoken_text
                clean_speech = spoken_text(answer)
                if clean_speech:
                    raw_parts = [p.strip() for p in re.split(r"(?<=[.!?;])\s+|\n+", clean_speech) if p.strip()]
                    segments, current = [], ""
                    for part in raw_parts:
                        current = f"{current} {part}".strip() if current else part
                        if len(current) >= 35:
                            segments.append(current)
                            current = ""
                    if current:
                        segments.append(current)
                    voice_target = request.voice_name or self.settings.tts_voice
                    for idx, seg in enumerate(segments):
                        run.event("tts_segment", index=idx, total=len(segments), text=seg, voice=voice_target)
            if request.voice and not request.stream_voice:
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
        await self.harness.close()
        await self.tts.close()
        await self.providers.close()
