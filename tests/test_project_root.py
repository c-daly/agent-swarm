#!/usr/bin/env python3
"""Tests for project_root.py - project root detection from working directory."""

import sys
import tempfile
from pathlib import Path


# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))


class TestFindProjectRoot:
    """Tests for find_project_root function."""

    def test_finds_git_directory(self):
        """Should find project root by .git directory."""
        from project_root import find_project_root
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            subdir = root / "src" / "lib"
            subdir.mkdir(parents=True)
            
            result = find_project_root(subdir)
            
            assert result == root

    def test_finds_pyproject_toml(self):
        """Should find project root by pyproject.toml."""
        from project_root import find_project_root
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").touch()
            subdir = root / "src"
            subdir.mkdir()
            
            result = find_project_root(subdir)
            
            assert result == root

    def test_finds_package_json(self):
        """Should find project root by package.json."""
        from project_root import find_project_root
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "package.json").touch()
            subdir = root / "src" / "components"
            subdir.mkdir(parents=True)
            
            result = find_project_root(subdir)
            
            assert result == root

    def test_finds_explicit_marker(self):
        """Should find project root by .project-root marker file."""
        from project_root import find_project_root
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".project-root").touch()
            subdir = root / "deep" / "nested" / "path"
            subdir.mkdir(parents=True)
            
            result = find_project_root(subdir)
            
            assert result == root

    def test_prioritizes_git_over_other_markers(self):
        """Should prefer .git over other markers when both exist."""
        from project_root import find_project_root
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            (root / "pyproject.toml").touch()
            subdir = root / "src"
            subdir.mkdir()
            
            result = find_project_root(subdir)
            
            assert result == root

    def test_fallback_to_cwd_if_no_markers(self):
        """Should return cwd if no project markers found."""
        from project_root import find_project_root
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # No markers, should return the directory itself
            path = Path(tmpdir)
            
            result = find_project_root(path)
            
            assert result == path

    def test_handles_nested_git_repositories(self):
        """Should find nearest .git, not root one."""
        from project_root import find_project_root
        
        with tempfile.TemporaryDirectory() as tmpdir:
            outer = Path(tmpdir)
            (outer / ".git").mkdir()
            
            inner = outer / "submodule"
            inner.mkdir()
            (inner / ".git").mkdir()
            
            subdir = inner / "src"
            subdir.mkdir()
            
            result = find_project_root(subdir)
            
            # Should find the inner/closer .git
            assert result == inner

    def test_accepts_string_path(self):
        """Should accept string path as well as Path object."""
        from project_root import find_project_root
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            subdir = root / "src"
            subdir.mkdir()
            
            # Pass string instead of Path
            result = find_project_root(str(subdir))
            
            assert result == root

    def test_uses_cwd_as_default(self):
        """Should use cwd if no path specified."""
        from project_root import find_project_root
        
        # Current directory should have a .git (we're in agent-swarm)
        result = find_project_root()
        
        # Should find the agent-swarm root
        assert (result / ".git").exists() or (result / "pyproject.toml").exists()


class TestGetHandoffDir:
    """Tests for get_handoff_dir function."""

    def test_returns_serena_memories_path(self):
        """Should return .serena/memories under project root."""
        from project_root import get_handoff_dir
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            
            result = get_handoff_dir(root)
            
            assert result == root / ".serena" / "memories"

    def test_creates_directory_if_not_exists(self):
        """Should create the handoff directory if it doesn't exist."""
        from project_root import get_handoff_dir
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            
            result = get_handoff_dir(root, create=True)
            
            assert result.exists()
            assert result.is_dir()

    def test_does_not_create_by_default(self):
        """Should not create directory if create=False (default)."""
        from project_root import get_handoff_dir
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            
            result = get_handoff_dir(root, create=False)
            
            assert not result.exists()


class TestFindRecentHandoffs:
    """Tests for find_recent_handoffs function."""

    def test_finds_handoff_files(self):
        """Should find handoff-*.md files in memories directory."""
        from project_root import find_recent_handoffs
        import time
        import os
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memories = root / ".serena" / "memories"
            memories.mkdir(parents=True)
            
            # Create older file first
            older = memories / "handoff-2026-01-23-other.md"
            older.write_text("# Other")
            older_mtime = time.time() - 3600  # 1 hour ago
            os.utime(older, (older_mtime, older_mtime))
            
            # Create newer file
            newer = memories / "handoff-2026-01-24-topic.md"
            newer.write_text("# Handoff")
            
            # Create non-handoff file
            (memories / "not-a-handoff.md").write_text("# Not")
            
            result = find_recent_handoffs(root)
            
            assert len(result) == 2
            # Should be sorted by mtime (most recent first)
            assert "2026-01-24" in result[0].name

    def test_returns_empty_if_no_handoffs(self):
        """Should return empty list if no handoff files exist."""
        from project_root import find_recent_handoffs
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memories = root / ".serena" / "memories"
            memories.mkdir(parents=True)
            
            result = find_recent_handoffs(root)
            
            assert result == []

    def test_returns_empty_if_dir_not_exists(self):
        """Should return empty list if memories directory doesn't exist."""
        from project_root import find_recent_handoffs
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # No .serena/memories directory
            
            result = find_recent_handoffs(root)
            
            assert result == []

    def test_limits_to_max_count(self):
        """Should return at most max_count handoffs."""
        from project_root import find_recent_handoffs
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memories = root / ".serena" / "memories"
            memories.mkdir(parents=True)
            
            for i in range(10):
                (memories / f"handoff-2026-01-{10+i:02d}-topic.md").write_text("# H")
            
            result = find_recent_handoffs(root, max_count=3)
            
            assert len(result) == 3

    def test_filters_by_age(self):
        """Should filter handoffs older than max_age_hours."""
        from project_root import find_recent_handoffs
        import time
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memories = root / ".serena" / "memories"
            memories.mkdir(parents=True)
            
            # Create a recent handoff
            recent = memories / "handoff-2026-01-24-recent.md"
            recent.write_text("# Recent")
            
            # Create an old handoff and set mtime to 3 days ago
            old = memories / "handoff-2026-01-20-old.md"
            old.write_text("# Old")
            old_mtime = time.time() - (72 * 3600)  # 72 hours ago
            import os
            os.utime(old, (old_mtime, old_mtime))
            
            # Only get handoffs from last 48 hours
            result = find_recent_handoffs(root, max_age_hours=48)
            
            assert len(result) == 1
            assert "recent" in result[0].name


class TestBuildHandoffFilename:
    """Tests for build_handoff_filename function."""

    def test_includes_date_and_topic(self):
        """Should include date and topic in filename."""
        from project_root import build_handoff_filename
        
        result = build_handoff_filename("subagent-tools")
        
        assert result.startswith("handoff-")
        assert "subagent-tools" in result
        assert result.endswith(".md")

    def test_sanitizes_topic(self):
        """Should sanitize topic to be filesystem-safe."""
        from project_root import build_handoff_filename
        
        result = build_handoff_filename("Fix Issue #123: Feature/Branch")
        
        # Should not contain special characters
        assert "/" not in result
        assert "#" not in result
        assert ":" not in result

    def test_includes_current_date(self):
        """Should include current date in YYYY-MM-DD format."""
        from project_root import build_handoff_filename
        from datetime import date
        
        result = build_handoff_filename("test")
        today = date.today().isoformat()
        
        assert today in result


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
