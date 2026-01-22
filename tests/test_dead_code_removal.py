"""Tests verifying dead code has been removed from the codebase.

Part of Phase 1 of the MCP router refactor - removing file-based persistence.
"""

import subprocess
from pathlib import Path

import pytest


class TestLastSummaryRemoval:
    """Verify all last_summary.json references have been removed."""

    @pytest.fixture
    def project_root(self) -> Path:
        """Get the project root directory."""
        return Path(__file__).parent.parent

    def test_no_last_summary_references_in_python_files(self, project_root: Path):
        """No Python files should reference last_summary."""
        result = subprocess.run(
            ["grep", "-r", "last_summary", "--include=*.py", str(project_root)],
            capture_output=True,
            text=True,
        )
        # Filter out this test file and any plan/doc files
        matches = [
            line for line in result.stdout.strip().split("\n")
            if line and "test_dead_code_removal.py" not in line
        ]
        assert not matches, f"Found last_summary references in Python files:\n{chr(10).join(matches)}"

    def test_no_last_summary_json_file_exists(self, project_root: Path):
        """The last_summary.json state file should not exist."""
        state_file = project_root / ".state" / "last_summary.json"
        assert not state_file.exists(), f"Dead state file still exists: {state_file}"

    def test_no_last_summary_in_hooks_json(self, project_root: Path):
        """hooks.json should not reference last_summary or mcp-summarizer."""
        hooks_json = project_root / "hooks" / "hooks.json"
        if hooks_json.exists():
            content = hooks_json.read_text()
            assert "last_summary" not in content, "hooks.json references last_summary"
            assert "mcp-summarizer" not in content, "hooks.json references mcp-summarizer"
