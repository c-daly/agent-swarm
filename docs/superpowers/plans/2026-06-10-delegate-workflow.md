# Delegate Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `delegate` workflow to agent-swarm where Fable 5 decomposes work into a tiered task manifest, haiku/sonnet workers execute in parallel worktrees, and Fable re-enters only for escalations and integration.

**Architecture:** Extends the existing parallel-orchestrate machinery (`lib/manifest.py`, `lib/orchestrator.py`) with per-task `model`/`escalation` fields and an `escalated` completion outcome. Adds a phase-gated workflow (`config/workflows/delegate.yaml` + `config/permissions.yaml` block + `_KNOWN_WORKFLOWS` entry, so the conformance gate sees it as governed) and a driving skill (`skills/delegate/SKILL.md`).

**Tech Stack:** Python 3 (dataclasses, PyYAML), pytest, agent-swarm router/workflow daemon.

**Spec:** `docs/superpowers/specs/2026-06-10-delegate-workflow-design.md`

**Repo:** `/home/fearsidhe/.claude/plugins/agent-swarm` (run all commands from this directory; current branch `l1/106-conformance-all-workflows`)

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `lib/manifest.py` | Modify | `ManifestTask` gains `model`/`escalation` fields; parse + validation |
| `lib/orchestrator.py` | Modify | `SpawnRequest.model`, current-tier resolution, `escalated` outcome, CLI JSON |
| `lib/permission_query.py` | Modify | Add `delegate` to `_KNOWN_WORKFLOWS` |
| `config/permissions.yaml` | Modify | `workflows.delegate.<phase>` L1 governance blocks |
| `config/workflows/delegate.yaml` | Create | Phase definitions, checkpoints, transitions |
| `skills/delegate/SKILL.md` | Create | Lifecycle driver: decomposition contract, tier rubric, commands |
| `config/manifests/demo_delegate.yaml` | Create | Tiered demo manifest for smoke testing |
| `tests/test_manifest.py` | Modify | Tier-field tests (append) |
| `tests/test_parallel_orchestrator.py` | Modify | Tier passthrough + escalation tests (append) |
| `tests/test_delegate_workflow_config.py` | Create | Workflow YAML structure + governance tests |
| `tests/test_demo_delegate_manifest.py` | Create | Demo manifest round-trip test |
| `tests/test_conformance_static.py` | Modify | Add `delegate` to `CORE_GOVERNED` |

Tier vocabulary used throughout: worker tiers are `haiku` and `sonnet`; `fable` is not a worker tier — `escalation: fable` means "no re-dispatch, route to the escalate phase (Fable handles it personally)". Tier order is haiku < sonnet < fable, and `escalation` must be a strictly higher tier than `model`.

---

### Task 1: Manifest tier fields (`model`, `escalation`)

**Files:**
- Modify: `lib/manifest.py`
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write the failing tests**

Append to the end of `tests/test_manifest.py`:

```python
class TestTierFields:
    def test_default_model_and_escalation(self):
        task = ManifestTask(
            name="stack",
            description="Implement a stack",
            target_dir="src/stack",
            test_dir="tests/test_stack",
        )
        assert task.model == "sonnet"
        assert task.escalation == "fable"

    def test_explicit_model_and_escalation_parsed(self, tmp_path):
        manifest_file = tmp_path / "m.yaml"
        manifest_file.write_text(
            "project: p\n"
            "tasks:\n"
            "  - name: t1\n"
            "    description: d\n"
            "    target_dir: src\n"
            "    test_dir: tests\n"
            "    model: haiku\n"
            "    escalation: sonnet\n"
        )
        m = parse_manifest(str(manifest_file))
        assert m.tasks[0].model == "haiku"
        assert m.tasks[0].escalation == "sonnet"

    def test_invalid_model_rejected(self, tmp_path):
        manifest_file = tmp_path / "m.yaml"
        manifest_file.write_text(
            "project: p\n"
            "tasks:\n"
            "  - name: t1\n"
            "    description: d\n"
            "    target_dir: src\n"
            "    test_dir: tests\n"
            "    model: opus\n"
        )
        with pytest.raises(ValueError, match="invalid model"):
            parse_manifest(str(manifest_file))

    def test_invalid_escalation_rejected(self, tmp_path):
        manifest_file = tmp_path / "m.yaml"
        manifest_file.write_text(
            "project: p\n"
            "tasks:\n"
            "  - name: t1\n"
            "    description: d\n"
            "    target_dir: src\n"
            "    test_dir: tests\n"
            "    escalation: haiku\n"
        )
        with pytest.raises(ValueError, match="invalid escalation"):
            parse_manifest(str(manifest_file))

    def test_escalation_must_be_higher_tier_than_model(self, tmp_path):
        manifest_file = tmp_path / "m.yaml"
        manifest_file.write_text(
            "project: p\n"
            "tasks:\n"
            "  - name: t1\n"
            "    description: d\n"
            "    target_dir: src\n"
            "    test_dir: tests\n"
            "    model: sonnet\n"
            "    escalation: sonnet\n"
        )
        with pytest.raises(ValueError, match="higher tier"):
            parse_manifest(str(manifest_file))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_manifest.py::TestTierFields -v`
