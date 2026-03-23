# Experiment Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `/experiment-batch` — a skill that discovers multiple tasks from a query, resolves them into per-task goal.yaml files, and orchestrates parallel experiment runs with a two-level eval hierarchy.

**Architecture:** A new skill (SKILL.md) defines the protocol. A new `lib/batch_resolver.py` handles task discovery (GitHub search, issue parsing, directory glob). The skill orchestrates by spawning `/experiment` runs per task, gating integration eval on all task evals passing.

**Tech Stack:** Python (resolver library), YAML (goal.yaml schema), GitHub MCP tools (search_issues, issue_read), existing experiment workflow infrastructure.

---

### Task 1: Batch resolver — goal.yaml parsing and validation

**Files:**
- Create: `lib/batch_resolver.py`
- Test: `tests/test_batch_resolver.py`

- [ ] **Step 1: Write failing test — parse query-based goal.yaml**

```python
"""Tests for batch_resolver."""
import pytest
from lib.batch_resolver import parse_batch_goal, BatchGoal


def test_parse_query_based():
    goal = parse_batch_goal({
        "query": "repo:c-daly/agora label:experiment-ready is:open",
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    })
    assert goal.query == "repo:c-daly/agora label:experiment-ready is:open"
    assert goal.tasks == []
    assert goal.success_criteria[0]["metric"] == "test_pass_rate"


def test_parse_explicit_tasks():
    goal = parse_batch_goal({
        "tasks": [{"issue": 42}, {"issue": 43}],
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    })
    assert len(goal.tasks) == 2
    assert goal.tasks[0]["issue"] == 42


def test_parse_inline_tasks():
    goal = parse_batch_goal({
        "tasks": [
            {"target": "agora/adapters/foo.py", "objective": "Build foo"},
        ],
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    })
    assert goal.tasks[0]["target"] == "agora/adapters/foo.py"


def test_parse_mixed():
    goal = parse_batch_goal({
        "query": "repo:c-daly/agora label:ready",
        "tasks": [{"target": "agora/analysis/bar.py", "objective": "Build bar"}],
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    })
    assert goal.query is not None
    assert len(goal.tasks) == 1


def test_parse_on_failure_default():
    goal = parse_batch_goal({
        "tasks": [{"issue": 1}],
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    })
    assert goal.on_failure == "continue"


def test_parse_on_failure_stop():
    goal = parse_batch_goal({
        "tasks": [{"issue": 1}],
        "on_failure": "stop",
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    })
    assert goal.on_failure == "stop"


def test_requires_query_or_tasks():
    with pytest.raises(ValueError, match="query.*tasks"):
        parse_batch_goal({
            "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
        })


def test_requires_success_criteria():
    with pytest.raises(ValueError, match="success_criteria"):
        parse_batch_goal({"tasks": [{"issue": 1}]})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && python -m pytest tests/test_batch_resolver.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_batch_goal'`

- [ ] **Step 3: Implement BatchGoal and parse_batch_goal**

```python
"""Batch resolver — parse batch goal.yaml and resolve tasks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BatchGoal:
    """Parsed batch goal.yaml."""
    query: str | None = None
    tasks: list[dict[str, Any]] = field(default_factory=list)
    success_criteria: list[dict[str, Any]] = field(default_factory=list)
    on_failure: str = "continue"
    constraints: dict[str, Any] = field(default_factory=dict)


def parse_batch_goal(data: dict[str, Any]) -> BatchGoal:
    """Parse and validate a batch goal.yaml dict."""
    query = data.get("query")
    tasks = data.get("tasks", [])

    if not query and not tasks:
        raise ValueError("Batch goal.yaml must have 'query' and/or 'tasks'")

    success_criteria = data.get("success_criteria")
    if not success_criteria:
        raise ValueError("Batch goal.yaml must have 'success_criteria'")

    on_failure = data.get("on_failure", "continue")
    if on_failure not in ("continue", "stop"):
        raise ValueError(f"on_failure must be 'continue' or 'stop', got '{on_failure}'")

    return BatchGoal(
        query=query,
        tasks=tasks,
        success_criteria=success_criteria,
        on_failure=on_failure,
        constraints=data.get("constraints", {}),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && python -m pytest tests/test_batch_resolver.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add lib/batch_resolver.py tests/test_batch_resolver.py
git commit -m "feat: add batch_resolver with BatchGoal parsing and validation"
```

