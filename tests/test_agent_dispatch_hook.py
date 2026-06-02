"""Regression guard for the agent-dispatch PreToolUse hook's field extraction.

Claude Code sends the hook payload with snake_case keys (tool_name/tool_input).
If the hook ever reads camelCase (toolName/toolInput) again, tool_name resolves
to "" and the hook returns allow() WITHOUT calling prepare_dispatch -- silently
turning the whole dispatch path into a no-op. These tests pin the field names
from both directions (the fix had zero coverage; surfaced by adversarial review).
"""

import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import patch

_HOOK = Path(__file__).parent.parent / "hooks" / "agent-dispatch.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("agent_dispatch_hook", _HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(payload):
    """Run the hook's main() with `payload` on stdin; return the prepare_dispatch calls."""
    mod = _load_hook()
    calls = []

    def fake_call_router(tool_name, args=None, timeout=5.0):
        calls.append((tool_name, args or {}))
        return {
            "success": True,
            "agent_id": "sub-test",
            "briefing": "B",
            "agent_type": (args or {}).get("agent_type"),
        }

    with patch.object(mod, "call_router", fake_call_router), \
            patch("sys.stdin", io.StringIO(json.dumps(payload))), \
            patch("sys.stdout", io.StringIO()):
        mod.main()
    return calls


def test_snake_case_payload_triggers_prepare_dispatch():
    """The real (snake_case) payload must reach prepare_dispatch -- this fails if
    the hook regresses to reading camelCase."""
    calls = _run({
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "implementer", "prompt": "do x", "description": "d"},
    })
    assert len(calls) == 1
    assert calls[0][0] == "prepare_dispatch"
    assert calls[0][1]["agent_type"] == "implementer"
    assert calls[0][1]["prompt"] == "do x"


def test_task_tool_also_dispatched():
    calls = _run({
        "tool_name": "Task",
        "tool_input": {"subagent_type": "reviewer", "prompt": "p"},
    })
    assert len(calls) == 1
    assert calls[0][1]["agent_type"] == "reviewer"


def test_camelcase_payload_is_not_dispatched():
    """A camelCase payload is the regression shape; with correct snake_case reads
    it resolves to tool_name='' and prepare_dispatch is never called."""
    calls = _run({
        "toolName": "Agent",
        "toolInput": {"subagent_type": "implementer", "prompt": "do x"},
    })
    assert calls == []


def test_non_dispatch_tool_is_passthrough():
    calls = _run({"tool_name": "Read", "tool_input": {"file_path": "/x"}})
    assert calls == []