Expected: 5 failures — `TypeError`/`AttributeError` on the missing `model` attribute and `Failed: DID NOT RAISE` for the three rejection tests.

- [ ] **Step 3: Implement in `lib/manifest.py`**

Add two fields to `ManifestTask` (after `depends_on`):

```python
    model: str = "sonnet"
    escalation: str = "fable"
```

Add module-level constants directly above `_REQUIRED_TASK_FIELDS`:

```python
_VALID_MODELS = ["haiku", "sonnet"]
_VALID_ESCALATIONS = ["sonnet", "fable"]
_TIER_ORDER = {"haiku": 0, "sonnet": 1, "fable": 2}
```

Extend `_validate_task_fields` — after the existing required-field loop, add:

```python
    model = raw.get("model", "sonnet")
    escalation = raw.get("escalation", "fable")
    if model not in _VALID_MODELS:
        raise ValueError(
            f"Task {index} has invalid model: {model} (valid: {_VALID_MODELS})"
        )
    if escalation not in _VALID_ESCALATIONS:
        raise ValueError(
            f"Task {index} has invalid escalation: {escalation} "
            f"(valid: {_VALID_ESCALATIONS})"
        )
    if _TIER_ORDER[escalation] <= _TIER_ORDER[model]:
        raise ValueError(
            f"Task {index}: escalation '{escalation}' must be a "
            f"higher tier than model '{model}'"
        )
```

In `parse_manifest`, extend the `ManifestTask(...)` construction with:

```python
                model=raw.get("model", "sonnet"),
                escalation=raw.get("escalation", "fable"),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_manifest.py -v`
Expected: all PASS (new TestTierFields plus all pre-existing manifest tests).

- [ ] **Step 5: Commit**

```bash
git add lib/manifest.py tests/test_manifest.py
git commit -m "feat(delegate): per-task model/escalation tier fields in manifest"
```

---

### Task 2: SpawnRequest carries the current tier

**Files:**
- Modify: `lib/orchestrator.py` (SpawnRequest dataclass ~line 21, `get_pending_tasks` ~line 189, `pending --json` CLI branch in `main()`)
- Test: `tests/test_parallel_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Append to the end of `tests/test_parallel_orchestrator.py`:

```python
@pytest.fixture
def tiered_manifest_path(tmp_path):
    """Manifest with explicit per-task tiers. max_retries=1 keeps
    escalation tests short: one 'retrying', then the escalation decision."""
    content = """\
project: tiered-project
base_branch: main
max_retries: 1
tasks:
  - name: leaf
    description: "Mechanical leaf task"
    target_dir: src/leaf
    test_dir: tests/test_leaf
    model: haiku
    escalation: sonnet
  - name: core
    description: "Locally-reasoned task"
    target_dir: src/core
    test_dir: tests/test_core
    model: sonnet
"""
    path = tmp_path / "tiered.yaml"
    path.write_text(content)
    return str(path)


@pytest.fixture
def tiered_orchestrator(tmp_state_dir, tiered_manifest_path):
    orch = ParallelOrchestrator()
    orch.load_manifest(tiered_manifest_path)
    return orch


class TestTierPassthrough:
    def test_spawn_requests_carry_manifest_model(self, tiered_orchestrator):
        tiered_orchestrator.start()
        pending = {r.task_name: r for r in tiered_orchestrator.get_pending_tasks()}
        assert pending["leaf"].model == "haiku"
        assert pending["core"].model == "sonnet"

    def test_state_model_overrides_manifest_model(self, tiered_orchestrator):
        """After a tier bump, state['model'] is the current tier."""
        tiered_orchestrator.start()
        tiered_orchestrator._state.update_task("leaf", model="sonnet")
        tiered_orchestrator._state.save()
        pending = {r.task_name: r for r in tiered_orchestrator.get_pending_tasks()}
        assert pending["leaf"].model == "sonnet"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_parallel_orchestrator.py::TestTierPassthrough -v`
Expected: FAIL — `AttributeError: 'SpawnRequest' object has no attribute 'model'`.

- [ ] **Step 3: Implement in `lib/orchestrator.py`**

Add a field to `SpawnRequest` (after `worktree_dir`):

```python
    model: str = "sonnet"
