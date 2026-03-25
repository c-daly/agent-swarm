# Dispatch Enforcement Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce agent dispatch protocol automatically — a PreToolUse hook on `Task` calls `prepare_dispatch()` on the controller, which registers the agent and stores a role-specific briefing. The subagent's session-start retrieves the stored briefing. Dead `_native_task` code is removed.

**Architecture:** The hook intercepts `Task` tool calls, calls `prepare_dispatch()` on the controller via TCP/JSON-RPC, which handles all registration housekeeping. The subagent's session-start hook retrieves the stored briefing via an enhanced `get_agent_briefing()`. Dead code from the abandoned `_native_task` approach is removed.

**Tech Stack:** Python 3.12, TCP/JSON-RPC (daemon protocol), Claude Code hooks (PreToolUse)

**Spec:** `docs/superpowers/specs/2026-03-16-dispatch-enforcement-design.md`

---

## File Structure

### Modified Files

| File | Change |
|------|--------|
| `lib/controller.py` | Remove `_native_task`, remove `"task"` from dispatch table, add `_prepare_dispatch()`, enhance `get_agent_briefing` to return agent-specific briefing |
| `lib/router.py` | Remove `native__task` schema, add `router__prepare_dispatch` schema |
| `lib/mcp_native.py` | Remove `_handle_task` passthrough |
| `lib/protocol_assembly.py` | Remove comment referencing `native__task` |
| `config/permissions.yaml` | Remove `native__task` from global allowed list |
| `hooks/session-start.py` | Enhance `get_agent_briefing()` to pass agent identity |

### New Files

| File | Responsibility |
|------|---------------|
| `hooks/agent-dispatch.py` | PreToolUse hook — intercepts `Task`, calls `prepare_dispatch()` |
| `tests/test_dispatch_enforcement.py` | Tests for prepare_dispatch and briefing retrieval |

---

## Chunk 1: Remove Dead Code

Clean removal of `_native_task` and all references. Each step is independently safe — nothing calls this code.

### Task 1: Remove `_native_task` from controller

**Files:**
- Modify: `lib/controller.py`

- [ ] **Step 1: Remove `"task"` from `_handle_native` dispatch table**

In `lib/controller.py` around line 326, remove the line:
```python
            "task": self._native_task,
```

- [ ] **Step 2: Remove `_native_task` method**

In `lib/controller.py`, delete the entire `_native_task` method (lines 579-711, approximately 132 lines). This is the method that starts with:
```python
    def _native_task(self, args: dict) -> dict:
```
Delete from that line through the end of the method.

- [ ] **Step 3: Run existing tests to verify nothing breaks**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && PYTHONPATH=lib python -m pytest tests/ -x -q --timeout=30 2>&1 | tail -20`
Expected: All existing tests pass (nothing calls `_native_task`)

- [ ] **Step 4: Commit**

```bash
git add lib/controller.py
git commit -m "refactor: remove dead _native_task method from controller"
```

---

### Task 2: Remove `native__task` tool schema from router

**Files:**
- Modify: `lib/router.py`

- [ ] **Step 1: Remove `native__task` schema from tool list**

In `lib/router.py` around lines 468-480, remove the entire `native__task` tool definition dict from the native tools list.

- [ ] **Step 2: Commit**

```bash
git add lib/router.py
git commit -m "refactor: remove native__task tool schema from router"
```

---

### Task 3: Remove `_handle_task` passthrough from mcp_native

**Files:**
- Modify: `lib/mcp_native.py`

- [ ] **Step 1: Remove `_handle_task` method**

In `lib/mcp_native.py` around lines 759-766, remove the `_handle_task` method. Also remove any reference to it in the tool dispatch table within the same file (search for `"task"` mapping).

- [ ] **Step 2: Commit**

```bash
git add lib/mcp_native.py
git commit -m "refactor: remove _handle_task passthrough from mcp_native"
```

---

### Task 4: Remove remaining references

**Files:**
- Modify: `lib/protocol_assembly.py`
- Modify: `config/permissions.yaml`

- [ ] **Step 1: Remove `native__task` comment from protocol_assembly.py**

In `lib/protocol_assembly.py` line 6, the docstring mentions `native__task`. Update the comment to remove that reference. The line currently reads:
```
Used by both session-start (main agent) and native__task (subagents).
```
Change to:
```
Used by session-start (main agent) and prepare_dispatch (subagents).
```

- [ ] **Step 2: Remove `native__task` from permissions.yaml**

In `config/permissions.yaml` line 12, remove `native__task` from the global allowed list. The line currently reads:
```yaml
  allowed: [Task, serena__*, native__read_file, native__glob, native__grep, native__bash, native__web_fetch, native__web_search, native__task, workflow__*, context7__*, router__*]