---

### Task 2: Batch resolver — task resolution (GitHub + inline + dir)

**Files:**
- Modify: `lib/batch_resolver.py`
- Test: `tests/test_batch_resolver.py`

- [ ] **Step 1: Write failing tests — resolve_tasks**

```python
import os
import tempfile
import yaml


def test_resolve_inline_tasks():
    goal = BatchGoal(
        tasks=[
            {"target": "agora/adapters/foo.py", "objective": "Build foo"},
            {"target": "agora/adapters/bar.py", "objective": "Build bar"},
        ],
        success_criteria=[{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    )
    with tempfile.TemporaryDirectory() as run_dir:
        resolved = resolve_tasks(goal, run_dir)
        assert len(resolved) == 2
        # Check per-task goal.yaml was created
        for task in resolved:
            task_goal_path = os.path.join(run_dir, "tasks", task["id"], "goal.yaml")
            assert os.path.exists(task_goal_path)
            with open(task_goal_path) as f:
                task_goal = yaml.safe_load(f)
            assert "objective" in task_goal
            assert "target" in task_goal


def test_resolve_deduplicates_by_target():
    goal = BatchGoal(
        tasks=[
            {"target": "agora/adapters/foo.py", "objective": "Build foo"},
            {"target": "agora/adapters/foo.py", "objective": "Build foo again"},
        ],
        success_criteria=[{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    )
    with tempfile.TemporaryDirectory() as run_dir:
        resolved = resolve_tasks(goal, run_dir)
        assert len(resolved) == 1


def test_resolve_inherits_success_criteria():
    goal = BatchGoal(
        tasks=[{"target": "foo.py", "objective": "Build foo"}],
        success_criteria=[{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    )
    with tempfile.TemporaryDirectory() as run_dir:
        resolved = resolve_tasks(goal, run_dir)
        task_goal_path = os.path.join(run_dir, "tasks", resolved[0]["id"], "goal.yaml")
        with open(task_goal_path) as f:
            task_goal = yaml.safe_load(f)
        assert task_goal["success_criteria"][0]["metric"] == "test_pass_rate"


def test_resolve_dir_query():
    with tempfile.TemporaryDirectory() as base:
        # Create two experiment dirs
        for name in ["exp_a", "exp_b"]:
            exp_dir = os.path.join(base, name)
            os.makedirs(exp_dir)
            with open(os.path.join(exp_dir, "goal.yaml"), "w") as f:
                yaml.dump({"objective": f"Do {name}", "target": f"{name}.py"}, f)

        goal = BatchGoal(
            query=f"dir:{base}/*/goal.yaml",
            success_criteria=[{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
        )
        run_dir = tempfile.mkdtemp()
        resolved = resolve_tasks(goal, run_dir)
        assert len(resolved) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && python -m pytest tests/test_batch_resolver.py -v -k resolve`
Expected: FAIL — `ImportError: cannot import name 'resolve_tasks'`

- [ ] **Step 3: Implement resolve_tasks**

Add to `lib/batch_resolver.py`:

```python
import glob
import os
import yaml


def resolve_tasks(goal: BatchGoal, run_dir: str) -> list[dict]:
    """Resolve batch goal into per-task directories with goal.yaml files.

    Returns list of resolved task dicts with 'id' and 'dir' keys.
    """
    raw_tasks: list[dict] = list(goal.tasks)

    # Resolve dir: queries
    if goal.query and goal.query.startswith("dir:"):
        pattern = goal.query[4:]
        for goal_path in sorted(glob.glob(pattern)):
            with open(goal_path) as f:
                task_data = yaml.safe_load(f)
            if task_data:
                raw_tasks.append(task_data)

    # Note: GitHub query resolution is handled by the skill at runtime
    # (requires MCP tools not available in library code).
    # The skill calls search_issues, parses results, and adds to raw_tasks
    # before calling resolve_tasks.

    # Deduplicate by target or issue number
    seen: set[str] = set()
    unique_tasks: list[dict] = []
    for task in raw_tasks:
        key = task.get("target") or str(task.get("issue", id(task)))
        if key not in seen:
            seen.add(key)
            unique_tasks.append(task)

    # Create per-task directories and goal.yaml files
    resolved: list[dict] = []
    tasks_dir = os.path.join(run_dir, "tasks")
    os.makedirs(tasks_dir, exist_ok=True)

    for i, task in enumerate(unique_tasks):
        task_id = _task_id(task, i)
        task_dir = os.path.join(tasks_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)

        # Build task goal.yaml — inherit run-level defaults
        task_goal = dict(task)
        if "success_criteria" not in task_goal:
            task_goal["success_criteria"] = goal.success_criteria
        if "eval" not in task_goal:
            task_goal["eval"] = "eval/"

        with open(os.path.join(task_dir, "goal.yaml"), "w") as f:
            yaml.dump(task_goal, f, default_flow_style=False)

        resolved.append({"id": task_id, "dir": task_dir, **task})

    return resolved


def _task_id(task: dict, index: int) -> str:
    """Generate a stable task ID from task definition."""
    if "issue" in task:
        return str(task["issue"])
    if "target" in task:
        # e.g., agora/adapters/foo.py → foo
        name = os.path.basename(task["target"])
        return os.path.splitext(name)[0]
    return f"task_{index}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && python -m pytest tests/test_batch_resolver.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add lib/batch_resolver.py tests/test_batch_resolver.py
git commit -m "feat: add resolve_tasks with inline, dir, and dedup support"
```

