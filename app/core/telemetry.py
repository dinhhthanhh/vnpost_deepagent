"""OpenTelemetry & Tracing helpers for VNPost Deep Agent."""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from opentelemetry import baggage, trace
    from opentelemetry.context import Context

    OTEL_AVAILABLE = True
    _tracer = trace.get_tracer("vnpost_deepagent")
except ImportError:
    OTEL_AVAILABLE = False
    _tracer = None
    Context = Any


def _clean_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Filter metadata: drop private keys (prefixed with _), otel_context, and None values."""
    return {
        key: value
        for key, value in (meta or {}).items()
        if not key.startswith("_") and key != "otel_context" and value is not None
    }


def set_request_attributes(span: Any, meta: dict[str, Any] | None) -> None:
    """Set request identification attributes on an OpenTelemetry span."""
    if not span or not hasattr(span, "set_attribute"):
        return
    cleaned = _clean_meta(meta)
    session_id = cleaned.get("session_id")
    user_id = cleaned.get("user_id")
    if session_id:
        span.set_attribute("session.id", str(session_id))
    if user_id:
        span.set_attribute("user.id", str(user_id))
    for key, value in cleaned.items():
        if isinstance(value, (str, bool, int, float)):
            span.set_attribute(f"meta.{key}", value)
        else:
            span.set_attribute(f"meta.{key}", json.dumps(value, ensure_ascii=False, default=str))


def add_request_baggage(ctx: Any, meta: dict[str, Any] | None) -> Any:
    """Inject session.id and user.id into OTel baggage."""
    if not OTEL_AVAILABLE or ctx is None:
        return ctx
    session_id = (meta or {}).get("session_id")
    user_id = (meta or {}).get("user_id")
    try:
        if session_id:
            ctx = baggage.set_baggage("session.id", str(session_id), ctx)
        if user_id:
            ctx = baggage.set_baggage("user.id", str(user_id), ctx)
    except Exception as exc:
        logger.debug("Failed to set baggage: %s", exc)
    return ctx
