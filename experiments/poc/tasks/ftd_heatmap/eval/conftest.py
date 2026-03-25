import pytest


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Emit [METRIC] test_pass_rate for the experiment harness."""
    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))
    total = passed + failed
    rate = passed / total if total > 0 else 0.0
    print(f"\n[METRIC] test_pass_rate={rate:.4f}")
