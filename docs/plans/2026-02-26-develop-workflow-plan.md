# Develop Workflow Implementation Plan

> **Status: COMPLETED / OUTDATED** — This plan was executed and the develop
> workflow is implemented. References to `workflow_client` and
> `workflow_set_state` are obsolete; all state persistence now uses
> `DaemonClient` with `workflow_set_value` / `workflow_advance_phase`.
> See PR #75 for the migration.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement a `develop` workflow — a PR-based SE team simulation with PM, Researcher, Architect, Implementer, Reviewer, Git-agent, and Debugger roles using Claude Code native teams.

**Architecture:** New workflow YAML (`config/workflows/develop.yaml`) defines the phase state machine. A new `lib/develop_workflow.py` module manages state, kickbacks, subtask scheduling. Protocol assembly (`lib/protocol_assembly.py`) gets new role/workflow/phase entries. Permissions YAML gets a `pm` agent type and develop workflow phase rules. A new skill (`skills/develop/SKILL.md`) drives PM behavior.

**Tech Stack:** Python 3.11+, PyYAML, pytest. All state via `workflow_client.workflow_set_state()` (same pattern as `lib/iterate_workflow.py`).

---

## Prerequisites & Known Gaps

### Interface Contracts

- **`workflow_client.py`** — The existing module provides: `workflow_get_state`, `workflow_set_state`, `workflow_get_value`, `workflow_set_value`, `workflow_start`, `workflow_stop`, `workflow_is_active`, `workflow_update`. It does NOT provide `workflow_advance_phase` or `workflow_pass_checkpoint`. We will manage transitions in Python (same pattern as `iterate_workflow.py`) and NOT depend on daemon-side validation.

- **`conftest.py`** — The existing `MockWorkflowState` class mocks all `workflow_client` functions listed above. The autouse `mock_workflow_client` fixture patches them automatically. All test files get this mock for free.

- **Transition validation** — `lib/daemon.py:load_workflow_configs()` parses `develop.yaml` into a `WorkflowConfig(initial_phase, terminal_phase, phases, transitions)`. The daemon's `_wf_advance_phase` would validate against this, but we use `workflow_set_state` directly (bypasses validation). We implement our own transition validation in `develop_workflow.py`.

### Project Root

All paths are relative to: `/home/fearsidhe/.claude/plugins/agent-swarm/`

### Running Tests

```bash
cd /home/fearsidhe/.claude/plugins/agent-swarm
python -m pytest tests/<file> -v
```

Or via mcp-call if in a subagent:
```
mcp-call pytest tests/<file> -v
```

---

## Task 1: Create `config/workflows/develop.yaml`

### 1.1 Write the failing test

**Create file:** `tests/test_develop_workflow_config.py`

Complete test file content is in the design doc appendix. Key test classes:
- `TestConfigFileStructure` — file exists, valid YAML, correct name/initial/terminal
- `TestPhases` — all 11 phases present, checkpoints on design/test/review/acceptance
- `TestTransitions` — forward transitions and kickback transitions all present
- `TestCustomConfig` — max_review_retries, max_agent_respawns, tickets config
- `TestDaemonLoading` — `load_workflow_configs()` includes develop with correct fields

Test count: ~25

### 1.2 Run test — confirm failure

```bash
python -m pytest tests/test_develop_workflow_config.py -v 2>&1 | head -30
```

Expected: FAIL — FileNotFoundError because develop.yaml doesn't exist.

### 1.3 Create the YAML config

**Create file:** `config/workflows/develop.yaml`

