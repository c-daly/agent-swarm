#!/usr/bin/env python3
"""
Worker Pool - Manages parallel subagent workers for orchestration.

Tracks worker state, determines spawn decisions, and handles completions.
The actual Task tool spawning is done by the main agent - this module
just manages the state.

Usage:
    from worker_pool import start, should_spawn_worker, spawn_worker, on_worker_complete

    start(max_agents=3, task="Build feature X")

    while not is_complete(queue_empty=queue.is_empty()):
        if should_spawn_worker(queue_has_work=not queue.is_empty()):
            task = queue.pop()
            worker_id = spawn_worker(task.id, task.description)
            # ... spawn subagent with Task tool ...

        # ... handle completions ...
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# State file location - can be overridden via environment variable
_state_dir_override = os.environ.get("WORKER_POOL_STATE_DIR")
STATE_DIR = Path(_state_dir_override) if _state_dir_override else Path.home() / ".claude/plugins/agent-swarm/.state"
STATE_FILE = STATE_DIR / "worker_pool.json"


def _generate_worker_id() -> str:
    """Generate unique worker ID."""
    return f"worker-{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    """Generate ISO timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_state() -> dict:
    """Load worker pool state from file."""
    if not STATE_FILE.exists():
        return {"active": False}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, IOError):
        return {"active": False}


def _save_state(state: dict) -> None:
    """Save worker pool state to file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


def start(max_agents: int, task: str = "") -> None:
    """Start orchestration with worker pool.

    Args:
        max_agents: Maximum number of parallel workers.
        task: Optional task description.

    Raises:
        RuntimeError: If orchestration already active.
    """
    state = _load_state()
    if state.get("active"):
        raise RuntimeError("Orchestration already active")

    state = {
        "active": True,
        "max_agents": max_agents,
        "task": task,
        "active_workers": [],
        "completed_workers": [],
        "started_at": _now_iso(),
    }
    _save_state(state)


def stop() -> None:
    """Stop orchestration.

    Raises:
        RuntimeError: If orchestration not active.
    """
    state = _load_state()
    if not state.get("active"):
        raise RuntimeError("Orchestration not active")

    state["active"] = False
    state["exit_reason"] = "user_stopped"
    state["stopped_at"] = _now_iso()
    _save_state(state)


def get_state() -> dict:
    """Get current worker pool state."""
    return _load_state()


def is_active() -> bool:
    """Check if orchestration is active."""
    return _load_state().get("active", False)


def should_spawn_worker(queue_has_work: bool) -> bool:
    """Determine if a new worker should be spawned.

    Args:
        queue_has_work: Whether the queue has tasks available.

    Returns:
        True if should spawn (active < max AND queue has work).
    """
    state = _load_state()
    if not state.get("active"):
        return False
    if not queue_has_work:
        return False

    active_count = len(state.get("active_workers", []))
    max_agents = state.get("max_agents", 1)

    return active_count < max_agents


def spawn_worker(task_id: str, task_description: str) -> str:
    """Record a new worker being spawned.

    Args:
        task_id: ID of the task being worked on.
        task_description: Description of the task.

    Returns:
        Generated worker ID.

    Raises:
        RuntimeError: If at max_agents or not active.
    """
    state = _load_state()
    if not state.get("active"):
        raise RuntimeError("Orchestration not active")

    active_count = len(state.get("active_workers", []))
    max_agents = state.get("max_agents", 1)

    if active_count >= max_agents:
        raise RuntimeError(f"Cannot spawn: at max agents ({max_agents})")

    worker_id = _generate_worker_id()
    worker = {
        "worker_id": worker_id,
        "task_id": task_id,
        "task_description": task_description,
        "started_at": _now_iso(),
    }

    state["active_workers"].append(worker)
    _save_state(state)

    return worker_id


def on_worker_complete(worker_id: str, success: bool, result: Optional[dict] = None) -> None:
    """Record a worker completing its task.

    Args:
        worker_id: ID of the completed worker.
        success: Whether the task succeeded.
        result: Optional result metadata.

    Raises:
        ValueError: If worker_id not found in active workers.
    """
    state = _load_state()

    # Find and remove from active workers
    active_workers = state.get("active_workers", [])
    worker = None
    for i, w in enumerate(active_workers):
        if w["worker_id"] == worker_id:
            worker = active_workers.pop(i)
            break

    if worker is None:
        raise ValueError(f"Unknown worker: {worker_id}")

    # Add to completed workers
    worker["success"] = success
    worker["result"] = result
    worker["completed_at"] = _now_iso()

    if "completed_workers" not in state:
        state["completed_workers"] = []
    state["completed_workers"].append(worker)

    state["active_workers"] = active_workers
    _save_state(state)


def get_active_workers() -> list:
    """Get list of currently active workers."""
    state = _load_state()
    return state.get("active_workers", [])


def is_complete(queue_empty: bool) -> bool:
    """Check if orchestration is complete.

    Args:
        queue_empty: Whether the queue is empty.

    Returns:
        True if no active workers AND queue is empty AND orchestration is active.
    """
    state = _load_state()
    if not state.get("active"):
        return False

    if not queue_empty:
        return False

    active_workers = state.get("active_workers", [])
    return len(active_workers) == 0