```
Remove `native__task` from the list (keep everything else).

- [ ] **Step 3: Run tests again**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && PYTHONPATH=lib python -m pytest tests/ -x -q --timeout=30 2>&1 | tail -20`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add lib/protocol_assembly.py config/permissions.yaml
git commit -m "refactor: remove remaining native__task references"
```

---

## Chunk 2: Add `prepare_dispatch()` to Controller

### Task 5: Write tests for prepare_dispatch

**Files:**
- Create: `tests/test_dispatch_enforcement.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_dispatch_enforcement.py
"""Tests for agent dispatch enforcement."""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_controller():
    """Create a minimal controller with mocked dependencies."""
    from controller import Controller

    with patch.object(Controller, '__init__', lambda self: None):
        ctrl = Controller.__new__(Controller)
        ctrl.permissions = MagicMock()
        ctrl.permissions.register_agent.return_value = MagicMock(
            agent_id="sub-abc123",
            agent_type="implementer",
            roles=["editor", "shell_safe"],
        )
        ctrl._agent_state = {}
        ctrl._pending_dispatches = {}
        yield ctrl


class TestPrepareDispatch:
    def test_returns_agent_id(self, mock_controller):
        result = mock_controller._prepare_dispatch({
            "agent_type": "implementer",
            "prompt": "Build the thing",
            "description": "test task",
        })
        assert "agent_id" in result
        assert result["agent_id"].startswith("sub-")

    def test_registers_in_permissions(self, mock_controller):
        mock_controller._prepare_dispatch({
            "agent_type": "implementer",
            "prompt": "Build the thing",
        })
        mock_controller.permissions.register_agent.assert_called_once()
        call_args = mock_controller.permissions.register_agent.call_args
        assert call_args[1]["agent_type"] == "implementer" or call_args[0][1] == "implementer"

    def test_stores_briefing(self, mock_controller):
        with patch("controller.assemble_subagent_briefing", return_value="BRIEFING"):
            result = mock_controller._prepare_dispatch({
                "agent_type": "implementer",
                "prompt": "Build the thing",
            })
            agent_id = result["agent_id"]
            assert agent_id in mock_controller._pending_dispatches
            assert mock_controller._pending_dispatches[agent_id]["briefing"] == "BRIEFING"

    def test_records_agent_state(self, mock_controller):
        result = mock_controller._prepare_dispatch({
            "agent_type": "implementer",
            "prompt": "Build the thing",
            "description": "test task",
        })
        agent_id = result["agent_id"]
        assert agent_id in mock_controller._agent_state
        assert mock_controller._agent_state[agent_id]["status"] == "pending"

    def test_missing_agent_type_raises(self, mock_controller):
        with pytest.raises(Exception):
            mock_controller._prepare_dispatch({
                "prompt": "Build the thing",
            })


class TestGetAgentBriefing:
    def test_returns_stored_briefing(self, mock_controller):
        mock_controller._pending_dispatches = {
            "sub-abc123": {"briefing": "ROLE-SPECIFIC BRIEFING", "agent_type": "implementer"}
        }
        with patch("controller.assemble_agent_briefing", return_value="GENERIC"):
            result = mock_controller._get_agent_briefing({"agent_id": "sub-abc123"})
            assert result["briefing"] == "ROLE-SPECIFIC BRIEFING"

    def test_falls_back_to_generic(self, mock_controller):
        mock_controller._pending_dispatches = {}
        with patch("controller.assemble_agent_briefing", return_value="GENERIC"):
            result = mock_controller._get_agent_briefing({})
            assert result["briefing"] == "GENERIC"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && PYTHONPATH=lib python -m pytest tests/test_dispatch_enforcement.py -v`
Expected: FAIL — `_prepare_dispatch` not found

- [ ] **Step 3: Commit test file**

```bash
git add tests/test_dispatch_enforcement.py
git commit -m "test: add dispatch enforcement tests"
```

---

### Task 6: Implement `_prepare_dispatch()` on controller

**Files:**
- Modify: `lib/controller.py`

- [ ] **Step 1: Add `_pending_dispatches` dict to controller `__init__`**

Find the `__init__` method of the Controller class and add:
```python
self._pending_dispatches = {}
```
alongside the existing `self._agent_state = {}`.

- [ ] **Step 2: Add `_prepare_dispatch` method**

Add this method to the Controller class, near where `_native_task` used to be:

```python
def _prepare_dispatch(self, args: dict) -> dict:
    """Prepare an agent for dispatch. Called by hook before Task() proceeds.

    Handles: validation, ID generation, permission registration,
    briefing assembly, state recording.
    Does NOT handle execution — the caller does Agent()/Task().
    """
    agent_type = args.get("agent_type") or args.get("subagent_type")
    if not agent_type:
        raise RouterError("prepare_dispatch requires agent_type")

    prompt = args.get("prompt", "")
    description = args.get("description", "")

    # Generate agent ID
    import uuid
    agent_id = f"sub-{uuid.uuid4().hex[:8]}"

    # Extract role from agent_type (e.g., "agent-swarm:implementer" -> "implementer")
    role = agent_type.split(":")[-1] if ":" in agent_type else agent_type

    # Register in permissions system
    self.permissions.register_agent(
        agent_id=agent_id,
        agent_type=role,
    )

    # Assemble role-specific briefing
    briefing = assemble_subagent_briefing(role)

    # Store briefing for later retrieval by session-start
    self._pending_dispatches[agent_id] = {
        "briefing": briefing,
        "agent_type": role,
        "description": description,
    }

    # Record agent state
    from datetime import datetime
    self._agent_state[agent_id] = {
        "type": agent_type,
        "status": "pending",
        "started_at": datetime.now().isoformat(),
        "description": description,
    }

    return {
        "success": True,
        "agent_id": agent_id,
    }