```yaml
name: develop
description: "PR-based SE team simulation with TDD and adversarial review"
initial_phase: intake
terminal_phase: complete
max_agents: 8
max_review_retries: 0
max_agent_respawns: 3

tickets:
  enabled: true
  provider: github
  feature_ticket: true
  subtask_tickets: true
  followup_tickets: true

phases:
  - name: intake
    allowed_tool_categories: [FILE_READ, FILE_SEARCH, CODE_QUERY, USER_INTERACTION]
    blocked_tools: [native__bash, native__write_file, native__edit_file]
    eligible_agents: [pm]
    checkpoint: false

  - name: research
    allowed_tool_categories: [FILE_READ, FILE_SEARCH, CODE_QUERY, WEB_RESEARCH]
    blocked_tools: [native__bash, native__write_file, native__edit_file]
    eligible_agents: [researcher]
    checkpoint: false

  - name: design
    allowed_tool_categories: [FILE_READ, FILE_SEARCH, CODE_QUERY]
    blocked_tools: [native__bash, native__write_file, native__edit_file]
    eligible_agents: [architect]
    checkpoint: true

  - name: branch
    allowed_tool_categories: [SHELL_SAFE]
    blocked_tools: [native__write_file, native__edit_file]
    eligible_agents: [git-agent]
    checkpoint: false

  - name: test_writing
    allowed_tool_categories: [FILE_READ, FILE_WRITE, CODE_QUERY, CODE_EDIT, FILE_SEARCH, SHELL_SAFE]
    blocked_tools: []
    eligible_agents: [implementer]
    checkpoint: false

  - name: implement
    allowed_tool_categories: [FILE_READ, FILE_WRITE, CODE_QUERY, CODE_EDIT, FILE_SEARCH, SHELL_SAFE]
    blocked_tools: []
    eligible_agents: [implementer]
    checkpoint: false

  - name: test
    allowed_tool_categories: [FILE_READ, SHELL_SAFE]
    blocked_tools: [native__write_file, native__edit_file]
    eligible_agents: [implementer, debugger]
    checkpoint: true

  - name: review
    allowed_tool_categories: [FILE_READ, CODE_QUERY]
    blocked_tools: [native__bash, native__write_file, native__edit_file]
    eligible_agents: [reviewer]
    checkpoint: true

  - name: merge
    allowed_tool_categories: [FILE_READ, SHELL_SAFE]
    blocked_tools: [native__write_file, native__edit_file]
    eligible_agents: [git-agent]
    checkpoint: false

  - name: acceptance
    allowed_tool_categories: [FILE_READ, CODE_QUERY, USER_INTERACTION]
    blocked_tools: [native__bash, native__write_file, native__edit_file]
    eligible_agents: [pm]
    checkpoint: true

  - name: complete
    allowed_tool_categories: []
    blocked_tools: []
    eligible_agents: []
    checkpoint: false

transitions:
  intake: [research]
  research: [design]
  design: [branch]
  branch: [test_writing]
  test_writing: [implement]
  implement: [test]
  test: [review, implement]
  review: [merge, implement, test_writing]
  merge: [acceptance, implement]
  acceptance: [complete, implement, test_writing]
```

### 1.4 Run test — confirm pass

```bash
python -m pytest tests/test_develop_workflow_config.py -v
```

Expected: ALL PASS (~25 tests).

### 1.5 Commit

```bash
git add config/workflows/develop.yaml tests/test_develop_workflow_config.py
git commit -m "feat: add develop workflow YAML config with TDD phases and kickbacks"
```

---

## Task 2: Add PM agent type and develop workflow phases to `config/permissions.yaml`

### 2.1 Write the failing test

**Create file:** `tests/test_develop_permissions.py`

Key test classes:
- `TestPMAgentType` — pm defined, can read/glob/grep/workflow, blocked from write/edit/bash
- `TestDevelopWorkflowSection` — develop section exists, all 10 non-terminal phases defined, correct allow/block per phase

Test count: ~18

### 2.2 Run test — confirm failure

Expected: FAIL — "pm" not in agents, "develop" not in workflows.

### 2.3 Edit `config/permissions.yaml`

**Edit 1 — Add PM agent type.** In the `agents:` section, after the `architect:` block, add:

```yaml
  # PM - stakeholder proxy, read + workflow control
  pm:
    allowed: [native__read_file, native__glob, native__grep, serena__*, workflow__*, context7__*]
    blocked: [native__write_file, native__edit_file, native__bash]
```

**Edit 2 — Add develop workflow section.** In the `workflows:` section, after the last existing workflow block, add:

