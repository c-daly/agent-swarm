# Experiment Workflow Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fully integrated agent-swarm workflow for autonomous experiment execution — reading tickets, planning approaches, executing work (standalone or integration, local or remote), evaluating results, journaling learnings, and iterating until success criteria are met.

**Architecture:** The experiment workflow follows the same patterns as `iterate` and `develop`: a skill file defines the protocol, a Python workflow engine manages state via DaemonClient, a YAML config defines phase permissions, and `permissions.yaml` enforces tool restrictions. The harness code from `logos-experiments` becomes library code in `lib/`, callable directly by the workflow engine. The workflow supports fan-out parallel hypothesis testing within the work phase, team-based execution for complex experiments, and an extensible execution environment backend (local first, RunPod later).

**Tech Stack:** Python 3.12, agent-swarm daemon (DaemonClient/JSON-RPC), YAML configs, pytest for evals

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `skills/experiment/SKILL.md` | Skill definition — phase flow, kickback table, agent lifecycle, CLI |
| `lib/experiment_workflow.py` | Workflow engine — state machine, transitions, phase validation, CLI |
| `lib/experiment_harness.py` | Harness library — goal loading, journal management, eval execution, metrics parsing |
| `lib/execution_backend.py` | Execution environment abstraction — local backend, extension point for remote |
| `config/workflows/experiment.yaml` | Phase definitions, tool categories, agent roles, transitions |
| `tests/test_experiment_workflow.py` | Workflow engine unit tests |
| `tests/test_experiment_harness.py` | Harness library unit tests |
| `tests/test_execution_backend.py` | Backend abstraction unit tests |

### Modified Files

| File | Change |
|------|--------|
| `config/permissions.yaml` | Add `experiment` workflow section with per-phase tool restrictions |

---

## Chunk 1: Harness Library

Extract the logos-experiments harness into agent-swarm as a library. No workflow yet — just the building blocks that the workflow engine will call.

### Task 1: Goal Loader

**Files:**
- Create: `lib/experiment_harness.py`
- Test: `tests/test_experiment_harness.py`

- [ ] **Step 1: Write failing test for goal loading**

```python
# tests/test_experiment_harness.py
"""Tests for experiment harness library."""
import pytest
import yaml
from pathlib import Path


@pytest.fixture
def tmp_experiment(tmp_path):
    """Create a minimal experiment directory."""
    exp_dir = tmp_path / "test-exp"
    exp_dir.mkdir()
    return exp_dir


def write_goal(exp_dir: Path, goal: dict) -> Path:
    """Helper: write a goal.yaml to an experiment directory."""
    goal_path = exp_dir / "goal.yaml"
    goal_path.write_text(yaml.dump(goal))
    return goal_path


class TestLoadGoal:
    def test_loads_standalone_goal(self, tmp_experiment):
        from experiment_harness import load_goal

        write_goal(tmp_experiment, {
            "objective": "Train a model",
            "eval": "eval/test_model.py",
            "success_criteria": [
                {"metric": "accuracy", "threshold": 0.9, "primary": True}
            ],
        })

        goal = load_goal(tmp_experiment)
        assert goal.objective == "Train a model"
        assert goal.is_standalone
        assert not goal.is_integration
        assert goal.primary_criterion["metric"] == "accuracy"

    def test_loads_integration_goal(self, tmp_experiment):
        from experiment_harness import load_goal

        write_goal(tmp_experiment, {
            "objective": "Add retry to EventBus",
            "eval": "eval/",
            "target": "logos/logos_events/event_bus.py",
            "success_criteria": [
                {"metric": "test_pass_rate", "threshold": 1.0, "primary": True}
            ],
        })

        goal = load_goal(tmp_experiment)
        assert goal.is_integration
        assert goal.target == "logos/logos_events/event_bus.py"

    def test_missing_goal_raises(self, tmp_experiment):
        from experiment_harness import load_goal

        with pytest.raises(FileNotFoundError):
            load_goal(tmp_experiment)

    def test_loads_environment(self, tmp_experiment):
        from experiment_harness import load_goal

        write_goal(tmp_experiment, {
            "objective": "Train on GPU",
            "eval": "eval/",
            "success_criteria": [{"metric": "loss", "threshold": 0.1, "primary": True}],
            "environment": {"type": "runpod", "gpu": "RTX 3090"},
        })

        goal = load_goal(tmp_experiment)
        assert goal.environment["type"] == "runpod"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && python -m pytest tests/test_experiment_harness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'experiment_harness'`

- [ ] **Step 3: Implement Goal dataclass and loader**

