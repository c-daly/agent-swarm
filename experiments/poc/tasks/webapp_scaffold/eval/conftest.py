"""
Conftest for webapp_scaffold eval.

This bridges the frontend vitest tests into the pytest-based experiment harness.
The actual tests live in webapp_scaffold.test.tsx and are run by vitest.
This conftest emits [METRIC] test_pass_rate by running the shell wrapper.
"""
import subprocess
import os
import re

import pytest


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Emit [METRIC] test_pass_rate for the experiment harness.

    Runs run_eval.sh (which invokes vitest) and extracts the metric.
    Falls back to pytest's own stats if the shell script is unavailable.
    """
    eval_dir = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(eval_dir, "run_eval.sh")

    if os.path.exists(script):
        try:
            result = subprocess.run(
                ["bash", script],
                cwd=os.path.dirname(eval_dir),  # task root
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = result.stdout + result.stderr
            # Find [METRIC] line in the output
            match = re.search(r"\[METRIC\]\s+test_pass_rate=([0-9.]+)", output)
            if match:
                rate = float(match.group(1))
                print(f"\n[METRIC] test_pass_rate={rate:.4f}")
                return
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            print(f"\nWarning: run_eval.sh failed ({exc}), falling back to pytest stats")

    # Fallback: use pytest's own pass/fail counts
    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))
    total = passed + failed
    rate = passed / total if total > 0 else 0.0
    print(f"\n[METRIC] test_pass_rate={rate:.4f}")