```yaml
  # Develop workflow (PR-based SE team)
  develop:
    intake:
      allowed: [native__read_file, native__glob, native__grep, serena__*, workflow__*]
      blocked: [native__write_file, native__edit_file, native__bash]
    research:
      allowed: [native__read_file, native__glob, native__grep, serena__*, context7__*, native__web_fetch, native__web_search]
      blocked: [native__write_file, native__edit_file, native__bash]
    design:
      allowed: [native__read_file, native__glob, native__grep, serena__*, context7__*]
      blocked: [native__write_file, native__edit_file, native__bash]
    branch:
      allowed: [native__read_file, native__bash(git*)]
      blocked: [native__write_file, native__edit_file]
    test_writing:
      allowed: [native__write_file, native__edit_file, native__read_file, native__glob, native__grep, native__bash(pytest*), serena__*]
      blocked: []
    implement:
      allowed: [native__write_file, native__edit_file, native__read_file, native__glob, native__grep, native__bash(pytest*), native__bash(python*), native__bash(ruff*), serena__*]
      blocked: []
    test:
      allowed: [native__read_file, native__bash(pytest*), native__bash(python -m pytest*), native__bash(ruff*)]
      blocked: [native__write_file, native__edit_file]
    review:
      allowed: [native__read_file, native__glob, native__grep, serena__*]
      blocked: [native__write_file, native__edit_file, native__bash]
    merge:
      allowed: [native__read_file, native__bash(git*), native__bash(gh*)]
      blocked: [native__write_file, native__edit_file]
    acceptance:
      allowed: [native__read_file, native__glob, native__grep, serena__*, workflow__*]
      blocked: [native__write_file, native__edit_file, native__bash]
```

### 2.4 Run test — confirm pass

```bash
python -m pytest tests/test_develop_permissions.py -v
```

Expected: ALL PASS (~18 tests).

### 2.5 Commit

```bash
git add config/permissions.yaml tests/test_develop_permissions.py
git commit -m "feat: add pm agent type and develop workflow phase permissions"
```

---

## Task 3: Add protocols to `lib/protocol_assembly.py`

### 3.1 Write the failing test

**Create file:** `tests/test_develop_protocol_assembly.py`

Key test classes:
- `TestPMRole` — "pm" in ROLE_PROTOCOLS, mentions stakeholder/stories/acceptance
- `TestDevelopWorkflow` — "develop" in WORKFLOW_PROTOCOLS, mentions intake/kickback/team
- `TestDevelopPhases` — research/branch/merge/acceptance in PHASE_PROTOCOLS
- `TestBriefingAssembly` — PM briefing includes role+workflow+phase, reviewer briefing works

Test count: ~20

### 3.2 Run test — confirm failure

Expected: FAIL — KeyError: "pm" not in ROLE_PROTOCOLS.

### 3.3 Edit `lib/protocol_assembly.py`

**Edit 1 — Add PM to ROLE_PROTOCOLS dict.** After the `"researcher"` entry, add:

```python
    "pm": """## PM Role
- Stakeholder proxy -- owns the feature from intake to acceptance
- Write user stories with clear acceptance criteria at intake
- Approve or reject design specs from Architect
- Schedule subtasks based on Architect's dependency graph
- Monitor kickback history -- intervene if progress stalls
- Validate implementation against original user stories at acceptance
- Can create GitHub tickets when ticket config is enabled
- Read-only for code -- no file writes, edits, or bash
""",
```

**Edit 2 — Add develop to WORKFLOW_PROTOCOLS dict.** After the `"orchestrate"` entry, add:

```python
    "develop": """## Develop Workflow
PR-based SE team: intake -> research -> design -> branch -> test_writing -> implement -> test -> review -> merge -> acceptance -> complete

### Team Coordination
- PM is team lead via Claude Code Teams (TeamCreate/SendMessage).
- All phase transitions decided by PM.
- Agents communicate via SendMessage. PM assigns work, receives results.
- Kickbacks target implement (code issue) or test_writing (test gap).
- Retry counters tracked per kickback source in workflow state.

### Subtask Parallelism
- Architect produces dependency graph. Independent subtasks run in parallel.
- Each parallel Implementer gets isolated worktree.
- Idle agents stay alive, PM messages to wake when work unblocks.
""",
```

