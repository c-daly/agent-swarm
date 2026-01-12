#!/usr/bin/env python3
"""Tests for hooks/post-tool-use.py hook.

Tests the post-tool-use hook's behavior, especially the git_approval.flag
cleanup logic that triggers after successful git commit/push commands.
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import io
import importlib.util


# Add hooks to path
hooks_dir = Path(__file__).parent.parent / "hooks"
sys.path.insert(0, str(hooks_dir))

# Import the post-tool-use module (handling hyphen in filename)
spec = importlib.util.spec_from_file_location(
    "post_tool_use",
    hooks_dir / "post-tool-use.py"
)
post_tool_use = importlib.util.module_from_spec(spec)
sys.modules["post_tool_use"] = post_tool_use
spec.loader.exec_module(post_tool_use)


class TestPostToolUseMain:
    """Tests for the main() function in post-tool-use.py."""

    def test_processes_bash_command_correctly(self):
        """main() should extract command and exit_code from Bash tool."""
        input_data = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hello"},
            "tool_result": {"content": "hello\nexit code: 0"}
        }

        with patch('sys.stdin', io.StringIO(json.dumps(input_data))):
            with patch.object(post_tool_use, 'on_bash_complete') as mock_callback:
                post_tool_use.main()
                mock_callback.assert_called_once_with("echo hello", 0)

    def test_ignores_non_bash_tools(self):
        """main() should ignore non-Bash tools."""
        input_data = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "test.py"},
            "tool_result": {"content": "success"}
        }

        with patch('sys.stdin', io.StringIO(json.dumps(input_data))):
            with patch('verification_gates.on_bash_complete') as mock_callback:
                from post_tool_use import main

                main()

                # Should not call on_bash_complete
                mock_callback.assert_not_called()

    def test_handles_invalid_json_gracefully(self):
        """main() should handle invalid JSON without crashing."""
        with patch('sys.stdin', io.StringIO("not valid json")):
            from post_tool_use import main

            # Should not raise exception
            try:
                main()
            except Exception as e:
                assert False, f"main() should handle invalid JSON gracefully, got: {e}"

    def test_extracts_exit_code_from_result(self):
        """main() should extract exit code from tool result content."""
        test_cases = [
            ("exit code: 0", 0),
            ("exit code: 1", 1),
            ("Exit Code: 127", 127),
            ("command failed\nerror", 1),  # Heuristic failure detection
            ("success", 0),  # Default to 0
        ]

        for content, expected_code in test_cases:
            input_data = {
                "tool_name": "Bash",
                "tool_input": {"command": "test"},
                "tool_result": {"content": content}
            }

            with patch('sys.stdin', io.StringIO(json.dumps(input_data))):
                with patch.object(post_tool_use, 'on_bash_complete') as mock_callback:
                    post_tool_use.main()

                    # Verify exit code extraction
                    call_args = mock_callback.call_args[0]
                    assert call_args[1] == expected_code, \
                        f"Expected exit_code {expected_code} for content '{content}', got {call_args[1]}"


class TestGitApprovalFlagCleanup:
    """Tests for git_approval.flag cleanup logic."""

    def test_git_commit_success_deletes_flag(self):
        """Successful git commit should delete git_approval.flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            flag_path = Path(tmpdir) / "git_approval.flag"
            flag_path.touch()  # Create the flag file

            assert flag_path.exists(), "Flag should exist before test"

            input_data = {
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'test commit'"},
                "tool_result": {"content": "exit code: 0"}
            }

            with patch('sys.stdin', io.StringIO(json.dumps(input_data))):
                with patch('pathlib.Path.home', return_value=Path(tmpdir).parent):
                    # Mock the specific flag path
                    with patch('post_tool_use.Path') as mock_path_class:
                        mock_flag = MagicMock()
                        mock_flag.exists.return_value = True
                        mock_flag.unlink = lambda: flag_path.unlink()

                        mock_path_home = MagicMock()
                        mock_path_home.__truediv__ = lambda self, other: mock_flag if "git_approval.flag" in str(other) else MagicMock()

                        mock_path_class.home.return_value = mock_path_home

                        from post_tool_use import main
                        main()

            assert not flag_path.exists(), "Flag should be deleted after successful git commit"

    def test_git_push_success_deletes_flag(self):
        """Successful git push should delete git_approval.flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            flag_path = Path(tmpdir) / "git_approval.flag"
            flag_path.touch()

            input_data = {
                "tool_name": "Bash",
                "tool_input": {"command": "git push origin main"},
                "tool_result": {"content": "exit code: 0"}
            }

            with patch('sys.stdin', io.StringIO(json.dumps(input_data))):
                with patch('post_tool_use.Path') as mock_path_class:
                    mock_flag = MagicMock()
                    mock_flag.exists.return_value = True
                    mock_flag.unlink = lambda: flag_path.unlink()

                    mock_path_home = MagicMock()
                    mock_path_home.__truediv__ = lambda self, other: mock_flag if "git_approval.flag" in str(other) else MagicMock()

                    mock_path_class.home.return_value = mock_path_home

                    from post_tool_use import main
                    main()

            assert not flag_path.exists(), "Flag should be deleted after successful git push"

    def test_failed_git_commit_preserves_flag(self):
        """Failed git commit should NOT delete git_approval.flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            flag_path = Path(tmpdir) / "git_approval.flag"
            flag_path.touch()

            input_data = {
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'test'"},
                "tool_result": {"content": "error: failed\nexit code: 1"}
            }

            with patch('sys.stdin', io.StringIO(json.dumps(input_data))):
                with patch('post_tool_use.Path') as mock_path_class:
                    mock_flag = MagicMock()
                    mock_flag.exists.return_value = True

                    # Should not call unlink
                    mock_flag.unlink = MagicMock()

                    mock_path_home = MagicMock()
                    mock_path_home.__truediv__ = lambda self, other: mock_flag if "git_approval.flag" in str(other) else MagicMock()

                    mock_path_class.home.return_value = mock_path_home

                    from post_tool_use import main
                    main()

                    # unlink should not have been called
                    mock_flag.unlink.assert_not_called()

    def test_non_git_command_preserves_flag(self):
        """Non-git commands should NOT delete git_approval.flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            flag_path = Path(tmpdir) / "git_approval.flag"
            flag_path.touch()

            input_data = {
                "tool_name": "Bash",
                "tool_input": {"command": "echo 'not a git command'"},
                "tool_result": {"content": "exit code: 0"}
            }

            with patch('sys.stdin', io.StringIO(json.dumps(input_data))):
                with patch('post_tool_use.Path') as mock_path_class:
                    mock_flag = MagicMock()
                    mock_flag.exists.return_value = True
                    mock_flag.unlink = MagicMock()

                    mock_path_home = MagicMock()
                    mock_path_home.__truediv__ = lambda self, other: mock_flag if "git_approval.flag" in str(other) else MagicMock()

                    mock_path_class.home.return_value = mock_path_home

                    from post_tool_use import main
                    main()

                    # unlink should not have been called
                    mock_flag.unlink.assert_not_called()

    def test_flag_not_exists_no_error(self):
        """If flag doesn't exist, cleanup should not raise error."""
        input_data = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'test'"},
            "tool_result": {"content": "exit code: 0"}
        }

        with patch('sys.stdin', io.StringIO(json.dumps(input_data))):
            with patch('post_tool_use.Path') as mock_path_class:
                mock_flag = MagicMock()
                mock_flag.exists.return_value = False

                mock_path_home = MagicMock()
                mock_path_home.__truediv__ = lambda self, other: mock_flag if "git_approval.flag" in str(other) else MagicMock()

                mock_path_class.home.return_value = mock_path_home

                from post_tool_use import main

                # Should not raise exception
                try:
                    main()
                except Exception as e:
                    assert False, f"Should handle missing flag gracefully, got: {e}"

    def test_git_commit_with_and_operator(self):
        """git commit in a compound command should trigger cleanup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            flag_path = Path(tmpdir) / "git_approval.flag"
            flag_path.touch()

            input_data = {
                "tool_name": "Bash",
                "tool_input": {"command": "git add . && git commit -m 'compound'"},
                "tool_result": {"content": "exit code: 0"}
            }

            with patch('sys.stdin', io.StringIO(json.dumps(input_data))):
                with patch('post_tool_use.Path') as mock_path_class:
                    mock_flag = MagicMock()
                    mock_flag.exists.return_value = True
                    mock_flag.unlink = lambda: flag_path.unlink()

                    mock_path_home = MagicMock()
                    mock_path_home.__truediv__ = lambda self, other: mock_flag if "git_approval.flag" in str(other) else MagicMock()

                    mock_path_class.home.return_value = mock_path_home

                    from post_tool_use import main
                    main()

            assert not flag_path.exists(), "Flag should be deleted for compound git commit command"


class TestVerificationGatesIntegration:
    """Tests for verification_gates integration."""

    def test_verification_gates_unavailable_no_error(self):
        """If verification_gates is unavailable, hook should not crash."""
        input_data = {
            "tool_name": "Bash",
            "tool_input": {"command": "pytest"},
            "tool_result": {"content": "exit code: 0"}
        }

        with patch('sys.stdin', io.StringIO(json.dumps(input_data))):
            with patch.dict('sys.modules', {'verification_gates': None}):
                # Force reimport without verification_gates
                import importlib
                import post_tool_use

                # Mock VERIFICATION_GATES_AVAILABLE to False
                with patch.object(post_tool_use, 'VERIFICATION_GATES_AVAILABLE', False):
                    try:
                        post_tool_use.main()
                    except Exception as e:
                        assert False, f"Should handle missing verification_gates gracefully, got: {e}"
