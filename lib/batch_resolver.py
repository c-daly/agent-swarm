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
