# Agent Registration Briefing — Implementation Plan

**Status:** Implemented (2026-02-12)

**Goal:** Make `register_agent` the single entry point for subagent lifecycle — returning assembled briefings so orchestrators include them in Task prompts.

**Architecture:** Enhanced `_handle_router("register_agent")` in controller.py to register the agent, set initial phase (if workflow), record agent state, and assemble a signal-dense briefing. Removed the blanket workflow requirement for file writes in permission_store.py so agents can operate outside workflows.

**Tech Stack:** Python, existing controller/permissions/protocol_assembly infrastructure

**Implementation notes:**
- Removed ALLOWED_BACKENDS from mcp-call — router handles all permissions
- Fixed SUBAGENT_PROTOCOL tool table: was using native__ (blocked by mcp-call), now uses serena__ + shell aliases
- Deleted stale test_session_start.py (tested removed functions)
- Fixed stale daemon integration test (phase now controller-managed from config)

---

### Task 1: Remove workflow-only file write restriction

**Files:**
- Modify: `lib/permission_store.py:87-88`
- Test: `tests/test_permission_store.py`

**Step 1: Write the failing test**

```python
# tests/test_permission_store.py — add to existing or create
from permission_store import PermissionStore

def test_file_write_allowed_without_workflow():
    """File writes should not be blocked solely because no workflow is active."""
    store = PermissionStore(workflow_active=False)
    allowed, reason = store.is_tool_allowed("serena__replace_content")
    assert allowed is True
    assert "workflow" not in reason.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_permission_store.py::test_file_write_allowed_without_workflow -v`
Expected: FAIL — currently returns `(False, "No active workflow - editing blocked")`

**Step 3: Remove the blanket workflow gate**

In `lib/permission_store.py`, delete lines 87-88:
```python
# DELETE these two lines:
if not self.workflow_active and tool_name in FILE_WRITE_TOOLS:
    return False, "No active workflow - editing blocked"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_permission_store.py::test_file_write_allowed_without_workflow -v`
Expected: PASS

**Step 5: Run full test suite to check for regressions**

Run: `pytest tests/ -x -q`
Expected: All pass. Existing tests that depend on this behavior may need updating.

**Step 6: Commit**

```bash
git add lib/permission_store.py tests/test_permission_store.py
git commit -m "fix: remove blanket workflow requirement for file writes

Agents should be able to edit files based on their registration and
phase permissions, not solely on workflow presence. This enables
ad-hoc agent spawning outside of workflows."
```

---

### Task 2: Enhance register_agent to record agent state

**Files:**
- Modify: `lib/controller.py:653-663`
- Test: `tests/test_controller.py`

**Step 1: Write the failing test**

```python
# In tests/test_controller.py, add to TestRouterOps:

def test_register_agent_creates_state(self, ctrl):
    """register_agent should create agent state entry."""
    result = ctrl.handle_call(
        "router__register_agent",
        {"agent_id": "sub-test1", "agent_type": "implementer"},
    )
    assert result["agent_id"] == "sub-test1"
    # Agent state should be recorded
    state = ctrl.handle_call(
        "workflow__agent_get_state", {"agent_id": "sub-test1"}
    )
    assert state is not None
    assert state["agent_type"] == "implementer"
    assert state["status"] == "registered"
    assert "registered_at" in state
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_controller.py::TestRouterOps::test_register_agent_creates_state -v`
Expected: FAIL — current register_agent doesn't call agent_set_state

**Step 3: Enhance register_agent in controller.py**

