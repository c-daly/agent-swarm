#!/usr/bin/env python3
"""Tests for the daemon-health probe cache in hooks/native-tool-blocking.py.

Guards the two properties the PR #155 review flagged as P1s:
- the cache is scoped per-user and per-port (a cached "down" for one endpoint
  must not gate another), and
- a *failure* is never cached (so recovery is picked up on the next call
  instead of blocking every native tool for the TTL), and
- the truncating write refuses to follow a symlink planted at the cache path.
"""

import importlib.util
import os
from pathlib import Path

import pytest

HOOK_PATH = Path(__file__).resolve().parent.parent / "hooks" / "native-tool-blocking.py"


def _load():
    """Load the hyphen-named hook module fresh (constants bind at import)."""
    spec = importlib.util.spec_from_file_location("ntb_probe_test", HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_probe_cache_path_is_per_user_and_per_port(monkeypatch):
    monkeypatch.setenv("DAEMON_PORT", "9999")
    mod = _load()
    uid = getattr(os, "getuid", lambda: "u")()
    assert mod._PROBE_CACHE.endswith(f"agent-swarm-daemon-probe-{uid}-9999")


def test_unhealthy_result_is_not_cached(monkeypatch, tmp_path):
    mod = _load()
    cache = tmp_path / "probe"
    monkeypatch.setattr(mod, "_PROBE_CACHE", str(cache))
    calls = {"n": 0}

    def fake_probe():
        calls["n"] += 1
        return False

    monkeypatch.setattr(mod, "_probe_daemon", fake_probe)
    assert mod._daemon_healthy() is False
    assert mod._daemon_healthy() is False
    assert calls["n"] == 2  # re-probed each call, not served from a cached "0"
    assert not cache.exists()  # a down daemon writes nothing


def test_healthy_result_is_cached(monkeypatch, tmp_path):
    mod = _load()
    cache = tmp_path / "probe"
    monkeypatch.setattr(mod, "_PROBE_CACHE", str(cache))
    calls = {"n": 0}

    def fake_probe():
        calls["n"] += 1
        return True

    monkeypatch.setattr(mod, "_probe_daemon", fake_probe)
    assert mod._daemon_healthy() is True
    assert mod._daemon_healthy() is True
    assert calls["n"] == 1  # second call served from cache, no re-probe
    assert cache.read_bytes() == b"1"


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="O_NOFOLLOW unavailable")
def test_write_refuses_symlinked_cache_path(monkeypatch, tmp_path):
    mod = _load()
    victim = tmp_path / "victim"
    victim.write_text("precious")
    cache = tmp_path / "probe"
    os.symlink(victim, cache)  # attacker plants a symlink at the cache name
    monkeypatch.setattr(mod, "_PROBE_CACHE", str(cache))
    monkeypatch.setattr(mod, "_probe_daemon", lambda: True)  # healthy -> tries to write

    assert mod._daemon_healthy() is True  # still returns the real probe result
    assert victim.read_text() == "precious"  # O_NOFOLLOW refused to truncate it
