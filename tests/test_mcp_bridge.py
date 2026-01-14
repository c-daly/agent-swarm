#!/usr/bin/env python3
"""Minimal tests for mcp_bridge.py native functions."""

import sys
from pathlib import Path

import pytest

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

from mcp_bridge import native_glob, native_grep


class TestNativeGlob:
    """Tests for native_glob function."""

    def test_finds_python_files(self):
        """Can find python files."""
        results = native_glob("*.py", str(lib_dir))
        assert len(results) > 0
        assert all(r.endswith(".py") for r in results)

    def test_empty_for_nonexistent_pattern(self):
        """Returns empty for pattern with no matches."""
        results = native_glob("*.nonexistent", str(lib_dir))
        assert results == []


class TestNativeGrep:
    """Tests for native_grep function."""

    def test_finds_pattern_in_files(self):
        """Can find pattern in files."""
        results = native_grep("def native_glob", str(lib_dir))
        assert len(results) > 0

    def test_files_with_matches_mode(self):
        """files_with_matches mode returns dict with files."""
        results = native_grep("import", str(lib_dir), output_mode="files_with_matches")
        assert isinstance(results, dict)
        assert "files" in results
        assert len(results["files"]) > 0

    def test_content_mode(self):
        """content mode returns dict with output."""
        results = native_grep("def native", str(lib_dir), output_mode="content")
        assert isinstance(results, dict)
        assert "output" in results

    def test_count_mode(self):
        """count mode returns counts per file."""
        results = native_grep("def", str(lib_dir), output_mode="count")
        assert isinstance(results, dict)
        assert "counts" in results
        assert "total" in results
        assert results["total"] > 0

    def test_case_insensitive(self):
        """case_sensitive=False uses -i flag."""
        results = native_grep("DEF NATIVE", str(lib_dir), case_sensitive=False)
        assert isinstance(results, dict)
        # Should find matches with case insensitive search
        assert "files" in results

    def test_glob_filter(self):
        """glob parameter filters files."""
        results = native_grep("def", str(lib_dir), glob="*.py")
        assert isinstance(results, dict)
        assert "files" in results

    def test_context_lines(self):
        """context_lines adds -C flag."""
        results = native_grep("native_glob", str(lib_dir), output_mode="content", context_lines=2)
        assert isinstance(results, dict)
        assert "output" in results

    def test_default_output_mode(self):
        """Unknown output_mode returns raw output."""
        results = native_grep("def", str(lib_dir), output_mode="raw")
        assert isinstance(results, dict)
        assert "output" in results

    def test_timeout_error(self, monkeypatch):
        """Handles subprocess timeout."""
        import subprocess
        def raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="rg", timeout=30)
        monkeypatch.setattr(subprocess, "run", raise_timeout)
        results = native_grep("pattern", str(lib_dir))
        assert results == {"error": "Search timed out after 30s"}

    def test_rg_not_found(self, monkeypatch):
        """Handles missing ripgrep."""
        import subprocess
        def raise_not_found(*args, **kwargs):
            raise FileNotFoundError()
        monkeypatch.setattr(subprocess, "run", raise_not_found)
        results = native_grep("pattern", str(lib_dir))
        assert results == {"error": "ripgrep (rg) not installed"}

    def test_generic_error(self, monkeypatch):
        """Handles generic exceptions."""
        import subprocess
        def raise_error(*args, **kwargs):
            raise RuntimeError("test error")
        monkeypatch.setattr(subprocess, "run", raise_error)
        results = native_grep("pattern", str(lib_dir))
        assert results == {"error": "test error"}
