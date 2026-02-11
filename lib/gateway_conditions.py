"""Gateway condition validators for workflow phase transitions.

Subprocess-based validators that shell out to git/pytest directly,
making them self-contained and testable via subprocess.run mocking.

Signature: (context: dict) -> tuple[bool, str]
    Returns (passed, message) where message explains the result.

Usage:
    from gateway_conditions import GATEWAY_CONDITIONS

    passed, msg = GATEWAY_CONDITIONS["branch_exists"]({"branch": "task/stack"})
    if not passed:
        print(f"Gate failed: {msg}")
"""

import subprocess
from pathlib import Path
from typing import Callable


def branch_exists(context: dict) -> tuple[bool, str]:
    """Check if a git branch exists.

    Context keys:
        branch (str): Branch name to check (e.g. "task/stack").
        cwd (str, optional): Working directory for git command.
    """
    branch = context.get("branch", "")
    if not branch:
        return False, "no branch name provided"

    cwd = context.get("cwd")
    result = subprocess.run(
        ["git", "branch", "--list", branch],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    output = result.stdout.strip()
    if output:
        return True, f"branch '{branch}' exists"
    return False, f"branch '{branch}' does not exist"


def tests_written(context: dict) -> tuple[bool, str]:
    """Check if a test file has enough test functions.

    Context keys:
        test_path (str): Path to the test file.
        min_tests (int, optional): Minimum number of test functions. Default 1.
    """
    test_path = context.get("test_path", "")
    if not test_path:
        return False, "no test path provided"

    min_tests = context.get("min_tests", 1)
    path = Path(test_path)

    if not path.exists():
        return False, f"test file not found: {test_path}"

    content = path.read_text()
    count = content.count("def test_")
    if count >= min_tests:
        return True, f"found {count} test functions (min: {min_tests})"
    return False, f"found {count} test functions, need at least {min_tests}"


def all_tests_pass(context: dict) -> tuple[bool, str]:
    """Check if pytest passes for a given test path.

    Context keys:
        test_path (str): Path to test file or directory.
        cwd (str, optional): Working directory for pytest.
    """
    test_path = context.get("test_path", "")
    if not test_path:
        return False, "no test path provided"

    cwd = context.get("cwd")
    result = subprocess.run(
        ["pytest", test_path, "--tb=short", "-q"],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode == 0:
        return True, f"all tests pass: {result.stdout.strip().splitlines()[-1] if result.stdout.strip() else 'ok'}"
    # Include last line of output for context
    last_line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else result.stderr.strip()
    return False, f"tests failed: {last_line}"


def all_branches_merged(context: dict) -> tuple[bool, str]:
    """Check if all task/* branches have been merged and deleted.

    Context keys:
        prefix (str, optional): Branch prefix to check. Default "task/".
        cwd (str, optional): Working directory for git command.
    """
    prefix = context.get("prefix", "task/")
    cwd = context.get("cwd")

    result = subprocess.run(
        ["git", "branch", "--list", f"{prefix}*"],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    branches = [b.strip() for b in result.stdout.strip().splitlines() if b.strip()]
    if not branches:
        return True, "all task branches merged and deleted"
    return False, f"remaining branches: {', '.join(branches)}"


def full_suite_passes(context: dict) -> tuple[bool, str]:
    """Check if the full pytest suite passes.

    Context keys:
        cwd (str, optional): Working directory for pytest.
        args (list[str], optional): Extra pytest arguments.
    """
    cwd = context.get("cwd")
    extra_args = context.get("args", [])

    cmd = ["pytest", "--tb=short", "-q"] + extra_args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode == 0:
        last_line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "ok"
        return True, f"full suite passes: {last_line}"
    last_line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else result.stderr.strip()
    return False, f"full suite failed: {last_line}"


# Prevent pytest from collecting gateway functions as tests
tests_written.__test__ = False  # type: ignore[attr-defined]

# Registry mapping string names to callables
GATEWAY_CONDITIONS: dict[str, Callable[[dict], tuple[bool, str]]] = {
    "branch_exists": branch_exists,
    "tests_written": tests_written,
    "all_tests_pass": all_tests_pass,
    "all_branches_merged": all_branches_merged,
    "full_suite_passes": full_suite_passes,
}
