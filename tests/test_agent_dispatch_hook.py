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
import os
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



# ---------------------------------------------------------------------------
# Helper for enforcement tests -- captures stdout decision as parsed dict
# ---------------------------------------------------------------------------




def _run_with_decision(payload, *, briefing="B", router_success=True, env=None):
    """Run main() and return (calls, decision_dict).

    `briefing` is the text returned by fake_call_router so tests can
    put it into the prompt to simulate a briefed spawn.
    `router_success` controls whether the fake router returns success.
    `env` is an optional dict of extra os.environ overrides.
    """
    mod = _load_hook()
    calls = []
    stdout_buf = io.StringIO()

    def fake_call_router(tool_name, args=None, timeout=5.0):
        calls.append((tool_name, args or {}))
        if not router_success:
            return None
        return {
            "success": True,
            "agent_id": "sub-test",
            "briefing": briefing,
            "agent_type": (args or {}).get("agent_type"),
        }

    env_overrides = env or {}
    orig_env = {k: os.environ.get(k) for k in env_overrides}
    try:
        for k, v in env_overrides.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        with patch.object(mod, "call_router", fake_call_router), \
                patch("sys.stdin", io.StringIO(json.dumps(payload))), \
                patch("sys.stdout", stdout_buf):
            mod.main()
    finally:
        for k, v in orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    raw = stdout_buf.getvalue()
    decision = json.loads(raw) if raw.strip() else {}
    return calls, decision


BRIEFING_MARKER = "## Your Agent Identity"
_BRIEFED_PROMPT = BRIEFING_MARKER + chr(10) + "Agent ID: sub-test" + chr(10) + "some briefing text"
_UNBRIEFED_PROMPT = "do something without briefing"


# ---------------------------------------------------------------------------
# Enforcement tests (6 required)
# ---------------------------------------------------------------------------


def test_briefed_prompt_allows():
    """When the spawn prompt contains the briefing marker, the hook allows."""
    _, decision = _run_with_decision(
        {
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "implementer", "prompt": _BRIEFED_PROMPT, "description": "d"},
        }
    )
    hso = decision["hookSpecificOutput"]
    assert hso["permissionDecision"] == "allow"


def test_unbriefed_default_blocks_with_agent_id_and_marker():
    """Unbriefed prompt + default env (block) must block, with reason containing
    the agent_id and the briefing marker so the spawner can comply."""
    _, decision = _run_with_decision(
        {
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "implementer", "prompt": _UNBRIEFED_PROMPT, "description": "d"},
        },
        env={"AGENT_SWARM_BRIEFING_ENFORCE": "block"},
    )
    hso = decision["hookSpecificOutput"]
    assert hso["permissionDecision"] == "block"
    reason = hso["permissionDecisionReason"]
    assert "## Your Agent Identity" in reason
    assert "sub-test" in reason


def test_unbriefed_default_env_absent_blocks():
    """Default behavior (env var absent) must also block -- same as explicit 'block'."""
    _, decision = _run_with_decision(
        {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "reviewer", "prompt": _UNBRIEFED_PROMPT},
        },
        env={"AGENT_SWARM_BRIEFING_ENFORCE": None},  # ensure absent
    )
    hso = decision["hookSpecificOutput"]
    assert hso["permissionDecision"] == "block"


def test_unbriefed_warn_allows_with_warning():
    """AGENT_SWARM_BRIEFING_ENFORCE=warn must allow but put a WARNING in additionalContext."""
    _, decision = _run_with_decision(
        {
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "implementer", "prompt": _UNBRIEFED_PROMPT, "description": "d"},
        },
        env={"AGENT_SWARM_BRIEFING_ENFORCE": "warn"},
    )
    hso = decision["hookSpecificOutput"]
    assert hso["permissionDecision"] == "allow"
    ctx = hso.get("additionalContext", "")
    parsed = json.loads(ctx)  # payload must remain valid JSON for consumers
    assert "WARNING" in parsed["warning"]


def test_unbriefed_off_allows_no_warning():
    """AGENT_SWARM_BRIEFING_ENFORCE=off is today's behavior -- allow with no warning."""
    _, decision = _run_with_decision(
        {
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "implementer", "prompt": _UNBRIEFED_PROMPT, "description": "d"},
        },
        env={"AGENT_SWARM_BRIEFING_ENFORCE": "off"},
    )
    hso = decision["hookSpecificOutput"]
    assert hso["permissionDecision"] == "allow"
    ctx = hso.get("additionalContext", "")
    assert "WARNING" not in ctx


def test_daemon_down_allows():
    """When prepare_dispatch returns None (daemon down), the hook must always allow."""
    _, decision = _run_with_decision(
        {
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "implementer", "prompt": _UNBRIEFED_PROMPT, "description": "d"},
        },
        router_success=False,
        env={"AGENT_SWARM_BRIEFING_ENFORCE": "block"},
    )
    hso = decision["hookSpecificOutput"]
    assert hso["permissionDecision"] == "allow"


def test_none_prompt_does_not_crash():
    """A null prompt must not raise TypeError on the briefing-marker check.
    With no briefing present it falls through to the default block path."""
    _, decision = _run_with_decision(
        {
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "implementer", "prompt": None, "description": "d"},
        },
        env={"AGENT_SWARM_BRIEFING_ENFORCE": "block"},
    )
    hso = decision["hookSpecificOutput"]
    assert hso["permissionDecision"] == "block"


def test_briefed_prompt_does_not_reregister():
    """A briefed prompt must NOT call prepare_dispatch again. prepare_dispatch mints
    a fresh agent_id every call, so a second call would register a duplicate identity
    and leave the first as a ghost. The hook reuses the agent_id from the briefing."""
    calls, decision = _run_with_decision(
        {
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "implementer", "prompt": _BRIEFED_PROMPT, "description": "d"},
        },
    )
    assert [c[0] for c in calls] == []  # prepare_dispatch was never called
    hso = decision["hookSpecificOutput"]
    assert hso["permissionDecision"] == "allow"
    ctx = json.loads(hso["additionalContext"])
    assert ctx["agent_id"] == "sub-test"  # reused from the briefing, not freshly minted


def test_unrecognized_enforce_value_treated_as_block():
    """An unrecognized AGENT_SWARM_BRIEFING_ENFORCE value must fail safe to block,
    not silently fall through to some other behavior."""
    _, decision = _run_with_decision(
        {
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "implementer", "prompt": _UNBRIEFED_PROMPT, "description": "d"},
        },
        env={"AGENT_SWARM_BRIEFING_ENFORCE": "enabled"},
    )
    hso = decision["hookSpecificOutput"]
    assert hso["permissionDecision"] == "block"