```

In `get_pending_tasks`, after the line `worktree_dir = ts.get("worktree_dir", "")`, add:

```python
                model = ts.get("model", task.model)
```

and extend the `pending.append(SpawnRequest(...))` call with:

```python
                    model=model,
```

In `main()`, in the `pending` command's `--json` branch, add a `"model"` key to the per-request dict:

```python
                    "model": req.model,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_parallel_orchestrator.py -v`
Expected: all PASS (new and pre-existing).

- [ ] **Step 5: Verify the CLI end-to-end**

```bash
python3 -c "
import subprocess, json, tempfile, os
m = '''project: cli-check
tasks:
  - name: t1
    description: d
    target_dir: src
    test_dir: tests
    model: haiku
'''
with tempfile.TemporaryDirectory() as d:
    os.environ['ORCHESTRATION_STATE_DIR'] = d
    p = os.path.join(d, 'm.yaml')
    open(p, 'w').write(m)
    subprocess.run(['python3', 'lib/orchestrator.py', 'start', p, ''], check=True, capture_output=True)
    out = subprocess.run(['python3', 'lib/orchestrator.py', 'pending', p, '--json'], check=True, capture_output=True, text=True)
    data = json.loads(out.stdout)
    assert data[0]['model'] == 'haiku', data
    print('CLI model passthrough OK')
"
```

Expected output: `CLI model passthrough OK`
(If `start` with an empty cwd errors in this environment, run the same check but call `ParallelOrchestrator` directly in-process: load, `start()`, `get_pending_tasks()`, assert `.model == 'haiku'`.)

- [ ] **Step 6: Commit**

```bash
git add lib/orchestrator.py tests/test_parallel_orchestrator.py
git commit -m "feat(delegate): SpawnRequest and pending --json carry current model tier"
```

---

### Task 3: Escalation outcome in `record_completion`

**Files:**
- Modify: `lib/orchestrator.py` (`record_completion` ~line 235)
- Test: `tests/test_parallel_orchestrator.py`

Behavior being built: when a task exhausts `max_retries` at its current tier, instead of going straight to `failed` it bumps to its `escalation` tier (status back to `pending`, `retries` reset to 0, `escalated_from` recorded) and `record_completion` returns `"escalated"`. If the escalation tier is `fable`, or the task already ran at its escalation tier, it fails — the skill then routes it to the workflow's escalate phase. The escalated task gets a *fresh* `build_subagent_prompt` (not the retry prompt) because `retries` is 0 — intentional: the higher-tier worker starts clean in the preserved worktree.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_parallel_orchestrator.py` (uses the `tiered_orchestrator` fixture from Task 2; `max_retries=1`, so failures go: first → `retrying`, second → escalation decision):

```python
class TestEscalation:
    def test_escalates_after_max_retries(self, tiered_orchestrator):
        tiered_orchestrator.start()
        assert tiered_orchestrator.record_completion(
            "leaf", success=False, error="red"
        ) == "retrying"
        result = tiered_orchestrator.record_completion(
            "leaf", success=False, error="still red"
        )
        assert result == "escalated"
        task_state = tiered_orchestrator.get_status()["tasks"]["leaf"]
        assert task_state["status"] == "pending"
        assert task_state["model"] == "sonnet"
        assert task_state["retries"] == 0
        assert task_state["escalated_from"] == "haiku"

    def test_escalated_task_redispatches_at_higher_tier(self, tiered_orchestrator):
        tiered_orchestrator.start()
        tiered_orchestrator.record_completion("leaf", success=False, error="e")
        tiered_orchestrator.record_completion("leaf", success=False, error="e")
        pending = {r.task_name: r for r in tiered_orchestrator.get_pending_tasks()}
        assert pending["leaf"].model == "sonnet"

    def test_fails_for_good_at_escalation_tier(self, tiered_orchestrator):
        tiered_orchestrator.start()
        tiered_orchestrator.record_completion("leaf", success=False, error="e1")
        assert tiered_orchestrator.record_completion(
            "leaf", success=False, error="e2"
        ) == "escalated"
        assert tiered_orchestrator.record_completion(
            "leaf", success=False, error="e3"
        ) == "retrying"
        result = tiered_orchestrator.record_completion(
            "leaf", success=False, error="e4"
        )
        assert result == "failed"
        task_state = tiered_orchestrator.get_status()["tasks"]["leaf"]
        assert task_state["status"] == "failed"

    def test_fable_escalation_fails_without_redispatch(self, tiered_orchestrator):
        """'core' has escalation: fable -> no spawnable higher tier, so
        exhausted retries mean failed (skill routes to escalate phase,
        where Fable handles it personally)."""
        tiered_orchestrator.start()
        assert tiered_orchestrator.record_completion(
            "core", success=False, error="e1"
        ) == "retrying"
        result = tiered_orchestrator.record_completion(
            "core", success=False, error="e2"
        )
        assert result == "failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_parallel_orchestrator.py::TestEscalation -v`
