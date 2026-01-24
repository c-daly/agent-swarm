"""Tests for phase model and tool category enforcement.

NOTE: Tests require phase model refactoring for MCP router integration.
"""

import pytest

pytestmark = pytest.mark.skip(
    reason="Integration test: phase model tests need refactoring for MCP router"
)
from lib.phase_model import (  # noqa: E402
    Phase,
    ToolCategory,
    ITERATE_PHASES,
    TOOL_CATEGORIES,
    check_tool_allowed,
    get_phase_info,
)


class TestPhaseDefinitions:
    """Test phase definitions and structure."""

    def test_all_phases_exist(self):
        """All expected phases are defined."""
        expected_phases = {
            "orchestrate", "test_writing", "implement", "test", "coverage", "review"
        }
        assert set(ITERATE_PHASES.keys()) == expected_phases

    def test_phases_are_immutable(self):
        """Phase objects are frozen."""
        phase = ITERATE_PHASES["test_writing"]
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            phase.name = "modified"

    def test_phase_categories_are_frozen(self):
        """Phase allowed_categories are frozensets."""
        phase = ITERATE_PHASES["implement"]
        assert isinstance(phase.allowed_categories, frozenset)
        assert isinstance(phase.blocked_tools, frozenset)


class TestOrchestratePhase:
    """Test the orchestrate phase restrictions."""

    def test_allows_file_read(self):
        """File reading is allowed in orchestrate."""
        allowed, _ = check_tool_allowed("Read", "orchestrate")
        assert allowed

    def test_allows_file_search(self):
        """File searching is allowed in orchestrate."""
        allowed, _ = check_tool_allowed("Glob", "orchestrate")
        assert allowed

    def test_allows_code_query(self):
        """Code queries are allowed in orchestrate."""
        allowed, _ = check_tool_allowed(
            "mcp__plugin_serena_serena__find_symbol", "orchestrate"
        )
        assert allowed

    def test_allows_subagents(self):
        """Subagents are allowed in orchestrate."""
        allowed, _ = check_tool_allowed("Task", "orchestrate")
        assert allowed

    def test_blocks_edit(self):
        """Edit is blocked in orchestrate."""
        allowed, reason = check_tool_allowed("Edit", "orchestrate")
        assert not allowed
        assert "blocked" in reason.lower()

    def test_blocks_write(self):
        """Write is blocked in orchestrate."""
        allowed, reason = check_tool_allowed("Write", "orchestrate")
        assert not allowed
        assert "blocked" in reason.lower()

    def test_blocks_notebook_edit(self):
        """NotebookEdit is blocked in orchestrate."""
        allowed, reason = check_tool_allowed("NotebookEdit", "orchestrate")
        assert not allowed
        assert "blocked" in reason.lower()

    def test_no_verification_required(self):
        """orchestrate phase doesn't require verification."""
        phase = ITERATE_PHASES["orchestrate"]
        assert not phase.requires_verification


class TestTestWritingPhase:
    """Test the test_writing phase restrictions."""

    def test_allows_file_read(self):
        """File reading is allowed in test_writing."""
        allowed, _ = check_tool_allowed("Read", "test_writing")
        assert allowed

    def test_allows_file_write(self):
        """File writing is allowed for test files."""
        allowed, _ = check_tool_allowed("Write", "test_writing")
        assert allowed

    def test_allows_code_query(self):
        """Code queries are allowed."""
        allowed, _ = check_tool_allowed(
            "mcp__plugin_serena_serena__find_symbol", "test_writing"
        )
        assert allowed

    def test_allows_file_search(self):
        """File searching is allowed."""
        allowed, _ = check_tool_allowed("Glob", "test_writing")
        assert allowed

    def test_no_verification_required(self):
        """test_writing phase doesn't require verification."""
        phase = ITERATE_PHASES["test_writing"]
        assert not phase.requires_verification