```python
# lib/experiment_harness.py
"""Experiment harness library — goal loading, journal management, eval execution.

Shared utilities:
- run_eval(): Run pytest or custom eval, parse metrics — usable by any workflow
- check_criteria(): Check metrics against thresholds — usable by any workflow
- Journal: Append-only structured log — usable by any workflow needing attempt memory

Experiment-specific:
- load_goal(): Parse goal.yaml ticket format
- load_constraints(): Parse constraints.yaml guardrails
"""

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Goal:
    """Parsed goal.yaml with convenience properties."""
    objective: str
    eval: str
    success_criteria: list
    target: Optional[str] = None
    context: Optional[str] = None
    environment: Optional[dict] = None
    constraints: Optional[dict] = None
    _raw: dict = field(default_factory=dict, repr=False)

    @property
    def is_integration(self) -> bool:
        return self.target is not None

    @property
    def is_standalone(self) -> bool:
        return self.target is None

    @property
    def primary_criterion(self) -> Optional[dict]:
        """Return the criterion marked primary: true."""
        for c in self.success_criteria:
            if c.get("primary"):
                return c
        return self.success_criteria[0] if self.success_criteria else None

    def get(self, key, default=None):
        return self._raw.get(key, default)


def load_goal(exp_dir: Path) -> Goal:
    """Load and parse goal.yaml from an experiment directory."""
    goal_path = exp_dir / "goal.yaml"
    if not goal_path.exists():
        raise FileNotFoundError(f"No goal.yaml in {exp_dir}")

    raw = yaml.safe_load(goal_path.read_text())

    return Goal(
        objective=raw.get("objective", ""),
        eval=raw.get("eval", "eval/"),
        success_criteria=raw.get("success_criteria", []),
        target=raw.get("target"),
        context=raw.get("context"),
        environment=raw.get("environment"),
        _raw=raw,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && PYTHONPATH=lib python -m pytest tests/test_experiment_harness.py::TestLoadGoal -v`
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add lib/experiment_harness.py tests/test_experiment_harness.py
git commit -m "feat: add Goal loader for experiment harness"
```

---

### Task 2: Constraints Loader

**Files:**
- Modify: `lib/experiment_harness.py`
- Modify: `tests/test_experiment_harness.py`

- [ ] **Step 1: Write failing test for constraints loading**

```python
# append to tests/test_experiment_harness.py

class TestLoadConstraints:
    def test_loads_constraints(self, tmp_experiment):
        from experiment_harness import load_constraints

        constraints = {
            "time_limits": {"max_hours_per_run": 4},
            "do_not_do": ["Do NOT fine-tune encoder"],
            "escalate_if": ["Cannot load weights"],
        }
        (tmp_experiment / "constraints.yaml").write_text(yaml.dump(constraints))

        result = load_constraints(tmp_experiment)
        assert result.max_hours_per_run == 4
        assert "Do NOT fine-tune encoder" in result.do_not_do
        assert "Cannot load weights" in result.escalate_if

    def test_missing_constraints_returns_empty(self, tmp_experiment):
        from experiment_harness import load_constraints

        result = load_constraints(tmp_experiment)
        assert result.do_not_do == []
        assert result.escalate_if == []
        assert result.max_hours_per_run is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && PYTHONPATH=lib python -m pytest tests/test_experiment_harness.py::TestLoadConstraints -v`
Expected: FAIL — `ImportError: cannot import name 'load_constraints'`

- [ ] **Step 3: Implement Constraints dataclass and loader**

```python
# append to lib/experiment_harness.py

@dataclass
class Constraints:
    """Parsed constraints.yaml — guardrails for experiment execution."""
    max_hours_per_run: Optional[float] = None
    max_total_gpu_hours: Optional[float] = None
    do_not_do: list[str] = field(default_factory=list)
    escalate_if: list[str] = field(default_factory=list)
    known_findings: list[str] = field(default_factory=list)
    _raw: dict = field(default_factory=dict, repr=False)