Expected: the first three tests FAIL (`'failed' == 'escalated'` mismatches); `test_fable_escalation_fails_without_redispatch` PASSES already (existing behavior) — fine, it pins the contract.

- [ ] **Step 3: Implement in `lib/orchestrator.py`**

Change `record_completion`'s return type:

```python
    def record_completion(
        self, task_name: str, success: bool, error: str = ""
    ) -> Literal["completed", "retrying", "failed", "escalated"]:
```

Replace the existing retries-exhausted block:

```python
        if retries >= self._manifest.max_retries:
            self._state.update_task(
                task_name, status="failed", last_error=error
            )
            self._propagate_failure(task_name)
            self._update_phase()
            self._state.save()
            return "failed"
```

with:

```python
        if retries >= self._manifest.max_retries:
            task = next(
                t for t in self._manifest.tasks if t.name == task_name
            )
            current_model = task_state.get("model", task.model)
            if task.escalation != "fable" and current_model != task.escalation:
                self._state.update_task(
                    task_name,
                    status="pending",
                    retries=0,
                    model=task.escalation,
                    last_error=error,
                    escalated_from=current_model,
                )
                self._update_phase()
                self._state.save()
                return "escalated"
            self._state.update_task(
                task_name, status="failed", last_error=error
            )
            self._propagate_failure(task_name)
            self._update_phase()
            self._state.save()
            return "failed"
```

No CLI change needed: the `complete` command already prints `Result: {result}`, which now surfaces `escalated`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_parallel_orchestrator.py tests/test_manifest.py -v`
Expected: all PASS. Pre-existing retry/failure tests keep passing because their tasks carry the defaults (`model: sonnet`, `escalation: fable`), which preserve the old exhausted-retries → `failed` behavior.

- [ ] **Step 5: Commit**

```bash
git add lib/orchestrator.py tests/test_parallel_orchestrator.py
git commit -m "feat(delegate): escalated outcome bumps task to escalation tier"
```

---

### Task 4: Workflow config + governance (delegate.yaml, permissions, conformance)

**Files:**
- Create: `config/workflows/delegate.yaml`
- Modify: `lib/permission_query.py:14` (`_KNOWN_WORKFLOWS`)
- Modify: `config/permissions.yaml` (append under the `workflows:` section, line 99+)
- Modify: `tests/test_conformance_static.py` (`CORE_GOVERNED`)
- Test: `tests/test_delegate_workflow_config.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_delegate_workflow_config.py`:

```python
"""Tests for the delegate workflow YAML configuration and its governance.

TDD: defines the expected structure of config/workflows/delegate.yaml
and its L1 governance before the files are modified.
"""
import sys
from pathlib import Path

import yaml
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

PROJECT_ROOT = Path(__file__).parent.parent
DELEGATE_YAML = PROJECT_ROOT / "config" / "workflows" / "delegate.yaml"

ALL_PHASES = ["decompose", "dispatch", "monitor", "escalate", "integrate"]
CHECKPOINT_PHASES = {"escalate", "integrate"}
FABLE_PHASES = {"decompose", "escalate", "integrate"}

EXPECTED_TRANSITIONS = {
    "decompose": {"dispatch"},
    "dispatch": {"monitor"},
    "monitor": {"dispatch", "escalate", "integrate"},
    "escalate": {"dispatch", "integrate"},
    "integrate": {"done"},
}


