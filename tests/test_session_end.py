#!/usr/bin/env python3
"""Tests for hooks/session-end.py."""

import importlib.util
from pathlib import Path

SESSION_END_PY = Path(__file__).parent.parent / "hooks" / "session-end.py"


def _load_session_end(name="session_end_mod"):
    spec = importlib.util.spec_from_file_location(name, SESSION_END_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_memory_capture_points_at_memory_plugin_not_serena():
    # C6 seam: session-end must direct end-of-session memory capture to the
    # memory plugin (the single substrate), not serena's write_memory.
    mod = _load_session_end()
    result = mod.check_memory_write_needed({})
    assert result["needed"] is True
    msg = result["message"]
    assert "mcp__plugin_memory_memory__memory_write" in msg
    assert "mcp__plugin_serena_serena__write_memory" not in msg
