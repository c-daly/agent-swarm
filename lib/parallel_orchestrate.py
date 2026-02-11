#!/usr/bin/env python3
"""Parallel Orchestrator — spawn N independent subagents from a YAML manifest.

Each subagent works on its own git branch with TDD discipline. Gateway
conditions gate phase transitions. Failed tasks are retried up to max_retries.
After all tasks complete, branches are merged and the full suite is verified.

Usage:
    from parallel_orchestrate import ParallelOrchestrator

    orch = ParallelOrchestrator()
    orch.load_manifest("config/manifests/demo_data_structures.yaml")
    orch.start()
    orch.spawn_all()
    # ... monitor, handle completions ...
    orch.merge_all()
    orch.verify()
    print(orch.generate_summary())

CLI:
    python3 lib/parallel_orchestrate.py load <manifest_path>
    python3 lib/parallel_orchestrate.py status
    python3 lib/parallel_orchestrate.py summary
"""

import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

# Ensure lib directory is in path
lib_dir = Path(__file__).parent
if str(lib_dir) not in sys.path:
    sys.path.insert(0, str(lib_dir))

import worker_pool  # noqa: E402
import workflow_client  # noqa: E402
from gateway_conditions import GATEWAY_CONDITIONS  # noqa: E402
from workflow_queue import WorkflowQueue  # noqa: E402

WORKFLOW_ID = "parallel_orchestrate"

# Phases in order
PHASES = ["load_manifest", "spawn_agents", "monitor", "merge", "verify", "done"]


@dataclass
class ManifestTask:
    """A single task from the manifest."""

    name: str
    module_path: str
    test_path: str
    description: str
    min_tests: int = 1


