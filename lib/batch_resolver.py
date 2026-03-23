"""Batch resolver — parse batch goal.yaml and resolve tasks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import glob
import os
import yaml


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
        name = os.path.basename(task["target"])
        return os.path.splitext(name)[0]
    return f"task_{index}"


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
