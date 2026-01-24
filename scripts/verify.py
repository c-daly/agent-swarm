#!/usr/bin/env python3
"""
Verify script - runs code quality checks.

Usage:
    verify.py [--fix] [lint|format|types|tests]

Runs ruff, black, mypy, and pytest with unified output.
Sets verify_passed flag in session state when all pass.
"""

import subprocess
import sys
import json
import shutil
from pathlib import Path
from typing import NamedTuple

STATE_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/session.json"


class CheckResult(NamedTuple):
    name: str
    passed: bool
    output: str
    skipped: bool = False


def load_state() -> dict:
    """Load session state."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass  # Silent exception
    return {}


def save_state(state: dict) -> None:
    """Save session state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def set_verify_passed(passed: bool) -> None:
    """Set the verify_passed flag in session state."""
    state = load_state()
    state["verify_passed"] = passed
    save_state(state)


def find_tool(name: str) -> str | None:
    """Find tool in PATH or common locations."""
    # Check PATH first
    if shutil.which(name):
        return name

    # Check common virtual env locations
    venv_paths = [
        Path.cwd() / ".venv" / "bin" / name,
        Path.cwd() / "venv" / "bin" / name,
        Path.home() / ".local" / "bin" / name,
    ]

    for p in venv_paths:
        if p.exists():
            return str(p)

    return None


def run_check(name: str, cmd: list[str]) -> CheckResult:
    """Run a single check and return result."""
    tool = find_tool(cmd[0])

    if not tool:
        return CheckResult(name, False, f"{cmd[0]} not found", skipped=True)

    cmd[0] = tool

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300  # 5 minute timeout
        )

        passed = result.returncode == 0
        output = result.stdout + result.stderr

        # Truncate long output
        if len(output) > 1000:
            output = output[:500] + "\n...[truncated]...\n" + output[-500:]

        return CheckResult(name, passed, output.strip())

    except subprocess.TimeoutExpired:
        return CheckResult(name, False, "Timeout after 5 minutes")
    except Exception as e:
        return CheckResult(name, False, str(e))


def run_lint(fix: bool) -> CheckResult:
    """Run ruff linter."""
    cmd = ["ruff", "check", "."]
    if fix:
        cmd.append("--fix")
    return run_check("lint", cmd)


def run_format(fix: bool) -> CheckResult:
    """Run black formatter."""
    cmd = ["black", "."]
    if not fix:
        cmd.append("--check")
    return run_check("format", cmd)


def run_types() -> CheckResult:
    """Run mypy type checker."""
    return run_check("types", ["mypy", "."])


def run_tests() -> CheckResult:
    """Run pytest."""
    return run_check("tests", ["pytest", "-q"])


def main():
    args = sys.argv[1:]

    fix_mode = "--fix" in args
    if fix_mode:
        args.remove("--fix")

    # Determine which checks to run
    check_filter = args[0] if args else None

    checks = {
        "lint": lambda: run_lint(fix_mode),
        "format": lambda: run_format(fix_mode),
        "types": run_types,
        "tests": run_tests,
    }

    if check_filter and check_filter in checks:
        checks = {check_filter: checks[check_filter]}
    elif check_filter and check_filter not in checks:
        print(f"Unknown check: {check_filter}")
        print(f"Available: {', '.join(checks.keys())}")
        sys.exit(2)

    # Run checks
    results = {}
    all_passed = True

    for name, check_fn in checks.items():
        result = check_fn()
        results[name] = result

        if not result.passed and not result.skipped:
            all_passed = False
            # Print detailed output for failures
            if result.output:
                print(f"\n=== {name.upper()} ===")
                print(result.output)

    # Print summary line
    summary_parts = []
    for name in ["tests", "types", "lint", "format"]:
        if name in results:
            r = results[name]
            if r.skipped:
                summary_parts.append(f"{name}: -")
            elif r.passed:
                summary_parts.append(f"{name}: \u2713")
            else:
                summary_parts.append(f"{name}: \u2717")

    print(f"\n[VERIFY] {' | '.join(summary_parts)}")

    # Update state
    set_verify_passed(all_passed)

    if all_passed:
        print("All checks passed!")
        sys.exit(0)
    else:
        failed = [r.name for r in results.values() if not r.passed and not r.skipped]
        print(f"Failed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
