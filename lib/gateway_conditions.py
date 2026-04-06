"""Phase gate validators. Never raise — always return (bool, str)."""

import subprocess
from typing import Any


def _last_line(output: str, fallback: str = "unknown") -> str:
    """Extract the last line from output, or return fallback."""
    stripped = output.strip()
    if stripped:
        return stripped.splitlines()[-1]
    return fallback


def branch_exists(*, branch: str, cwd: str, **kwargs: Any) -> tuple[bool, str]:
    """Check if a git branch exists."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", branch],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True, f"Branch '{branch}' exists"
        return False, f"Branch '{branch}' does not exist"
    except Exception as e:
        return False, f"Error checking branch: {e}"


def tests_written(
    *, test_dir: str, min_tests: int, cwd: str, **kwargs: Any
) -> tuple[bool, str]:
    """Check if enough test functions have been written."""
    try:
        result = subprocess.run(
            ["grep", "-r", "-c", "def test_", test_dir],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        # Count lines of output (each line is file:count)
        lines = [line for line in result.stdout.strip().split("\n") if line]
        total = 0
        for line in lines:
            # grep -c output: filename:count or just count
            parts = line.rsplit(":", 1)
            try:
                total += int(parts[-1])
            except ValueError:
                # Line itself is a test function name (non -c mode fallback)
                total += 1

        if total >= min_tests:
            return True, f"Found {total} tests (minimum: {min_tests})"
        return False, f"Found {total} tests, need at least {min_tests}"
    except Exception as e:
        return False, f"Error counting tests: {e}"


def all_tests_pass(*, test_dir: str, cwd: str, **kwargs: Any) -> tuple[bool, str]:
    """Run pytest on a test directory and check all pass."""
    try:
        result = subprocess.run(
            ["python3", "-m", "pytest", test_dir, "-v", "--tb=short"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        last = _last_line(result.stdout, "ok")
        if result.returncode == 0:
            return True, f"All tests passed: {last}"
        return False, f"Tests failed: {last}"
    except Exception as e:
        return False, f"Error running tests: {e}"


def all_branches_merged(
    *, branches: list[str], cwd: str, **kwargs: Any
) -> tuple[bool, str]:
    """Check if all specified branches have been merged into current branch."""
    try:
        result = subprocess.run(
            ["git", "branch", "--merged"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        merged = {b.strip().lstrip("* ") for b in result.stdout.strip().split("\n")}
        unmerged = [b for b in branches if b not in merged]
        if not unmerged:
            return True, "All branches merged"
        return False, f"Unmerged branches: {', '.join(unmerged)}"
    except Exception as e:
        return False, f"Error checking merged branches: {e}"


def full_suite_passes(*, cwd: str, **kwargs: Any) -> tuple[bool, str]:
    """Run the full test suite and check all pass."""
    try:
        result = subprocess.run(
            ["python3", "-m", "pytest", "-v", "--tb=short"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        last = _last_line(result.stdout, "ok")
        if result.returncode == 0:
            return True, f"Full suite passed: {last}"
        return False, f"Full suite failed: {last}"
    except Exception as e:
        return False, f"Error running full suite: {e}"


def commit_exists(*, branch: str, cwd: str, **kwargs: Any) -> tuple[bool, str]:
    """Check if a branch has commits beyond the base."""
    try:
        result = subprocess.run(
            ["git", "log", branch, "-1", "--format=%h"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return True, f"Commit found on '{branch}': {result.stdout.strip()}"
        return False, f"No commits found on '{branch}'"
    except Exception as e:
        return False, f"Error checking commits: {e}"





def eval_tests_exist(
    *, eval_dir: str, cwd: str, **kwargs: Any
) -> tuple[bool, str]:
    """Check if eval test files exist in the task eval directory."""
    import os

    full_path = os.path.join(cwd, eval_dir) if not os.path.isabs(eval_dir) else eval_dir
    if not os.path.isdir(full_path):
        return False, f"Eval directory does not exist: {eval_dir}"

    test_files = [
        f for f in os.listdir(full_path)
        if f.startswith("test_") and f.endswith(".py")
    ]
    if not test_files:
        return False, f"No eval test files (test_*.py) found in {eval_dir}"
    return True, f"Found {len(test_files)} eval test file(s) in {eval_dir}"


def agent_registered(
    *, agent_id: str, cwd: str, **kwargs: Any
) -> tuple[bool, str]:
    """Check if an agent ID is registered with the daemon."""
    import re

    if not re.match(r"sub-[0-9a-f]{8}", agent_id):
        return False, f"Invalid agent ID format: {agent_id}"
    try:
        from daemon_client import DaemonClient
        with DaemonClient() as dc:
            state = dc.agent_get_state(agent_id)
            if state:
                return True, f"Agent {agent_id} is registered"
            return False, f"Agent {agent_id} not found in daemon"
    except Exception as e:
        return False, f"Error checking agent registration: {e}"


def workflow_phase_is(
    *, workflow_id: str, expected_phase: str, cwd: str, **kwargs: Any
) -> tuple[bool, str]:
    """Check if a workflow is in the expected phase."""
    try:
        from daemon_client import DaemonClient
        with DaemonClient() as dc:
            state = dc.workflow_get_state(workflow_id)
            if not state:
                return False, f"Workflow {workflow_id} not found"
            actual = state.get("phase", "unknown")
            if actual == expected_phase:
                return True, f"Workflow is in phase '{expected_phase}'"
            return False, f"Workflow is in phase '{actual}', expected '{expected_phase}'"
    except Exception as e:
        return False, f"Error checking workflow phase: {e}"


GATEWAY_CONDITIONS: dict[str, callable] = {
    "branch_exists": branch_exists,
    "tests_written": tests_written,
    "all_tests_pass": all_tests_pass,
    "all_branches_merged": all_branches_merged,
    "full_suite_passes": full_suite_passes,
    "commit_exists": commit_exists,
    "eval_tests_exist": eval_tests_exist,
    "agent_registered": agent_registered,
    "workflow_phase_is": workflow_phase_is,
}