def load_constraints(exp_dir: Path) -> Constraints:
    """Load constraints.yaml, returning empty Constraints if not found."""
    constraints_path = exp_dir / "constraints.yaml"
    if not constraints_path.exists():
        return Constraints()

    raw = yaml.safe_load(constraints_path.read_text()) or {}
    time_limits = raw.get("time_limits", {})

    return Constraints(
        max_hours_per_run=time_limits.get("max_hours_per_run"),
        max_total_gpu_hours=time_limits.get("max_total_gpu_hours"),
        do_not_do=raw.get("do_not_do", []),
        escalate_if=raw.get("escalate_if", []),
        known_findings=raw.get("known_findings", []),
        _raw=raw,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && PYTHONPATH=lib python -m pytest tests/test_experiment_harness.py::TestLoadConstraints -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add lib/experiment_harness.py tests/test_experiment_harness.py
git commit -m "feat: add Constraints loader for experiment harness"
```

---

### Task 3: Journal Manager

**Files:**
- Modify: `lib/experiment_harness.py`
- Modify: `tests/test_experiment_harness.py`

- [ ] **Step 1: Write failing tests for journal operations**

```python
# append to tests/test_experiment_harness.py

class TestJournal:
    @pytest.fixture
    def journal_dir(self, tmp_experiment):
        d = tmp_experiment / "journal"
        d.mkdir()
        return d

    def test_list_entries_empty(self, tmp_experiment):
        from experiment_harness import Journal

        journal = Journal(tmp_experiment)
        assert journal.list_entries() == []

    def test_add_and_list_entry(self, tmp_experiment):
        from experiment_harness import Journal

        journal = Journal(tmp_experiment)
        journal.add_entry(
            title="MSE baseline",
            hypothesis="Linear projection is sufficient",
            changes="Implemented linear layer",
            result="R@5=0.24, below threshold",
            diagnosis="Frozen encoders have no alignment",
            next_direction="Try fine-tuning text encoder",
        )

        entries = journal.list_entries()
        assert len(entries) == 1
        assert "MSE baseline" in entries[0].name

    def test_entries_auto_increment(self, tmp_experiment):
        from experiment_harness import Journal

        journal = Journal(tmp_experiment)
        journal.add_entry(title="First", hypothesis="A", changes="x",
                         result="fail", diagnosis="d", next_direction="n")
        journal.add_entry(title="Second", hypothesis="B", changes="y",
                         result="pass", diagnosis="d", next_direction="n")

        entries = journal.list_entries()
        assert len(entries) == 2
        assert entries[0].name.startswith("001_")
        assert entries[1].name.startswith("002_")

    def test_summary(self, tmp_experiment):
        from experiment_harness import Journal

        journal = Journal(tmp_experiment)
        journal.add_entry(title="First attempt", hypothesis="A",
                         changes="x", result="fail", diagnosis="d",
                         next_direction="try B")

        summary = journal.summary()
        assert "First attempt" in summary
        assert "try B" in summary
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && PYTHONPATH=lib python -m pytest tests/test_experiment_harness.py::TestJournal -v`
Expected: FAIL — `ImportError: cannot import name 'Journal'`

- [ ] **Step 3: Implement Journal class**

```python
# append to lib/experiment_harness.py

class Journal:
    """Append-only experiment journal.

    Manages numbered markdown entries in experiments/<name>/journal/.
    Entries are never modified — only appended.
    """

    TEMPLATE = """# {title}

**Attempt:** {number}
**Hypothesis:** {hypothesis}

## Changes
{changes}

## Result
{result}

## Diagnosis
{diagnosis}

## Next Direction
{next_direction}
"""

    def __init__(self, exp_dir: Path):
        self.journal_dir = exp_dir / "journal"
        self.journal_dir.mkdir(parents=True, exist_ok=True)

    def list_entries(self) -> list[Path]:
        """List journal entries in order."""
        return sorted(self.journal_dir.glob("*.md"))

    def _next_number(self) -> int:
        entries = self.list_entries()
        if not entries:
            return 1
        last = entries[-1].name
        try:
            return int(last.split("_")[0]) + 1
        except (ValueError, IndexError):
            return len(entries) + 1

    def add_entry(self, *, title: str, hypothesis: str, changes: str,
                  result: str, diagnosis: str, next_direction: str) -> Path:
        """Add a new journal entry. Returns the path to the created file."""
        number = self._next_number()
        slug = title.lower().replace(" ", "_")[:40]
        filename = f"{number:03d}_{slug}.md"
        content = self.TEMPLATE.format(
            title=title, number=number, hypothesis=hypothesis,
            changes=changes, result=result, diagnosis=diagnosis,
            next_direction=next_direction,
        )
        path = self.journal_dir / filename
        path.write_text(content)
        return path

    def summary(self) -> str:
        entries = self.list_entries()
        if not entries:
            return "No journal entries yet."
        return "\n---\n".join(e.read_text() for e in entries)

    def read_all(self) -> str:
        return self.summary()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && PYTHONPATH=lib python -m pytest tests/test_experiment_harness.py::TestJournal -v`
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add lib/experiment_harness.py tests/test_experiment_harness.py
git commit -m "feat: add Journal manager for experiment harness"
```

---

### Task 4: Eval Runner

**Files:**
- Modify: `lib/experiment_harness.py`
- Modify: `tests/test_experiment_harness.py`

- [ ] **Step 1: Write failing tests for eval execution**

```python
# append to tests/test_experiment_harness.py

class TestEvalRunner:
    def test_run_pytest_eval_pass(self, tmp_experiment):
        from experiment_harness import run_eval

        eval_dir = tmp_experiment / "eval"
        eval_dir.mkdir()
        (eval_dir / "test_simple.py").write_text("def test_passes(): assert True\n")

        result = run_eval(tmp_experiment, eval_path="eval/")
        assert result.passed
        assert result.tests_run > 0
        assert result.tests_passed > 0

    def test_run_pytest_eval_fail(self, tmp_experiment):
        from experiment_harness import run_eval

        eval_dir = tmp_experiment / "eval"
        eval_dir.mkdir()
        (eval_dir / "test_simple.py").write_text("def test_fails(): assert False\n")

        result = run_eval(tmp_experiment, eval_path="eval/")
        assert not result.passed
        assert result.tests_failed > 0

    def test_eval_timeout(self, tmp_experiment):
        from experiment_harness import run_eval

        eval_dir = tmp_experiment / "eval"
        eval_dir.mkdir()
        (eval_dir / "test_slow.py").write_text("import time\ndef test_slow(): time.sleep(10)\n")

        result = run_eval(tmp_experiment, eval_path="eval/", timeout=2)
        assert not result.passed
        assert result.timed_out

    def test_eval_result_has_metrics(self, tmp_experiment):
        from experiment_harness import run_eval

        eval_dir = tmp_experiment / "eval"
        eval_dir.mkdir()
        (eval_dir / "test_metrics.py").write_text(
            'def test_with_metric(capsys):\n'
            '    print("[METRIC] accuracy=0.95")\n'
            '    assert True\n'
        )

        result = run_eval(tmp_experiment, eval_path="eval/")
        assert result.passed
        assert result.metrics.get("accuracy") == 0.95
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement EvalResult and run_eval**

```python
# append to lib/experiment_harness.py
import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)
_DEFAULT_EVAL_TIMEOUT = int(os.environ.get("HARNESS_EVAL_TIMEOUT", "300"))


@dataclass
class EvalResult:
    """Result of running an evaluation."""
    passed: bool
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    metrics: dict = field(default_factory=dict)
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0


