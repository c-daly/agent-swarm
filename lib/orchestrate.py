#!/usr/bin/env python3
"""ORCHESTRATE State Machine - Task management for iterate workflow.

This module implements the orchestrate state machine that:
1. Spawns subagents for eligible tasks (respecting max_agents and dependencies)
2. Tracks active subagents (Task tool handles actual execution)
3. Processes subagent output when Task tool returns
4. Triggers gated push when all tasks committed
5. Polls for review comments at configurable intervals
6. Converts review comments to new tasks
7. Exits when: queue empty + no active subagents + review clean

Note: This is NOT a daemon. The orchestrator is invoked at each step:
- spawn_eligible_tasks() when ready to start new work
- handle_worker_completion() when Task tool returns output
- check_review_poll() periodically to check for review comments

The Task tool returns output directly - no "listening" needed.

CLI:
    python3 lib/orchestrate.py start --max-agents=3 --poll-interval=5
    python3 lib/orchestrate.py status
    python3 lib/orchestrate.py stop
"""

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

# Add paths for imports
lib_dir = Path(__file__).parent
scripts_dir = lib_dir.parent / "scripts"
sys.path.insert(0, str(lib_dir))
sys.path.insert(0, str(scripts_dir))

import workflow_client  # noqa: E402
from iterate_state import (  # noqa: E402
    TaskStatus,
    load_queue,
    save_queue,
)
from worker_pool import (  # noqa: E402
    start as worker_pool_start,
    stop as worker_pool_stop,
    is_active as worker_pool_is_active,
    should_spawn_worker,
    spawn_worker,
    on_worker_complete,
    get_active_workers,
)


@dataclass
class OrchestrateConfig:
    """Configuration for orchestrate loop."""
    max_agents: int = 3
    review_poll_interval_minutes: int = 5
    spec_file: Optional[str] = None
    pr_id: str = "default"


@dataclass
class OrchestrateState:
    """State of the orchestrate loop."""
    active: bool = False
    config: OrchestrateConfig = field(default_factory=OrchestrateConfig)
    started_at: Optional[str] = None
    last_poll: Optional[str] = None
    push_pending: bool = False
    review_pending: bool = False
    exit_reason: Optional[str] = None


