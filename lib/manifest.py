"""YAML manifest parser and dataclasses for parallel orchestration tasks."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ManifestTask:
    """A single task to be executed by a subagent."""

    name: str
    description: str
    target_dir: str
    test_dir: str
    min_tests: int = 5
    branch_name: str = ""
    depends_on: list[str] = field(default_factory=list)
    model: str = "sonnet"
    escalation: str = "fable"

    def __post_init__(self):
        if not self.branch_name:
            self.branch_name = f"task/{self.name}"


@dataclass
class Manifest:
    """Parsed manifest containing project config and tasks."""

    project: str
    tasks: list[ManifestTask]
    base_branch: str = "main"
    max_retries: int = 2
    project_dir: str = "."


def parse_manifest(path: str) -> Manifest:
    """Parse a YAML manifest file into a Manifest object.

    Raises FileNotFoundError if path doesn't exist.
    Raises ValueError for missing or invalid fields.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")

    data = yaml.safe_load(p.read_text())
    if not isinstance(data, dict):
        raise ValueError("Manifest must be a YAML mapping")

    if "project" not in data:
        raise ValueError("Manifest missing required field: project")

    if "tasks" not in data:
        raise ValueError("Manifest missing required field: tasks")

    raw_tasks = data["tasks"]
    if not raw_tasks:
        raise ValueError("Manifest must contain at least one task")

    tasks = []
    for i, raw in enumerate(raw_tasks):
        _validate_task_fields(raw, i)
        tasks.append(
            ManifestTask(
                name=raw["name"],
                description=raw["description"],
                target_dir=raw["target_dir"],
                test_dir=raw["test_dir"],
                min_tests=raw.get("min_tests", 5),
                branch_name=raw.get("branch_name", ""),
                depends_on=raw.get("depends_on", []),
                model=raw.get("model", "sonnet"),
                escalation=raw.get("escalation", "fable"),
            )
        )

    return Manifest(
        project=data["project"],
        tasks=tasks,
        base_branch=data.get("base_branch", "main"),
        max_retries=data.get("max_retries", 2),
        project_dir=data.get("project_dir", "."),
    )


_VALID_MODELS = ["haiku", "sonnet"]
_VALID_ESCALATIONS = ["sonnet", "fable"]
_TIER_ORDER = {"haiku": 0, "sonnet": 1, "fable": 2}

_REQUIRED_TASK_FIELDS = ["name", "description", "target_dir", "test_dir"]


def _validate_task_fields(raw: dict[str, Any], index: int) -> None:
    """Validate that a raw task dict has all required fields."""
    for field_name in _REQUIRED_TASK_FIELDS:
        if field_name not in raw:
            raise ValueError(f"Task {index} missing required field: {field_name}")

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
            f"Task {index}: escalation {escalation!r} must be a "
            f"higher tier than model {model!r}"
        )


def _detect_cycles(manifest: Manifest) -> None:
    """Raise ValueError if dependency graph has cycles."""
    dep_map = {t.name: t.depends_on for t in manifest.tasks}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {name: WHITE for name in dep_map}
    path: list[str] = []

    def dfs(node: str) -> None:
        color[node] = GRAY
        path.append(node)
        for dep in dep_map.get(node, []):
            if color[dep] == GRAY:
                cycle_start = path.index(dep)
                cycle = path[cycle_start:] + [dep]
                raise ValueError(
                    f"Circular dependency detected: {' -> '.join(cycle)}"
                )
            if color[dep] == WHITE:
                dfs(dep)
        path.pop()
        color[node] = BLACK

    for name in dep_map:
        if color[name] == WHITE:
            dfs(name)


def validate_manifest(manifest: Manifest) -> list[str]:
    """Return a list of warning strings (non-fatal issues)."""
    warnings = []

    # Check duplicate task names
    names = [t.name for t in manifest.tasks]
    if len(names) != len(set(names)):
        seen = set()
        for name in names:
            if name in seen:
                warnings.append(f"Duplicate task name: {name}")
            seen.add(name)

    # Check duplicate branch names
    branches = [t.branch_name for t in manifest.tasks]
    if len(branches) != len(set(branches)):
        seen = set()
        for branch in branches:
            if branch in seen:
                warnings.append(f"Duplicate branch name: {branch}")
            seen.add(branch)

    # Check low min_tests
    for task in manifest.tasks:
        if task.min_tests < 3:
            warnings.append(f"Task '{task.name}' has low min_tests ({task.min_tests})")

    # Validate depends_on references
    task_names = {t.name for t in manifest.tasks}
    for task in manifest.tasks:
        for dep in task.depends_on:
            if dep not in task_names:
                raise ValueError(
                    f"Task '{task.name}' depends on unknown task: {dep}"
                )

    # Detect circular dependencies via DFS
    _detect_cycles(manifest)

    return warnings
