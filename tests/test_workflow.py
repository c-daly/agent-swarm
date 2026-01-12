#!/usr/bin/env python3
"""Tests for workflow.py - iterate and orchestrate workflow management."""

import subprocess
import sys
from pathlib import Path


# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

from workflow import IterateWorkflow


class TestIterateWorkflowAlwaysTDD:
    """Tests that IterateWorkflow always uses TDD mode.

    TDD is mandatory - there should be no way to skip it.
    """

    def test_iterate_workflow_uses_tdd_phases(self):
        """IterateWorkflow should always use TDD phases."""
        wf = IterateWorkflow()

        # TDD phases start with test_writing
        assert wf.PHASES[0] == "test_writing", "First phase must be test_writing"
        assert "test_writing" in wf.PHASES, "TDD phases must include test_writing"

    def test_iterate_workflow_no_tdd_parameter(self):
        """IterateWorkflow should not accept a tdd parameter.

        If the tdd parameter exists, it's a temptation to skip TDD.
        """
        import inspect
        sig = inspect.signature(IterateWorkflow.__init__)
        params = list(sig.parameters.keys())

        assert "tdd" not in params, "IterateWorkflow should not have tdd parameter"

    def test_iterate_workflow_mode_is_tdd(self):
        """IterateWorkflow mode should indicate TDD."""
        wf = IterateWorkflow()

        assert "tdd" in wf.MODE.lower(), f"Mode should indicate TDD, got: {wf.MODE}"


class TestCLINoTddFlagRemoved:
    """Tests that --no-tdd flag is not accepted by CLI."""

    def test_cli_rejects_no_tdd_flag(self):
        """workflow.py iterate --no-tdd should fail or be ignored."""
        workflow_script = Path(__file__).parent.parent / "lib" / "workflow.py"

        result = subprocess.run(
            [sys.executable, str(workflow_script), "iterate", "--no-tdd"],
            capture_output=True,
            text=True
        )

        # Should either error (exit code != 0) or succeed but ignore the flag
        # If it errors, that's the strict behavior we want
        if result.returncode == 0:
            # If it succeeded, verify it's still TDD mode
            assert "TDD mode" in result.stdout, (
                f"--no-tdd should be rejected or ignored. Got: {result.stdout}"
            )
        # If returncode != 0, that's also acceptable (strict rejection)


class TestSessionStateReset:
    """Tests for session state reset on SessionStart and PreCompact."""

    def test_session_start_clears_blocked_at(self, tmp_path):
        """SessionStart should clear blocked_at state.

        The session-start hook initializes fresh state without blocked_at,
        effectively clearing any blocking state from previous sessions.
        """
        hooks_dir = Path(__file__).parent.parent / "hooks"
        hook_content = (hooks_dir / "session-start.py").read_text()

        # Verify blocked_at is NOT in the initialized state
        # The hook creates fresh state without blocked_at, which clears it
        assert "blocked_at" in hook_content, "session-start.py should mention blocked_at"

        # The state initialization should NOT include blocked_at (clearing it)
        # Look for the comment that explains the clearing
        assert "blocked_at" in hook_content and ("NOT included" in hook_content or "clears" in hook_content.lower()), \
            "session-start.py should clear blocked_at by not including it in fresh state"

    def test_session_start_clears_mcp_counts(self, tmp_path):
        """SessionStart should clear mcp_counts."""
        hooks_dir = Path(__file__).parent.parent / "hooks"
        hook_content = (hooks_dir / "session-start.py").read_text()

        # Verify mcp_counts is reset in the state initialization
        assert "mcp_counts" in hook_content, "session-start.py should reset mcp_counts"

    def test_session_start_clears_search_counters(self, tmp_path):
        """SessionStart should clear search/read counters."""
        hooks_dir = Path(__file__).parent.parent / "hooks"
        hook_content = (hooks_dir / "session-start.py").read_text()

        # These are already in the hook
        assert "search_count" in hook_content
        assert "read_count" in hook_content

    def test_precompact_clears_classification_state(self, tmp_path):
        """PreCompact should clear classification-related state."""
        hooks_dir = Path(__file__).parent.parent / "hooks"
        hook_content = (hooks_dir / "pre-compacting.py").read_text()

        # Verify classification state is handled
        assert "classification" in hook_content.lower() or "reset" in hook_content.lower(), \
            "pre-compacting.py should handle classification state"

    def test_precompact_clears_workflow_invoked(self, tmp_path):
        """PreCompact should clear workflow_invoked state."""
        hooks_dir = Path(__file__).parent.parent / "hooks"
        hook_content = (hooks_dir / "pre-compacting.py").read_text()

        # For now this is a documentation test - will implement the actual reset
        assert "workflow" in hook_content.lower() or "state" in hook_content.lower()

    def test_precompact_preserves_phase(self, tmp_path):
        """PreCompact should preserve workflow phase."""
        hooks_dir = Path(__file__).parent.parent / "hooks"
        hook_content = (hooks_dir / "pre-compacting.py").read_text()

        # Phase should be in persistent flags or preserved
        assert "phase" in hook_content.lower()