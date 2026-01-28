"""Tests for remember.py - persistent memory save utility."""

import sys
from pathlib import Path


# Add context directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "context"))

from remember import parse_args, save_memory, main


class TestParseArgs:
    """Tests for argument parsing."""

    def test_simple_content(self):
        args = parse_args(["Use pytest for testing"])
        assert args.content == "Use pytest for testing"
        assert args.scope is None

    def test_scope_override_global(self):
        args = parse_args(["--scope=global", "Always use type hints"])
        assert args.content == "Always use type hints"
        assert args.scope == "global"

    def test_scope_override_user(self):
        args = parse_args(["--scope=user", "I prefer dark mode"])
        assert args.content == "I prefer dark mode"
        assert args.scope == "user"

    def test_scope_override_repo(self):
        args = parse_args(["--scope=repo", "This repo uses FastAPI"])
        assert args.content == "This repo uses FastAPI"
        assert args.scope == "repo"

    def test_scope_override_component(self):
        args = parse_args(["--scope=component", "This module handles auth"])
        assert args.content == "This module handles auth"
        assert args.scope == "component"

    def test_content_with_spaces(self):
        args = parse_args(["This has many words in it"])
        assert args.content == "This has many words in it"

    def test_scope_and_content_order(self):
        # --scope can come before or after content
        args = parse_args(["Content first", "--scope=repo"])
        assert args.content == "Content first"
        assert args.scope == "repo"


class TestSaveMemory:
    """Tests for save_memory function."""

    def test_explicit_user_scope(self, tmp_path):
        """Explicit scope should override inference."""
        working_dir = tmp_path / "project"
        working_dir.mkdir()
        user_dir = tmp_path / "user_home"
        user_dir.mkdir()

        result = save_memory(
            content="Test memory",
            scope="user",
            working_dir=working_dir,
            user_dir=user_dir,
        )

        assert result == user_dir / ".context" / "MEMORY.md"
        assert result.exists()
        assert "Test memory" in result.read_text()

    def test_explicit_repo_scope(self, tmp_path):
        """Explicit repo scope saves at repo root."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()

        result = save_memory(
            content="Repo-level memory",
            scope="repo",
            working_dir=repo_dir / "subdir",
            user_dir=tmp_path / "user",
        )

        # Should save at repo root
        assert result.parent.parent == repo_dir
        assert "Repo-level memory" in result.read_text()

    def test_explicit_component_scope(self, tmp_path):
        """Explicit component scope saves at working dir."""
        working_dir = tmp_path / "project" / "src" / "module"
        working_dir.mkdir(parents=True)

        result = save_memory(
            content="Component memory",
            scope="component",
            working_dir=working_dir,
            user_dir=tmp_path / "user",
        )

        assert result.parent.parent == working_dir
        assert "Component memory" in result.read_text()

    def test_auto_inference_global(self, tmp_path):
        """Content with 'always' should infer user scope."""
        working_dir = tmp_path / "project"
        working_dir.mkdir()
        (working_dir / ".git").mkdir()
        user_dir = tmp_path / "user_home"
        user_dir.mkdir()

        result = save_memory(
            content="Always use descriptive variable names",
            scope=None,  # Let it infer
            working_dir=working_dir,
            user_dir=user_dir,
        )

        # Should infer user scope due to "always"
        assert result.parent.parent == user_dir

    def test_auto_inference_repo(self, tmp_path):
        """Generic content should default to repo scope."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()
        user_dir = tmp_path / "user_home"
        user_dir.mkdir()

        result = save_memory(
            content="This project uses FastAPI",
            scope=None,
            working_dir=repo_dir,
            user_dir=user_dir,
        )

        # Should default to repo scope
        assert result.parent.parent == repo_dir

    def test_global_scope_alias(self, tmp_path):
        """'global' should map to 'user' scope."""
        working_dir = tmp_path / "project"
        working_dir.mkdir()
        user_dir = tmp_path / "user_home"
        user_dir.mkdir()

        result = save_memory(
            content="Global preference",
            scope="global",
            working_dir=working_dir,
            user_dir=user_dir,
        )

        assert result.parent.parent == user_dir


class TestMain:
    """Integration tests for main function."""

    def test_main_outputs_confirmation(self, tmp_path, capsys):
        """Main should print confirmation of save location."""
        working_dir = tmp_path / "project"
        working_dir.mkdir()
        (working_dir / ".git").mkdir()
        user_dir = tmp_path / "user"
        user_dir.mkdir()

        result = main(
            ["Test content"],
            working_dir=working_dir,
            user_dir=user_dir,
        )

        assert result == 0
        captured = capsys.readouterr()
        assert "Saved to" in captured.out
        assert "MEMORY.md" in captured.out

    def test_main_shows_scope(self, tmp_path, capsys):
        """Main should indicate the scope in output."""
        working_dir = tmp_path / "project"
        working_dir.mkdir()
        user_dir = tmp_path / "user"
        user_dir.mkdir()

        main(
            ["--scope=user", "User preference"],
            working_dir=working_dir,
            user_dir=user_dir,
        )

        captured = capsys.readouterr()
        assert "user" in captured.out.lower()
