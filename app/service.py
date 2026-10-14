import asyncio
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from app.agents import AgentHarness, validate_answer
from app.calculator import safe_calculate
from app.config import Settings
from app.context import RunContext, current_run
from app.fast_rag import FastRAGExecutor, PreparedRAG
from app.providers import ProviderClients
from app.rag import KnowledgeBases
from app.router import RouterDecision, classify_query_adaptive, rule_based_decision
from app.schemas import ChatRequest, ChatResponse
from app.store import Store
from app.tts import TTSError, ZeroTTS


_ARITHMETIC = re.compile(r"^[0-9+*/%().\s-]+$")


def _simple_calculation(message: str) -> float | int | None:
    expression = message.strip()
    if not expression or not _ARITHMETIC.fullmatch(expression) or not re.search(r"[+*/%-]", expression):
        return None
    try:
        return safe_calculate(expression)
    except (SyntaxError, ValueError):
        return None

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
        run = RunContext(tenant, request_id, self.settings.max_subagents,
                         self.settings.max_tasks, session_id=session_id, queue=queue)
        run.event("start", request_id=request_id, session_id=session_id)
        token = current_run.set(run)
        try:
            calculation = _simple_calculation(request.message) if not request.image else None
            if calculation is not None:
                decision = RouterDecision("fast", "Phép tính số học đơn giản", "rule", 1.0, tier=0)
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

            if calculation is not None:
                route, route_reason = "calculator", "deterministic arithmetic"
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

                    if route == "calculator":
                        raw = f"Kết quả: {calculation}"
                        answer, sources, status, warnings = raw, [], "calculated", []
                    elif route == "fast":
                        if queue is not None:
                            parts = []
                            async for delta in self.fast_rag.stream(
                                tenant, request.message.strip(), history, request.grounded, prepared=prepared,
                            ):
                                parts.append(delta)
                                run.event("token", delta=delta)
                            raw = "".join(parts)
                        else:
                            raw = await self.fast_rag.execute(
                                tenant, request.message.strip(), history, request.grounded, prepared=prepared,
                            )
                    elif route != "calculator":
                        run.event("planning", message=f"Tier {decision.tier if decision.tier > 1 else 2} — Deep Agent: {route_reason}")
                        raw, route, route_reason = await self._deep_or_fallback(
                            request, history, prepared, route_reason,
                        )

                    if route != "calculator":
                        answer, sources, status, warnings = validate_answer(
                            raw, run.sources, request.grounded, request.message,
                        )
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
        await self.tts.close()
        await self.providers.close()
