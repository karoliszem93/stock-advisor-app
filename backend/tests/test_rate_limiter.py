"""RateLimiter behavior."""

import pytest

from app.providers.rate_limiter import RateLimiter, RateLimitError


def test_acquire_within_capacity(tmp_path):
    rl = RateLimiter(tmp_path, namespace="t", capacity=3, window_seconds=60)
    rl.acquire()
    rl.acquire()
    rl.acquire()
    # 4th in same window should raise
    with pytest.raises(RateLimitError):
        rl.acquire()


def test_persists_across_instances(tmp_path):
    rl1 = RateLimiter(tmp_path, namespace="t", capacity=2, window_seconds=60)
    rl1.acquire()
    rl1.acquire()

    rl2 = RateLimiter(tmp_path, namespace="t", capacity=2, window_seconds=60)
    with pytest.raises(RateLimitError):
        rl2.acquire()


def test_status_reports_used_remaining(tmp_path):
    rl = RateLimiter(tmp_path, namespace="t", capacity=5, window_seconds=60)
    rl.acquire()
    rl.acquire()
    s = rl.status()
    assert s["used"] == 2
    assert s["remaining"] == 3