**Edit 3 — Add new phases to PHASE_PROTOCOLS dict.** Only add keys that don't already exist. Check first. Add these if missing:

```python
    "research": """## Phase: Research
- Investigate codebase, APIs, libraries, prior art
- Produce structured context document for Architect
- -> design when context is sufficient
""",
    "branch": """## Phase: Branch
- Create feature branch from main
- If ticket exists, reference ticket ID in branch name
- -> test_writing when branch is created
""",
    "merge": """## Phase: Merge
- Create PR linking to feature ticket if tickets enabled
- Attempt merge
- If merge conflicts -> kickback to implement with list of conflicting files
- If clean -> advance to acceptance
""",
    "acceptance": """## Phase: Acceptance
- PM validates implementation against original user stories
- Check each acceptance criterion from the stories
- Accept -> complete (workflow done)
- Reject (code issue) -> kickback to implement with feedback
- Reject (insufficient tests) -> kickback to test_writing with feedback
""",
```

### 3.4 Run test — confirm pass

```bash
python -m pytest tests/test_develop_protocol_assembly.py -v
```

Expected: ALL PASS (~20 tests).

### 3.5 Commit

```bash
git add lib/protocol_assembly.py tests/test_develop_protocol_assembly.py
git commit -m "feat: add PM role and develop workflow/phase protocols"
```

---

## Task 4: Create `lib/develop_workflow.py` — state machine core

### 4.1 Write the failing test

**Create file:** `tests/test_develop_workflow.py`

Key test classes:
- `TestStart` — returns state dict, correct defaults, overrides work
- `TestStop` — sets inactive, stores reason
- `TestPhaseQueries` — get_phase, is_active
- `TestForwardTransitions` — full happy path, individual transitions
- `TestInvalidTransitions` — intake->implement fails, unknown phase fails
- `TestCheckpoints` — design/test/review/acceptance require checkpoint before advance
- `TestKickbacks` — test->implement, review->implement, review->test_writing, merge->implement, acceptance->implement, acceptance->test_writing
- `TestKickbackCounters` — increment, separate per source, 0=unlimited, bounded raises
- `TestSubtasks` — add, eligible respects deps, complete unblocks dependents, chain deps

Test count: ~50

### 4.2 Run test — confirm failure

Expected: `ModuleNotFoundError: No module named 'develop_workflow'`

### 4.3 Create `lib/develop_workflow.py`

