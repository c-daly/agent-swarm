#!/usr/bin/env python3
"""
Verification gates for agent-swarm plugin.

Enforces:
1. Verification state tracking - block [VERIFY] without actual runs
2. Tool version validation - warn on pyproject.toml mismatch
3. Agent spawning enforcement - require Task tool for >1 pending
4. PR completion composite gate
"""

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# State file for tracking verification runs
STATE_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/verification.json"


def load_verification_state() -> Dict:
    """Load verification state from file."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {
        "lint_run": False,
        "tests_run": False,
        "format_run": False,
        "last_reset": datetime.now().isoformat(),
    }


def save_verification_state(state: Dict) -> None:
    """Save verification state to file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def reset_verification_state() -> None:
    """Reset verification state for new task."""
    save_verification_state({
        "lint_run": False,
        "tests_run": False,
        "format_run": False,
        "last_reset": datetime.now().isoformat(),
    })


def on_bash_complete(command: str, exit_code: int) -> None:
    """Update verification state after bash commands complete."""
    state = load_verification_state()

    # Track lint runs
    if re.search(r'ruff check|black --check|pylint|flake8', command):
        state["lint_run"] = True
        state["lint_timestamp"] = datetime.now().isoformat()

    # Track test runs
    if re.search(r'pytest|python.*-m\s+pytest', command):
        state["tests_run"] = True
        state["tests_timestamp"] = datetime.now().isoformat()
        state["tests_passed"] = (exit_code == 0)

    # Track format runs (not just --check)
    if re.search(r'ruff format|black\s', command) and '--check' not in command:
        state["format_run"] = True
        state["format_timestamp"] = datetime.now().isoformat()

    save_verification_state(state)


def check_verify_signal(message: str) -> Optional[str]:
    """
    Block [VERIFY] or completion claims without actual verification runs.

    Returns error message if blocked, None if allowed.
    """
    # Patterns that indicate claiming verification complete
    verify_patterns = [
        r'\[VERIFY\].*✓',
        r'Complete.*all.*pass',
        r'all checks pass',
        r'ready for merge',
        r'PR.*ready',
    ]

    is_claiming_complete = any(
        re.search(pattern, message, re.IGNORECASE)
        for pattern in verify_patterns
    )

    if not is_claiming_complete:
        return None

    state = load_verification_state()
    missing = []

    if not state.get("lint_run"):
        missing.append("lint (run: ruff check or black --check)")
    if not state.get("tests_run"):
        missing.append("tests (run: pytest)")

    if missing:
        return (
            f"[BLOCKED] Cannot claim verification without running: {missing}\n\n"
            "Run the missing checks before declaring complete."
        )

    # Also check if tests actually passed
    if state.get("tests_run") and not state.get("tests_passed", True):
        return "[BLOCKED] Tests failed. Fix before claiming verification complete."

    return None


