"""Cache TTL + safe-key behavior."""

from pathlib import Path

import pytest

from app.providers.cache import FileCache


def test_cache_set_and_get(tmp_path: Path):
    c = FileCache(tmp_path, namespace="testns")
    c.set("hello", {"x": 1}, ttl_seconds=60)
    got = c.get("hello")
    assert got == {"x": 1}


def test_cache_expiry(tmp_path: Path):
    c = FileCache(tmp_path, namespace="testns")
    c.set("k", "v", ttl_seconds=0)
    # immediately expired
    assert c.get("k") is None


def test_cache_handles_long_keys(tmp_path: Path):
    c = FileCache(tmp_path, namespace="testns")
    long_key = "a" * 500 + "/" + "b" * 500
    c.set(long_key, {"ok": True}, ttl_seconds=60)
    assert c.get(long_key) == {"ok": True}


def test_evict_expired(tmp_path: Path):
    c = FileCache(tmp_path, namespace="testns")
    c.set("a", "1", ttl_seconds=0)  # expired immediately
    c.set("b", "2", ttl_seconds=120)  # alive
    n = c.evict_expired()
    assert n == 1
    assert c.get("a") is None
    assert c.get("b") == "2"


def test_namespaces_are_isolated(tmp_path: Path):
    c1 = FileCache(tmp_path, namespace="ns1")
    c2 = FileCache(tmp_path, namespace="ns2")
    c1.set("k", "in_ns1", ttl_seconds=60)
    assert c2.get("k") is None
