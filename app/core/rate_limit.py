"""Production Sliding-Window Rate Limiter for VNPost Deep Agent API.

Provides:
- Thread-safe sliding window tracking per client IP / Tenant.
- Separate buckets for expensive endpoints (chat/LLM, voice/TTS/STT, and general).
- Automatic cleanup of stale IP records to prevent memory leaks.
- Clear HTTP 429 response with Retry-After header.
"""

from __future__ import annotations

import collections
import logging
import threading
import time
from typing import Any

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


class SlidingWindowRateLimiter:
    """In-memory sliding window rate limiter."""

    def __init__(self, cleanup_interval_seconds: float = 300.0):
        self._buckets: dict[str, collections.deque[float]] = {}
        self._lock = threading.Lock()
        self._cleanup_interval = cleanup_interval_seconds
        self._last_cleanup = time.monotonic()

    def check(
        self,
        key: str,
        max_requests: int,
        window_seconds: float = 60.0,
    ) -> tuple[bool, int, float]:
        """Check if request for key is allowed under rate limit.

        Returns:
            (allowed: bool, current_count: int, retry_after_seconds: float)
        """
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            # Periodic cleanup of completely stale keys
            if now - self._last_cleanup > self._cleanup_interval:
                self._cleanup_stale_keys(cutoff)
                self._last_cleanup = now

            timestamps = self._buckets.setdefault(key, collections.deque())

            # Drop timestamps outside the window
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            count = len(timestamps)
            if count >= max_requests:
                # Calculate remaining time until the oldest request expires
                oldest = timestamps[0]
                retry_after = max(1.0, window_seconds - (now - oldest))
                return False, count, retry_after

            timestamps.append(now)
            return True, count + 1, 0.0

    def _cleanup_stale_keys(self, cutoff: float) -> None:
        stale = [
            k
            for k, deq in self._buckets.items()
            if not deq or deq[-1] <= cutoff
        ]
        for k in stale:
            self._buckets.pop(k, None)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


# Global singleton rate limiter
_GLOBAL_LIMITER = SlidingWindowRateLimiter()


def get_client_identifier(request: Request) -> str:
    """Extract reliable client identifier taking reverse proxies into account."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # First IP in X-Forwarded-For is the originating client IP
        return forwarded.split(",")[0].strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    if request.client and request.client.host:
        return request.client.host

    return "unknown-client"


def check_rate_limit(
    request: Request,
    bucket_type: str = "general",
    max_requests: int | None = None,
    window_seconds: float = 60.0,
) -> None:
    """Enforce rate limit for the given request. Raises HTTPException(429) if exceeded."""
    settings = getattr(request.app.state, "settings", None)
    if settings and not getattr(settings, "rate_limit_enabled", True):
        return

    # Determine limits
    if max_requests is None and settings:
        if bucket_type == "chat":
            max_requests = getattr(settings, "rate_limit_chat_rpm", 60)
        elif bucket_type == "voice":
            max_requests = getattr(settings, "rate_limit_voice_rpm", 40)
        else:
            max_requests = getattr(settings, "rate_limit_general_rpm", 120)
    elif max_requests is None:
        max_requests = 60

    # Rate limiting key is client_id + bucket
    client_id = get_client_identifier(request)
    # Check if API key exists in header, use it to group tenant requests
    api_key = request.headers.get("x-api-key")
    if api_key:
        rate_key = f"key:{api_key[:8]}:{bucket_type}"
    else:
        rate_key = f"ip:{client_id}:{bucket_type}"

    allowed, current_count, retry_after = _GLOBAL_LIMITER.check(
        key=rate_key,
        max_requests=max_requests,
        window_seconds=window_seconds,
    )

    if not allowed:
        retry_int = int(retry_after) or 1
        logger.warning(
            "Rate limit exceeded: key=%s bucket=%s current=%s max=%s retry_after=%ss",
            rate_key,
            bucket_type,
            current_count,
            max_requests,
            retry_int,
        )
        raise HTTPException(
            status_code=429,
            detail=f"Quá nhiều yêu cầu trong thời gian ngắn ({current_count}/{max_requests} req/phút). Vui lòng thử lại sau {retry_int} giây.",
            headers={"Retry-After": str(retry_int)},
        )
