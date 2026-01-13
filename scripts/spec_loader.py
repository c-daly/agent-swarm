#!/usr/bin/env python3
"""Load tasks from SPEC.md into the TaskQueue.

Usage:
    python3 spec_loader.py load [--spec SPEC.md] [--clear]
    python3 spec_loader.py show [--spec SPEC.md]

Tasks are grouped by priority (P0, P1, etc.) into separate PRs for commit management.
"""

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path

from iterate_state import (
    Task,
    TaskQueue,
    TaskSource,
    TaskStatus,
    load_queue,
    save_queue,
)


def parse_spec(spec_path: Path) -> list[dict]:
    """Parse SPEC.md and extract tasks from tables.

    Looks for markdown tables with columns: ID | Task | Acceptance Criteria
    Returns list of task dicts with id, description, criteria, priority_group
    """
    content = spec_path.read_text()
    tasks = []

    # Track current priority group (P0, P1, etc.)
    current_priority = "P0"
    priority_map = {
        "P0": 0,  # Most painful - highest priority
        "P1": 1,
        "P2": 2,
        "P3": 3,
        "P4": 4,
        "P5": 5,
        "INT": 6,  # Integration - lowest priority
    }

    lines = content.split("\n")
    in_table = False

    for line in lines:
        # Detect priority section headers (## P0:, ## P1:, ## Integration, etc.)
        priority_match = re.match(r"^##\s+(P\d+):", line)
        if priority_match:
            current_priority = priority_match.group(1)
            continue

        # Integration section
        if re.match(r"^##\s+Integration", line):
            current_priority = "INT"
            continue

        # Detect table start (header row)
        if re.match(r"^\|\s*ID\s*\|", line):
            in_table = True
            continue

        # Skip separator row
        if re.match(r"^\|[-\s|]+\|$", line):
            continue

        # Parse data rows
        if in_table and line.startswith("|"):
            parts = [p.strip() for p in line.split("|")]
            # parts[0] is empty (before first |), parts[-1] is empty (after last |)
            if len(parts) >= 4:
                task_id = parts[1].strip()
                task_desc = parts[2].strip()
                criteria = parts[3].strip() if len(parts) > 3 else ""

                # Skip if not a real task ID (e.g., header row that slipped through)
                if not re.match(r"^[A-Z]+\d*\.\d+$", task_id):
                    continue

                tasks.append(
                    {
                        "id": task_id,
                        "description": task_desc,
                        "criteria": criteria,
                        "priority_group": current_priority,
                        "priority": priority_map.get(current_priority, 3),
                    }
                )
        elif in_table and not line.startswith("|"):
            # End of table
            in_table = False

    return tasks


def show_spec(spec_path: Path) -> None:
    """Show parsed tasks from spec."""
    tasks = parse_spec(spec_path)

    if not tasks:
        print("No tasks found in spec.")
        return

    print(f"Found {len(tasks)} tasks in {spec_path.name}\n")

    current_group = None
    for task in tasks:
        if task["priority_group"] != current_group:
            current_group = task["priority_group"]
            print(f"\n=== {current_group} ===")

        desc = (
            task["description"][:50] + "..."
            if len(task["description"]) > 50
            else task["description"]
        )
        print(f"  {task['id']:<8} {desc}")


def load_spec_to_queue(spec_path: Path, clear: bool = False) -> None:
    """Load tasks from spec into the queue.

    Tasks are grouped by priority_group (P0, P1, etc.) into separate PRs.
    This enables commit management per priority.
    """
    tasks = parse_spec(spec_path)

    if not tasks:
        print("No tasks found in spec.")
        return

    if clear:
        queue = TaskQueue()
        print("Cleared existing queue.")
    else:
        queue = load_queue()

    # Group tasks by priority
    by_priority: dict[str, list[dict]] = {}
    for task_data in tasks:
        group = task_data["priority_group"]
        if group not in by_priority:
            by_priority[group] = []
        by_priority[group].append(task_data)

    # PR naming: P0 -> pr-p0-subagent-prompting, etc.
    pr_names = {
        "P0": "pr-p0-subagent-prompting",
        "P1": "pr-p1-bash-escape",
        "P2": "pr-p2-phase-enforcement",
        "P3": "pr-p3-classification",
        "P4": "pr-p4-review-gate",
        "P5": "pr-p5-agent-protocols",
        "INT": "pr-int-integration",
    }

    added = 0
    for group, group_tasks in by_priority.items():
        pr_id = pr_names.get(group, f"pr-{group.lower()}")

        for task_data in group_tasks:
            task_id = f"task-{task_data['id'].lower().replace('.', '-')}"

            # Skip if already exists
            if task_id in queue.tasks:
                print(f"  Skipping {task_data['id']} (already exists)")
                continue

            task = Task(
                id=task_id,
                description=task_data["description"],
                status=TaskStatus.PENDING,
                priority=task_data["priority"],
                source=TaskSource.ORIGINAL,
                pr_id=pr_id,
                assigned_agent=None,
                phase="test_writing",  # Start in TDD phase
                iteration=0,
                created_at=datetime.now(timezone.utc).isoformat(),
                metadata={
                    "spec_id": task_data["id"],
                    "criteria": task_data["criteria"],
                    "priority_group": task_data["priority_group"],
                },
            )

            queue.add_task(task)
            added += 1

        print(f"  {group}: {len(group_tasks)} tasks -> {pr_id}")

    save_queue(queue)
    print(f"\nLoaded {added} tasks into queue")
    print(f"Total tasks: {len(queue.tasks)}, PRs: {len(queue.prs)}")


