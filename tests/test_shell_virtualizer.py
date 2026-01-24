"""Tests for shell_virtualizer module.

Tests command categorization and redirect suggestions for Bash commands
that should use dedicated tools instead (cat -> FILE_READ, grep -> FILE_SEARCH, etc).
"""

import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))


class TestCommandCategorization:
    """Test categorize_command() function."""

    def test_cat_detected(self):
        """cat should be detected and suggest FILE_READ category."""
        from shell_virtualizer import categorize_command

        result = categorize_command("cat /path/to/file.py")
        assert result["blocked"] is True
        assert result["suggested_tool"] == "FILE_READ"
        assert "FILE_READ" in result["message"]

    def test_grep_detected(self):
        """grep should be detected and suggest FILE_SEARCH category."""
        from shell_virtualizer import categorize_command

        result = categorize_command("grep 'pattern' /path/to/file.py")
        assert result["blocked"] is True
        assert result["suggested_tool"] == "FILE_SEARCH"

    def test_rg_detected(self):
        """rg (ripgrep) should be detected and suggest FILE_SEARCH category."""
        from shell_virtualizer import categorize_command

        result = categorize_command("rg 'pattern' /path/to/file.py")
        assert result["blocked"] is True
        assert result["suggested_tool"] == "FILE_SEARCH"

    def test_find_with_name_detected(self):
        """find with -name should suggest FILE_SEARCH category."""
        from shell_virtualizer import categorize_command

        result = categorize_command("find . -name '*.py'")
        assert result["blocked"] is True
        assert result["suggested_tool"] == "FILE_SEARCH"

    def test_ls_detected(self):
        """ls should suggest FILE_LIST category."""
        from shell_virtualizer import categorize_command

        result = categorize_command("ls -la /path/to/dir")
        assert result["blocked"] is True
        assert result["suggested_tool"] == "FILE_LIST"

    def test_head_detected(self):
        """head should suggest FILE_READ with limit."""
        from shell_virtualizer import categorize_command

        result = categorize_command("head -n 20 file.py")
        assert result["blocked"] is True
        assert result["suggested_tool"] == "FILE_READ"
        assert "limit" in result["message"].lower()

    def test_tail_detected(self):
        """tail should suggest FILE_READ with offset."""
        from shell_virtualizer import categorize_command

        result = categorize_command("tail -n 20 file.py")
        assert result["blocked"] is True
        assert result["suggested_tool"] == "FILE_READ"
        assert "offset" in result["message"].lower()


class TestSafeCommands:
    """Test that safe shell commands are allowed."""

    def test_git_allowed(self):
        """git commands should be allowed."""
        from shell_virtualizer import categorize_command

        result = categorize_command("git status")
        assert result["blocked"] is False

        result = categorize_command("git log -5")
        assert result["blocked"] is False

    def test_python_allowed(self):
        """python commands should be allowed."""
        from shell_virtualizer import categorize_command

        result = categorize_command("python3 script.py")
        assert result["blocked"] is False

    def test_poetry_allowed(self):
        """poetry commands should be allowed."""
        from shell_virtualizer import categorize_command

        result = categorize_command("poetry install")
        assert result["blocked"] is False

    def test_pytest_allowed(self):
        """pytest should be allowed."""
        from shell_virtualizer import categorize_command

        result = categorize_command("pytest -v tests/")
        assert result["blocked"] is False

    def test_linters_allowed(self):
        """Linters (mypy, ruff, black) should be allowed."""
        from shell_virtualizer import categorize_command

        assert categorize_command("mypy src/")["blocked"] is False
        assert categorize_command("ruff check .")["blocked"] is False
        assert categorize_command("black --check .")["blocked"] is False

    def test_gh_allowed(self):
        """GitHub CLI should be allowed."""
        from shell_virtualizer import categorize_command

        result = categorize_command("gh pr list")
        assert result["blocked"] is False


class TestCheckCommand:
    """Test check_command() enforcement function."""

    def test_returns_block_message_for_cat(self):
        """check_command should return block message for cat."""
        from shell_virtualizer import check_command

        allowed, message = check_command("cat file.py")
        assert allowed is False
        assert "FILE_READ" in message

    def test_returns_allow_for_git(self):
        """check_command should allow git."""
        from shell_virtualizer import check_command

        allowed, message = check_command("git status")
        assert allowed is True
        assert message == "OK"

    def test_handles_piped_commands(self):
        """Piped commands with blocked command should be blocked."""
        from shell_virtualizer import categorize_command

        # cat in pipe should still be detected
        result = categorize_command("cat file.py | grep pattern")
        assert result["blocked"] is True

    def test_handles_command_substitution(self):
        """Command substitution with blocked command should be detected."""
        from shell_virtualizer import categorize_command

        result = categorize_command("echo $(cat file.py)")
        assert result["blocked"] is True


class TestEdgeCases:
    """Test edge cases and unusual inputs."""

    def test_empty_command(self):
        """Empty command should not crash."""
        from shell_virtualizer import categorize_command

        result = categorize_command("")
        assert result["blocked"] is False

    def test_whitespace_only(self):
        """Whitespace-only command should not crash."""
        from shell_virtualizer import categorize_command

        result = categorize_command("   ")
        assert result["blocked"] is False

    def test_cat_in_filename(self):
        """File named 'cat.py' should not trigger cat block."""
        from shell_virtualizer import categorize_command

        # This is python running cat.py, not the cat command
        result = categorize_command("python3 cat.py")
        assert result["blocked"] is False

    def test_grep_as_argument(self):
        """'grep' as argument to another command should not block."""
        from shell_virtualizer import categorize_command

        # apt install grep - grep is an argument, not the command
        result = categorize_command("apt install grep")
        assert result["blocked"] is False


class TestToolCategories:
    """Test that tool categories are properly defined."""

    def test_file_read_category_exists(self):
        """FILE_READ category should be defined."""
        from shell_virtualizer import TOOL_CATEGORIES
        
        assert "FILE_READ" in TOOL_CATEGORIES
        assert "Read" in TOOL_CATEGORIES["FILE_READ"]
        assert "Serena" in TOOL_CATEGORIES["FILE_READ"]

    def test_file_search_category_exists(self):
        """FILE_SEARCH category should be defined."""
        from shell_virtualizer import TOOL_CATEGORIES
        
        assert "FILE_SEARCH" in TOOL_CATEGORIES
        assert "Grep" in TOOL_CATEGORIES["FILE_SEARCH"]

    def test_file_list_category_exists(self):
        """FILE_LIST category should be defined."""
        from shell_virtualizer import TOOL_CATEGORIES
        
        assert "FILE_LIST" in TOOL_CATEGORIES
        assert "list_directory" in TOOL_CATEGORIES["FILE_LIST"]