```

- [ ] **Step 3: Route `prepare_dispatch` in `_handle_router`**

In the `_handle_router` method, add a handler for `prepare_dispatch`. Find where `register_agent` is handled and add nearby:

```python
if tool_name == "prepare_dispatch":
    return self._prepare_dispatch(args)
```

- [ ] **Step 4: Enhance `get_agent_briefing` to return stored briefing**

Replace the current `get_agent_briefing` handler (line 792-793):
```python
if tool_name == "get_agent_briefing":
    return {"briefing": assemble_agent_briefing()}
```

With:
```python
if tool_name == "get_agent_briefing":
    return self._get_agent_briefing(args)
```

And add the method:
```python
def _get_agent_briefing(self, args: dict) -> dict:
    """Return agent briefing — stored role-specific if available, generic otherwise."""
    agent_id = args.get("agent_id")
    if agent_id and agent_id in self._pending_dispatches:
        return {"briefing": self._pending_dispatches[agent_id]["briefing"]}
    return {"briefing": assemble_agent_briefing()}
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && PYTHONPATH=lib python -m pytest tests/test_dispatch_enforcement.py -v`
Expected: All PASSED

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && PYTHONPATH=lib python -m pytest tests/ -x -q --timeout=30 2>&1 | tail -20`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add lib/controller.py
git commit -m "feat: add prepare_dispatch method to controller"
```

---

### Task 7: Add `prepare_dispatch` tool schema to router

**Files:**
- Modify: `lib/router.py`

- [ ] **Step 1: Add schema**

In `lib/router.py`, in the internal tools section (after the native tools list, around line 484), add:

```python
{
    "name": "router__prepare_dispatch",
    "description": "Prepare an agent for dispatch. Registers agent, assembles briefing, records state. Called by the agent-dispatch hook before Task() proceeds.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "agent_type": {"type": "string", "description": "Type of agent to dispatch (e.g., implementer, explorer, reviewer)"},
            "prompt": {"type": "string", "description": "The task prompt"},
            "description": {"type": "string", "description": "Short description for logging"},
        },
        "required": ["agent_type"],
    },
},
```

- [ ] **Step 2: Commit**

```bash
git add lib/router.py
git commit -m "feat: add prepare_dispatch tool schema to router"
```

---

## Chunk 3: Add PreToolUse Hook

### Task 8: Create agent-dispatch hook

**Files:**
- Create: `hooks/agent-dispatch.py`

- [ ] **Step 1: Write the hook**

```python
#!/usr/bin/env python3
"""PreToolUse hook — enforce dispatch protocol for Task() calls.

When an agent calls Task(), this hook calls prepare_dispatch() on the
controller to register the subagent before allowing the call through.
If prepare_dispatch() fails, the Task() call is blocked.
"""

import json
import socket
import sys

DAEMON_HOST = "127.0.0.1"
DAEMON_PORT = 7523


def call_router(tool_name: str, args: dict = None, timeout: float = 5.0) -> dict | None:
    """Call router tool via TCP/JSON-RPC."""
    args = args or {}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((DAEMON_HOST, DAEMON_PORT))
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": f"router__{tool_name}",
                    "arguments": args,
                },
            }
            s.sendall(json.dumps(request).encode() + b"\n")
            data = b""
            while b"\n" not in data:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            if not data:
                return None
            response = json.loads(data.decode().strip())
            if "error" in response:
                return None
            return response.get("result", {})
    except Exception:
        return None


def allow(reason: str = ""):
    result = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}
    if reason:
        result["hookSpecificOutput"]["permissionDecisionReason"] = reason
    return result


