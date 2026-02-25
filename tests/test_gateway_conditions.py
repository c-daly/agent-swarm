"""Tests for gateway condition validators."""

from unittest.mock import MagicMock, patch

from lib.gateway_conditions import (
    GATEWAY_CONDITIONS,
    all_branches_merged,
    all_tests_pass,
    branch_exists,
    commit_exists,
    full_suite_passes,
)
from lib.gateway_conditions import (
    tests_written as check_tests_written,
)


def _mock_run(returncode=0, stdout="", stderr=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


class TestBranchExists:
    @patch("lib.gateway_conditions.subprocess.run")
    def test_branch_exists_true(self, mock_run):
        mock_run.return_value = _mock_run(returncode=0)
        ok, msg = branch_exists(branch="task/stack", cwd="/repo")
        assert ok is True
        assert "exists" in msg.lower()

    @patch("lib.gateway_conditions.subprocess.run")
    def test_branch_exists_false(self, mock_run):
        mock_run.return_value = _mock_run(returncode=1)
        ok, msg = branch_exists(branch="task/stack", cwd="/repo")
        assert ok is False

    @patch("lib.gateway_conditions.subprocess.run")
    def test_branch_exists_exception(self, mock_run):
        mock_run.side_effect = OSError("git not found")
        ok, msg = branch_exists(branch="task/stack", cwd="/repo")
        assert ok is False
        assert "error" in msg.lower()


class TestTestsWritten:
    @patch("lib.gateway_conditions.subprocess.run")
    def test_enough_tests(self, mock_run):
        # Simulate 12 test functions found
        mock_run.return_value = _mock_run(stdout="test_a\ntest_b\n" * 6)
        ok, msg = check_tests_written(test_dir="tests/", min_tests=10, cwd="/repo")
        assert ok is True

    @patch("lib.gateway_conditions.subprocess.run")
    def test_not_enough_tests(self, mock_run):
        mock_run.return_value = _mock_run(stdout="test_a\n")
        ok, msg = check_tests_written(test_dir="tests/", min_tests=10, cwd="/repo")
        assert ok is False
        assert "10" in msg

    @patch("lib.gateway_conditions.subprocess.run")
    def test_no_output(self, mock_run):
        mock_run.return_value = _mock_run(stdout="")
        ok, msg = check_tests_written(test_dir="tests/", min_tests=5, cwd="/repo")
        assert ok is False

    @patch("lib.gateway_conditions.subprocess.run")
    def test_exception(self, mock_run):
        mock_run.side_effect = OSError("grep not found")
        ok, msg = check_tests_written(test_dir="tests/", min_tests=5, cwd="/repo")
        assert ok is False


class TestAllTestsPass:
    @patch("lib.gateway_conditions.subprocess.run")
    def test_tests_pass(self, mock_run):
        mock_run.return_value = _mock_run(returncode=0, stdout="10 passed")
        ok, msg = all_tests_pass(test_dir="tests/", cwd="/repo")
        assert ok is True

    @patch("lib.gateway_conditions.subprocess.run")
    def test_tests_fail(self, mock_run):
        mock_run.return_value = _mock_run(returncode=1, stdout="3 failed")
        ok, msg = all_tests_pass(test_dir="tests/", cwd="/repo")
        assert ok is False

    @patch("lib.gateway_conditions.subprocess.run")
    def test_exception(self, mock_run):
        mock_run.side_effect = OSError("pytest not found")
        ok, msg = all_tests_pass(test_dir="tests/", cwd="/repo")
        assert ok is False


class TestAllBranchesMerged:
    @patch("lib.gateway_conditions.subprocess.run")
    def test_all_merged(self, mock_run):
        # git branch --merged lists all branches including the ones we want
        mock_run.return_value = _mock_run(stdout="  main\n  task/stack\n  task/queue\n")
        ok, msg = all_branches_merged(
            branches=["task/stack", "task/queue"], cwd="/repo"
        )
        assert ok is True

    @patch("lib.gateway_conditions.subprocess.run")
    def test_not_all_merged(self, mock_run):
        mock_run.return_value = _mock_run(stdout="  main\n  task/stack\n")
        ok, msg = all_branches_merged(
            branches=["task/stack", "task/queue"], cwd="/repo"
        )
        assert ok is False
        assert "task/queue" in msg

    @patch("lib.gateway_conditions.subprocess.run")
    def test_exception(self, mock_run):
        mock_run.side_effect = OSError("git error")
        ok, msg = all_branches_merged(branches=["task/stack"], cwd="/repo")
        assert ok is False


class TestFullSuitePasses:
    @patch("lib.gateway_conditions.subprocess.run")
    def test_suite_passes(self, mock_run):
        mock_run.return_value = _mock_run(returncode=0, stdout="50 passed")
        ok, msg = full_suite_passes(cwd="/repo")
        assert ok is True

    @patch("lib.gateway_conditions.subprocess.run")
    def test_suite_fails(self, mock_run):
        mock_run.return_value = _mock_run(returncode=1, stdout="2 failed")
        ok, msg = full_suite_passes(cwd="/repo")
        assert ok is False

    @patch("lib.gateway_conditions.subprocess.run")
    def test_exception(self, mock_run):
        mock_run.side_effect = OSError("pytest not found")
        ok, msg = full_suite_passes(cwd="/repo")
        assert ok is False


class TestCommitExists:
    @patch("lib.gateway_conditions.subprocess.run")
    def test_commit_exists(self, mock_run):
        mock_run.return_value = _mock_run(returncode=0, stdout="abc1234")
        ok, msg = commit_exists(branch="task/stack", cwd="/repo")
        assert ok is True

    @patch("lib.gateway_conditions.subprocess.run")
    def test_no_commits(self, mock_run):
        mock_run.return_value = _mock_run(returncode=1, stdout="")
        ok, msg = commit_exists(branch="task/stack", cwd="/repo")
        assert ok is False

    @patch("lib.gateway_conditions.subprocess.run")
    def test_exception(self, mock_run):
        mock_run.side_effect = OSError("git error")
        ok, msg = commit_exists(branch="task/stack", cwd="/repo")
        assert ok is False


class TestRegistry:
    def test_registry_has_all_conditions(self):
        expected = {
            "branch_exists",
            "tests_written",
            "all_tests_pass",
            "all_branches_merged",
            "full_suite_passes",
            "commit_exists",
        }
        assert set(GATEWAY_CONDITIONS.keys()) == expected

    def test_registry_values_are_callable(self):
        for name, fn in GATEWAY_CONDITIONS.items():
            assert callable(fn), f"{name} is not callable"