def _parse_metrics(output: str) -> dict:
    metrics = {}
    for match in re.finditer(r"\[METRIC\]\s*(\w+)\s*=\s*([\d.]+)", output):
        try:
            metrics[match.group(1)] = float(match.group(2))
        except ValueError:
            metrics[match.group(1)] = match.group(2)
    return metrics


def _parse_pytest_summary(output: str) -> tuple[int, int, int]:
    passed = failed = 0
    for m in re.finditer(r"(\d+) passed", output):
        passed = int(m.group(1))
    for m in re.finditer(r"(\d+) failed", output):
        failed = int(m.group(1))
    return passed + failed, passed, failed


def run_eval(exp_dir: Path, eval_path: str = "eval/",
             timeout: int = _DEFAULT_EVAL_TIMEOUT,
             env_override: Optional[dict] = None) -> EvalResult:
    full_eval_path = exp_dir / eval_path
    env = os.environ.copy()
    if env_override:
        env.update(env_override)

    if full_eval_path.is_dir():
        cmd = ["python", "-m", "pytest", str(full_eval_path), "-v", "-s"]
    elif full_eval_path.suffix == ".py":
        cmd = ["python", str(full_eval_path)]
    else:
        cmd = [str(full_eval_path)]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, cwd=str(exp_dir), env=env)
        output = proc.stdout + proc.stderr
        total, passed, failed = _parse_pytest_summary(output)
        return EvalResult(
            passed=(proc.returncode == 0), tests_run=total,
            tests_passed=passed, tests_failed=failed,
            metrics=_parse_metrics(output),
            stdout=proc.stdout, stderr=proc.stderr,
            return_code=proc.returncode,
        )
    except subprocess.TimeoutExpired as e:
        output = (e.stdout or "") + (e.stderr or "")
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return EvalResult(passed=False, timed_out=True,
                          stdout=str(e.stdout or ""), stderr=str(e.stderr or ""),
                          metrics=_parse_metrics(output))
```

- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git add lib/experiment_harness.py tests/test_experiment_harness.py
git commit -m "feat: add eval runner for experiment harness"
```

---

### Task 5: Success Criteria Checker

**Files:**
- Modify: `lib/experiment_harness.py`
- Modify: `tests/test_experiment_harness.py`

- [ ] **Step 1: Write failing tests for criteria checking**

```python
# append to tests/test_experiment_harness.py

class TestCheckCriteria:
    def test_all_criteria_met(self):
        from experiment_harness import check_criteria
        criteria = [
            {"metric": "accuracy", "threshold": 0.9, "primary": True},
            {"metric": "loss", "threshold": 0.1, "comparison": "<="},
        ]
        result = check_criteria(criteria, {"accuracy": 0.95, "loss": 0.05})
        assert result.passed and result.primary_passed

    def test_primary_failed(self):
        from experiment_harness import check_criteria
        criteria = [{"metric": "accuracy", "threshold": 0.9, "primary": True}]
        result = check_criteria(criteria, {"accuracy": 0.7})
        assert not result.passed and not result.primary_passed

    def test_missing_metric(self):
        from experiment_harness import check_criteria
        criteria = [{"metric": "accuracy", "threshold": 0.9, "primary": True}]
        result = check_criteria(criteria, {})
        assert not result.passed

    def test_secondary_failed_primary_passed(self):
        from experiment_harness import check_criteria
        criteria = [
            {"metric": "accuracy", "threshold": 0.9, "primary": True},
            {"metric": "f1", "threshold": 0.85},
        ]
        result = check_criteria(criteria, {"accuracy": 0.95, "f1": 0.7})
        assert result.primary_passed and not result.all_passed
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement criteria checker**

```python
# append to lib/experiment_harness.py

@dataclass
class CriteriaResult:
    passed: bool
    primary_passed: bool
    all_passed: bool
    details: list[dict] = field(default_factory=list)


def check_criteria(criteria: list[dict], metrics: dict) -> CriteriaResult:
    details = []
    primary_passed = all_met = True

    for c in criteria:
        metric_name = c["metric"]
        threshold = c["threshold"]
        comparison = c.get("comparison", ">=")
        is_primary = c.get("primary", False)
        actual = metrics.get(metric_name)

        if actual is None:
            met = False
        elif comparison == ">=": met = actual >= threshold
        elif comparison == "<=": met = actual <= threshold
        elif comparison == ">":  met = actual > threshold
        elif comparison == "<":  met = actual < threshold
        elif comparison == "==": met = actual == threshold
        else: met = actual >= threshold

        details.append({"metric": metric_name, "threshold": threshold,
                        "actual": actual, "met": met, "primary": is_primary})
        if not met:
            all_met = False
            if is_primary:
                primary_passed = False

    return CriteriaResult(passed=primary_passed, primary_passed=primary_passed,
                          all_passed=all_met, details=details)
```

- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git add lib/experiment_harness.py tests/test_experiment_harness.py
git commit -m "feat: add success criteria checker for experiment harness"
```

---

## Chunk 2: Execution Backend

### Task 6: Execution Backend Abstraction

**Files:**
- Create: `lib/execution_backend.py`
- Create: `tests/test_execution_backend.py`

- [ ] **Step 1: Write failing tests for local backend**