@dataclass
class Manifest:
    """Parsed manifest."""

    name: str
    base_branch: str
    max_agents: int
    max_retries: int
    tasks: list[ManifestTask]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_manifest(path: str) -> Manifest:
    """Parse and validate a YAML manifest file.

    Args:
        path: Path to the YAML manifest.

    Returns:
        Parsed Manifest object.

    Raises:
        FileNotFoundError: If manifest file doesn't exist.
        ValueError: If manifest is missing required fields or has duplicates.
    """
    manifest_path = Path(path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")

    with open(manifest_path) as f:
        data = yaml.safe_load(f)

    if not data:
        raise ValueError("Manifest is empty")
    if "name" not in data:
        raise ValueError("Manifest missing required field: name")
    if "tasks" not in data or not data["tasks"]:
        raise ValueError("Manifest missing required field: tasks")

    # Validate tasks and check for duplicates
    seen_names: set[str] = set()
    tasks = []
    for i, task_data in enumerate(data["tasks"]):
        for required in ("name", "module_path", "test_path", "description"):
            if required not in task_data:
                raise ValueError(f"Task {i} missing required field: {required}")

        name = task_data["name"]
        if name in seen_names:
            raise ValueError(f"Duplicate task name: {name}")
        seen_names.add(name)

        tasks.append(
            ManifestTask(
                name=name,
                module_path=task_data["module_path"],
                test_path=task_data["test_path"],
                description=task_data["description"],
                min_tests=task_data.get("min_tests", 1),
            )
        )

    return Manifest(
        name=data["name"],
        base_branch=data.get("base_branch", "dev"),
        max_agents=data.get("max_agents", 3),
        max_retries=data.get("max_retries", 2),
        tasks=tasks,
    )


def build_subagent_prompt(task: ManifestTask, base_branch: str) -> str:
    """Build the subagent prompt for a manifest task.

    Args:
        task: The manifest task to build a prompt for.
        base_branch: The base branch to branch from.

    Returns:
        Formatted prompt string.
    """
    return f"""Task: Implement {task.name} module with TDD

## Branch
Create and switch to branch: task/{task.name}
git checkout -b task/{task.name}

## TDD Cycle
1. Create {task.test_path} with {task.min_tests}+ tests (all must initially fail or error)
2. Create {task.module_path} implementing the interface to make tests pass
3. Run: pytest {task.test_path} -v
4. Iterate until all tests pass
5. Run: ruff check {task.module_path} {task.test_path}
6. Commit: git add {task.module_path} {task.test_path} && git commit -m "feat({task.name}): implement {task.name} with tests"

## Constraints
- ONLY modify files: {task.module_path}, {task.test_path}
- Write failing tests FIRST, then implement
- Conventional commit message required
- All tests must pass before committing

## Acceptance Criteria
- Branch task/{task.name} exists
- {task.test_path} has {task.min_tests}+ test functions
- pytest {task.test_path} exits 0
- ruff check exits 0
- Exactly 1 commit on task/{task.name} ahead of {base_branch}"""


class ParallelOrchestrator:
    """Orchestrates parallel subagent execution from a YAML manifest."""

    def __init__(self):
        self.manifest: Optional[Manifest] = None
        self._retries: dict[str, int] = {}  # task_name -> retry count
        self._worker_task_map: dict[str, str] = {}  # worker_id -> task_name
        self._results: dict[str, dict] = {}  # task_name -> result info

    def load_manifest(self, path: str) -> Manifest:
        """Load and validate a manifest file.

        Args:
            path: Path to the YAML manifest.

        Returns:
            The parsed Manifest.
        """
        self.manifest = parse_manifest(path)
        self._retries = {t.name: 0 for t in self.manifest.tasks}
        return self.manifest

    def start(self) -> None:
        """Initialize workflow state and worker pool from the loaded manifest.

        Raises:
            RuntimeError: If no manifest loaded or workflow already active.
        """
        if not self.manifest:
            raise RuntimeError("No manifest loaded")

        if workflow_client.workflow_is_active(WORKFLOW_ID):
            raise RuntimeError("Parallel orchestration already active")

        # Start workflow state
        workflow_client.workflow_start(
            WORKFLOW_ID,
            {
                "phase": "load_manifest",
                "manifest_name": self.manifest.name,
                "base_branch": self.manifest.base_branch,
                "max_retries": self.manifest.max_retries,
                "tasks": {
                    t.name: {"status": "pending", "retries": 0, "worker_id": None}
                    for t in self.manifest.tasks
                },
                "started_at": _now_iso(),
            },
        )

        # Start worker pool
        worker_pool.start(
            max_agents=self.manifest.max_agents,
            task=f"Parallel: {self.manifest.name}",
        )

        # Initialize task queue
        wq = WorkflowQueue(pr_id=self.manifest.name)
        wq.initialize_from_tasks(
            [
                {
                    "description": f"[{t.name}] {t.description}",
                    "metadata": {
                        "task_name": t.name,
                        "module_path": t.module_path,
                        "test_path": t.test_path,
                        "min_tests": t.min_tests,
                    },
                }
                for t in self.manifest.tasks
            ]
        )

        self._set_phase("spawn_agents")

    def stop(self) -> None:
        """Stop the orchestration."""
        if workflow_client.workflow_is_active(WORKFLOW_ID):
            workflow_client.workflow_stop(WORKFLOW_ID)
        if worker_pool.is_active():
            worker_pool.stop()

    def _set_phase(self, phase: str) -> None:
        """Update the current phase in workflow state."""
        workflow_client.workflow_set_value(WORKFLOW_ID, "phase", phase)

    def get_phase(self) -> Optional[str]:
        """Get the current phase."""
        return workflow_client.workflow_get_value(WORKFLOW_ID, "phase")

    def check_status(self) -> dict:
        """Return status of all tasks.

        Returns:
            Dict of {task_name: {"status": str, "retries": int, "worker_id": str|None}}
        """
        state = workflow_client.workflow_get_state(WORKFLOW_ID)
        if not state:
            return {}
        return state.get("tasks", {})

    def spawn_all(self) -> list[tuple[str, str]]:
        """Spawn subagents for all pending tasks (up to max_agents).

        Returns:
            List of (worker_id, task_name) pairs for spawned workers.
        """
        if not self.manifest:
            raise RuntimeError("No manifest loaded")

        spawned = []
        wq = WorkflowQueue(pr_id=self.manifest.name)

        while worker_pool.should_spawn_worker(queue_has_work=wq.get_next_task() is not None):
            task_obj = wq.get_next_task()
            if not task_obj:
                break

            # Find the manifest task by name from metadata
            task_name = task_obj.metadata.get("task_name", "")
            manifest_task = next(
                (t for t in self.manifest.tasks if t.name == task_name), None
            )
            if not manifest_task:
                wq.start_task(task_obj.id)
                continue

            prompt = build_subagent_prompt(manifest_task, self.manifest.base_branch)
            worker_id = worker_pool.spawn_worker(task_obj.id, prompt)

            # Track mapping
            self._worker_task_map[worker_id] = task_name
            wq.start_task(task_obj.id, agent_id=worker_id)

            # Update workflow state
            state = workflow_client.workflow_get_state(WORKFLOW_ID)
            if state and task_name in state.get("tasks", {}):
                state["tasks"][task_name]["status"] = "running"
                state["tasks"][task_name]["worker_id"] = worker_id
                workflow_client.workflow_set_state(WORKFLOW_ID, state)

            spawned.append((worker_id, task_name))

        if spawned:
            self._set_phase("monitor")

        return spawned

    def handle_completion(self, worker_id: str, success: bool, result: Optional[dict] = None) -> str:
        """Handle a worker completing its task.

        Args:
            worker_id: The completed worker's ID.
            success: Whether the task succeeded.
            result: Optional result metadata.

        Returns:
            "completed", "retrying", or "failed" indicating what happened.
        """
        if not self.manifest:
            raise RuntimeError("No manifest loaded")

        task_name = self._worker_task_map.get(worker_id, "")
        worker_pool.on_worker_complete(worker_id, success, result)

        state = workflow_client.workflow_get_state(WORKFLOW_ID)
        if not state or task_name not in state.get("tasks", {}):
            return "completed" if success else "failed"

        task_state = state["tasks"][task_name]

        if success:
            task_state["status"] = "completed"
            task_state["completed_at"] = _now_iso()
            self._results[task_name] = result or {}
            workflow_client.workflow_set_state(WORKFLOW_ID, state)
            return "completed"

        # Failed — check retries
        retries = self._retries.get(task_name, 0)
        max_retries = self.manifest.max_retries

        if retries < max_retries:
            self._retries[task_name] = retries + 1
            task_state["status"] = "pending"
            task_state["retries"] = retries + 1
            task_state["worker_id"] = None
            task_state["last_error"] = (result or {}).get("error", "unknown error")
            workflow_client.workflow_set_state(WORKFLOW_ID, state)

            # Re-enqueue with error context
            manifest_task = next(
                (t for t in self.manifest.tasks if t.name == task_name), None
            )
            if manifest_task:
                error_msg = (result or {}).get("error", "unknown error")
                wq = WorkflowQueue(pr_id=self.manifest.name)
                wq.initialize_from_tasks(
                    [
                        {
                            "description": (
                                f"[{task_name}] RETRY {retries + 1}/{max_retries}: "
                                f"{manifest_task.description} (previous error: {error_msg})"
                            ),
                            "metadata": {
                                "task_name": task_name,
                                "module_path": manifest_task.module_path,
                                "test_path": manifest_task.test_path,
                                "min_tests": manifest_task.min_tests,
                                "retry": retries + 1,
                                "previous_error": error_msg,
                            },
                        }
                    ]
                )
            return "retrying"

        # Max retries exceeded
        task_state["status"] = "failed"
        task_state["failed_at"] = _now_iso()
        task_state["last_error"] = (result or {}).get("error", "unknown error")
        workflow_client.workflow_set_state(WORKFLOW_ID, state)
        return "failed"

    def merge_all(self, cwd: Optional[str] = None) -> list[dict]:
        """Merge all completed task branches into the base branch.

        Args:
            cwd: Working directory for git commands.

        Returns:
            List of merge results [{task_name, success, message}].
        """
        if not self.manifest:
            raise RuntimeError("No manifest loaded")

        self._set_phase("merge")
        results = []

        state = workflow_client.workflow_get_state(WORKFLOW_ID)
        tasks = state.get("tasks", {}) if state else {}

        for task in self.manifest.tasks:
            task_state = tasks.get(task.name, {})
            if task_state.get("status") != "completed":
                continue

            branch = f"task/{task.name}"
            merge_result = subprocess.run(
                ["git", "merge", "--no-ff", branch, "-m", f"Merge branch '{branch}'"],
                capture_output=True,
                text=True,
                cwd=cwd,
            )

            if merge_result.returncode == 0:
                # Delete the branch after successful merge
                subprocess.run(
                    ["git", "branch", "-d", branch],
                    capture_output=True,
                    text=True,
                    cwd=cwd,
                )
                results.append(
                    {"task_name": task.name, "success": True, "message": f"merged {branch}"}
                )
            else:
                # Merge conflict — kickback to monitor
                self._set_phase("monitor")
                results.append(
                    {
                        "task_name": task.name,
                        "success": False,
                        "message": f"conflict merging {branch}: {merge_result.stderr.strip()}",
                    }
                )

        return results

    def verify(self, cwd: Optional[str] = None) -> tuple[bool, str]:
        """Run full_suite_passes gateway condition.

        Args:
            cwd: Working directory for pytest.

        Returns:
            (passed, message) from the gateway condition.
        """
        self._set_phase("verify")
        passed, msg = GATEWAY_CONDITIONS["full_suite_passes"]({"cwd": cwd})
        if passed:
            self._set_phase("done")
        else:
            self._set_phase("merge")
        return passed, msg

    def generate_summary(self) -> str:
        """Generate a markdown summary table of all tasks.

        Returns:
            Markdown string with task status table.
        """
        state = workflow_client.workflow_get_state(WORKFLOW_ID)
        if not state:
            return "No orchestration state found."

        tasks = state.get("tasks", {})
        phase = state.get("phase", "unknown")

        lines = [
            f"# Parallel Orchestration: {state.get('manifest_name', 'unknown')}",
            f"**Phase:** {phase}",
            "",
            "| Task | Status | Retries | Branch |",
            "|------|--------|---------|--------|",
        ]

        for name, info in tasks.items():
            status = info.get("status", "unknown")
            retries = info.get("retries", 0)
            branch = f"task/{name}"
            lines.append(f"| {name} | {status} | {retries} | {branch} |")

        return "\n".join(lines)


# =============================================================================
# CLI
# =============================================================================


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: parallel_orchestrate.py <load|status|summary> [args]")
        sys.exit(1)

    command = sys.argv[1]
    orch = ParallelOrchestrator()

    if command == "load":
        if len(sys.argv) < 3:
            print("Usage: parallel_orchestrate.py load <manifest_path>")
            sys.exit(1)
        manifest = orch.load_manifest(sys.argv[2])
        print(f"Loaded manifest: {manifest.name}")
        print(f"  Base branch: {manifest.base_branch}")
        print(f"  Max agents: {manifest.max_agents}")
        print(f"  Max retries: {manifest.max_retries}")
        print(f"  Tasks: {len(manifest.tasks)}")
        for t in manifest.tasks:
            print(f"    - {t.name}: {t.description}")

    elif command == "status":
        status = orch.check_status()
        if not status:
            print("No active orchestration.")
        else:
            for name, info in status.items():
                print(f"  {name}: {info.get('status', 'unknown')}")

    elif command == "summary":
        print(orch.generate_summary())

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
