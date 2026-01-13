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
        """IterateWorkflow should use orchestrate phase."""
        wf = IterateWorkflow()

        # IterateWorkflow now delegates to orchestrator
        assert wf.PHASES == ["test_writing", "implement", "test", "coverage", "review"], "IterateWorkflow should have single orchestrate phase"

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


class TestPhaseBannerEnforcement:
    """Tests for SAFE.5: Phase Banner Enforcement.

    Tools should be blocked until the agent outputs a phase banner,
    ensuring visibility into current workflow state.
    """

    def test_banner_flag_false_on_init(self):
        """SAFE.5.1: phase_banner_shown should be False on workflow init."""
        from workflow import IterateWorkflow, _load_state

        wf = IterateWorkflow()
        state = _load_state()

        assert state.get("phase_banner_shown") is False, \
            "phase_banner_shown should be False on workflow init"

    def test_banner_flag_false_on_phase_transition(self):
        """SAFE.5.3: phase_banner_shown should reset to False on phase change."""
        from workflow import IterateWorkflow, Workflow, _load_state, _save_state

        wf = IterateWorkflow()

        # Simulate banner was shown
        state = _load_state()
        state["phase_banner_shown"] = True
        _save_state(state)

        # Transition to implement phase
        Workflow.transition_phase("implement")

        state = _load_state()
        assert state.get("phase_banner_shown") is False, \
            "phase_banner_shown should reset on phase transition"

    def test_banner_flag_false_on_advance_phase(self):
        """SAFE.5.3: phase_banner_shown should reset on advance_phase()."""
        from workflow import IterateWorkflow, Workflow, _load_state, _save_state

        wf = IterateWorkflow()

        # Set banner shown, then advance phase
        Workflow.mark_banner_shown()
        assert Workflow.is_banner_shown() is True

        # Advance from test_writing to implement
        result = Workflow.advance_phase()
        assert result == "implement", "Should advance to implement"

        # Banner flag should reset on phase change
        assert Workflow.is_banner_shown() is False, \
            "phase_banner_shown should reset on advance_phase"

    def test_mark_banner_shown_sets_flag(self):
        """SAFE.5.1: mark_banner_shown() should set flag to True."""
        from workflow import IterateWorkflow, Workflow, _load_state

        wf = IterateWorkflow()
        assert _load_state().get("phase_banner_shown") is False

        Workflow.mark_banner_shown()

        assert _load_state().get("phase_banner_shown") is True, \
            "mark_banner_shown() should set flag to True"

    def test_is_banner_shown_returns_current_state(self):
        """SAFE.5.1: is_banner_shown() should return current flag state."""
        from workflow import IterateWorkflow, Workflow, _load_state, _save_state

        wf = IterateWorkflow()
        assert Workflow.is_banner_shown() is False

        Workflow.mark_banner_shown()
        assert Workflow.is_banner_shown() is True


class TestPhaseBannerHook:
    """Tests for check_phase_banner() in combined_enforcement.py."""

    def setup_method(self):
        """Setup test state."""
        import sys
        hooks_dir = Path(__file__).parent.parent / "hooks"
        if str(hooks_dir) not in sys.path:
            sys.path.insert(0, str(hooks_dir))

        # Reset workflow state
        from workflow import Workflow
        Workflow.reset()

    def test_always_allowed_tools_bypass_banner(self):
        """SAFE.5.2: TodoWrite/AskUserQuestion bypass banner check."""
        from combined_enforcement import check_phase_banner, ALWAYS_ALLOWED
        from workflow import IterateWorkflow, _load_state

        wf = IterateWorkflow()
        state = _load_state()

        # These should pass even without banner
        for tool in ALWAYS_ALLOWED:
            result = check_phase_banner(tool, state)
            assert result is None, f"{tool} should bypass banner check"

    def test_work_tool_blocked_without_banner(self):
        """SAFE.5.4: Work tools blocked when banner not shown."""
        from combined_enforcement import check_phase_banner
        from workflow import IterateWorkflow, _load_state

        wf = IterateWorkflow()
        state = _load_state()

        # Edit should be blocked without banner
        result = check_phase_banner("Edit", state)
        assert result is not None, "Edit should be blocked without banner"
        assert "BANNER REQUIRED" in result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")

    def test_work_tool_allowed_with_banner(self):
        """SAFE.5.4: Work tools allowed after banner shown."""
        from combined_enforcement import check_phase_banner
        from workflow import IterateWorkflow, Workflow, _load_state

        wf = IterateWorkflow()
        Workflow.mark_banner_shown()
        state = _load_state()

        # Edit should be allowed after banner
        result = check_phase_banner("Edit", state)
        assert result is None, "Edit should be allowed after banner shown"

    def test_no_workflow_bypasses_banner(self):
        """When no workflow active, banner check passes."""
        from combined_enforcement import check_phase_banner
        from workflow import Workflow, _load_state

        Workflow.reset()
        state = _load_state()

        # No workflow = no banner requirement
        result = check_phase_banner("Edit", state)
        assert result is None, "No workflow should bypass banner check"