```python
# tests/test_execution_backend.py
"""Tests for execution backend abstraction."""
import pytest
from pathlib import Path


class TestLocalBackend:
    def test_setup_standalone(self, tmp_path):
        from execution_backend import LocalBackend
        exp_dir = tmp_path / "exp"
        exp_dir.mkdir()
        (exp_dir / "workspace").mkdir()
        backend = LocalBackend()
        ctx = backend.setup(exp_dir, mode="standalone")
        assert ctx.work_dir == exp_dir / "workspace"
        assert ctx.cleanup is None

    def test_setup_integration_creates_worktree(self, tmp_path):
        from execution_backend import LocalBackend
        import subprocess
        repo = tmp_path / "target-repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"],
                       cwd=repo, capture_output=True,
                       env={"GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t",
                            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"})
        exp_dir = tmp_path / "exp"
        exp_dir.mkdir()
        backend = LocalBackend()
        ctx = backend.setup(exp_dir, mode="integration", target_repo=repo)
        assert ctx.work_dir.exists()
        assert ctx.cleanup is not None

    def test_run_command(self, tmp_path):
        from execution_backend import LocalBackend
        backend = LocalBackend()
        result = backend.run_command(["echo", "hello"], cwd=tmp_path)
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_run_command_timeout(self, tmp_path):
        from execution_backend import LocalBackend
        backend = LocalBackend()
        result = backend.run_command(["sleep", "10"], cwd=tmp_path, timeout=1)
        assert result.timed_out


class TestBackendRegistry:
    def test_get_local(self):
        from execution_backend import get_backend
        assert get_backend("local").__class__.__name__ == "LocalBackend"

    def test_get_unknown_raises(self):
        from execution_backend import get_backend
        with pytest.raises(ValueError, match="Unknown backend"):
            get_backend("quantum-cloud")
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement backend abstraction**

```python
# lib/execution_backend.py
"""Execution backend abstraction for experiments.

Local backend built-in; remote backends (RunPod, Modal, etc.) can be registered.
"""
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


@dataclass
class ExecutionContext:
    work_dir: Path
    env: dict = field(default_factory=dict)
    cleanup: Optional[Callable] = None


@dataclass
class CommandResult:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class ExecutionBackend(ABC):
    @abstractmethod
    def setup(self, exp_dir: Path, mode: str, **kwargs) -> ExecutionContext: ...
    @abstractmethod
    def run_command(self, cmd: list[str], cwd: Path,
                    timeout: Optional[int] = None,
                    env: Optional[dict] = None) -> CommandResult: ...


class LocalBackend(ExecutionBackend):
    def setup(self, exp_dir: Path, mode: str, **kwargs) -> ExecutionContext:
        if mode == "standalone":
            workspace = exp_dir / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            return ExecutionContext(work_dir=workspace)
        elif mode == "integration":
            target_repo = kwargs.get("target_repo")
            if not target_repo:
                raise ValueError("Integration mode requires target_repo")
            target_repo = Path(target_repo)
            import uuid
            branch_name = f"experiment-{exp_dir.name}-{uuid.uuid4().hex[:6]}"
            worktree_path = exp_dir / ".worktree"
            subprocess.run(
                ["git", "worktree", "add", str(worktree_path), "-b", branch_name],
                cwd=target_repo, capture_output=True, check=True)
            def cleanup():
                subprocess.run(["git", "worktree", "remove", str(worktree_path), "--force"],
                               cwd=target_repo, capture_output=True)
                subprocess.run(["git", "branch", "-D", branch_name],
                               cwd=target_repo, capture_output=True)
            return ExecutionContext(work_dir=worktree_path, cleanup=cleanup)
        else:
            raise ValueError(f"Unknown mode: {mode}")

    def run_command(self, cmd: list[str], cwd: Path,
                    timeout: Optional[int] = None,
                    env: Optional[dict] = None) -> CommandResult:
        import os
        run_env = os.environ.copy()
        if env: run_env.update(env)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout, cwd=str(cwd), env=run_env)
            return CommandResult(returncode=proc.returncode,
                                stdout=proc.stdout, stderr=proc.stderr)
        except subprocess.TimeoutExpired as e:
            return CommandResult(timed_out=True,
                                stdout=str(e.stdout or ""), stderr=str(e.stderr or ""))


_BACKENDS: dict[str, type[ExecutionBackend]] = {"local": LocalBackend}

def register_backend(name: str, cls: type[ExecutionBackend]) -> None:
    _BACKENDS[name] = cls

def get_backend(name: str) -> ExecutionBackend:
    cls = _BACKENDS.get(name)
    if cls is None:
        raise ValueError(f"Unknown backend: {name}. Available: {list(_BACKENDS.keys())}")
    return cls()
```

- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git add lib/execution_backend.py tests/test_execution_backend.py
git commit -m "feat: add execution backend abstraction with local backend"
```

---

## Chunk 3: Workflow Engine

### Task 7: Workflow State Machine and CLI

**Files:**
- Create: `lib/experiment_workflow.py`
- Create: `tests/test_experiment_workflow.py`

- [ ] **Step 1: Write failing tests for workflow lifecycle**

