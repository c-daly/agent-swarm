"""
Pytest bridge for webapp_scaffold vitest tests.

The real frontend tests live in webapp_scaffold.test.tsx and run under
vitest. This file shells out to vitest so the experiment harness (which
calls `pytest eval/`) still exercises the frontend eval.
"""
import os
import re
import subprocess

import pytest


TASK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEBAPP_DIR = os.path.join(TASK_DIR, "webapp")


def _vitest_available() -> bool:
    """Check whether the webapp directory and vitest are set up."""
    if not os.path.isdir(WEBAPP_DIR):
        return False
    pkg_json = os.path.join(WEBAPP_DIR, "package.json")
    return os.path.isfile(pkg_json)


@pytest.mark.skipif(
    not _vitest_available(),
    reason="webapp/ not built yet -- nothing to test",
)
class TestVitestBridge:
    """Run vitest and assert all frontend tests pass."""

    def test_vitest_passes(self):
        """Shell out to vitest and verify all tests pass."""
        result = subprocess.run(
            [
                "npx", "vitest", "run",
                "--config", "eval/vitest.config.ts",
                "--reporter=verbose",
            ],
            cwd=TASK_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )

        output = result.stdout + "\n" + result.stderr

        # Parse summary line to get pass/fail counts
        summary = re.search(
            r"Tests\s+(?:(\d+)\s+passed)?(?:\s*\|\s*(\d+)\s+failed)?",
            output,
        )

        if summary:
            passed = int(summary.group(1) or 0)
            failed = int(summary.group(2) or 0)
            assert failed == 0, (
                f"vitest: {failed} test(s) failed out of {passed + failed}\n\n"
                f"{output}"
            )
            assert passed > 0, f"vitest ran but reported 0 passed tests\n\n{output}"
        else:
            # If we can't parse the summary, check the exit code
            assert result.returncode == 0, (
                f"vitest exited with code {result.returncode}\n\n{output}"
            )
