"""Tests for protocol_assembly.py briefing quality."""

import sys
from pathlib import Path

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

from protocol_assembly import assemble_subagent_briefing  # noqa: E402


class TestBriefingContent:
    def test_briefing_contains_correct_tool_patterns(self):
        """Briefing must contain mcp-call with both native and serena tools."""
        briefing = assemble_subagent_briefing("implementer")
        assert "mcp-call" in briefing
        # Must document native tools (read, write, edit, grep, glob, bash)
        assert "native__read_file" in briefing
        assert "native__bash" in briefing
        # Must document serena symbolic tools
        assert "serena__find_symbol" in briefing

    def test_briefing_contains_shell_aliases(self):
        """Briefing must document shell alias pattern for commands."""
        briefing = assemble_subagent_briefing("implementer")
        assert "pytest" in briefing.lower()
        assert "git" in briefing.lower()

    def test_briefing_contains_operational_rules(self):
        """Briefing must contain rules for observed failure modes."""
        briefing = assemble_subagent_briefing("implementer")
        # Must mention parallelization
        assert "parallel" in briefing.lower()
        # Must mention not re-reading
        assert "duplicate" in briefing.lower() or "re-read" in briefing.lower() or "already read" in briefing.lower()

    def test_briefing_contains_role_info(self):
        """Briefing should contain role-specific content."""
        impl_briefing = assemble_subagent_briefing("implementer")
        expl_briefing = assemble_subagent_briefing("explorer")
        # They should differ
        assert impl_briefing != expl_briefing

    def test_briefing_within_token_budget(self):
        """Briefing should be concise — under 2000 tokens (~8000 chars)."""
        briefing = assemble_subagent_briefing("implementer")
        assert len(briefing) < 8000

    def test_briefing_documents_timeout(self):
        """Briefing should mention MCP call timeout for long-running commands."""
        briefing = assemble_subagent_briefing("implementer")
        assert "timeout" in briefing.lower()
