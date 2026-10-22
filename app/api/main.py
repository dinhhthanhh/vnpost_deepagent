import asyncio
import hmac
import json
import logging
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.api.schemas import (
    ActionCancelRequest,
    ActionConfirmRequest,
    ChatRequest,
    S3IngestRequest,
    SpeechRequest,
)
from app.core.config import Settings
from app.core.rate_limit import check_rate_limit
from app.service import ChatService
from app.tts import TTSError

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, service: ChatService | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        svc = service or ChatService(settings)
        app.state.service = svc
        warmup_task = asyncio.create_task(svc.warmup())
        try:
            yield
        finally:
            if not warmup_task.done():
                warmup_task.cancel()
            await app.state.service.close()

    app = FastAPI(title="VNPost Deep Agent Chatbot", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    if service is not None:
        app.state.service = service

    try:
        from app.a2a.server import mount_a2a_server

        mount_a2a_server(
            app,
            service_provider=lambda: getattr(app.state, "service", None),
            rpc_url="/a2a",
        )
    except Exception as exc:
        logger.warning("Could not mount A2A routes: %s", exc)

    async def tenant(request: Request, x_api_key: str | None = Header(default=None)) -> str:
        # The browser cannot choose its tenant in a query, body, tool argument or file path.
        if x_api_key:
            if not x_api_key.isascii():
                raise HTTPException(401, "API key không hợp lệ")
            for key, value in settings.api_keys.items():
                if hmac.compare_digest(key, x_api_key):
                    return value
            raise HTTPException(401, "API key không hợp lệ")

        forwarded = request.headers.get("x-forwarded-for")
        peer = request.client.host if request.client else ""
        # Anonymous access is strictly allowed ONLY on direct local connections with no external proxy forwarding
        is_direct_local = peer in {"127.0.0.1", "::1", "testclient"} and (
            not forwarded or forwarded.split(",")[0].strip() in {"127.0.0.1", "::1", "testclient"}
        )
        if settings.allow_anonymous and is_direct_local:
            if settings.api_keys:
                return next(iter(settings.api_keys.values()))
            return "vnpost"
        raise HTTPException(
            401, "Cần X-API-Key; truy cập không xác thực chỉ cho phép trên localhost"
        )

    def get_service(request: Request) -> ChatService:
        return request.app.state.service

    @app.get("/api/health")
    @app.get("/healthz")
    async def health():
        return {
            "status": "ok",
            "router_enabled": settings.router_enabled,
            "embedding_provider": settings.embedding_provider,
            "reranker_enabled": settings.reranker_enabled,
            "tts_enabled": settings.tts_enabled,
            "upstream_status": "not_probed",
            "version": "1.0.0",
        }

    @app.get("/.well-known/agent.json")
    @app.get("/a2a/agent_card.json")
    async def get_agent_card():
        card_file = Path("agent_card.json")
        if card_file.is_file():
            return json.loads(card_file.read_text(encoding="utf-8"))
        return {
            "name": "VNPost Deep Agent Mipo",
            "version": "1.0.0",
            "description": "Enterprise VNPost Postal Assistant",
        }

    @app.post("/api/chat")
    async def chat(request: Request, body: ChatRequest, scope=Depends(tenant), svc=Depends(get_service)):
        check_rate_limit(request, bucket_type="chat")
        try:
            return await svc.chat(scope, body)
        except TimeoutError as exc:
            raise HTTPException(
                504, "Quá thời gian xử lý; hãy rút gọn yêu cầu hoặc thử lại"
            ) from exc
        except Exception as exc:
            logger.error("chat_failed error_type=%s", type(exc).__name__)
            raise HTTPException(
                502, "Không hoàn thành được yêu cầu agent; kiểm tra cấu hình LLM/embedding"
            ) from exc

    @app.post("/api/chat/stream")
    async def chat_stream(
        body: ChatRequest, request: Request, scope=Depends(tenant), svc=Depends(get_service)
    ):
        check_rate_limit(request, bucket_type="chat")
        async def events():
            queue = asyncio.Queue()

            async def run():
                try:
                    await svc.chat(scope, body, queue=queue)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("stream_failed error_type=%s", type(exc).__name__)
                    queue.put_nowait(
                        {
                            "type": "error",
                            "message": "Quá thời gian hoặc lỗi dịch vụ agent. Kiểm tra cấu hình rồi thử lại.",
                        }
                    )

            task = asyncio.create_task(run())
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=10)
                    except TimeoutError:
                        if task.done():
                            break
                        yield ": keepalive\n\n"
                        continue
                    yield (
                        "event: "
                        + item["type"]
                        + "\ndata: "
                        + json.dumps(item, ensure_ascii=False)
                        + "\n\n"
                    )
                    if item["type"] in {"done", "error"}:
                        break
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/documents")
    async def documents(
        session_id: str | None = None,
        only_session: bool = False,
        scope=Depends(tenant),
        svc=Depends(get_service),
    ):
        kb = await asyncio.to_thread(svc.knowledge.for_tenant, scope)
        snapshot = kb.snapshot
        records = snapshot.records
        if session_id:
            if only_session:
                records = [r for r in records if str(r.get("session_id", "")) == str(session_id)]
            else:
                records = [
                    r
                    for r in records
                    if r.get("is_global", True) or str(r.get("session_id", "")) == str(session_id)
                ]
        return {
            "documents": [{k: v for k, v in r.items() if k != "stored_name"} for r in records],
            "chunks": len(snapshot.nodes),
            "revision": snapshot.revision,
        }

    @app.post("/api/documents", status_code=201)
    async def upload(
        request: Request, file: UploadFile, scope=Depends(tenant), svc=Depends(get_service)
    ):
        try:
            raw = await file.read(settings.max_upload_bytes + 1)
            if len(raw) > settings.max_upload_bytes:
                raise HTTPException(413, "File vượt giới hạn upload")
            query_params = request.query_params
            session_id = query_params.get("session_id")
            user_id = query_params.get("user_id")
            is_global_val = query_params.get("is_global")
            is_global = None
            if is_global_val is not None:
                is_global = str(is_global_val).lower() in ("true", "1")
            async with svc.ingest_slots:
                kb = await asyncio.to_thread(svc.knowledge.for_tenant, scope)
                result = await asyncio.to_thread(
                    kb.ingest,
                    file.filename or "untitled.txt",
                    raw,
                    is_global=is_global,
                    session_id=session_id,
                    user_id=user_id,
                )
            return {k: v for k, v in result.items() if k != "stored_name"}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("ingest_failed error_type=%s", type(exc).__name__)
            raise HTTPException(
                502, "Không lập chỉ mục được tài liệu; kiểm tra embedding/API"
            ) from exc
        finally:
            await file.close()

    @app.post("/api/documents/verified", status_code=201)
    async def upload_verified(
        file: UploadFile,
        authority: str = "official_public",
        source_url: str = "",
        x_source_admin_key: str | None = Header(default=None),
        scope=Depends(tenant),
        svc=Depends(get_service),
    ):
        """Administrative evidence onboarding; ordinary browser uploads stay untrusted."""
        configured_secret = settings.trusted_ingest_key
        configured_key = (
            configured_secret.get_secret_value()
            if hasattr(configured_secret, "get_secret_value")
            else str(configured_secret)
        )
        if not configured_key:
            raise HTTPException(503, "Chua cau hinh TRUSTED_INGEST_KEY")
        if not x_source_admin_key or not hmac.compare_digest(configured_key, x_source_admin_key):
            raise HTTPException(403, "Khong co quyen nap nguon da xac minh")
        if authority != "official_public":
            raise HTTPException(422, "Only official_public is accepted here")
        parsed = urlsplit(source_url)
        hostname = (parsed.hostname or "").lower()
        allowed = any(
            hostname == domain or hostname.endswith("." + domain)
            for domain in settings.official_domains
        )
        if parsed.scheme != "https" or not allowed:
            raise HTTPException(422, "source_url must be HTTPS on configured vietnampost.vn")
        try:
            raw = await file.read(settings.max_upload_bytes + 1)
            if len(raw) > settings.max_upload_bytes:
                raise HTTPException(413, "File vuot gioi han upload")
            async with svc.ingest_slots:
                kb = await asyncio.to_thread(svc.knowledge.for_tenant, scope)
                result = await asyncio.to_thread(
                    kb.ingest,
                    file.filename or "untitled.txt",
                    raw,
                    is_global=True,
                    authority="official_public",
                    source_url=source_url,
                    issuer="Vietnam Post",
                )
            return {k: v for k, v in result.items() if k != "stored_name"}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except HTTPException:
            raise
        finally:
            await file.close()

    @app.post("/api/documents/s3", status_code=201)
    async def ingest_from_s3(
        body: S3IngestRequest, scope=Depends(tenant), svc=Depends(get_service)
    ):
        """Đồng bộ và nạp tài liệu từ S3 (Presigned GET URL hoặc S3 Bucket + Key)."""
        from urllib.parse import urlparse

        import httpx

        raw_bytes = b""
        filename = body.filename

        if body.url:
            parsed = urlparse(body.url)
            if parsed.scheme not in {"http", "https"}:
                raise HTTPException(422, "URL phải là http hoặc https")
            if not filename:
                filename = Path(parsed.path).name or "s3_document.pdf"
            if settings.s3_allowed_domains:
                try:
                    from app.api.schemas import validate_safe_url

                    validate_safe_url(body.url, allowed_domains=settings.s3_allowed_domains)
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
            try:
                chunks = []
                total_bytes = 0
                max_bytes = settings.max_upload_bytes
                timeout_config = httpx.Timeout(30.0, connect=10.0)
                async with httpx.AsyncClient(
                    timeout=timeout_config, follow_redirects=False
                ) as client:
                    async with client.stream("GET", body.url) as resp:
                        if resp.status_code != 200:
                            raise HTTPException(
                                502,
                                f"Không tải được file từ S3 URL, HTTP status: {resp.status_code}",
                            )
                        content_len = resp.headers.get("content-length")
                        if content_len:
                            try:
                                if int(content_len) > max_bytes:
                                    raise HTTPException(
                                        413, f"File vượt quá dung lượng tối đa ({max_bytes} bytes)"
                                    )
                            except ValueError:
                                pass
                        async for chunk in resp.aiter_bytes(chunk_size=65536):
                            total_bytes += len(chunk)
                            if total_bytes > max_bytes:
                                raise HTTPException(
                                    413, f"File vượt quá dung lượng tối đa ({max_bytes} bytes)"
                                )
                            chunks.append(chunk)
                raw_bytes = b"".join(chunks)
            except Exception as exc:
                if isinstance(exc, HTTPException):
                    raise
                raise HTTPException(502, f"Lỗi kết nối khi tải tài liệu từ S3 URL: {exc}") from exc
        elif body.bucket and body.key:
            allowed_buckets = [
                b.strip() for b in (settings.allowed_s3_buckets or "").split(",") if b.strip()
            ]
            if not allowed_buckets:
                raise HTTPException(
                    403,
                    "Truy cập trực tiếp qua S3 bucket/key chưa được cấu hình cho phép (ALLOWED_S3_BUCKETS). Vui lòng sử dụng presigned URL.",
                )
            if body.bucket not in allowed_buckets:
                raise HTTPException(
                    403,
                    f"Bucket '{body.bucket}' không nằm trong danh sách được phép truy cập (allowed_s3_buckets).",
                )

            if not filename:
                filename = Path(body.key).name or "s3_document.pdf"
            try:
                import boto3

                s3_client = boto3.client("s3")
                resp = await asyncio.to_thread(
                    s3_client.get_object, Bucket=body.bucket, Key=body.key
                )
                content_len = resp.get("ContentLength")
                max_bytes = settings.max_upload_bytes
                if content_len is not None and int(content_len) > max_bytes:
                    raise HTTPException(413, f"File vượt quá dung lượng tối đa ({max_bytes} bytes)")

                body_stream = resp["Body"]
                chunks = []
                total_bytes = 0
                while True:
                    chunk = await asyncio.to_thread(body_stream.read, 65536)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        raise HTTPException(
                            413, f"File vượt quá dung lượng tối đa ({max_bytes} bytes)"
                        )
                    chunks.append(chunk)
                raw_bytes = b"".join(chunks)
            except ImportError:
                raise HTTPException(
                    501, "Server chưa cài đặt boto3; hãy dùng S3 presigned URL hoặc cài boto3"
                )
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(502, f"Lỗi đọc từ S3 bucket/key: {exc}") from exc
        else:
            raise HTTPException(422, "Cần cung cấp url (presigned) hoặc bucket + key")

        if len(raw_bytes) > settings.max_upload_bytes:
            raise HTTPException(413, "File vượt giới hạn kích thước upload")

        try:
            async with svc.ingest_slots:
                kb = await asyncio.to_thread(svc.knowledge.for_tenant, scope)
                result = await asyncio.to_thread(
                    kb.ingest,
                    filename,
                    raw_bytes,
                    is_global=body.is_global,
                    session_id=body.session_id,
                    user_id=body.user_id,
                    authority=body.authority,
                    source_url=body.source_url
                    or (f"s3://{body.bucket}/{body.key}" if body.bucket and body.key else body.url),
                    issuer=body.issuer or "Vietnam Post",
                )
            return {k: v for k, v in result.items() if k != "stored_name"}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("s3_ingest_failed error_type=%s", type(exc).__name__)
            raise HTTPException(502, "Không lập chỉ mục được tài liệu S3") from exc

    @app.delete("/api/documents/{document_id}")
    async def remove(document_id: str, scope=Depends(tenant), svc=Depends(get_service)):
        if not re.fullmatch(r"[a-f0-9]{64}", document_id):
            raise HTTPException(422, "ID không hợp lệ")
        async with svc.ingest_slots:
            kb = await asyncio.to_thread(svc.knowledge.for_tenant, scope)
            if not await asyncio.to_thread(kb.remove, document_id):
                raise HTTPException(404, "Không tìm thấy tài liệu")
        return {"deleted": document_id}

    @app.get("/api/sessions")
    async def list_sessions(limit: int = 50, scope=Depends(tenant), svc=Depends(get_service)):
        return {"sessions": await asyncio.to_thread(svc.store.list_sessions, scope, limit)}

    @app.get("/api/sessions/{session_id}")
    async def history(session_id: str, scope=Depends(tenant), svc=Depends(get_service)):
        return {
            "session_id": str(session_id),
            "messages": await asyncio.to_thread(svc.store.history, scope, str(session_id)),
        }

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(
        session_id: str,
        background_tasks: BackgroundTasks,
        scope=Depends(tenant),
        svc=Depends(get_service),
    ):
        sid = str(session_id).strip()
        await asyncio.to_thread(svc.store.delete_session, scope, sid)
        if settings.postgres_url or settings.checkpointer_type == "postgres":
            from app.core.postgres import purge_session_from_postgres

            await asyncio.to_thread(
                purge_session_from_postgres, scope, sid, settings.postgres_url
            )

        async def cleanup_session_documents():
            try:
                async with svc.ingest_slots:
                    kb = await asyncio.to_thread(svc.knowledge.for_tenant, scope)
                    removed = await asyncio.to_thread(kb.remove_session, sid)
                logger.info(
                    "session_documents_removed tenant=%s session_id=%s count=%s",
                    scope,
                    sid,
                    removed,
                )
            except Exception:
                logger.exception(
                    "session_document_cleanup_failed tenant=%s session_id=%s", scope, sid
                )

        # Rebuilding the RAG snapshot can take seconds; it must not delay the UI.
        background_tasks.add_task(cleanup_session_documents)
        return {
            "deleted": sid,
            "storage_deleted": True,
            "document_cleanup": "scheduled",
            "message": "Đã xóa hoàn toàn cuộc trò chuyện khỏi bộ lưu trữ.",
        }

    @app.get("/api/replies/{request_id}")
    async def reply(request_id: str, scope=Depends(tenant), svc=Depends(get_service)):
        data = await asyncio.to_thread(svc.store.reply, scope, request_id)
        if not data:
            raise HTTPException(404, "Không tìm thấy câu trả lời")
        return data

    @app.get("/api/tts/voices")
    async def voices(scope=Depends(tenant), svc=Depends(get_service)):
        try:
            return await svc.tts.voices()
        except TTSError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.post("/api/tts")
    async def speech(body: SpeechRequest, scope=Depends(tenant), svc=Depends(get_service)):
        try:
            url = await svc.save_speech(
                scope,
                body.text,
                body.voice,
                body.mode,
                cfg_scale=body.cfg_scale,
                audio_temperature=body.audio_temperature,
                text_temperature=body.text_temperature,
                audio_topk=body.audio_topk,
                audio_topp=body.audio_topp,
                audio_repetition_penalty=body.audio_repetition_penalty,
                speed=body.speed,
            )
            return {"audio_url": url}
        except TTSError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.post("/api/tts/stream")
    async def speech_stream(
        request: Request, body: SpeechRequest, scope=Depends(tenant), svc=Depends(get_service)
    ):
        check_rate_limit(request, bucket_type="voice")
        try:
            upstream = await svc.tts.open_stream(
                body.text,
                body.voice,
                cfg_scale=body.cfg_scale,
                audio_temperature=body.audio_temperature,
                text_temperature=body.text_temperature,
                audio_topk=body.audio_topk,
                audio_topp=body.audio_topp,
                audio_repetition_penalty=body.audio_repetition_penalty,
                speed=body.speed,
            )
        except TTSError as exc:
            raise HTTPException(502, str(exc)) from exc

        async def chunks():
            size = 0
            try:
                async with asyncio.timeout(settings.tts_timeout_seconds):
                    async for chunk in upstream.aiter_bytes():
                        size += len(chunk)
                        if size > settings.max_audio_bytes:
                            raise TTSError("Luồng âm thanh vượt giới hạn kích thước")
                        yield chunk
            finally:
                await upstream.aclose()

        # No invented TTFA; real playback is measured by the frontend on the first PCM buffer.
        return StreamingResponse(
            chunks(), media_type="audio/wav", headers={"Cache-Control": "no-store"}
        )

    @app.get("/api/audio/{audio_id}")
    async def audio(audio_id: str, scope=Depends(tenant), svc=Depends(get_service)):
        if not re.fullmatch(r"[a-f0-9]{32}", audio_id):
            raise HTTPException(404, "Không tìm thấy âm thanh")
        path = await asyncio.to_thread(
            svc.store.audio_path, scope, audio_id, settings.audio_ttl_seconds
        )
        if not path:
            raise HTTPException(404, "Âm thanh không tồn tại hoặc đã hết hạn")
        return FileResponse(
            path,
            media_type="audio/wav",
            filename="answer.wav",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/voice/transcribe")
    async def transcribe_voice(
        request: Request,
        file: UploadFile,
        language: str = "vi",
        scope=Depends(tenant),
        svc=Depends(get_service),
    ):
        check_rate_limit(request, bucket_type="voice")
        """Tiếp nhận tệp ghi âm giọng nói (WAV/WebM/OGG/MP3) và chuyển đổi thành văn bản tiếng Việt (STT)."""
        from app.tts import STTError

        try:
            raw_audio = await file.read(settings.max_audio_bytes + 1)
            if len(raw_audio) > settings.max_audio_bytes:
                raise HTTPException(413, "Tệp âm thanh vượt quá giới hạn dung lượng cho phép")
            if not raw_audio:
                raise HTTPException(422, "Tệp âm thanh trống")

            result = await svc.transcribe_speech(
                raw_audio,
                filename=file.filename or "audio.webm",
                content_type=file.content_type or "audio/webm",
                language=language,
            )
            return result
        except STTError as exc:
            raise HTTPException(502, str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("stt_transcribe_failed error_type=%s", type(exc).__name__)
            raise HTTPException(502, f"Lỗi chuyển đổi giọng nói: {exc}") from exc
        finally:
            await file.close()

    @app.get("/api/actions/orders")
    async def get_orders(session_id: str | None = None, scope=Depends(tenant)):
        """Tra cứu danh sách đơn hàng, đơn nháp và phiếu khiếu nại trong phiên (session)."""
        from app.agents.postal_actions import get_session_drafts

        return get_session_drafts(session_id=session_id, tenant=scope)

    @app.post("/api/actions/confirm")
    async def confirm_action(body: ActionConfirmRequest, scope=Depends(tenant)):
        """Xác nhận trực tiếp một bản nháp đơn hàng hoặc khiếu nại (Human-in-the-Loop approval)."""
        from app.agents.postal_actions import confirm_booking, confirm_complaint

        if body.action_type == "booking":
            res_str = confirm_booking(body.draft_id, confirmed_by_user=True, tenant=scope)
        elif body.action_type == "complaint":
            res_str = confirm_complaint(body.draft_id, confirmed_by_user=True, tenant=scope)
        else:
            raise HTTPException(
                400, "action_type không hợp lệ (chấp nhận 'booking' hoặc 'complaint')"
            )
        data = json.loads(res_str)
        if data.get("status") == "error":
            msg = data.get("message", "")
            if "không có quyền" in msg.lower():
                raise HTTPException(403, msg)
            if "không tìm thấy" in msg.lower():
                raise HTTPException(404, msg)
        return data

    @app.post("/api/actions/cancel")
    async def cancel_action(body: ActionCancelRequest, scope=Depends(tenant)):
        """Hủy trực tiếp một đơn hàng hoặc khiếu nại."""
        from app.agents.postal_actions import cancel_booking, cancel_complaint

        if body.action_type == "booking":
            res_str = cancel_booking(
                item_code_or_draft_id=body.target_id,
                reason=body.reason,
                verification_phone=body.verification_phone,
                tenant=scope,
                session_id=body.session_id,
                is_rest=True,
            )
        elif body.action_type == "complaint":
            res_str = cancel_complaint(
                ticket_id_or_draft_id=body.target_id,
                reason=body.reason,
                verification_phone=body.verification_phone,
                tenant=scope,
                session_id=body.session_id,
                is_rest=True,
            )
        else:
            raise HTTPException(
                400, "action_type không hợp lệ (chấp nhận 'booking' hoặc 'complaint')"
            )
        data = json.loads(res_str)
        if data.get("status") == "error":
            msg = data.get("message", "")
            if "không có quyền" in msg.lower():
                raise HTTPException(403, msg)
            if "không tìm thấy" in msg.lower():
                raise HTTPException(404, msg)
        elif data.get("status") in {"requires_verification", "verification_failed"}:
            raise HTTPException(400, data.get("message", "Yêu cầu xác minh thông tin chủ sở hữu"))
        return data

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