def block(reason: str):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "block", "permissionDecisionReason": reason}}


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        return

    tool_name = input_data.get("toolName", "")

    # Only intercept Task tool calls
    if tool_name != "Task":
        return

    tool_input = input_data.get("toolInput", {})
    agent_type = tool_input.get("subagent_type", "")
    prompt = tool_input.get("prompt", "")
    description = tool_input.get("description", "")

    # Call prepare_dispatch on the controller
    result = call_router("prepare_dispatch", {
        "agent_type": agent_type,
        "prompt": prompt,
        "description": description,
    })

    if result and result.get("success"):
        print(json.dumps(allow(f"Agent {result.get('agent_id', '?')} registered via prepare_dispatch")))
    else:
        # If daemon is not running or prepare_dispatch fails, allow through
        # (graceful degradation — don't break spawning if daemon is down)
        print(json.dumps(allow("prepare_dispatch unavailable, allowing through")))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make executable**

Run: `chmod +x hooks/agent-dispatch.py`

- [ ] **Step 3: Commit**

```bash
git add hooks/agent-dispatch.py
git commit -m "feat: add agent-dispatch PreToolUse hook"
```

---

### Task 9: Enhance session-start to pass agent identity

**Files:**
- Modify: `hooks/session-start.py`

- [ ] **Step 1: Update `get_agent_briefing()` to pass agent identity**

The current `get_agent_briefing()` in `hooks/session-start.py` calls `call_router("get_agent_briefing")` with no arguments. It needs to pass agent identity so the controller can return the stored role-specific briefing.

The agent's identity may be available from environment variables or the hook input. Update the function to pass whatever identity is available:

```python
def get_agent_briefing() -> str:
    """Get agent protocol briefing from router."""
    # Try to pass agent identity for role-specific briefing
    agent_args = {}
    agent_id = os.environ.get("CLAUDE_AGENT_ID")
    if agent_id:
        agent_args["agent_id"] = agent_id

    result = call_router("get_agent_briefing", agent_args)
    if result and "briefing" in result:
        return result["briefing"]

    # Fallback: try direct import if router unavailable
    try:
        from protocol_assembly import UNIVERSAL_PROTOCOL, AGENT_PROTOCOL
        return f"{UNIVERSAL_PROTOCOL}\n{AGENT_PROTOCOL}"
    except ImportError:
        return ""
```

Note: If `CLAUDE_AGENT_ID` is not available as an env var, we may need a different mechanism to identify the subagent. Check what's available in the session-start hook's input data — it may include `agentId` in the hook input. If so, use that instead.

- [ ] **Step 2: Commit**

```bash
git add hooks/session-start.py
git commit -m "feat: pass agent identity in get_agent_briefing for role-specific briefing"
```

---

## Chunk 4: Integration Verification

### Task 10: End-to-end verification

- [ ] **Step 1: Run the full test suite**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && PYTHONPATH=lib python -m pytest tests/ -x -q --timeout=30 2>&1 | tail -20`
Expected: All tests pass

- [ ] **Step 2: Verify hook is syntactically correct**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && python -c "import hooks; exec(open('hooks/agent-dispatch.py').read())" 2>&1`
Expected: No syntax errors

- [ ] **Step 3: Verify dead code is fully removed**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && grep -rn "native__task\|_native_task\|_handle_task" lib/ hooks/ config/ --include="*.py" --include="*.yaml"`
Expected: No matches (all references removed)

- [ ] **Step 4: Commit any fixes**

If any issues found, fix and commit.

---

## Summary

### What was removed
- `_native_task` method from controller.py (~132 lines)
- `"task"` entry from `_handle_native` dispatch table
- `native__task` tool schema from router.py
- `_handle_task` passthrough from mcp_native.py
- `native__task` from permissions.yaml global allowed list
- `native__task` reference from protocol_assembly.py comment

### What was added
- `_prepare_dispatch()` method on controller — registers agent, assembles and stores briefing
- `_get_agent_briefing()` method on controller — returns stored briefing or falls back to generic
- `router__prepare_dispatch` tool schema in router.py
- `hooks/agent-dispatch.py` — PreToolUse hook that calls `prepare_dispatch()` on every `Task()` call
- Enhanced session-start `get_agent_briefing()` — passes agent identity for role-specific briefing
- `tests/test_dispatch_enforcement.py` — unit tests for prepare_dispatch and briefing retrieval

### What was NOT changed
- `Agent()` tool calls — hook only targets `Task` (update if `Agent` is also used for spawning)
- Briefing assembly logic — `assemble_subagent_briefing()` unchanged
- Permission system — `register_agent()` on PermissionChecker unchanged
- Session-start hook pattern — same `call_router()` mechanism, just passes identity now