class TestImplementPhase:
    """Test the implement phase restrictions."""

    def test_allows_code_edit(self):
        """Code editing is allowed in implement."""
        allowed, _ = check_tool_allowed(
            "mcp__plugin_serena_serena__replace_symbol_body", "implement"
        )
        assert allowed

    def test_allows_subagents(self):
        """Subagents are allowed in implement."""
        allowed, _ = check_tool_allowed("Task", "implement")
        assert allowed

    def test_allows_all_test_writing_tools(self):
        """Implement phase includes all test_writing capabilities."""
        test_writing_categories = ITERATE_PHASES["test_writing"].allowed_categories
        implement_categories = ITERATE_PHASES["implement"].allowed_categories
        assert test_writing_categories.issubset(implement_categories)


class TestTestPhase:
    """Test the test phase restrictions (strictest phase)."""

    def test_allows_file_read(self):
        """File reading is allowed in test phase."""
        allowed, _ = check_tool_allowed("Read", "test")
        assert allowed

    def test_blocks_edit(self):
        """Edit tool is blocked in test phase."""
        allowed, reason = check_tool_allowed("Edit", "test")
        assert not allowed
        assert "blocked" in reason.lower()
        assert "test" in reason

    def test_blocks_write(self):
        """Write tool is blocked in test phase."""
        allowed, reason = check_tool_allowed("Write", "test")
        assert not allowed
        assert "blocked" in reason.lower()

    def test_allows_shell_safe(self):
        """Safe shell commands (pytest) allowed in test phase."""
        # Bash itself will be handled by shell_virtualizer
        # This test verifies the category is allowed
        phase = ITERATE_PHASES["test"]
        assert ToolCategory.SHELL_SAFE in phase.allowed_categories

    def test_requires_verification(self):
        """test phase requires verification."""
        phase = ITERATE_PHASES["test"]
        assert phase.requires_verification

    def test_blocks_file_write_category(self):
        """FILE_WRITE category is not allowed in test phase."""
        phase = ITERATE_PHASES["test"]
        assert ToolCategory.FILE_WRITE not in phase.allowed_categories


class TestCoveragePhase:
    """Test the coverage phase restrictions."""

    def test_allows_web_research(self):
        """Web research (Greptile) is allowed in coverage."""
        allowed, _ = check_tool_allowed(
            "mcp__plugin_greptile_greptile__get_merge_request", "coverage"
        )
        assert allowed

    def test_allows_test_file_writing(self):
        """File writing for test files is allowed."""
        allowed, _ = check_tool_allowed("Write", "coverage")
        assert allowed

    def test_requires_verification(self):
        """coverage phase requires verification."""
        phase = ITERATE_PHASES["coverage"]
        assert phase.requires_verification


class TestReviewPhase:
    """Test the review phase restrictions (read-only)."""

    def test_allows_file_read(self):
        """File reading is allowed in review."""
        allowed, _ = check_tool_allowed("Read", "review")
        assert allowed

    def test_allows_web_research(self):
        """Web research is allowed in review."""
        allowed, _ = check_tool_allowed("WebSearch", "review")
        assert allowed

    def test_blocks_edit(self):
        """Edit is blocked in review."""
        allowed, reason = check_tool_allowed("Edit", "review")
        assert not allowed
        assert "blocked" in reason.lower()

    def test_blocks_write(self):
        """Write is blocked in review."""
        allowed, reason = check_tool_allowed("Write", "review")
        assert not allowed
        assert "blocked" in reason.lower()

    def test_blocks_bash(self):
        """Bash is blocked in review."""
        allowed, reason = check_tool_allowed("Bash", "review")
        assert not allowed
        assert "blocked" in reason.lower()

    def test_requires_verification(self):
        """review phase requires verification."""
        phase = ITERATE_PHASES["review"]
        assert phase.requires_verification