def check_tool_versions(cwd: str) -> Optional[str]:
    """
    Warn if local tool versions don't match pyproject.toml.

    Returns warning message if mismatch, None if OK.
    """
    pyproject_path = Path(cwd) / "pyproject.toml"
    if not pyproject_path.exists():
        return None

    try:
        import tomli
        with open(pyproject_path, "rb") as f:
            pyproject = tomli.load(f)
    except ImportError:
        # tomli not available, skip check
        return None
    except Exception:
        return None

    warnings = []

    # Get dev dependencies
    dev_deps = (
        pyproject.get("tool", {})
        .get("poetry", {})
        .get("group", {})
        .get("dev", {})
        .get("dependencies", {})
    )

    # Check black version
    if "black" in dev_deps:
        expected = dev_deps["black"]
        try:
            result = subprocess.run(
                ["black", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                actual = result.stdout.split()[1] if result.stdout else "unknown"
                if not _version_matches(actual, expected):
                    warnings.append(f"black: local={actual}, pyproject={expected}")
        except Exception:
            pass

    if warnings:
        return f"[WARNING] Tool version mismatch: {warnings}"

    return None


def _version_matches(actual: str, expected: str) -> bool:
    """Check if actual version matches expected constraint."""
    # Handle ^X.Y.Z format
    if expected.startswith("^"):
        major_expected = expected[1:].split(".")[0]
        major_actual = actual.split(".")[0]
        return major_expected == major_actual

    # Handle >=X.Y.Z,<A.B.C format
    if ">=" in expected and "<" in expected:
        # Just check major version for simplicity
        parts = re.findall(r'\d+', expected)
        if parts:
            return actual.startswith(parts[0])

    return True  # Default to OK if we can't parse


def check_agent_spawning(todo_list: List[Dict], max_inline: int = 1) -> Optional[str]:
    """
    Enforce agent spawning when multiple tasks exist.

    Returns error message if blocked, None if allowed.
    """
    pending = [t for t in todo_list if t.get("status") == "pending"]
    in_progress = [t for t in todo_list if t.get("status") == "in_progress"]

    if len(pending) > max_inline and len(in_progress) <= 1:
        return (
            f"[BLOCKED] {len(pending)} pending tasks. "
            "Spawn agents for parallel work using Task tool."
        )

    return None


def update_greptile_state(
    pr_number: int,
    repo: str,
    unaddressed_p0_comments: List[Dict],
    api_available: bool = True
) -> None:
    """
    Update cached Greptile state after MCP tool call.

    Call this after using mcp__plugin_greptile_greptile__list_merge_request_comments
    to cache the results for the hook gate to use.

    Args:
        pr_number: The PR number checked
        repo: Repository in format "owner/repo"
        unaddressed_p0_comments: List of dicts with keys: id, body, path
        api_available: Whether the API call succeeded
    """
    state = load_verification_state()
    state["greptile_state"] = {
        "pr_number": pr_number,
        "repo": repo,
        "last_checked": datetime.now().isoformat(),
        "unaddressed_p0_count": len(unaddressed_p0_comments),
        "unaddressed_p0_comments": unaddressed_p0_comments[:5],  # Limit stored
        "api_available": api_available,
    }
    save_verification_state(state)


def clear_greptile_state() -> None:
    """Clear cached Greptile state (e.g., after addressing comments)."""
    state = load_verification_state()
    state.pop("greptile_state", None)
    save_verification_state(state)


def check_greptile_comments(pr_number: int, repo: str = "c-daly/apollo") -> Optional[str]:
    """
    Check if there are unaddressed P0 Greptile comments on PR.

    Returns error message if unaddressed P0 comments exist, None if OK.

    This function reads from cached state (populated by update_greptile_state()).
    The MCP tool mcp__plugin_greptile_greptile__list_merge_request_comments
    cannot be called from hooks - the agent must call it and cache results.

    State structure expected:
        greptile_state: {
            "pr_number": int,
            "repo": str,
            "last_checked": ISO timestamp,
            "unaddressed_p0_count": int,
            "unaddressed_p0_comments": [{"id": str, "body": str, "path": str}],
            "api_available": bool
        }
    """
    state = load_verification_state()
    greptile = state.get("greptile_state", {})

    # If no cached state, skip gracefully (API may not be available)
    if not greptile:
        return None

    # Check if cached state matches current PR
    cached_pr = greptile.get("pr_number")
    cached_repo = greptile.get("repo")
    if cached_pr != pr_number or cached_repo != repo:
        # Stale cache - skip check but warn
        return None

    # Check if API was unavailable during last check
    if not greptile.get("api_available", True):
        return None

    # Check for unaddressed P0 comments
    p0_count = greptile.get("unaddressed_p0_count", 0)
    if p0_count > 0:
        comments = greptile.get("unaddressed_p0_comments", [])
        preview = ""
        if comments:
            first = comments[0]
            path = first.get("path", "unknown")
            body = first.get("body", "")[:100]
            preview = f" (e.g., {path}: {body}...)"
        return f"[GREPTILE] {p0_count} unaddressed P0 comment(s) exist{preview}. Address before commit."

    return None


def check_pr_ready(pr_number: int, repo: str = "c-daly/apollo") -> Tuple[bool, List[str]]:
    """
    Composite gate for PR readiness.

    Returns (is_ready, list_of_issues).
    """
    issues = []
    state = load_verification_state()

    # Check verification state
    if not state.get("lint_run"):
        issues.append("Lint check not run")
    if not state.get("tests_run"):
        issues.append("Tests not run")
    if state.get("tests_run") and not state.get("tests_passed", True):
        issues.append("Tests failed")

    # Check Greptile (if integration available)
    greptile_msg = check_greptile_comments(pr_number, repo)
    if greptile_msg:
        issues.append(greptile_msg)

    return (len(issues) == 0, issues)


# Export for use in combined-enforcement.py
__all__ = [
    "load_verification_state",
    "save_verification_state",
    "reset_verification_state",
    "on_bash_complete",
    "check_verify_signal",
    "check_tool_versions",
    "check_agent_spawning",
    "check_greptile_comments",
    "update_greptile_state",
    "clear_greptile_state",
    "check_pr_ready",
]