```python
"""Develop workflow -- PR-based SE team simulation with TDD.

State machine for the develop workflow. Manages phase transitions,
kickback counters, subtask scheduling, and ticket configuration.

State persisted via workflow_client.workflow_set_state() (same pattern
as iterate_workflow.py). Transition validation done here in Python.

Flow:
  intake -> research -> design -> branch -> test_writing -> implement
       -> test -> review -> merge -> acceptance -> complete
"""

import sys
from pathlib import Path
from typing import Optional

lib_dir = Path(__file__).parent
if str(lib_dir) not in sys.path:
    sys.path.insert(0, str(lib_dir))

import workflow_client

WORKFLOW_ID = "develop"

# Valid transitions: source -> set of valid targets
# Must match config/workflows/develop.yaml
TRANSITIONS = {
    "intake": {"research"},
    "research": {"design"},
    "design": {"branch"},
    "branch": {"test_writing"},
    "test_writing": {"implement"},
    "implement": {"test"},
    "test": {"review", "implement"},
    "review": {"merge", "implement", "test_writing"},
    "merge": {"acceptance", "implement"},
    "acceptance": {"complete", "implement", "test_writing"},
}

CHECKPOINT_PHASES = {"design", "test", "review", "acceptance"}
ALL_PHASES = set(TRANSITIONS.keys()) | {"complete"}

DEFAULTS = {
    "max_review_retries": 0,
    "max_agent_respawns": 3,
    "max_agents": 8,
    "tickets": {
        "enabled": True,
        "provider": "github",
        "feature_ticket": True,
        "subtask_tickets": True,
        "followup_tickets": True,
    },
}


class DevelopWorkflowError(Exception):
    """Error in develop workflow logic."""
    pass


def _get_state() -> dict:
    return workflow_client.workflow_get_state(WORKFLOW_ID) or {}

def _set_state(state: dict) -> None:
    workflow_client.workflow_set_state(WORKFLOW_ID, state)

def _force_phase(phase: str) -> None:
    """TEST HELPER ONLY -- bypasses validation."""
    state = _get_state()
    state["phase"] = phase
    for key in list(state.keys()):
        if key.endswith("_checkpoint_passed"):
            del state[key]
    _set_state(state)


def start_develop(
    task: str,
    max_review_retries: Optional[int] = None,
    max_agent_respawns: Optional[int] = None,
    tickets_enabled: Optional[bool] = None,
) -> dict:
    tickets = dict(DEFAULTS["tickets"])
    if tickets_enabled is not None:
        tickets["enabled"] = tickets_enabled
    state = {
        "active": True,
        "task": task,
        "phase": "intake",
        "max_review_retries": (
            max_review_retries if max_review_retries is not None
            else DEFAULTS["max_review_retries"]
        ),
        "max_agent_respawns": (
            max_agent_respawns if max_agent_respawns is not None
            else DEFAULTS["max_agent_respawns"]
        ),
        "tickets": tickets,
        "kickback_counters": {},
        "subtasks": [],
        "user_stories": [],
        "design_spec": None,
        "feature_ticket": None,
        "team_name": None,
        "agents": {},
    }
    _set_state(state)
    return state


def stop(reason: str = "user_stopped") -> None:
    state = _get_state()
    if not state:
        return
    state["active"] = False
    state["exit_reason"] = reason
    _set_state(state)


def get_phase() -> Optional[str]:
    state = _get_state()
    return state.get("phase") if state else None


def is_active() -> bool:
    state = _get_state()
    return bool(state and state.get("active"))


def advance_phase(target: str) -> dict:
    state = _get_state()
    if not state or not state.get("active"):
        raise DevelopWorkflowError("Workflow not active")
    current = state["phase"]
    if target not in ALL_PHASES:
        raise DevelopWorkflowError(
            f"Unknown phase: '{target}'. Valid: {sorted(ALL_PHASES)}"
        )
    valid_targets = TRANSITIONS.get(current, set())
    if target not in valid_targets:
        raise DevelopWorkflowError(
            f"Invalid transition: {current} -> {target}. "
            f"Valid targets from '{current}': {sorted(valid_targets)}"
        )
    if current in CHECKPOINT_PHASES:
        ck_key = f"{current}_checkpoint_passed"
        if not state.get(ck_key):
            raise DevelopWorkflowError(
                f"Checkpoint not passed for phase '{current}'. "
                f"Call pass_checkpoint() before advancing."
            )
    state["phase"] = target
    state.pop(f"{current}_checkpoint_passed", None)
    if target == "complete":
        state["active"] = False
    _set_state(state)
    return state


def pass_checkpoint() -> None:
    state = _get_state()
    if not state or not state.get("active"):
        return
    current = state["phase"]
    if current in CHECKPOINT_PHASES:
        state[f"{current}_checkpoint_passed"] = True
        _set_state(state)


def record_kickback(source: str) -> None:
    state = _get_state()
    counters = state.get("kickback_counters", {})
    count = counters.get(source, 0) + 1
    max_retries = state.get("max_review_retries", 0)
    if max_retries > 0 and count > max_retries:
        raise DevelopWorkflowError(
            f"Max retries ({max_retries}) exceeded for kickback source "
            f"'{source}'. Attempted: {count}"
        )
    counters[source] = count
    state["kickback_counters"] = counters
    _set_state(state)


def add_subtask(subtask: dict) -> None:
    state = _get_state()
    if "status" not in subtask:
        subtask = {**subtask, "status": "pending"}
    state.setdefault("subtasks", []).append(subtask)
    _set_state(state)


def get_eligible_subtasks() -> list[dict]:
    state = _get_state()
    subtasks = state.get("subtasks", [])
    completed_ids = {s["id"] for s in subtasks if s.get("status") == "completed"}
    return [
        s for s in subtasks
        if s.get("status") == "pending"
        and all(d in completed_ids for d in s.get("depends_on", []))
    ]


def complete_subtask(subtask_id: int) -> None:
    state = _get_state()
    for s in state.get("subtasks", []):
        if s["id"] == subtask_id:
            s["status"] = "completed"
            break
    _set_state(state)
```