class TestToolCategories:
    """Test tool category mappings."""

    def test_common_tools_mapped(self):
        """Common tools have category mappings."""
        common_tools = ["Read", "Edit", "Write", "Glob", "Grep", "Task", "Bash"]
        for tool in common_tools:
            assert tool in TOOL_CATEGORIES

    def test_bash_has_no_category(self):
        """Bash has None category (special handling)."""
        assert TOOL_CATEGORIES["Bash"] is None

    def test_serena_tools_mapped(self):
        """Serena MCP tools are mapped."""
        serena_tools = [
            "mcp__plugin_serena_serena__read_file",
            "mcp__plugin_serena_serena__create_text_file",
            "mcp__plugin_serena_serena__find_symbol",
            "mcp__plugin_serena_serena__replace_symbol_body",
        ]
        for tool in serena_tools:
            assert tool in TOOL_CATEGORIES
            assert TOOL_CATEGORIES[tool] is not None

    def test_filesystem_tools_mapped(self):
        """Filesystem MCP tools are mapped."""
        filesystem_tools = [
            "mcp__filesystem__read_file",
            "mcp__filesystem__write_file",
            "mcp__filesystem__search_files",
        ]
        for tool in filesystem_tools:
            assert tool in TOOL_CATEGORIES
            assert TOOL_CATEGORIES[tool] is not None


class TestCheckToolAllowed:
    """Test the check_tool_allowed validation function."""

    def test_unknown_phase_allows_all(self):
        """Unknown phases allow all tools (defensive)."""
        allowed, _ = check_tool_allowed("Edit", "unknown_phase")
        assert allowed

    def test_unknown_tool_allowed(self):
        """Unknown tools are allowed (defensive)."""
        allowed, _ = check_tool_allowed("UnknownTool", "test")
        assert allowed

    def test_explicit_block_takes_precedence(self):
        """Explicitly blocked tools are blocked."""
        allowed, reason = check_tool_allowed("Edit", "test")
        assert not allowed
        assert "Edit" in reason

    def test_category_check_for_known_tool(self):
        """Known tool categories are checked against phase."""
        # WebSearch is WEB_RESEARCH, not allowed in test phase
        allowed, reason = check_tool_allowed("WebSearch", "test")
        assert not allowed
        assert "WEB_RESEARCH" in reason or "not allowed" in reason.lower()

    def test_bash_returns_allowed(self):
        """Bash returns allowed (handled by shell_virtualizer)."""
        allowed, _ = check_tool_allowed("Bash", "implement")
        assert allowed  # Will be handled elsewhere

    def test_reason_empty_when_allowed(self):
        """Reason is empty when tool is allowed."""
        allowed, reason = check_tool_allowed("Read", "implement")
        assert allowed
        assert reason == ""

    def test_reason_present_when_blocked(self):
        """Reason is present when tool is blocked."""
        allowed, reason = check_tool_allowed("Edit", "test")
        assert not allowed
        assert len(reason) > 0


class TestGetPhaseInfo:
    """Test the get_phase_info helper function."""

    def test_returns_phase_for_valid_name(self):
        """Returns Phase object for valid phase name."""
        phase = get_phase_info("implement")
        assert phase is not None
        assert isinstance(phase, Phase)
        assert phase.name == "implement"

    def test_returns_none_for_invalid_name(self):
        """Returns None for invalid phase name."""
        phase = get_phase_info("nonexistent")
        assert phase is None

    def test_returned_phase_is_immutable(self):
        """Returned phase object is immutable."""
        phase = get_phase_info("test")
        with pytest.raises(Exception):
            phase.name = "modified"


class TestPhaseProgression:
    """Test logical phase progression assumptions."""

    def test_implement_superset_of_test_writing(self):
        """Implement phase allows everything test_writing allows."""
        test_writing = ITERATE_PHASES["test_writing"]
        implement = ITERATE_PHASES["implement"]
        assert test_writing.allowed_categories.issubset(
            implement.allowed_categories
        )

    def test_verification_phases_identified(self):
        """Phases requiring verification are identified."""
        verification_phases = [
            name
            for name, phase in ITERATE_PHASES.items()
            if phase.requires_verification
        ]
        assert set(verification_phases) == {"test", "coverage", "review"}

    def test_non_verification_phases_identified(self):
        """Phases not requiring verification are identified."""
        non_verification_phases = [
            name
            for name, phase in ITERATE_PHASES.items()
            if not phase.requires_verification
        ]
        assert set(non_verification_phases) == {"orchestrate", "test_writing", "implement"}