@pytest.fixture(scope="module")
def config():
    assert DELEGATE_YAML.exists(), f"delegate.yaml not found at {DELEGATE_YAML}"
    with open(DELEGATE_YAML) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def phases_by_name(config):
    return {p["name"]: p for p in config["phases"]}


class TestStructure:
    def test_name_and_terminals(self, config):
        assert config["name"] == "delegate"
        assert config["initial_phase"] == "decompose"
        assert config["terminal_phase"] == "done"

    def test_all_phases_declared_in_order(self, phases_by_name):
        assert list(phases_by_name) == ALL_PHASES

    def test_checkpoints(self, phases_by_name):
        for name, phase in phases_by_name.items():
            expected = name in CHECKPOINT_PHASES
            assert phase.get("checkpoint", False) == expected, name

    def test_fable_phases_carry_advisory_model(self, phases_by_name):
        for name in FABLE_PHASES:
            assert phases_by_name[name].get("model") == "fable", name

    def test_transitions(self, config):
        actual = {k: set(v) for k, v in config["transitions"].items()}
        assert actual == EXPECTED_TRANSITIONS


class TestDaemonLoader:
    def test_loads_via_daemon_loader(self):
        from lib.daemon import load_workflow_configs
        configs = load_workflow_configs(PROJECT_ROOT / "config")
        assert "delegate" in configs
        wf = configs["delegate"]
        assert wf.initial_phase == "decompose"
        assert wf.terminal_phase == "done"
        assert wf.transitions["monitor"] == {"dispatch", "escalate", "integrate"}
        assert wf.phases["escalate"].checkpoint is True
        assert wf.phases["integrate"].checkpoint is True


class TestGovernance:
    def test_delegate_in_known_workflows(self):
        from lib.permission_query import _KNOWN_WORKFLOWS
        assert "delegate" in _KNOWN_WORKFLOWS

    def test_delegate_fully_governed(self):
        from lib.conformance import analyze
        by_name = {r.name: r for r in analyze()["workflows"]}
        assert "delegate" in by_name
        assert not by_name["delegate"].fail_open, by_name["delegate"].notes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_delegate_workflow_config.py -v`
Expected: FAIL — `delegate.yaml not found`, `'delegate' not in _KNOWN_WORKFLOWS`, etc.

- [ ] **Step 3: Create `config/workflows/delegate.yaml`**

```yaml
name: delegate
description: "Fable decomposes into a tiered manifest; cheap models execute; Fable escalates and integrates"
initial_phase: decompose
terminal_phase: done
max_agents: 8

phases:
  # FABLE touchpoint 1: read codebase, write the tiered task manifest.
  # `model` is advisory metadata read by the skill, not enforced by the
  # daemon (the loader ignores unknown keys).
  - name: decompose
    model: fable
    allowed_tool_categories:
      - FILE_READ
      - FILE_SEARCH
      - CODE_QUERY
      - FILE_WRITE
      - SHELL_SAFE
    blocked_tools: []
    eligible_agents:
      - architect
    checkpoint: false

  # Spawn pending tasks at their manifest tier (Agent tool, model override).
  - name: dispatch
    allowed_tool_categories:
      - SUBAGENT
      - SHELL_SAFE
      - FILE_READ
    blocked_tools:
      - native__write_file
      - native__edit_file
    eligible_agents: []
    checkpoint: false

  # Poll orchestrator state; record completions/failures/escalations.
  - name: monitor
    allowed_tool_categories:
      - SHELL_SAFE
      - FILE_READ
      - SUBAGENT
    blocked_tools:
      - native__write_file
      - native__edit_file
    eligible_agents: []
    checkpoint: false

  # FABLE touchpoint 2: tasks that failed at their top tier.
  # Fable re-specs, splits, or absorbs them.
  - name: escalate
    model: fable
    allowed_tool_categories:
      - FILE_READ
      - FILE_SEARCH
      - CODE_QUERY
      - FILE_WRITE
      - SHELL_SAFE
    blocked_tools: []
    eligible_agents: []
    checkpoint: true

  # FABLE touchpoint 3: merge, full suite, one coherence review.
  - name: integrate
    model: fable
    allowed_tool_categories:
      - FILE_READ
      - CODE_QUERY
      - SHELL_SAFE
      - CODE_EDIT
    blocked_tools:
      - native__write_file
    eligible_agents: []
    checkpoint: true

transitions:
  decompose:
    - dispatch
  dispatch:
    - monitor
  monitor:
    - dispatch
    - escalate
    - integrate
  escalate:
    - dispatch
    - integrate
  integrate:
    - done