---

### Task 3: Batch resolver — dependency sorting

**Files:**
- Modify: `lib/batch_resolver.py`
- Test: `tests/test_batch_resolver.py`

- [ ] **Step 1: Write failing tests — sort_by_dependencies**

```python
def test_sort_independent_tasks():
    tasks = [
        {"id": "a", "dir": "/tmp/a"},
        {"id": "b", "dir": "/tmp/b"},
    ]
    sorted_tasks = sort_by_dependencies(tasks)
    assert len(sorted_tasks) == 2


def test_sort_with_dependency():
    tasks = [
        {"id": "yield_curve", "dir": "/tmp/yc", "depends_on": ["treasury_adapter"]},
        {"id": "treasury_adapter", "dir": "/tmp/ta"},
    ]
    sorted_tasks = sort_by_dependencies(tasks)
    ids = [t["id"] for t in sorted_tasks]
    assert ids.index("treasury_adapter") < ids.index("yield_curve")


def test_sort_circular_dependency_raises():
    tasks = [
        {"id": "a", "dir": "/tmp/a", "depends_on": ["b"]},
        {"id": "b", "dir": "/tmp/b", "depends_on": ["a"]},
    ]
    with pytest.raises(ValueError, match="[Cc]ircular"):
        sort_by_dependencies(tasks)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && python -m pytest tests/test_batch_resolver.py -v -k sort`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement sort_by_dependencies**

Add to `lib/batch_resolver.py`:

```python
def sort_by_dependencies(tasks: list[dict]) -> list[dict]:
    """Topologically sort tasks by depends_on. Independent tasks retain original order."""
    task_map = {t["id"]: t for t in tasks}
    visited: set[str] = set()
    in_stack: set[str] = set()
    result: list[dict] = []

    def visit(task_id: str) -> None:
        if task_id in in_stack:
            raise ValueError(f"Circular dependency involving '{task_id}'")
        if task_id in visited:
            return
        in_stack.add(task_id)
        task = task_map.get(task_id)
        if task:
            for dep in task.get("depends_on", []):
                visit(dep)
        in_stack.discard(task_id)
        visited.add(task_id)
        if task:
            result.append(task)

    for t in tasks:
        visit(t["id"])

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && python -m pytest tests/test_batch_resolver.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add lib/batch_resolver.py tests/test_batch_resolver.py
git commit -m "feat: add topological sort for task dependencies"
```

---

### Task 4: Experiment-batch SKILL.md

**Files:**
- Create: `skills/experiment-batch/SKILL.md`

- [ ] **Step 1: Write the skill definition**

Create `skills/experiment-batch/SKILL.md` with the full protocol:

