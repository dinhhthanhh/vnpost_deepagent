"""Tests for SlidingWindowRateLimiter and reverse-proxy spoofing prevention."""

import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.rate_limit import SlidingWindowRateLimiter, check_rate_limit


def test_sliding_window_rate_limiter_basic():
    limiter = SlidingWindowRateLimiter(cleanup_interval_seconds=60.0)
    key = "test-client"

    # Allow up to 3 requests in 1 second window
    allowed, count, retry_after = limiter.check(key, max_requests=3, window_seconds=1.0)
    assert allowed is True
    assert count == 1
    assert retry_after == 0.0

    allowed, count, retry_after = limiter.check(key, max_requests=3, window_seconds=1.0)
    assert allowed is True
    assert count == 2

    allowed, count, retry_after = limiter.check(key, max_requests=3, window_seconds=1.0)
    assert allowed is True
    assert count == 3

    # 4th request should be rejected
    allowed, count, retry_after = limiter.check(key, max_requests=3, window_seconds=1.0)
    assert allowed is False
    assert count == 3
    assert retry_after > 0.0

    # Wait for window to expire
    time.sleep(1.05)
    allowed, count, retry_after = limiter.check(key, max_requests=3, window_seconds=1.0)
    assert allowed is True
    assert count == 1


def test_rate_limit_http_exception():
    limiter = SlidingWindowRateLimiter()
    # Fill up quota
    for _ in range(5):
        limiter.check("ip:1.2.3.4:chat", max_requests=5, window_seconds=60.0)

    from unittest.mock import MagicMock
    mock_app = MagicMock()
    mock_app.state.settings = MagicMock(
        rate_limit_enabled=True,
        rate_limit_chat_rpm=5,
    )
    scope = {
        "type": "http",
        "app": mock_app,
        "client": ("1.2.3.4", 12345),
        "headers": [(b"host", b"testserver")],
    }
    req = Request(scope)

    from app.core.rate_limit import _GLOBAL_LIMITER
    _GLOBAL_LIMITER.reset()

    # Hit 5 times
    for _ in range(5):
        check_rate_limit(req, bucket_type="chat", max_requests=5)

    # 6th time should raise 429
    with pytest.raises(HTTPException) as exc_info:
        check_rate_limit(req, bucket_type="chat", max_requests=5)

    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers
    assert "Quá nhiều yêu cầu" in exc_info.value.detail
