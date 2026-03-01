"""Core orchestrator for parallel TDD subagents."""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

# Ensure plugin root is on sys.path for CLI invocation
_plugin_root = str(Path(__file__).parent.parent)
if _plugin_root not in sys.path:
    sys.path.insert(0, _plugin_root)

from lib.gateway_conditions import GATEWAY_CONDITIONS  # noqa: E402
from lib.manifest import Manifest, parse_manifest, validate_manifest  # noqa: E402
from lib.prompt_builder import build_retry_prompt, build_subagent_prompt  # noqa: E402
from lib.orchestration_state import OrchestrationState  # noqa: E402


@dataclass
class SpawnRequest:
    """Request to spawn a subagent for a task."""

    task_name: str
    branch_name: str
    prompt: str
    worktree_dir: str = ""


@dataclass
class MergeResult:
    """Result of merging a single branch."""

    branch: str
    success: bool
    message: str


class ParallelOrchestrator:
    """Orchestrates N independent TDD subagents from a manifest."""

    def __init__(self):
        self._manifest: Manifest | None = None
        self._state: OrchestrationState | None = None

    def load_manifest(self, path: str) -> None:
        """Parse and validate a YAML manifest."""
        self._manifest = parse_manifest(path)
        warnings = validate_manifest(self._manifest)
        for w in warnings:
            print(f"[WARN] {w}", file=sys.stderr)
        self._state = OrchestrationState(self._manifest.project)
        if self._state.exists():
            self._state.load()

    def start(self, cwd: str = "") -> None:
        """Initialize orchestration state and create worktrees for all tasks.

        Args:
            cwd: Working directory containing the git repo. When provided,
                 worktrees are created under {project_dir}/.worktrees/{project}/
                 for each task.
        """
        self._require_manifest()
        if self.is_active():
            raise RuntimeError("Orchestration already active — stop first")

        self._state.set("active", True)
        self._state.set("phase", "spawning")
        self._state.set("tasks", {})

        for task in self._manifest.tasks:
            worktree_dir = ""
            if cwd:
                worktree_dir = self._create_worktree(cwd, task)
            self._state.update_task(
                task.name, status="pending", retries=0, worktree_dir=worktree_dir
            )
        self._state.save()

    def _create_worktree(self, cwd: str, task) -> str:
        """Create a git worktree for a task. Returns the worktree path.

        If the worktree already exists, reuses it.
        If the branch already exists (retry), adds worktree without -b.
        """
        project_root = str(Path(cwd) / self._manifest.project_dir)
        worktree_path = str(
            Path(project_root) / ".worktrees" / self._manifest.project / task.name
        )

        # Check if worktree already exists
        if Path(worktree_path).exists():
            return worktree_path

        # Check if branch already exists
        branch_check = subprocess.run(
            ["git", "rev-parse", "--verify", task.branch_name],
            cwd=project_root,
            capture_output=True,
            text=True,
        )

        Path(worktree_path).parent.mkdir(parents=True, exist_ok=True)

        if branch_check.returncode == 0:
            # Branch exists (retry case) — add worktree on existing branch
            subprocess.run(
                ["git", "worktree", "add", worktree_path, task.branch_name],
                cwd=project_root,
                capture_output=True,
                text=True,
                check=True,
            )
        else:
            # New branch — create from base_branch
            subprocess.run(
                [
                    "git", "worktree", "add",
                    worktree_path,
                    "-b", task.branch_name,
                    self._manifest.base_branch,
                ],
                cwd=project_root,
                capture_output=True,
                text=True,
                check=True,
            )

        return worktree_path

    def stop(self, cwd: str = "") -> None:
        """Deactivate orchestration and clean up worktrees.

        Args:
            cwd: Working directory. When provided, removes worktrees
                 created during start().
        """
        self._require_state()
        if cwd:
            self._cleanup_worktrees(cwd)
        self._state.set("active", False)
        self._state.set("phase", "stopped")
        self._state.save()

    def _cleanup_worktrees(self, cwd: str) -> None:
        """Remove all worktrees created for this orchestration."""
        self._require_manifest()
        project_root = str(Path(cwd) / self._manifest.project_dir)
        worktrees_parent = (
            Path(project_root) / ".worktrees" / self._manifest.project
        )

        tasks = self._state.get("tasks", {})
        for task in self._manifest.tasks:
            ts = tasks.get(task.name, {})
            worktree_dir = ts.get("worktree_dir", "")
            if worktree_dir and Path(worktree_dir).exists():
                subprocess.run(
                    ["git", "worktree", "remove", worktree_dir, "--force"],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                )

        # Remove empty .worktrees/{project}/ directory
        if worktrees_parent.exists():
            try:
                worktrees_parent.rmdir()
            except OSError:
                pass  # Not empty, leave it

    def is_active(self) -> bool:
        self._require_state()
        return bool(self._state.get("active", False))

    # --- Spawn ---

    def _dependencies_met(self, task) -> bool:
        """Check if all depends_on tasks are completed."""
        tasks_state = self._state.get("tasks", {})
        for dep_name in task.depends_on:
            dep_state = tasks_state.get(dep_name, {})
            if dep_state.get("status") != "completed":
                return False
        return True

    def get_pending_tasks(self) -> list[SpawnRequest]:
        """Return spawn requests for tasks still pending."""
        self._require_manifest()
        self._require_state()
        tasks_state = self._state.get("tasks", {})
        pending = []
        for task in self._manifest.tasks:
            ts = tasks_state.get(task.name, {})
            if ts.get("status") == "pending" and self._dependencies_met(task):
                retries = ts.get("retries", 0)
                last_error = ts.get("last_error", "")
                worktree_dir = ts.get("worktree_dir", "")
                if retries > 0 and last_error:
                    prompt = build_retry_prompt(
                        task,
                        base_branch=self._manifest.base_branch,
                        error=last_error,
                        attempt=retries + 1,
                        max_retries=self._manifest.max_retries,
                        worktree_dir=worktree_dir,
                        project_dir=self._manifest.project_dir,
                    )
                else:
                    prompt = build_subagent_prompt(
                        task,
                        self._manifest.base_branch,
                        worktree_dir=worktree_dir,
                        project_dir=self._manifest.project_dir,
                    )
                pending.append(SpawnRequest(
                    task_name=task.name,
                    branch_name=task.branch_name,
                    prompt=prompt,
                    worktree_dir=worktree_dir,
                ))
        return pending

    def record_spawn(self, task_name: str, worker_id: str) -> None:
        """Record that a task has been spawned."""
        self._require_state()
        self._state.update_task(task_name, status="spawned", worker_id=worker_id)
        self._update_phase()
        self._state.save()

    # --- Monitor ---

    def record_completion(
        self, task_name: str, success: bool, error: str = ""
    ) -> Literal["completed", "retrying", "failed"]:
        """Record task completion. Returns outcome."""
        self._require_manifest()
        self._require_state()
        tasks = self._state.get("tasks", {})
        task_state = tasks.get(task_name, {})
        retries = task_state.get("retries", 0)

        if success:
            self._state.update_task(task_name, status="completed", error="")
            self._update_phase()
            self._state.save()
            return "completed"

        if retries >= self._manifest.max_retries:
            self._state.update_task(
                task_name, status="failed", last_error=error
            )
            self._propagate_failure(task_name)
            self._update_phase()
            self._state.save()
            return "failed"

        self._state.update_task(
            task_name, status="pending", retries=retries + 1, last_error=error
        )
        self._update_phase()
        self._state.save()
        return "retrying"

    def check_all_done(self) -> bool:
        """Check if all tasks are completed or failed."""
        self._require_state()
        tasks = self._state.get("tasks", {})
        return all(
            t.get("status") in ("completed", "failed") for t in tasks.values()
        )

    # --- Merge ---

    def _topological_order(self) -> list[str]:
        """Return task names in topological order (dependencies first)."""
        dep_map = {t.name: list(t.depends_on) for t in self._manifest.tasks}
        order: list[str] = []
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            for dep in dep_map.get(name, []):
                visit(dep)
            order.append(name)

        for task in self._manifest.tasks:
            visit(task.name)
        return order

    def merge_all(self, cwd: str) -> list[MergeResult]:
        """Merge all completed task branches into base branch."""
        self._require_manifest()
        self._require_state()
        results = []
        tasks = self._state.get("tasks", {})
        project_root = str(Path(cwd) / self._manifest.project_dir)

        # Checkout base branch first
        subprocess.run(
            ["git", "checkout", self._manifest.base_branch],
            cwd=project_root,
            capture_output=True,
            text=True,
        )

        merge_order = self._topological_order()
        task_by_name = {t.name: t for t in self._manifest.tasks}
        for task_name in merge_order:
            task = task_by_name[task_name]
            ts = tasks.get(task.name, {})
            if ts.get("status") != "completed":
                continue

            result = subprocess.run(
                ["git", "merge", task.branch_name, "--no-ff",
                 "-m", f"Merge {task.branch_name}"],
                cwd=project_root,
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                results.append(MergeResult(
                    branch=task.branch_name,
                    success=True,
                    message=f"Merged {task.branch_name}",
                ))
            else:
                # Abort the failed merge
                subprocess.run(
                    ["git", "merge", "--abort"],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                )
                results.append(MergeResult(
                    branch=task.branch_name,
                    success=False,
                    message=f"Merge conflict: {result.stderr.strip()}",
                ))

        return results

    # --- Verify ---

    def verify(self, cwd: str) -> tuple[bool, str]:
        """Run full test suite after merges."""
        self._require_manifest()
        project_root = str(Path(cwd) / self._manifest.project_dir)
        result = subprocess.run(
            ["python3", "-m", "pytest", "-v", "--tb=short"],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            last_line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "ok"
            return True, f"Full suite passed: {last_line}"
        last_line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "unknown"
        return False, f"Full suite failed: {last_line}"

    # --- Gateway ---

    def check_gateway(
        self, name: str, context: dict[str, Any]
    ) -> tuple[bool, str]:
        """Check a named gateway condition."""
        fn = GATEWAY_CONDITIONS.get(name)
        if fn is None:
            return False, f"Unknown gateway condition: {name}"
        return fn(**context)

    # --- Status ---

    def get_phase(self) -> str:
        self._require_state()
        return self._state.get("phase", "unknown")

    def get_status(self) -> dict[str, Any]:
        self._require_state()
        return {
            "project": self._manifest.project if self._manifest else "unknown",
            "active": self._state.get("active", False),
            "phase": self._state.get("phase", "unknown"),
            "tasks": self._state.get("tasks", {}),
        }

    def generate_summary(self) -> str:
        """Generate a markdown summary table."""
        self._require_state()
        self._require_manifest()
        tasks = self._state.get("tasks", {})
        lines = [
            f"# Orchestration: {self._manifest.project}",
            f"Phase: {self.get_phase()}",
            "",
            "| Task | Status | Retries | Worker | Blocked by |",
            "|------|--------|---------|--------|------------|",
        ]
        for task in self._manifest.tasks:
            ts = tasks.get(task.name, {})
            # Show unmet dependencies
            unmet = []
            for dep in task.depends_on:
                dep_state = tasks.get(dep, {})
                if dep_state.get("status") != "completed":
                    unmet.append(dep)
            blocked = ", ".join(unmet) if unmet else "-"
            lines.append(
                f"| {task.name} | {ts.get('status', 'unknown')} | "
                f"{ts.get('retries', 0)} | {ts.get('worker_id', '-')} | {blocked} |"
            )
        return "\n".join(lines)

    # --- Internal ---

    def _propagate_failure(self, failed_task_name: str) -> None:
        """Mark all tasks that transitively depend on failed_task_name as failed."""
        # Build reverse dependency map: task -> list of tasks that depend on it
        dependents: dict[str, list[str]] = {}
        for task in self._manifest.tasks:
            for dep in task.depends_on:
                dependents.setdefault(dep, []).append(task.name)

        # BFS from failed task
        queue = [failed_task_name]
        visited = {failed_task_name}
        while queue:
            current = queue.pop(0)
            for dependent in dependents.get(current, []):
                if dependent not in visited:
                    visited.add(dependent)
                    self._state.update_task(
                        dependent,
                        status="failed",
                        last_error=f"Dependency '{failed_task_name}' failed",
                    )
                    queue.append(dependent)

    def _update_phase(self) -> None:
        """Auto-advance phase based on task states."""
        tasks = self._state.get("tasks", {})
        statuses = [t.get("status") for t in tasks.values()]

        if all(s in ("completed", "failed") for s in statuses):
            self._state.set("phase", "merging")
        elif any(s == "spawned" for s in statuses):
            self._state.set("phase", "monitoring")
        elif any(s == "pending" for s in statuses):
            self._state.set("phase", "spawning")

    def _require_manifest(self) -> None:
        if self._manifest is None:
            raise RuntimeError("No manifest loaded — call load_manifest() first")

    def _require_state(self) -> None:
        if self._state is None:
            raise RuntimeError("No state initialized — call load_manifest() first")


# --- CLI ---

def main():
    """CLI entry point for orchestrator commands."""
    if len(sys.argv) < 2:
        print("Usage: orchestrator.py <command> [args]")
        cmds = "load, start, pending, spawned, complete, status, merge, verify, summary, stop"
        print(f"Commands: {cmds}")
        sys.exit(1)

    cmd = sys.argv[1]
    orch = ParallelOrchestrator()

    if cmd == "load":
        if len(sys.argv) < 3:
            print("Usage: orchestrator.py load <manifest.yaml>")
            sys.exit(1)
        orch.load_manifest(sys.argv[2])
        print(json.dumps({
            "project": orch._manifest.project,
            "tasks": len(orch._manifest.tasks),
            "base_branch": orch._manifest.base_branch,
        }, indent=2))

    elif cmd == "start":
        if len(sys.argv) < 4:
            print("Usage: orchestrator.py start <manifest.yaml> <cwd>")
            sys.exit(1)
        orch.load_manifest(sys.argv[2])
        orch.start(cwd=sys.argv[3])
        print(json.dumps(orch.get_status(), indent=2))

    elif cmd == "pending":
        if len(sys.argv) < 3:
            print("Usage: orchestrator.py pending <manifest.yaml> [--json]")
            sys.exit(1)
        orch.load_manifest(sys.argv[2])
        pending = orch.get_pending_tasks()
        use_json = "--json" in sys.argv
        if use_json:
            print(json.dumps([
                {
                    "task_name": req.task_name,
                    "branch_name": req.branch_name,
                    "worktree_dir": req.worktree_dir,
                    "prompt": req.prompt,
                }
                for req in pending
            ], indent=2))
        else:
            for req in pending:
                header = f"\n=== {req.task_name} ({req.branch_name})"
                if req.worktree_dir:
                    header += f" [worktree: {req.worktree_dir}]"
                header += " ==="
                print(header)
                print(req.prompt)

    elif cmd == "spawned":
        if len(sys.argv) < 5:
            print("Usage: orchestrator.py spawned <manifest.yaml> <task_name> <worker_id>")
            sys.exit(1)
        orch.load_manifest(sys.argv[2])
        orch.record_spawn(sys.argv[3], sys.argv[4])
        print(json.dumps(orch.get_status(), indent=2))

    elif cmd == "complete":
        if len(sys.argv) < 4:
            print("Usage: orchestrator.py complete <manifest.yaml> <task_name> [error]")
            sys.exit(1)
        orch.load_manifest(sys.argv[2])
        task_name = sys.argv[3]
        error = sys.argv[4] if len(sys.argv) > 4 else ""
        success = not error
        result = orch.record_completion(task_name, success=success, error=error)
        print(f"Result: {result}")
        print(json.dumps(orch.get_status(), indent=2))

    elif cmd == "status":
        if len(sys.argv) < 3:
            print("Usage: orchestrator.py status <manifest.yaml>")
            sys.exit(1)
        orch.load_manifest(sys.argv[2])
        print(json.dumps(orch.get_status(), indent=2))

    elif cmd == "merge":
        if len(sys.argv) < 4:
            print("Usage: orchestrator.py merge <manifest.yaml> <cwd>")
            sys.exit(1)
        orch.load_manifest(sys.argv[2])
        results = orch.merge_all(cwd=sys.argv[3])
        for r in results:
            status = "OK" if r.success else "FAIL"
            print(f"[{status}] {r.branch}: {r.message}")

    elif cmd == "verify":
        if len(sys.argv) < 4:
            print("Usage: orchestrator.py verify <manifest.yaml> <cwd>")
            sys.exit(1)
        orch.load_manifest(sys.argv[2])
        ok, msg = orch.verify(cwd=sys.argv[3])
        print(f"{'PASS' if ok else 'FAIL'}: {msg}")

    elif cmd == "summary":
        if len(sys.argv) < 3:
            print("Usage: orchestrator.py summary <manifest.yaml>")
            sys.exit(1)
        orch.load_manifest(sys.argv[2])
        print(orch.generate_summary())

    elif cmd == "stop":
        if len(sys.argv) < 4:
            print("Usage: orchestrator.py stop <manifest.yaml> <cwd>")
            sys.exit(1)
        orch.load_manifest(sys.argv[2])
        orch.stop(cwd=sys.argv[3])
        print("Orchestration stopped.")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