In `lib/controller.py`, replace the `register_agent` handler (around line 653):
```python
if tool_name == "register_agent":
    agent_id = args.get("agent_id", "")
    agent_type = args.get("agent_type", "")
    workflow_id = args.get("workflow_id")

    # 1. Register in permissions system
    info = self.permissions.register_agent(
        agent_id=agent_id,
        agent_type=agent_type,
        roles=args.get("roles"),
    )

    # 2. Determine phase from workflow config (if applicable)
    phase = None
    if workflow_id:
        config = self._workflow_configs.get(workflow_id)
        if config:
            phase = config.initial_phase
            info.workflow = workflow_id
            info.phase = phase

    # 3. Record agent state
    from datetime import datetime, timezone
    agent_state = {
        "agent_id": agent_id,
        "agent_type": agent_type,
        "workflow_id": workflow_id,
        "phase": phase,
        "status": "registered",
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    self._agent_set_state({"agent_id": agent_id, "state": agent_state})

    return {
        "agent_id": info.agent_id,
        "agent_type": info.agent_type,
        "roles": info.roles,
        "workflow_id": workflow_id,
        "phase": phase,
    }
```

Note: `datetime` imports may already exist at file top — check before adding.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_controller.py::TestRouterOps::test_register_agent_creates_state -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/controller.py tests/test_controller.py
git commit -m "feat: register_agent records agent state with metadata"
```

---

### Task 3: Enhance register_agent to set phase from workflow config

**Files:**
- Modify: `lib/controller.py` (same handler as Task 2)
- Test: `tests/test_controller.py`

**Step 1: Write the failing test**

```python
def test_register_agent_with_workflow_sets_phase(self, ctrl_with_config):
    """register_agent with workflow_id should set initial phase."""
    # Start the iterate workflow first
    ctrl_with_config.handle_call(
        "workflow__workflow_start",
        {"workflow_id": "iterate", "initial_state": {}},
    )
    result = ctrl_with_config.handle_call(
        "router__register_agent",
        {"agent_id": "sub-impl1", "agent_type": "implementer", "workflow_id": "iterate"},
    )
    assert result["workflow_id"] == "iterate"
    assert result["phase"] == "test_writing"  # initial_phase from config

def test_register_agent_without_workflow_has_no_phase(self, ctrl):
    """register_agent without workflow_id should have no phase."""
    result = ctrl.handle_call(
        "router__register_agent",
        {"agent_id": "sub-expl1", "agent_type": "explorer"},
    )
    assert result["phase"] is None
    assert result.get("workflow_id") is None
```

**Step 2: Run tests to verify they pass**

Run: `pytest tests/test_controller.py::TestRouterOps::test_register_agent_with_workflow_sets_phase tests/test_controller.py::TestRouterOps::test_register_agent_without_workflow_has_no_phase -v`
Expected: PASS (implementation from Task 2 should handle this already)

**Step 3: Commit if tests pass (or fix and commit)**

```bash
git add tests/test_controller.py
git commit -m "test: verify register_agent phase assignment with and without workflow"
```

---

### Task 4: Add briefing assembly to register_agent

**Files:**
- Modify: `lib/controller.py` (register_agent handler)
- Test: `tests/test_controller.py`

**Step 1: Write the failing test**

```python
def test_register_agent_returns_briefing(self, ctrl):
    """register_agent should return an assembled briefing."""
    result = ctrl.handle_call(
        "router__register_agent",
        {"agent_id": "sub-b1", "agent_type": "implementer"},
    )
    assert "briefing" in result
    briefing = result["briefing"]
    # Must contain the tool table (critical for agents to function)
    assert "mcp-call" in briefing
    # Must contain some role-specific content
    assert "implementer" in briefing.lower() or "implement" in briefing.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_controller.py::TestRouterOps::test_register_agent_returns_briefing -v`
Expected: FAIL — current register_agent doesn't return briefing

**Step 3: Add briefing assembly to the register_agent handler**

In `lib/controller.py`, add the briefing call to the register_agent handler (after state recording, before return):

```python
    # 4. Assemble briefing
    briefing = assemble_subagent_briefing(agent_type)

    return {
        "agent_id": info.agent_id,
        "agent_type": info.agent_type,
        "roles": info.roles,
        "workflow_id": workflow_id,
        "phase": phase,
        "briefing": briefing,
    }