def show_queue_status() -> None:
    """Show queue progress by PR."""
    queue = load_queue()

    if not queue.tasks:
        print("Queue is empty.")
        return

    print("\n╔════════════════════════════════════════════════════════════════╗")
    print("║                    TASK QUEUE STATUS                           ║")
    print("╠════════════════════════════════════════════════════════════════╣")

    # Group by PR
    pr_order = [
        "pr-p0-subagent-prompting",
        "pr-p1-bash-escape",
        "pr-p2-phase-enforcement",
        "pr-p3-classification",
        "pr-p4-review-gate",
        "pr-p5-agent-protocols",
        "pr-int-integration",
    ]

    total_done = 0
    total_tasks = len(queue.tasks)

    for pr_id in pr_order:
        if pr_id not in queue.prs:
            continue

        pr_tasks = queue.get_tasks_for_pr(pr_id)

        done = sum(1 for t in pr_tasks if t.status == TaskStatus.COMPLETED)
        running = sum(1 for t in pr_tasks if t.status == TaskStatus.RUNNING)
        total_done += done

        # Progress bar
        pct = (done / len(pr_tasks) * 100) if pr_tasks else 0
        bar_len = 20
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)

        # Short name
        short_name = pr_id.replace("pr-", "").upper()

        status = "✓" if done == len(pr_tasks) else ("▶" if running > 0 else " ")
        print(f"║ {status} {short_name:<20} [{bar}] {done}/{len(pr_tasks):>2} ║")

    print("╠════════════════════════════════════════════════════════════════╣")
    pct = (total_done / total_tasks * 100) if total_tasks else 0
    print(
        f"║  TOTAL: {total_done}/{total_tasks} tasks ({pct:.0f}%)                               ║"
    )
    print("╚════════════════════════════════════════════════════════════════╝\n")


def mark_task_status(task_spec_id: str, new_status: str) -> None:
    """Mark a task by spec ID (e.g., P0.1) as in_progress or completed."""
    queue = load_queue()

    # Find task by spec_id in metadata
    task_id = f"task-{task_spec_id.lower().replace('.', '-')}"
    task = queue.get_task(task_id)

    if not task:
        print(f"Task not found: {task_spec_id} (looked for {task_id})")
        return

    if new_status == "start":
        task.status = TaskStatus.RUNNING
        print(f"▶ Started: {task_spec_id} - {task.description[:50]}")
    elif new_status == "done":
        task.status = TaskStatus.COMPLETED
        if task_id not in queue.completed:
            queue.completed.append(task_id)
        print(f"✓ Completed: {task_spec_id} - {task.description[:50]}")

    save_queue(queue)
    show_queue_status()


def main():
    parser = argparse.ArgumentParser(description="Load tasks from SPEC.md")
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # load command
    load_parser = subparsers.add_parser("load", help="Load tasks into queue")
    load_parser.add_argument("--spec", default="SPEC.md", help="Path to spec file")
    load_parser.add_argument("--clear", action="store_true", help="Clear queue first")

    # show command
    show_parser = subparsers.add_parser("show", help="Show tasks from spec")
    show_parser.add_argument("--spec", default="SPEC.md", help="Path to spec file")

    # status command
    subparsers.add_parser("status", help="Show queue progress")

    # start command
    start_parser = subparsers.add_parser("start", help="Mark task as in_progress")
    start_parser.add_argument("task_id", help="Task spec ID (e.g., P0.1)")

    # done command
    done_parser = subparsers.add_parser("done", help="Mark task as completed")
    done_parser.add_argument("task_id", help="Task spec ID (e.g., P0.1)")

    args = parser.parse_args()

    if args.command == "status":
        show_queue_status()
        return

    if args.command == "start":
        mark_task_status(args.task_id, "start")
        return

    if args.command == "done":
        mark_task_status(args.task_id, "done")
        return

    # Resolve spec path relative to plugin root
    plugin_root = Path(__file__).parent.parent
    spec_path = plugin_root / args.spec

    if not spec_path.exists():
        print(f"Spec not found: {spec_path}")
        return

    if args.command == "load":
        load_spec_to_queue(spec_path, args.clear)
    elif args.command == "show":
        show_spec(spec_path)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