### 4.4 Run test — confirm pass

```bash
python -m pytest tests/test_develop_workflow.py -v
```

Expected: ALL PASS (~50 tests).

### 4.5 Commit

```bash
git add lib/develop_workflow.py tests/test_develop_workflow.py
git commit -m "feat: add develop workflow state machine with transitions, kickbacks, subtasks"
```

---

## Task 5: Controller integration test

### 5.1 Write the test

**Create file:** `tests/test_develop_controller.py`

Uses real Controller with real config files (not mock). Tests:
- `TestDevelopWorkflowStart` — start returns intake phase, strips protected keys
- `TestDevelopTransitions` — intake->research works, invalid transition raises WorkflowError
- `TestDevelopCheckpoints` — design checkpoint enforcement

Test count: ~7

### 5.2 Run test

```bash
python -m pytest tests/test_develop_controller.py -v
```

Expected: ALL PASS. Controller is generic — it reads develop.yaml transitions.

### 5.3 Commit

```bash
git add tests/test_develop_controller.py
git commit -m "test: add controller integration tests for develop workflow"
```

---

## Task 6: Create develop skill

### 6.1 Create skill

**Create directory:** `skills/develop/`
**Create file:** `skills/develop/SKILL.md`

Skill frontmatter:
```yaml
---
name: develop
description: PR-based development workflow with SE team simulation
user_invocable: true
---
```

Content describes PM playbook for each phase: startup (team creation, workflow start), intake (user stories, optional tickets), research (spawn researcher), design (spawn architect, approve, checkpoint), branch (spawn git-agent), TDD loop (spawn implementers per subtask, parallel via worktrees), review (spawn reviewer, handle kickbacks), merge (git-agent PR), acceptance (validate stories), complete (shutdown team).

### 6.2 Commit

```bash
git add skills/develop/SKILL.md
git commit -m "feat: add develop workflow PM orchestration skill"
```

---

## Task 7: Full test suite — regression check

### 7.1 Run all new tests

```bash
python -m pytest tests/test_develop_workflow_config.py tests/test_develop_permissions.py tests/test_develop_protocol_assembly.py tests/test_develop_workflow.py tests/test_develop_controller.py -v
```

Expected: ALL PASS.

### 7.2 Run existing tests

```bash
python -m pytest tests/ -v --tb=short -x 2>&1 | tail -30
```

Expected: No new failures.

### 7.3 Fix regressions if any, commit

---

## Task 8: Daemon smoke test

### 8.1 Restart daemon

```bash
python lib/daemon.py --shutdown 2>/dev/null; sleep 2; python lib/daemon.py &
sleep 3; python lib/daemon.py --status
```

### 8.2 Test via mcp-call

```bash
mcp-call workflow__workflow_start '{"workflow_id": "develop", "initial_state": {"task": "smoke test"}}'
mcp-call workflow__workflow_get_state '{"workflow_id": "develop"}'
mcp-call workflow__workflow_advance_phase '{"workflow_id": "develop", "target_phase": "research"}'
mcp-call workflow__workflow_stop '{"workflow_id": "develop"}'
```

---

## Task Dependencies

```
Task 1 (YAML)  ──────────────────────────────> Task 5 (controller test)
Task 2 (permissions) ─┐                              │
Task 3 (protocols)  ──┤──> can run in parallel ──> Task 7 (regression)
Task 4 (state machine)┘                              │
Task 6 (skill)     ──────────────────────────────────>│
                                                      v
                                                 Task 8 (smoke)
```

Tasks 1-4 and 6 have no mutual dependencies. Task 5 needs Task 1. Tasks 7-8 need all prior.