```markdown
---
name: experiment-batch
description: "Discover and run multiple experiment tasks from a query or manifest"
user_invocable: true
---

# Experiment Batch

Discover multiple tasks, resolve them into per-task goal.yaml files, run experiments, gate integration eval on all task evals passing.

## Usage

`/experiment-batch <run-directory>`

The run directory must contain a `goal.yaml` with a `query` and/or `tasks` field.

## Protocol

### 1. Read

Load `<run-dir>/goal.yaml`. Parse with `batch_resolver.parse_batch_goal()`.

### 2. Resolve

Build the task list:

**If `query` starts with `dir:`:**
- Glob for goal.yaml files, each becomes a task

**If `query` is a GitHub search string:**
- Call `search_issues` MCP tool with the query
- For each issue, call `issue_read` to get full fields
- Parse issue body fields (agora-task template maps 1:1 to goal.yaml)
- Add to task list

**If `tasks` is set:**
- Inline definitions used directly
- Issue references resolved via `issue_read`

Merge query results with explicit tasks. Deduplicate by target path or issue number.

Call `batch_resolver.resolve_tasks()` to create per-task directories with goal.yaml files.

Sort by dependencies via `batch_resolver.sort_by_dependencies()`.

Report resolved task list to user.

### 3. Execute Tasks

For each task (respecting dependency order, parallelizing independent tasks):

1. Run `/experiment-setup` on the task directory (validate goal, generate constraints + eval if missing)
2. Run `/experiment` on the task directory (read → plan → work → eval → review → journal → decide)
3. Record result in run journal

If a task fails and `on_failure: continue`, skip it and proceed to next independent task. If `on_failure: stop`, halt the batch.

### 4. Task Eval Gate

After all tasks have been attempted:
- Check that ALL task evals passed
- If any failed, report which tasks failed and stop — do not run integration eval

### 5. Integration Eval (optional)

If `<run-dir>/eval/` exists:
- Run: `python -m pytest <run-dir>/eval/ -v -s`
- Parse [METRIC] from output
- If integration fails, identify the likely task from the traceback and report

If no run-level eval/ exists, skip this step.

### 6. Report

Summary table:

| Task | Status | Tests | Notes |
|------|--------|-------|-------|
| #42 sec_ftd | PASS | 18/18 | |
| #43 treasury | PASS | 21/21 | |
| #44 yield_curve | PASS | 17/17 | |
| Integration | PASS | 5/5 | |

The agent's job ends at reporting. It does NOT close issues, merge code, or archive the directory.
```

- [ ] **Step 2: Verify skill loads**

Run: `/reload-plugins` and check that `experiment-batch` appears in the skill list.

- [ ] **Step 3: Commit**

```bash
git add skills/experiment-batch/SKILL.md
git commit -m "feat: add /experiment-batch skill"
```

---

### Task 5: Add experiment-batch workflow config

**Files:**
- Create: `config/workflows/experiment-batch.yaml`

- [ ] **Step 1: Create workflow config**

```yaml
name: experiment-batch
description: "Multi-task experiment batch with eval hierarchy"
initial_phase: resolve
terminal_phase: done
max_iterations: 20
max_agents: 8

phases:
  - name: resolve
    allowed_tool_categories: [FILE_READ, FILE_SEARCH, CODE_QUERY, WEB_RESEARCH]
    blocked_tools: [native__write_file, native__edit_file, native__bash]
    eligible_agents: [pm]
    checkpoint: false

  - name: execute
    allowed_tool_categories: [FILE_READ, FILE_WRITE, CODE_QUERY, CODE_EDIT, FILE_SEARCH, SHELL_SAFE, WEB_RESEARCH]
    blocked_tools: []
    blocked_file_patterns: ["experiments/*/eval/**"]
    eligible_agents: [implementer, reviewer, researcher]
    checkpoint: false

  - name: gate
    allowed_tool_categories: [FILE_READ, SHELL_SAFE]
    blocked_tools: [native__write_file, native__edit_file]
    eligible_agents: [pm]
    checkpoint: false

  - name: integration
    allowed_tool_categories: [FILE_READ, SHELL_SAFE]
    blocked_tools: [native__write_file, native__edit_file]
    eligible_agents: [pm]
    checkpoint: false

  - name: report
    allowed_tool_categories: [FILE_READ, FILE_WRITE]
    blocked_tools: [native__bash]
    allowed_file_patterns: ["experiments/*/journal/**"]
    eligible_agents: [pm]
    checkpoint: false

  - name: done
    allowed_tool_categories: []
    blocked_tools: []
    eligible_agents: []
    checkpoint: false

transitions:
  resolve: [execute]
  execute: [gate]
  gate: [integration, execute, report]
  integration: [report, execute]
  report: [done]
```

- [ ] **Step 2: Register in known workflows**

Add `"experiment-batch"` to `_KNOWN_WORKFLOWS` in both:
- `lib/permission_query.py`
- `lib/protocol_assembly.py`