def _now_iso() -> str:
    """Generate ISO timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_state() -> OrchestrateState:
    """Load orchestrate state from workflow server."""
    data = workflow_client.workflow_get_state("orchestrate")
    if not data:
        return OrchestrateState()
    try:
        config = OrchestrateConfig(**data.get("config", {}))
        return OrchestrateState(
            active=data.get("active", False),
            config=config,
            started_at=data.get("started_at"),
            last_poll=data.get("last_poll"),
            push_pending=data.get("push_pending", False),
            review_pending=data.get("review_pending", False),
            exit_reason=data.get("exit_reason"),
        )
    except TypeError:
        return OrchestrateState()


def _save_state(state: OrchestrateState) -> None:
    """Save orchestrate state to workflow server."""
    data = {
        "active": state.active,
        "config": {
            "max_agents": state.config.max_agents,
            "review_poll_interval_minutes": state.config.review_poll_interval_minutes,
            "spec_file": state.config.spec_file,
            "pr_id": state.config.pr_id,
        },
        "started_at": state.started_at,
        "last_poll": state.last_poll,
        "push_pending": state.push_pending,
        "review_pending": state.review_pending,
        "exit_reason": state.exit_reason,
    }
    workflow_client.workflow_set_state("orchestrate", data)


def start_orchestrate(config: OrchestrateConfig) -> OrchestrateState:
    """Start orchestrate loop.

    Args:
        config: Configuration for the orchestrate loop.

    Returns:
        Initial state.

    Raises:
        RuntimeError: If orchestrate is already active.
    """
    state = _load_state()
    if state.active:
        raise RuntimeError("Orchestrate loop already active")

    # Start worker pool
    worker_pool_start(config.max_agents, f"Orchestrate: {config.pr_id}")

    state = OrchestrateState(
        active=True,
        config=config,
        started_at=_now_iso(),
    )
    _save_state(state)

    print("[ORCHESTRATE] Started")
    print(f"  Max agents: {config.max_agents}")
    print(f"  Poll interval: {config.review_poll_interval_minutes}m")
    print(f"  PR: {config.pr_id}")

    return state


def stop_orchestrate(reason: str = "user_stopped") -> None:
    """Stop orchestrate loop.

    Args:
        reason: Exit reason.
    """
    state = _load_state()
    if not state.active:
        print("[ORCHESTRATE] Not active")
        return

    state.active = False
    state.exit_reason = reason
    _save_state(state)

    # Stop worker pool
    try:
        worker_pool_stop()
    except RuntimeError:
        pass  # Already stopped

    print(f"[ORCHESTRATE] Stopped: {reason}")


def get_status() -> dict:
    """Get orchestrate status.

    Returns:
        Status dictionary with active flag, queue stats, worker stats.
    """
    state = _load_state()
    queue = load_queue()
    workers = get_active_workers() if worker_pool_is_active() else []

    pending_tasks = [t for t in queue.tasks.values() if t.status == TaskStatus.PENDING]
    running_tasks = [t for t in queue.tasks.values() if t.status == TaskStatus.RUNNING]
    completed_tasks = [t for t in queue.tasks.values() if t.status == TaskStatus.COMPLETED]

    return {
        "active": state.active,
        "config": {
            "max_agents": state.config.max_agents,
            "poll_interval": state.config.review_poll_interval_minutes,
            "pr_id": state.config.pr_id,
        },
        "started_at": state.started_at,
        "exit_reason": state.exit_reason,
        "queue": {
            "pending": len(pending_tasks),
            "running": len(running_tasks),
            "completed": len(completed_tasks),
            "total": len(queue.tasks),
        },
        "workers": {
            "active": len(workers),
            "max": state.config.max_agents,
        },
        "flags": {
            "push_pending": state.push_pending,
            "review_pending": state.review_pending,
        },
    }


def spawn_eligible_tasks(
    on_spawn: Optional[Callable[[str, str, str], str]] = None
) -> list[str]:
    """Spawn subagents for eligible tasks.

    Args:
        on_spawn: Callback(task_id, description, pr_id) -> subagent_id
                  If None, uses default Task tool spawning.

    Returns:
        List of spawned worker IDs.
    """
    queue = load_queue()
    state = _load_state()

    if not state.active:
        return []

    spawned = []

    # Get eligible tasks (respects dependencies)
    while should_spawn_worker(queue_has_work=queue.has_pending()):
        eligible = queue.get_eligible_tasks(1)
        if not eligible:
            break

        task = eligible[0]

        # Mark task as running
        queue.mark_running(task.id, "orchestrate")
        save_queue(queue)

        # Update iterate state with task context for subagent-enforcement hook
        # This sets current_group and current_repo_path before spawning
        iterate_state = workflow_client.workflow_get_state("iterate") or {}
        iterate_state["current_group"] = task.pr_id
        iterate_state["current_repo_path"] = getattr(task, "repo_path", "") or ""
        workflow_client.workflow_set_state("iterate", iterate_state)

        # Spawn worker
        worker_id = spawn_worker(task.id, task.description)

        # Call custom spawn callback if provided
        if on_spawn:
            try:
                on_spawn(task.id, task.description, task.pr_id)
            except Exception as e:
                print(f"[ORCHESTRATE] Spawn callback failed: {e}", file=sys.stderr)

        spawned.append(worker_id)
        print(f"[ORCHESTRATE] Spawned worker {worker_id} for task {task.id}")

        # Reload queue for next iteration
        queue = load_queue()

    return spawned


def handle_worker_completion(worker_id: str, success: bool, result: Optional[dict] = None) -> None:
    """Handle a worker completing its task.

    Args:
        worker_id: ID of the completed worker.
        success: Whether the task succeeded.
        result: Optional result metadata.
    """
    # Get worker info before marking complete
    workers = get_active_workers()
    worker = next((w for w in workers if w["worker_id"] == worker_id), None)

    if not worker:
        print(f"[ORCHESTRATE] Unknown worker: {worker_id}", file=sys.stderr)
        return

    task_id = worker["task_id"]

    # Update worker pool
    on_worker_complete(worker_id, success, result)

    # Update task queue
    queue = load_queue()
    task = queue.get_task(task_id)

    if task:
        if success:
            queue.mark_complete(task_id, result)
            print(f"[ORCHESTRATE] Task {task_id} completed successfully")
        else:
            error = result.get("error", "Unknown error") if result else "Unknown error"
            will_retry = queue.retry_or_escalate(task_id, error)
            if not will_retry:
                print(f"[ORCHESTRATE] Task {task_id} requires manual intervention", file=sys.stderr)

        save_queue(queue)

    # Check if ready for push
    _check_push_ready()


def _check_push_ready() -> None:
    """Check if all tasks are committed and trigger push if ready."""
    state = _load_state()
    queue = load_queue()

    if not state.active:
        return

    pr_id = state.config.pr_id
    if queue.is_pr_ready_for_push(pr_id):
        state.push_pending = True
        _save_state(state)
        print(f"[ORCHESTRATE] All tasks committed - push ready for {pr_id}")


def check_review_poll() -> bool:
    """Check if it's time to poll for review comments.

    Automatically fetches and processes comments when poll is triggered.

    Returns:
        True if poll was triggered, False if not time yet.
    """
    state = _load_state()

    if not state.active or not state.push_pending:
        return False

    # Check poll interval
    if state.last_poll:
        last_poll_time = datetime.fromisoformat(state.last_poll.replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - last_poll_time).total_seconds() / 60
        if elapsed < state.config.review_poll_interval_minutes:
            return False

    # Time to poll - update state first
    state.last_poll = _now_iso()
    state.review_pending = True
    _save_state(state)

    print("[ORCHESTRATE] Polling for review comments...")

    # Fetch and process comments automatically
    # Import here to avoid circular dependency
    from iterate_workflow import fetch_pr_review_status, get_pr_number

    pr_number = get_pr_number()
    if pr_number is None:
        print("[ORCHESTRATE] No PR number set - skipping poll")
        return True

    # Fetch comments from GitHub
    comments = fetch_pr_review_status(pr_number)
    print(f"[ORCHESTRATE] Fetched {len(comments)} unresolved comments")

    # Process comments into tasks
    if comments:
        tasks_added = process_review_comments(comments)
        print(f"[ORCHESTRATE] Added {tasks_added} review tasks")
    else:
        # No comments found - mark review as potentially clean
        print("[ORCHESTRATE] No review comments found")

    return True


def process_review_comments(comments: list[dict]) -> int:
    """Process review comments and add as tasks.

    Args:
        comments: List of comment dicts with 'id', 'body', 'path', etc.

    Returns:
        Number of new tasks created.
    """
    from workflow_queue import WorkflowQueue

    state = _load_state()
    if not state.active:
        return 0

    wq = WorkflowQueue(pr_id=state.config.pr_id)
    added = 0

    for comment in comments:
        try:
            wq.add_pr_comment(comment)
            added += 1
            print(f"[ORCHESTRATE] Added review task: {comment.get('id', 'unknown')}")
        except Exception as e:
            print(f"[ORCHESTRATE] Failed to add comment: {e}", file=sys.stderr)

    if added > 0:
        # Reset push pending since we have new tasks
        state.push_pending = False
        state.review_pending = False
        _save_state(state)
        print(f"[ORCHESTRATE] {added} review tasks added - resuming work")

    return added


def is_orchestrate_complete() -> bool:
    """Check if orchestrate loop is complete.

    Complete when:
    - Queue empty (no pending or running)
    - No active workers
    - Review is clean (no pending comments)
    """
    state = _load_state()
    if not state.active:
        return False

    queue = load_queue()
    workers = get_active_workers() if worker_pool_is_active() else []

    queue_empty = not queue.has_pending() and not queue.has_running()
    no_workers = len(workers) == 0
    review_clean = not state.review_pending

    return queue_empty and no_workers and review_clean


def run_single_iteration() -> str:
    """Run a single iteration of the orchestrate loop.

    Returns:
        Status string: "continue", "complete", "inactive"
    """
    state = _load_state()
    if not state.active:
        return "inactive"

    # Check if complete
    if is_orchestrate_complete():
        stop_orchestrate("complete")
        return "complete"

    # Spawn eligible tasks
    spawn_eligible_tasks()

    # Check if push ready
    _check_push_ready()

    # Check review poll
    check_review_poll()

    return "continue"


# =============================================================================
# CLI Interface
# =============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="ORCHESTRATE event loop management")
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # start command
    start_parser = subparsers.add_parser("start", help="Start orchestrate loop")
    start_parser.add_argument("--max-agents", type=int, default=3, help="Max parallel agents")
    start_parser.add_argument("--poll-interval", type=int, default=5, help="Review poll interval (minutes)")
    start_parser.add_argument("--pr", default="default", help="PR identifier")
    start_parser.add_argument("--spec", help="Spec file path")

    # status command
    subparsers.add_parser("status", help="Show orchestrate status")

    # stop command
    stop_parser = subparsers.add_parser("stop", help="Stop orchestrate loop")
    stop_parser.add_argument("--reason", default="user_stopped", help="Stop reason")

    # spawn command (single iteration)
    subparsers.add_parser("spawn", help="Spawn eligible tasks (single iteration)")

    # complete command (mark worker complete)
    complete_parser = subparsers.add_parser("complete", help="Mark worker as complete")
    complete_parser.add_argument("worker_id", help="Worker ID")
    complete_parser.add_argument("--success", action="store_true", default=True, help="Task succeeded")
    complete_parser.add_argument("--failed", action="store_true", help="Task failed")

    args = parser.parse_args()

    if args.command == "start":
        config = OrchestrateConfig(
            max_agents=args.max_agents,
            review_poll_interval_minutes=args.poll_interval,
            pr_id=args.pr,
            spec_file=args.spec,
        )
        start_orchestrate(config)

    elif args.command == "status":
        status = get_status()
        print(json.dumps(status, indent=2))

    elif args.command == "stop":
        stop_orchestrate(args.reason)

    elif args.command == "spawn":
        spawned = spawn_eligible_tasks()
        if spawned:
            print(f"Spawned {len(spawned)} workers: {', '.join(spawned)}")
        else:
            print("No tasks eligible for spawning")

    elif args.command == "complete":
        success = not args.failed
        handle_worker_completion(args.worker_id, success)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
