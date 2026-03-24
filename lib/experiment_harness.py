"""Experiment harness library — goal loading, journal management, eval execution.

Shared utilities:
- run_eval(): Run pytest or custom eval, parse metrics — usable by any workflow
- check_criteria(): Check metrics against thresholds — usable by any workflow
- Journal: Append-only structured log — usable by any workflow needing attempt memory

Experiment-specific:
- load_goal(): Parse goal.yaml ticket format
- load_constraints(): Parse constraints.yaml guardrails
"""

import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)
_DEFAULT_EVAL_TIMEOUT = int(os.environ.get("HARNESS_EVAL_TIMEOUT", "300"))


# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------

@dataclass
class Goal:
    """Parsed goal.yaml with convenience properties."""
    objective: str
    eval: str
    success_criteria: list
    target: Optional[str] = None
    context: Optional[str] = None
    environment: Optional[dict] = None
    _raw: dict = field(default_factory=dict, repr=False)

    @property
    def is_integration(self) -> bool:
        return self.target is not None

    @property
    def is_standalone(self) -> bool:
        return self.target is None

    @property
    def primary_criterion(self) -> Optional[dict]:
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


def validate_goal(goal: Goal) -> list[str]:
    """Validate a Goal object. Returns list of error strings (empty = valid)."""
    errors = []
    if not goal.objective or not goal.objective.strip():
        errors.append("objective is empty or missing")
    if not goal.success_criteria:
        errors.append("success_criteria is empty or missing")
    for i, c in enumerate(goal.success_criteria):
        if "metric" not in c:
            errors.append(f"success_criteria[{i}] missing 'metric'")
        if "threshold" not in c:
            errors.append(f"success_criteria[{i}] missing 'threshold'")
    return errors


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

@dataclass
class Constraints:
    """Parsed constraints.yaml — guardrails for experiment execution."""
    max_hours_per_run: Optional[float] = None
    max_total_gpu_hours: Optional[float] = None
    do_not_do: list[str] = field(default_factory=list)
    escalate_if: list = field(default_factory=list)
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


def normalize_escalation(entry) -> dict:
    """Normalize an escalate_if entry to {condition, reason} dict."""
    if isinstance(entry, str):
        return {"condition": entry, "reason": "error"}
    if isinstance(entry, dict):
        return {"condition": entry.get("condition", ""), "reason": entry.get("reason", "error")}
    return {"condition": str(entry), "reason": "error"}


@dataclass
class EscalationResult:
    """Result of checking escalation conditions."""
    should_stop: bool
    triggered: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    checkpoints: list[dict] = field(default_factory=list)


def check_escalations(constraints: Constraints, triggered_conditions: list[str]) -> EscalationResult:
    """Check which escalation conditions have been triggered.

    Args:
        constraints: Loaded constraints with escalate_if entries.
        triggered_conditions: Condition strings the agent reports as met.

    Returns:
        EscalationResult with categorized triggered escalations.
    """
    triggered = []
    errors = []
    checkpoints = []
    triggered_set = set(triggered_conditions)

    for entry in constraints.escalate_if:
        normalized = normalize_escalation(entry)
        if normalized["condition"] in triggered_set:
            triggered.append(normalized)
            if normalized["reason"] == "routine_checkpoint":
                checkpoints.append(normalized)
            else:
                errors.append(normalized)

    return EscalationResult(
        should_stop=len(errors) > 0,
        triggered=triggered,
        errors=errors,
        checkpoints=checkpoints,
    )


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------

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
    """Extract [METRIC] key=value pairs from eval output."""
    metrics = {}
    for match in re.finditer(r"\[METRIC\]\s*(\w+)\s*=\s*(-?[\d.]+(?:[eE][+-]?\d+)?)", output):
        try:
            metrics[match.group(1)] = float(match.group(2))
        except ValueError:
            metrics[match.group(1)] = match.group(2)
    return metrics


def _parse_pytest_summary(output: str) -> tuple[int, int, int]:
    """Parse pytest output for pass/fail counts. Returns (total, passed, failed)."""
    passed = failed = 0
    for m in re.finditer(r"(\d+) passed", output):
        passed = int(m.group(1))
    for m in re.finditer(r"(\d+) failed", output):
        failed = int(m.group(1))
    return passed + failed, passed, failed


def run_eval(exp_dir: Path, eval_path: str = "eval/",
             timeout: int = _DEFAULT_EVAL_TIMEOUT,
             env_override: Optional[dict] = None) -> EvalResult:
    """Run an experiment's eval and return structured results."""
    full_eval_path = exp_dir / eval_path
    env = os.environ.copy()
    if env_override:
        env.update(env_override)

    python = sys.executable

    if full_eval_path.is_dir():
        cmd = [python, "-m", "pytest", str(full_eval_path), "-v", "-s"]
    elif full_eval_path.suffix == ".py":
        cmd = [python, str(full_eval_path)]
    else:
        cmd = [str(full_eval_path)]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, cwd=str(exp_dir), env=env)
        output = proc.stdout + proc.stderr
        total, passed, failed = _parse_pytest_summary(output)
        metrics = _parse_metrics(output)
        if total > 0 and "test_pass_rate" not in metrics:
            metrics["test_pass_rate"] = passed / total
        return EvalResult(
            passed=(proc.returncode == 0), tests_run=total,
            tests_passed=passed, tests_failed=failed,
            metrics=metrics,
            stdout=proc.stdout, stderr=proc.stderr,
            return_code=proc.returncode,
        )
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout or b""
        stderr = e.stderr or b""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        output = stdout + stderr
        metrics = _parse_metrics(output)
        total, passed, _ = _parse_pytest_summary(output)
        if total > 0 and "test_pass_rate" not in metrics:
            metrics["test_pass_rate"] = passed / total
        return EvalResult(passed=False, timed_out=True,
                          stdout=stdout, stderr=stderr,
                          metrics=metrics)


# ---------------------------------------------------------------------------
# Criteria checker
# ---------------------------------------------------------------------------

@dataclass
class CriteriaResult:
    """Result of checking eval metrics against success criteria."""
    passed: bool
    primary_passed: bool
    all_passed: bool
    details: list[dict] = field(default_factory=list)


def check_criteria(criteria: list[dict], metrics: dict) -> CriteriaResult:
    """Check eval metrics against success criteria.

    Each criterion: {metric, threshold, comparison (default ">="), primary (bool)}.
    """
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
        elif comparison == ">=":
            met = actual >= threshold
        elif comparison == "<=":
            met = actual <= threshold
        elif comparison == ">":
            met = actual > threshold
        elif comparison == "<":
            met = actual < threshold
        elif comparison == "==":
            met = actual == threshold
        else:
            logger.warning(
                "Unknown comparison operator %r for metric %r; defaulting to '>=",
                comparison, metric_name,
            )
            met = actual >= threshold

        details.append({"metric": metric_name, "threshold": threshold,
                        "actual": actual, "met": met, "primary": is_primary})
        if not met:
            all_met = False
            if is_primary:
                primary_passed = False

    return CriteriaResult(passed=primary_passed, primary_passed=primary_passed,
                          all_passed=all_met, details=details)
