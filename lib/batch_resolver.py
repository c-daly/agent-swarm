"""Batch resolver — parse batch goal.yaml and resolve tasks."""
from __future__ import annotations

import glob
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import yaml

logger = logging.getLogger(__name__)


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
            try:
                with open(goal_path) as f:
                    task_data = yaml.safe_load(f)
            except (yaml.YAMLError, OSError) as exc:
                logger.warning("Failed to load %s: %s", goal_path, exc)
                continue
            if task_data:
                raw_tasks.append(task_data)

    # Note: GitHub query resolution is handled by the skill at runtime
    # (requires MCP tools not available in library code).

    # Deduplicate by target or issue number (namespaced to avoid collisions)
    seen: set[str] = set()
    unique_tasks: list[dict] = []
    for task in raw_tasks:
        if "target" in task:
            key = f"target:{task['target']}"
        elif "issue" in task:
            key = f"issue:{task['issue']}"
        else:
            # Anonymous tasks are never deduplicated
            key = f"anon:{id(task)}"
        if key not in seen:
            seen.add(key)
            unique_tasks.append(task)

    # Create per-task directories and goal.yaml files
    resolved: list[dict] = []
    tasks_dir = os.path.join(run_dir, "tasks")
    os.makedirs(tasks_dir, exist_ok=True)

    seen_ids: set[str] = set()
    for i, task in enumerate(unique_tasks):
        task_id = task.get("id") or _task_id(task, i)

        # Ensure unique directory names
        if task_id in seen_ids:
            task_id = f"{task_id}_{i}"
        seen_ids.add(task_id)

        task_dir = os.path.join(tasks_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)

        # Build task goal.yaml — inherit run-level defaults
        task_goal = dict(task)
        if "success_criteria" not in task_goal:
            task_goal["success_criteria"] = goal.success_criteria
        if "eval" not in task_goal:
            task_goal["eval"] = "eval/"

        # Propagate run-level constraints if task doesn't have its own
        if goal.constraints and "constraints" not in task_goal:
            task_goal["constraints"] = goal.constraints

        with open(os.path.join(task_dir, "goal.yaml"), "w") as f:
            yaml.dump(task_goal, f, default_flow_style=False)

        # Build resolved entry — task_id is authoritative, not **task
        resolved.append({
            **task,
            "id": task_id,
            "dir": task_dir,
        })

    return resolved


def _task_id(task: dict, index: int) -> str:
    """Generate a stable task ID from task definition."""
    if "issue" in task:
        return str(task["issue"])
    if "target" in task:
        # Use full path (minus extension) to avoid collisions
        # e.g., agora/adapters/foo.py -> agora_adapters_foo
        path = os.path.splitext(task["target"])[0]
        return path.replace("/", "_").replace("\\", "_")
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
        if task_id not in task_map:
            raise ValueError(f"Unknown dependency '{task_id}' — check depends_on for typos")
        in_stack.add(task_id)
        task = task_map[task_id]
        for dep in task.get("depends_on", []):
            visit(dep)
        in_stack.discard(task_id)
        visited.add(task_id)
        result.append(task)

    for t in tasks:
        visit(t["id"])

    return result


# --- Task Grouping ---

COMPONENT_ORDER = {
    "adapter": 0, "glossary": 0,
    "analysis": 1, "quant": 1,
    "api": 2,
    "frontend": 3, "app-shell": 3,
}


def _get_component(task: dict) -> str:
    """Extract component type from task labels."""
    for label in task.get("labels", []):
        if isinstance(label, str) and label.startswith("component:"):
            return label.split(":")[1]
        if isinstance(label, dict) and label.get("name", "").startswith("component:"):
            return label["name"].split(":")[1]
    return "unknown"


def _get_group_key(task: dict) -> str:
    """Extract group key from task (epic label, explicit group, or default)."""
    # Check explicit group field
    if "group" in task:
        return task["group"]

    # Check for epic label
    for label in task.get("labels", []):
        name = label if isinstance(label, str) else label.get("name", "")
        if name.startswith("epic:"):
            return name.split(":")[1]
        if name == "epic":
            continue  # Skip bare "epic" label (that's the epic issue itself)

    return "_ungrouped"


def group_tasks(tasks: list[dict], strategy: str = "auto") -> dict[str, list[dict]]:
    """Group tasks into execution units.

    Strategies:
        auto: Use epic labels if present, fall back to flat.
        epic: Group by epic labels. Ungrouped tasks go to "_ungrouped".
        explicit: Group by task["group"] field.
        flat: No grouping — each task is its own group.

    Within each group, tasks are sorted by component type
    (adapter -> analysis -> api -> frontend).
    """
    if strategy == "flat":
        return {task.get("id", str(i)): [task] for i, task in enumerate(tasks)}

    groups: dict[str, list[dict]] = {}

    for task in tasks:
        if strategy == "explicit":
            key = task.get("group", "_ungrouped")
        elif strategy == "epic":
            key = _get_group_key(task)
        else:  # auto
            key = _get_group_key(task)

        groups.setdefault(key, []).append(task)

    # If auto and everything ended up ungrouped, fall back to flat
    if strategy == "auto" and list(groups.keys()) == ["_ungrouped"]:
        return {task.get("id", str(i)): [task] for i, task in enumerate(tasks)}

    # Sort tasks within each group by component order
    for key in groups:
        groups[key].sort(key=lambda t: COMPONENT_ORDER.get(_get_component(t), 99))

    return groups