```python
# tests/test_experiment_workflow.py
"""Tests for experiment workflow state machine."""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_daemon():
    state = {}
    mock_dc = MagicMock()
    mock_dc.workflow_get_state.return_value = state
    mock_dc.workflow_set_value.side_effect = lambda wf_id, k, v: state.update({k: v})
    mock_dc.workflow_advance_phase.side_effect = lambda wf_id, phase: state.update({"phase": phase})
    mock_dc.__enter__ = MagicMock(return_value=mock_dc)
    mock_dc.__exit__ = MagicMock(return_value=False)
    with patch("experiment_workflow.DaemonClient", return_value=mock_dc):
        yield mock_dc, state


class TestExperimentWorkflow:
    def test_start(self, mock_daemon):
        from experiment_workflow import start_experiment
        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/test-exp", task="Train model")
        assert state["phase"] == "read"
        assert state["task"] == "Train model"
        assert state["iteration"] == 0

    def test_valid_transitions(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase
        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        for phase in ["plan", "work", "eval", "journal", "decide"]:
            advance_phase(phase)
            assert state["phase"] == phase

    def test_invalid_transition_raises(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase, ExperimentWorkflowError
        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        with pytest.raises(ExperimentWorkflowError, match="Invalid transition"):
            advance_phase("work")

    def test_kickback_from_decide_to_plan(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase
        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        for phase in ["plan", "work", "eval", "journal", "decide"]:
            advance_phase(phase)
        advance_phase("plan")
        assert state["phase"] == "plan"

    def test_decide_to_done(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase
        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        for phase in ["plan", "work", "eval", "journal", "decide"]:
            advance_phase(phase)
        advance_phase("done")
        assert state["phase"] == "done"

    def test_max_iterations(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase, ExperimentWorkflowError
        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test", max_iterations=2)
        for phase in ["plan", "work", "eval", "journal", "decide"]:
            advance_phase(phase)
        advance_phase("plan")  # kickback 1
        assert state.get("iteration") == 1
        for phase in ["work", "eval", "journal", "decide"]:
            advance_phase(phase)
        with pytest.raises(ExperimentWorkflowError, match="Max iterations"):
            advance_phase("plan")

    def test_stop(self, mock_daemon):
        from experiment_workflow import start_experiment, stop
        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        stop()
        assert state.get("active") == False

    def test_record_eval_result(self, mock_daemon):
        from experiment_workflow import start_experiment, record_eval_result
        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        record_eval_result({"accuracy": 0.85}, passed=False)
        assert state["best_metrics"]["accuracy"] == 0.85
        record_eval_result({"accuracy": 0.92}, passed=True)
        assert state["best_metrics"]["accuracy"] == 0.92

    def test_record_hypothesis(self, mock_daemon):
        from experiment_workflow import start_experiment, record_hypothesis
        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        record_hypothesis("Linear projection", "R@5=0.24, failed")
        assert len(state["hypotheses_tested"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement experiment workflow engine**

```python
# lib/experiment_workflow.py
"""Experiment workflow — autonomous experiment execution with eval gates.

Flow: read -> plan -> work -> eval -> journal -> decide -> [plan | done]
State persisted via DaemonClient.
"""
import sys
from pathlib import Path
from typing import Optional

lib_dir = Path(__file__).parent
if str(lib_dir) not in sys.path:
    sys.path.insert(0, str(lib_dir))

from daemon_client import DaemonClient, is_daemon_only_key  # noqa: E402

WORKFLOW_ID = "experiment"

TRANSITIONS: dict[str, set[str]] = {
    "read": {"plan"},
    "plan": {"work"},
    "work": {"eval"},
    "eval": {"journal", "work"},
    "journal": {"decide"},
    "decide": {"plan", "done"},
}
ALL_PHASES: set[str] = set(TRANSITIONS.keys()) | {"done"}
DEFAULTS = {"max_iterations": 10, "max_agents": 4}


class ExperimentWorkflowError(Exception): ...


def _get_state() -> dict:
    with DaemonClient() as dc:
        return dc.workflow_get_state(WORKFLOW_ID) or {}

def _set_state(state: dict) -> None:
    with DaemonClient() as dc:
        if "phase" in state:
            dc.workflow_advance_phase(WORKFLOW_ID, state["phase"])
        for key, value in state.items():
            if is_daemon_only_key(key): continue
            dc.workflow_set_value(WORKFLOW_ID, key, value)

def start_experiment(experiment_dir: str, task: str,
                     max_iterations: Optional[int] = None,
                     max_agents: Optional[int] = None) -> dict:
    state = {
        "active": True, "task": task, "phase": "read",
        "experiment_dir": experiment_dir, "iteration": 0,
        "max_iterations": max_iterations or DEFAULTS["max_iterations"],
        "max_agents": max_agents or DEFAULTS["max_agents"],
        "best_metrics": {}, "hypotheses_tested": [],
        "execution_mode": None, "environment": "local",
    }
    _set_state(state)
    return state

def stop(reason: str = "user_stopped") -> None:
    state = _get_state()
    if not state: return
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
        raise ExperimentWorkflowError("Workflow not active")
    current = state["phase"]
    if target not in ALL_PHASES:
        raise ExperimentWorkflowError(f"Unknown phase: {target}. Valid: {sorted(ALL_PHASES)}")
    valid_targets = TRANSITIONS.get(current, set())
    if target not in valid_targets:
        raise ExperimentWorkflowError(
            f"Invalid transition: {current} -> {target}. "
            f"Valid targets from {current}: {sorted(valid_targets)}")
    if current == "decide" and target == "plan":
        state["iteration"] = state.get("iteration", 0) + 1
        max_iter = state.get("max_iterations", DEFAULTS["max_iterations"])
        if state["iteration"] >= max_iter:
            state["active"] = False
            state["exit_reason"] = "max_iterations"
            state["phase"] = target
            _set_state(state)
            raise ExperimentWorkflowError(f"Max iterations ({max_iter}) reached")
    state["phase"] = target
    if target == "done":
        state["active"] = False
        state["exit_reason"] = "success"
    _set_state(state)
    return state