```

- [ ] **Step 4: Register in `_KNOWN_WORKFLOWS`**

In `lib/permission_query.py` line 14, change:

```python
_KNOWN_WORKFLOWS = ["iterate", "debug", "pr_comment", "simple", "develop", "experiment", "orchestrate"]
```

to:

```python
_KNOWN_WORKFLOWS = ["iterate", "debug", "pr_comment", "simple", "develop", "experiment", "orchestrate", "delegate"]
```

- [ ] **Step 5: Add the L1 governance block to `config/permissions.yaml`**

Append at the end of the `workflows:` section (same indentation as the `develop:` block):

```yaml
  # Delegate workflow — Fable decomposes into a tiered manifest; haiku/sonnet
  # workers execute via parallel-orchestrate; Fable escalates and integrates.
  delegate:
    decompose:
      allowed: [native__read_file, native__glob, native__grep, serena__*, context7__*, native__write_file, native__bash(python*), workflow__*]
      blocked: [native__edit_file]
    dispatch:
      allowed: [Task, native__read_file, native__bash(python*), workflow__*]
      blocked: [native__write_file, native__edit_file]
    monitor:
      allowed: [Task, native__read_file, native__bash(python*), workflow__*]
      blocked: [native__write_file, native__edit_file]
    escalate:
      allowed: [native__read_file, native__glob, native__grep, serena__*, native__write_file, native__edit_file, native__bash(python*), workflow__*]
      blocked: []
    integrate:
      allowed: [native__read_file, native__glob, native__grep, serena__*, native__edit_file, native__bash(python*), native__bash(pytest*), native__bash(git*), workflow__*]
      blocked: [native__write_file]
```

- [ ] **Step 6: Pin delegate as core-governed in the conformance baseline**

In `tests/test_conformance_static.py`, change:

```python
CORE_GOVERNED = {"simple", "iterate", "orchestrate"}
```

to:

```python
CORE_GOVERNED = {"simple", "iterate", "orchestrate", "delegate"}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_delegate_workflow_config.py tests/test_conformance_static.py -v`
Expected: all PASS. If `test_delegate_fully_governed` fails, read the `notes` in the assertion message — it names exactly which phase is missing at L1 (fix the permissions.yaml block, not the test).

- [ ] **Step 8: Commit**

```bash
git add config/workflows/delegate.yaml config/permissions.yaml lib/permission_query.py tests/test_delegate_workflow_config.py tests/test_conformance_static.py
git commit -m "feat(delegate): phase-gated delegate workflow, fully governed at L1"
```

---

### Task 5: The driving skill (`skills/delegate/SKILL.md`)

**Files:**
- Create: `skills/delegate/SKILL.md`

- [ ] **Step 1: Create `skills/delegate/SKILL.md` with this exact content**

````markdown
---
name: delegate
description: Fable decomposes work into a tiered task manifest; haiku/sonnet workers execute in parallel worktrees; Fable re-enters only for escalations and integration.
user_invocable: true
---

# Delegate

You (Fable) are the coherence-holder. You touch the work exactly three
times — **decompose**, **escalate**, **integrate**. Everything in between
runs on cheaper models through the parallel-orchestrate machinery.

## Phases

```
decompose → dispatch → monitor ⇄ dispatch (retries / tier bumps)
                          ↓
                      escalate → dispatch
                          ↓
                      integrate → done
```

| Phase | Driver | Purpose |
|-------|--------|---------|
| decompose | Fable | Read codebase, write tiered manifest, start orchestrator |
| dispatch | mechanical | Spawn pending tasks at their tier |
| monitor | mechanical | Record completions; orchestrator handles retries/bumps |
| escalate | Fable (checkpoint) | Re-spec / split / absorb top-tier failures |
| integrate | Fable (checkpoint) | Merge, full suite, one coherence review |

## Start

```
workflow__workflow_start(workflow_id="delegate", task="<description>")
mkdir -p .delegate/
```

## 1. decompose (Fable touchpoint 1)

Read the code you are decomposing. Then write the manifest to
`.delegate/<slug>.yaml`.

**Decomposition contract — every task you emit MUST be:**

- **Self-contained.** The description inlines everything the worker
  needs: exact file paths, interfaces to implement, types to use,
  acceptance criteria. The worker never re-explores the codebase and
  never makes an architectural judgment.
- **Verifiable.** Tests define done (`min_tests` enforced by the TDD
  worker prompt).
- **Bounded.** Explicit `target_dir`/`test_dir`; no cross-cutting edits.

**Inverse rule (load-bearing):** anything coherence-bound stays with
you. If you cannot spec a task tightly enough for a cheap model, split
it further or keep it for yourself in integrate. Delegation is for leaf
work, never the architectural core.

**Tier rubric:**

| Tier | Use for | escalation |
|------|---------|------------|
| `model: haiku` | Mechanical, well-templated work (CRUD, data classes, boilerplate tests, format conversions) | `sonnet` |
| `model: sonnet` | Local reasoning within one module (algorithms, refactors with clear contracts) | `fable` (default) |

`escalation: fable` means: no re-dispatch — the first top-tier failure
routes to you in the escalate phase.

**Manifest format** — parallel-orchestrate schema plus the two tier fields:

```yaml
project: <slug>
base_branch: main
max_retries: 2
tasks:
  - name: 1-todo-store
    description: |
      <fully self-contained spec: files, interfaces, acceptance criteria>
    target_dir: src/store
    test_dir: tests/store
    min_tests: 10
    model: haiku
    escalation: sonnet
    depends_on: []
