"""Tests for gateway condition validators."""

from unittest.mock import MagicMock, patch


from gateway_conditions import (
    GATEWAY_CONDITIONS,
    all_branches_merged,
    all_tests_pass,
    branch_exists,
    full_suite_passes,
    tests_written,
)


# ============================================================================
# branch_exists
# ============================================================================


class TestBranchExists:
    def test_branch_exists_true(self):
        mock_result = MagicMock(stdout="  task/stack\n", returncode=0)
        with patch("gateway_conditions.subprocess.run", return_value=mock_result) as mock_run:
            passed, msg = branch_exists({"branch": "task/stack"})
            assert passed is True
            assert "exists" in msg
            mock_run.assert_called_once_with(
                ["git", "branch", "--list", "task/stack"],
                capture_output=True,
                text=True,
                cwd=None,
            )

    def test_branch_exists_false(self):
        mock_result = MagicMock(stdout="", returncode=0)
        with patch("gateway_conditions.subprocess.run", return_value=mock_result):
            passed, msg = branch_exists({"branch": "task/nonexistent"})
            assert passed is False
            assert "does not exist" in msg

    def test_branch_exists_strips_whitespace(self):
        mock_result = MagicMock(stdout="  task/stack  \n", returncode=0)
        with patch("gateway_conditions.subprocess.run", return_value=mock_result):
            passed, msg = branch_exists({"branch": "task/stack"})
            assert passed is True

    def test_branch_exists_no_branch_name(self):
        passed, msg = branch_exists({})
        assert passed is False
        assert "no branch name" in msg

    def test_branch_exists_passes_cwd(self):
        mock_result = MagicMock(stdout="  task/foo\n", returncode=0)
        with patch("gateway_conditions.subprocess.run", return_value=mock_result) as mock_run:
            branch_exists({"branch": "task/foo", "cwd": "/some/repo"})
            mock_run.assert_called_once_with(
                ["git", "branch", "--list", "task/foo"],
                capture_output=True,
                text=True,
                cwd="/some/repo",
            )


# ============================================================================
# tests_written
# ============================================================================


class TestTestsWritten:
    def test_tests_written_sufficient(self, tmp_path):
        test_file = tmp_path / "test_stack.py"
        test_file.write_text(
            "def test_push(): pass\n"
            "def test_pop(): pass\n"
            "def test_peek(): pass\n"
        )
        passed, msg = tests_written({"test_path": str(test_file), "min_tests": 3})
        assert passed is True
        assert "3 test functions" in msg

    def test_tests_written_insufficient(self, tmp_path):
        test_file = tmp_path / "test_stack.py"
        test_file.write_text("def test_push(): pass\n")
        passed, msg = tests_written({"test_path": str(test_file), "min_tests": 5})
        assert passed is False
        assert "need at least 5" in msg

    def test_tests_written_file_missing(self):
        passed, msg = tests_written({"test_path": "/nonexistent/test_foo.py"})
        assert passed is False
        assert "not found" in msg

    def test_tests_written_no_min_tests_defaults(self, tmp_path):
        test_file = tmp_path / "test_x.py"
        test_file.write_text("def test_one(): pass\n")
        passed, msg = tests_written({"test_path": str(test_file)})
        assert passed is True
        assert "1 test functions" in msg

    def test_tests_written_no_test_path(self):
        passed, msg = tests_written({})
        assert passed is False
        assert "no test path" in msg


# ============================================================================
# all_tests_pass
# ============================================================================


class TestAllTestsPass:
    def test_all_tests_pass_success(self):
        mock_result = MagicMock(stdout="3 passed\n", returncode=0)
        with patch("gateway_conditions.subprocess.run", return_value=mock_result):
            passed, msg = all_tests_pass({"test_path": "tests/test_stack.py"})
            assert passed is True
            assert "pass" in msg

    def test_all_tests_pass_failure(self):
        mock_result = MagicMock(stdout="1 failed, 2 passed\n", returncode=1)
        with patch("gateway_conditions.subprocess.run", return_value=mock_result):
            passed, msg = all_tests_pass({"test_path": "tests/test_stack.py"})
            assert passed is False
            assert "failed" in msg

    def test_all_tests_pass_no_test_path(self):
        passed, msg = all_tests_pass({})
        assert passed is False
        assert "no test path" in msg

    def test_all_tests_pass_uses_pytest_args(self):
        mock_result = MagicMock(stdout="ok\n", returncode=0)
        with patch("gateway_conditions.subprocess.run", return_value=mock_result) as mock_run:
            all_tests_pass({"test_path": "tests/", "cwd": "/repo"})
            mock_run.assert_called_once_with(
                ["pytest", "tests/", "--tb=short", "-q"],
                capture_output=True,
                text=True,
                cwd="/repo",
            )


# ============================================================================
# all_branches_merged
# ============================================================================


class TestAllBranchesMerged:
    def test_all_branches_merged_all_gone(self):
        mock_result = MagicMock(stdout="", returncode=0)
        with patch("gateway_conditions.subprocess.run", return_value=mock_result):
            passed, msg = all_branches_merged({})
            assert passed is True
            assert "merged" in msg

    def test_all_branches_merged_remaining(self):
        mock_result = MagicMock(stdout="  task/stack\n  task/queue\n", returncode=0)
        with patch("gateway_conditions.subprocess.run", return_value=mock_result):
            passed, msg = all_branches_merged({})
            assert passed is False
            assert "task/stack" in msg
            assert "task/queue" in msg

    def test_all_branches_merged_custom_prefix(self):
        mock_result = MagicMock(stdout="", returncode=0)
        with patch("gateway_conditions.subprocess.run", return_value=mock_result) as mock_run:
            all_branches_merged({"prefix": "feature/"})
            mock_run.assert_called_once_with(
                ["git", "branch", "--list", "feature/*"],
                capture_output=True,
                text=True,
                cwd=None,
            )


# ============================================================================
# full_suite_passes
# ============================================================================


class TestFullSuitePasses:
    def test_full_suite_passes_success(self):
        mock_result = MagicMock(stdout="42 passed\n", returncode=0)
        with patch("gateway_conditions.subprocess.run", return_value=mock_result):
            passed, msg = full_suite_passes({})
            assert passed is True
            assert "passes" in msg

    def test_full_suite_passes_failure(self):
        mock_result = MagicMock(stdout="5 failed, 37 passed\n", returncode=1)
        with patch("gateway_conditions.subprocess.run", return_value=mock_result):
            passed, msg = full_suite_passes({})
            assert passed is False
            assert "failed" in msg

    def test_full_suite_passes_extra_args(self):
        mock_result = MagicMock(stdout="ok\n", returncode=0)
        with patch("gateway_conditions.subprocess.run", return_value=mock_result) as mock_run:
            full_suite_passes({"args": ["--cov", "src/"]})
            mock_run.assert_called_once_with(
                ["pytest", "--tb=short", "-q", "--cov", "src/"],
                capture_output=True,
                text=True,
                cwd=None,
            )


# ============================================================================
# Registry
# ============================================================================


class TestRegistry:
    def test_registry_contains_all_conditions(self):
        expected = {"branch_exists", "tests_written", "all_tests_pass", "all_branches_merged", "full_suite_passes"}
        assert set(GATEWAY_CONDITIONS.keys()) == expected

    def test_all_conditions_are_callable(self):
        for name, fn in GATEWAY_CONDITIONS.items():
            assert callable(fn), f"{name} is not callable"