def record_eval_result(metrics: dict, passed: bool) -> None:
    state = _get_state()
    state["last_eval_passed"] = passed
    state["last_eval_metrics"] = metrics
    best = state.get("best_metrics", {})
    for k, v in metrics.items():
        if k not in best or v > best[k]: best[k] = v
    state["best_metrics"] = best
    _set_state(state)

def record_hypothesis(hypothesis: str, result: str) -> None:
    state = _get_state()
    tested = state.get("hypotheses_tested", [])
    tested.append({"hypothesis": hypothesis, "result": result,
                    "iteration": state.get("iteration", 0)})
    state["hypotheses_tested"] = tested
    _set_state(state)

def _print_status():
    state = _get_state()
    if not state:
        print("No experiment workflow active."); return
    print(f"Experiment: {state.get('task', '?')}")
    print(f"Phase: {state.get('phase', '?')}")
    print(f"Iteration: {state.get('iteration', 0)}/{state.get('max_iterations', '?')}")
    print(f"Active: {state.get('active', False)}")
    print(f"Mode: {state.get('execution_mode', '?')}")
    print(f"Environment: {state.get('environment', 'local')}")
    best = state.get("best_metrics", {})
    if best: print(f"Best metrics: {best}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Experiment workflow control")
    sub = parser.add_subparsers(dest="command")
    start_p = sub.add_parser("start")
    start_p.add_argument("experiment_dir")
    start_p.add_argument("task")
    start_p.add_argument("--max-iterations", type=int, default=None)
    sub.add_parser("status")
    sub.add_parser("phase")
    adv_p = sub.add_parser("advance")
    adv_p.add_argument("target")
    setp = sub.add_parser("set-phase")
    setp.add_argument("phase")
    sub.add_parser("stop")
    args = parser.parse_args()
    if args.command == "start":
        start_experiment(args.experiment_dir, args.task, max_iterations=args.max_iterations)
        print(f"Started experiment workflow: {args.task}")
    elif args.command == "status": _print_status()
    elif args.command == "phase": print(get_phase() or "No active workflow")
    elif args.command == "advance":
        try: advance_phase(args.target); print(f"Advanced to: {args.target}")
        except ExperimentWorkflowError as e: print(f"Error: {e}", file=sys.stderr); sys.exit(1)
    elif args.command == "set-phase":
        state = _get_state(); state["phase"] = args.phase; _set_state(state)
        print(f"Phase set to: {args.phase}")
    elif args.command == "stop": stop(); print("Workflow stopped.")
    else: parser.print_help()

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git add lib/experiment_workflow.py tests/test_experiment_workflow.py
git commit -m "feat: add experiment workflow state machine with CLI"
```

---

## Chunk 4: Configuration and Permissions

### Task 8: Workflow Config

**Files:**
- Create: `config/workflows/experiment.yaml`

- [ ] **Step 1: Write config**

```yaml
name: experiment
description: "Autonomous experiment workflow with eval gates and journal memory"
initial_phase: read
terminal_phase: done
max_iterations: 10
max_agents: 4

phases:
  - name: read
    allowed_tool_categories: [FILE_READ, FILE_SEARCH, CODE_QUERY]
    blocked_tools: [native__write_file, native__edit_file, native__bash]
    eligible_agents: [pm]
    checkpoint: false

  - name: plan
    allowed_tool_categories: [FILE_READ, FILE_SEARCH, CODE_QUERY, WEB_RESEARCH]
    blocked_tools: [native__write_file, native__edit_file, native__bash]
    eligible_agents: [pm, researcher]
    checkpoint: false

  - name: work
    allowed_tool_categories: [FILE_READ, FILE_WRITE, CODE_QUERY, CODE_EDIT, FILE_SEARCH, SHELL_SAFE, WEB_RESEARCH]
    blocked_tools: []
    blocked_file_patterns: ["experiments/*/eval/**"]
    eligible_agents: [implementer, researcher]
    checkpoint: false

  - name: eval
    allowed_tool_categories: [FILE_READ, SHELL_SAFE]
    blocked_tools: [native__write_file, native__edit_file]
    blocked_file_patterns: ["experiments/*/eval/**"]
    eligible_agents: [implementer]
    checkpoint: false

  - name: journal
    allowed_tool_categories: [FILE_READ, FILE_WRITE]
    blocked_tools: [native__bash]
    allowed_file_patterns: ["experiments/*/journal/**"]
    eligible_agents: [pm, implementer]
    checkpoint: false

  - name: decide
    allowed_tool_categories: [FILE_READ]
    blocked_tools: [native__write_file, native__edit_file, native__bash]
    eligible_agents: [pm]
    checkpoint: false

  - name: done
    allowed_tool_categories: []
    blocked_tools: []
    eligible_agents: []
    checkpoint: false

transitions:
  read: [plan]
  plan: [work]
  work: [eval]
  eval: [journal, work]
  journal: [decide]
  decide: [plan, done]