```

Then initialize and advance:

```bash
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py load .delegate/<slug>.yaml
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py start .delegate/<slug>.yaml <cwd>
```

```
workflow__advance_phase(wf_id, "dispatch")
```

## 2. dispatch

```bash
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py pending .delegate/<slug>.yaml --json
```

For each entry, spawn a worker with the **Agent tool**:

- `subagent_type: "general-purpose"` (same as parallel-orchestrate)
- `model: <entry.model>` — **this is the tiering lever; never omit it**
- `prompt`: the `prompt` field verbatim
- Spawn all pending tasks **in parallel** — worktrees isolate them

Record each spawn, then advance:

```bash
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py spawned .delegate/<slug>.yaml <task_name> <worker_id>
```

```
workflow__advance_phase(wf_id, "monitor")
```

## 3. monitor

As workers complete, record results:

```bash
# success
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py complete .delegate/<slug>.yaml <task_name>
# failure
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py complete .delegate/<slug>.yaml <task_name> "<error>"
```

Route on the printed `Result:`:

- `retrying` → advance to dispatch, re-spawn at the same tier
- `escalated` → advance to dispatch, re-spawn (the pending entry now
  carries the bumped tier — spawn with the new `model`)
- `failed` → advance to escalate
- all tasks `completed` → advance to integrate

Do not investigate failures yourself in this phase — that is what the
tier bump is for. You read code again only in escalate/integrate.

## 4. escalate (Fable touchpoint 2 — checkpoint)

Entered only when a task failed at its top tier. For each failed task,
pick one:

1. **Re-spec** — the task spec was ambiguous or wrong. Rewrite its
   manifest description, reset it, return to dispatch.
2. **Split** — too big for one worker. Replace it with smaller manifest
   tasks, return to dispatch.
3. **Absorb** — it was coherence-bound after all. Mark it yours; do it
   personally during integrate.

Then `workflow__advance_phase(wf_id, "dispatch")` (cases 1–2) or
`workflow__advance_phase(wf_id, "integrate")` (case 3 or nothing left).

## 5. integrate (Fable touchpoint 3 — checkpoint)

```bash
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py merge .delegate/<slug>.yaml <cwd>
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py verify .delegate/<slug>.yaml <cwd>
```

Then do **one coherence review of the merged diff** (`git diff
<base_branch>...HEAD`): naming drift across tasks, duplicated helpers,
interface mismatches, violated invariants. Fix what you find — this is
also where absorbed tasks get done. Do not re-review individual tasks;
workers already passed their test gates.

On suite failure, offer the standard three options: fix and retry /
rollback / continue anyway.

Finish:

```bash
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py summary .delegate/<slug>.yaml
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py stop .delegate/<slug>.yaml <cwd>
```

```
workflow__advance_phase(wf_id, "done")
workflow__workflow_stop(workflow_id="delegate")
```

## Cost discipline

- Your tokens are the expensive ones. If you notice yourself reading
  worker diffs during monitor, stop — that is integrate's job, once.
- Prefer more, smaller haiku tasks over fewer, bigger sonnet tasks
  **only when** the spec-writing overhead stays small; a task whose
  description takes longer to write than the work itself should be
  absorbed or batched.
- Every escalation is recorded in orchestrator state
  (`escalated_from`); check `summary` output to calibrate your tier
  rubric over time.
````

- [ ] **Step 2: Verify the skill file**

```bash
python3 -c "
import yaml, pathlib
text = pathlib.Path('skills/delegate/SKILL.md').read_text()
assert text.startswith('---')
fm = yaml.safe_load(text.split('---')[1])
assert fm['name'] == 'delegate'
assert fm['user_invocable'] is True
print('SKILL.md frontmatter OK')
"
```

Expected output: `SKILL.md frontmatter OK`

- [ ] **Step 3: Commit**

```bash
git add skills/delegate/SKILL.md
git commit -m "feat(delegate): driving skill with decomposition contract and tier rubric"
```

---

### Task 6: Demo manifest + round-trip test

**Files:**
- Create: `config/manifests/demo_delegate.yaml`
- Test: `tests/test_demo_delegate_manifest.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_demo_delegate_manifest.py`:

```python
"""The demo delegate manifest parses and carries tier fields end-to-end."""
from pathlib import Path