- [ ] **Step 3: Commit**

```bash
git add config/workflows/experiment-batch.yaml lib/permission_query.py lib/protocol_assembly.py
git commit -m "feat: add experiment-batch workflow config and register"
```

---

### Task 6: Integration test — end-to-end batch with inline tasks

**Files:**
- Create: `tests/test_experiment_batch_e2e.py`

- [ ] **Step 1: Write end-to-end test**

```python
"""End-to-end test for experiment batch resolver.

Tests the full resolve flow with inline tasks in a temporary directory.
Does NOT test actual experiment execution (that requires MCP tools).
"""
import os
import tempfile
import yaml
import pytest

from lib.batch_resolver import parse_batch_goal, resolve_tasks, sort_by_dependencies


def test_e2e_inline_tasks():
    """Full flow: parse → resolve → sort → verify directory structure."""
    batch_goal = {
        "tasks": [
            {"target": "agora/adapters/foo.py", "objective": "Build foo adapter"},
            {"target": "agora/analysis/bar.py", "objective": "Build bar analysis", "depends_on": ["foo"]},
        ],
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
        "on_failure": "continue",
    }

    goal = parse_batch_goal(batch_goal)
    assert goal.on_failure == "continue"

    with tempfile.TemporaryDirectory() as run_dir:
        resolved = resolve_tasks(goal, run_dir)
        assert len(resolved) == 2

        sorted_tasks = sort_by_dependencies(resolved)
        ids = [t["id"] for t in sorted_tasks]
        assert ids.index("foo") < ids.index("bar")

        # Verify directory structure
        for task in resolved:
            task_dir = os.path.join(run_dir, "tasks", task["id"])
            assert os.path.isdir(task_dir)
            goal_path = os.path.join(task_dir, "goal.yaml")
            assert os.path.isfile(goal_path)

            with open(goal_path) as f:
                task_goal = yaml.safe_load(f)
            assert "objective" in task_goal
            assert "success_criteria" in task_goal


def test_e2e_dir_query():
    """Full flow with dir: query picking up existing experiment directories."""
    with tempfile.TemporaryDirectory() as base:
        # Simulate existing experiment dirs
        for name, obj in [("alpha", "Build alpha"), ("beta", "Build beta")]:
            exp_dir = os.path.join(base, "experiments", name)
            os.makedirs(exp_dir)
            with open(os.path.join(exp_dir, "goal.yaml"), "w") as f:
                yaml.dump({"objective": obj, "target": f"src/{name}.py"}, f)

        batch_goal = {
            "query": f"dir:{base}/experiments/*/goal.yaml",
            "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
        }

        goal = parse_batch_goal(batch_goal)

        run_dir = tempfile.mkdtemp()
        resolved = resolve_tasks(goal, run_dir)
        assert len(resolved) == 2

        targets = {t.get("target") for t in resolved}
        assert "src/alpha.py" in targets
        assert "src/beta.py" in targets
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && python -m pytest tests/test_experiment_batch_e2e.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_experiment_batch_e2e.py
git commit -m "test: add end-to-end tests for experiment batch resolver"
```

---

### Task 7: Copy to cache and verify

**Files:**
- No new files — sync and verify

- [ ] **Step 1: Copy new files to plugin cache**

```bash
cp -r skills/experiment-batch /Users/cdaly/.claude/plugins/cache/fearsidhe-plugins/agent-swarm/1.0.0/skills/
cp lib/batch_resolver.py /Users/cdaly/.claude/plugins/cache/fearsidhe-plugins/agent-swarm/1.0.0/lib/
cp config/workflows/experiment-batch.yaml /Users/cdaly/.claude/plugins/cache/fearsidhe-plugins/agent-swarm/1.0.0/config/workflows/
cp lib/permission_query.py /Users/cdaly/.claude/plugins/cache/fearsidhe-plugins/agent-swarm/1.0.0/lib/
cp lib/protocol_assembly.py /Users/cdaly/.claude/plugins/cache/fearsidhe-plugins/agent-swarm/1.0.0/lib/
```

- [ ] **Step 2: Reload plugins and verify**

Run: `/reload-plugins`
Verify: `experiment-batch` appears in skill list

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && python -m pytest tests/test_batch_resolver.py tests/test_experiment_batch_e2e.py -v`
Expected: ALL PASS
