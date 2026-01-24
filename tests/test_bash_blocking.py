"""Tests for Bash tool blocking in orchestrate phase.

The orchestrator should NOT have access to native Bash tool,
but should be able to use mcp__router__native__bash for gh commands.
"""

import sys
from pathlib import Path

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

from phase_model import check_tool_allowed, ITERATE_PHASES


class TestBashBlockingInOrchestrate:
    """Test that native Bash is blocked in orchestrate phase."""

    def test_native_bash_blocked_in_orchestrate(self):
        """Native Bash tool should be blocked in orchestrate phase."""
        allowed, reason = check_tool_allowed("Bash", "orchestrate")
        assert not allowed
        assert "blocked" in reason.lower()

    def test_native_bash_in_blocked_tools(self):
        """Bash should be in orchestrate blocked_tools."""
        phase = ITERATE_PHASES["orchestrate"]
        assert "Bash" in phase.blocked_tools

    def test_mcp_router_native_bash_allowed_in_orchestrate(self):
        """MCP router native__bash should be allowed for gh commands.

        The enforcement hook strips 'mcp__router__' prefix, so we test 'native__bash'.
        Since native__bash is not in TOOL_CATEGORIES, it's allowed by default.
        """
        # After prefix stripping: mcp__router__native__bash -> native__bash
        allowed, reason = check_tool_allowed("native__bash", "orchestrate")
        assert allowed
        assert reason == ""

    def test_edit_still_blocked_in_orchestrate(self):
        """Edit should still be blocked in orchestrate."""
        allowed, reason = check_tool_allowed("Edit", "orchestrate")
        assert not allowed

    def test_write_still_blocked_in_orchestrate(self):
        """Write should still be blocked in orchestrate."""
        allowed, reason = check_tool_allowed("Write", "orchestrate")
        assert not allowed


class TestBashAllowedInOtherPhases:
    """Test that Bash behavior is correct in other phases."""

    def test_bash_allowed_in_implement(self):
        """Bash should be allowed in implement phase (handled by shell_virtualizer)."""
        allowed, _ = check_tool_allowed("Bash", "implement")
        # Bash has None category, so it returns True (handled by shell_virtualizer)
        assert allowed

    def test_bash_blocked_in_review(self):
        """Bash should be blocked in review phase."""
        allowed, reason = check_tool_allowed("Bash", "review")
        assert not allowed
        assert "blocked" in reason.lower()

    def test_native_bash_allowed_in_implement(self):
        """MCP router native__bash should be allowed in implement."""
        allowed, reason = check_tool_allowed("native__bash", "implement")
        assert allowed