from lib.manifest import parse_manifest

DEMO = Path(__file__).parent.parent / "config" / "manifests" / "demo_delegate.yaml"


def test_demo_manifest_parses_with_tiers():
    m = parse_manifest(str(DEMO))
    assert m.project == "demo-delegate"
    tiers = {t.name: (t.model, t.escalation) for t in m.tasks}
    assert tiers["greeting"] == ("haiku", "sonnet")
    assert tiers["word_count"] == ("sonnet", "fable")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_demo_delegate_manifest.py -v`
Expected: FAIL — `FileNotFoundError: Manifest not found`.

- [ ] **Step 3: Create `config/manifests/demo_delegate.yaml`**

```yaml
# Demo manifest for the delegate workflow: two tiny tiered tasks.
# Smoke-test with:
#   python3 lib/orchestrator.py load config/manifests/demo_delegate.yaml

project: demo-delegate
base_branch: main
max_retries: 2

tasks:
  - name: greeting
    description: |
      Implement a greet(name: str) -> str function in src/greeting/greeting.py.
      Returns "Hello, {name}!". Raises ValueError on empty or whitespace-only
      name. Strip surrounding whitespace before formatting.
    target_dir: src/greeting
    test_dir: tests/test_greeting
    min_tests: 5
    model: haiku
    escalation: sonnet

  - name: word_count
    description: |
      Implement word_count(text: str) -> dict[str, int] in src/word_count/word_count.py.
      Case-insensitive, strips punctuation (string.punctuation), splits on
      whitespace, returns counts keyed by lowercased word. Empty string
      returns {}.
    target_dir: src/word_count
    test_dir: tests/test_word_count
    min_tests: 5
    model: sonnet
    escalation: fable
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_demo_delegate_manifest.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config/manifests/demo_delegate.yaml tests/test_demo_delegate_manifest.py
git commit -m "feat(delegate): tiered demo manifest"
```

---

### Task 7: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run every test module this plan touched**

Run:
```bash
python3 -m pytest tests/test_manifest.py tests/test_parallel_orchestrator.py tests/test_delegate_workflow_config.py tests/test_demo_delegate_manifest.py tests/test_conformance_static.py -v
```
Expected: all PASS.

- [ ] **Step 2: Run the conformance CLI for a human-readable governance check**

Run: `python3 -m lib.conformance`
Expected: `delegate` listed with flag `ok` (not `FAIL-OPEN`).

- [ ] **Step 3: Run the full suite to catch cross-module regressions**

Run: `python3 -m pytest tests/ -q --ignore=tests/integration --ignore=tests/maintenance`
Expected: no failures in files this plan touched; pre-existing failures elsewhere on the branch are out of scope — compare against the branch baseline before claiming regression.

- [ ] **Step 4: Final commit (only if fixups were needed)**

```bash
git add -A
git commit -m "test(delegate): full verification fixups"
```

---

## Out of scope (deliberate)

- **Daemon restart / live router pickup.** The daemon loads workflow
  configs at startup; exercising live phase gating requires a daemon
  restart, which is session-disruptive. The conformance + loader tests
  cover the contract; first live use of `/delegate` validates the rest.
- **Worker-spawn live check.** Spec risk "worker spawn path": the skill
  copies parallel-orchestrate's spawn pattern verbatim (native Agent
  tool, `general-purpose`, now with `model`). If parallel-orchestrate
  works today, delegate's dispatch works; if it is broken, fixing it is
  its own task, not this plan's.
- **Auto-tier learning.** `escalated_from` is recorded for later
  calibration; no automation built on it yet (YAGNI).