```

- [ ] **Step 2: Commit**

```bash
git add config/workflows/experiment.yaml
git commit -m "feat: add experiment workflow config"
```

### Task 9: Permissions

**Files:**
- Modify: `config/permissions.yaml`

- [ ] **Step 1: Add experiment workflow permissions**

Add under `workflows:` in `config/permissions.yaml`:

```yaml
  experiment:
    read:
      allowed: [native__read_file, native__glob, native__grep, serena__*]
      blocked: [native__write_file, native__edit_file, native__bash]
    plan:
      allowed: [native__read_file, native__glob, native__grep, serena__*, context7__*, native__web_fetch, native__web_search]
      blocked: [native__write_file, native__edit_file, native__bash]
    work:
      allowed: [native__write_file, native__edit_file, native__read_file, native__glob, native__grep, native__bash(pytest*), native__bash(python*), native__bash(ruff*), serena__*]
      blocked: []
    eval:
      allowed: [native__read_file, native__bash(pytest*), native__bash(python*)]
      blocked: [native__write_file, native__edit_file]
    journal:
      allowed: [native__read_file, native__write_file, native__glob]
      blocked: [native__edit_file, native__bash]
    decide:
      allowed: [native__read_file, native__glob, native__grep]
      blocked: [native__write_file, native__edit_file, native__bash]
```

- [ ] **Step 2: Commit**

```bash
git add config/permissions.yaml
git commit -m "feat: add experiment workflow permissions"
```

---

## Chunk 5: Skill Definition

### Task 10: Skill File

**Files:**
- Create: `skills/experiment/SKILL.md`

- [ ] **Step 1: Create skill definition**

The skill defines:
- Phase flow: `read -> plan -> work -> eval -> journal -> decide -> [plan | done]`
- Phase table with tool permissions per phase
- Protocol for each phase (what the agent does)
- Kickback table: eval->work (crash), decide->plan (fail), decide->done (pass)
- Execution modes: standalone vs integration (determined by goal.yaml `target:`)
- Execution environments: local (default), extensible for remote backends
- Team support: researcher agents in plan, parallel implementers in work, fan-out hypothesis testing
- Constraints enforcement: time limits tracked, do-not-do as context, escalate_if checked in decide, eval immutability via file pattern blocks
- CLI reference for workflow control
- Exit conditions: success, max_iterations, escalation, user_stopped

- [ ] **Step 2: Commit**

```bash
git add skills/experiment/SKILL.md
git commit -m "feat: add experiment workflow skill definition"
```

---

## Chunk 6: Integration Test

### Task 11: Integration Test

**Files:**
- Create: `tests/test_experiment_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_experiment_integration.py
"""Integration test — full harness loop without daemon."""
import yaml
from pathlib import Path


def test_full_loop_trivial_pass(tmp_path):
    from experiment_harness import load_goal, load_constraints, Journal, run_eval, check_criteria

    exp = tmp_path / "trivial"
    exp.mkdir()
    (exp / "goal.yaml").write_text(yaml.dump({
        "objective": "Make a trivial test pass",
        "eval": "eval/",
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    }))
    eval_dir = exp / "eval"
    eval_dir.mkdir()
    (eval_dir / "test_trivial.py").write_text("def test_ok(): assert True\n")
    (exp / "workspace").mkdir()

    goal = load_goal(exp)
    constraints = load_constraints(exp)
    journal = Journal(exp)

    assert goal.is_standalone
    assert constraints.do_not_do == []
    assert journal.list_entries() == []

    result = run_eval(exp, eval_path=goal.eval)
    assert result.passed

    rate = result.tests_passed / max(result.tests_run, 1)
    criteria = check_criteria(goal.success_criteria, {"test_pass_rate": rate})
    assert criteria.primary_passed

    journal.add_entry(title="Trivial", hypothesis="Already passes",
                     changes="None", result=f"rate={rate}",
                     diagnosis="OK", next_direction="Done")
    assert len(journal.list_entries()) == 1
```

- [ ] **Step 2: Run integration test**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && PYTHONPATH=lib python -m pytest tests/test_experiment_integration.py -v`
Expected: 1 PASSED

- [ ] **Step 3: Commit**

```bash
git add tests/test_experiment_integration.py
git commit -m "test: add experiment workflow integration test"
```

---

## Summary

### What We Built

1. **Harness library** (`lib/experiment_harness.py`) — Goal/Constraints loading, Journal, eval runner, criteria checker
2. **Execution backend** (`lib/execution_backend.py`) — Pluggable local/remote abstraction
3. **Workflow engine** (`lib/experiment_workflow.py`) — 6-phase state machine with kickbacks, CLI
4. **Config** (`config/workflows/experiment.yaml`) — Phase permissions and transitions
5. **Permissions** (`config/permissions.yaml`) — Per-phase tool restrictions
6. **Skill** (`skills/experiment/SKILL.md`) — Agent protocol with team/fan-out support

### What's Deferred

- Remote backends (RunPod, Modal) — interface ready, implementations deferred
- Time-based constraints auto-stop — tracked in state, enforcement deferred
- Adversary gates — the eval is the adversary in experiments

### Shared Utilities Extracted

- `run_eval()` + `check_criteria()` — importable by other workflows
- `Journal` — reusable append-only memory pattern
- `ExecutionBackend` — pluggable execution environment