```

Verify `assemble_subagent_briefing` is imported at the top of controller.py:
```python
from protocol_assembly import assemble_subagent_briefing
```
Check if this import already exists (it's used by `_native_task`).

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_controller.py::TestRouterOps::test_register_agent_returns_briefing -v`
Expected: PASS

**Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

**Step 6: Commit**

```bash
git add lib/controller.py tests/test_controller.py
git commit -m "feat: register_agent returns assembled briefing for subagent prompts"
```

---

### Task 5: Sharpen briefing content in protocol_assembly.py

**Files:**
- Modify: `lib/protocol_assembly.py`
- Test: `tests/test_protocol_assembly.py` (create)

**Context:** The current briefing content has signal-to-noise issues. Every line must address an observed failure mode. Review `SUBAGENT_PROTOCOL`, `UNIVERSAL_PROTOCOL`, and `ROLE_PROTOCOLS`.

**Step 1: Write tests for briefing content quality**

```python
# tests/test_protocol_assembly.py
from protocol_assembly import assemble_subagent_briefing

class TestBriefingContent:
    def test_briefing_contains_tool_table(self):
        """Briefing must contain mcp-call tool patterns."""
        briefing = assemble_subagent_briefing("implementer")
        assert "mcp-call" in briefing
        # Key operations must be listed
        assert "read" in briefing.lower()
        assert "search" in briefing.lower() or "grep" in briefing.lower()
        assert "edit" in briefing.lower() or "replace" in briefing.lower()

    def test_briefing_contains_operational_rules(self):
        """Briefing must contain rules for observed failure modes."""
        briefing = assemble_subagent_briefing("implementer")
        # Must mention parallelization
        assert "parallel" in briefing.lower()
        # Must mention not re-reading
        assert "duplicate" in briefing.lower() or "re-read" in briefing.lower() or "already read" in briefing.lower()

    def test_briefing_contains_role_info(self):
        """Briefing should contain role-specific content."""
        impl_briefing = assemble_subagent_briefing("implementer")
        expl_briefing = assemble_subagent_briefing("explorer")
        # They should differ
        assert impl_briefing != expl_briefing

    def test_briefing_within_token_budget(self):
        """Briefing should be concise — under 2000 tokens (~8000 chars)."""
        briefing = assemble_subagent_briefing("implementer")
        assert len(briefing) < 8000
```

**Step 2: Run tests — some may pass, some may fail**

Run: `pytest tests/test_protocol_assembly.py -v`

**Step 3: Sharpen the briefing content**

Review and update in `lib/protocol_assembly.py`:

- `SUBAGENT_PROTOCOL`: Verify mcp-call patterns are correct. Ensure every tool operation has a working example.
- `UNIVERSAL_PROTOCOL`: Cut generic advice. Keep only: parallelize independent calls, don't re-read files, use scripts for 3+ operations, process data in scripts not in context.
- `ROLE_PROTOCOLS`: Keep thin for now but ensure each role has at least its key constraint. These will grow over time.

The exact content changes depend on what the current patterns are and what's correct for the mcp-call invocation format. Check `bin/mcp-call` to verify the correct syntax.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_protocol_assembly.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add lib/protocol_assembly.py tests/test_protocol_assembly.py
git commit -m "refactor: sharpen briefing content for signal density

Remove generic advice, ensure tool table has correct mcp-call patterns,
keep only operational rules that address observed failure modes."
```

---

### Task 6: Update design doc with final state

**Files:**
- Modify: `docs/plans/2026-02-12-register-agent-briefing-design.md`

**Step 1: Update status to Implemented, add notes on the workflow gate removal**

**Step 2: Commit**

```bash
git add docs/plans/2026-02-12-register-agent-briefing-design.md
git commit -m "docs: update design doc with implementation notes"
```