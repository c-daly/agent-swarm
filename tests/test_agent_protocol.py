"""Tests for agent protocol specifications."""

from lib.agent_protocol import (
    get_protocol,
    validate_agent_spawn,
)
from lib.phase_model import ToolCategory


class TestProtocolLookups:
    """Test protocol retrieval."""

    def test_get_explorer_protocol(self):
        """Explorer protocol should be retrievable."""
        protocol = get_protocol("explorer")
        assert protocol is not None
        assert protocol.name == "explorer"
        assert protocol.model == "haiku"

    def test_get_implementer_protocol(self):
        """Implementer protocol should be retrievable."""
        protocol = get_protocol("implementer")
        assert protocol is not None
        assert protocol.name == "implementer"
        assert protocol.model == "sonnet"

    def test_get_reviewer_protocol(self):
        """Reviewer protocol should be retrievable."""
        protocol = get_protocol("reviewer")
        assert protocol is not None
        assert protocol.name == "reviewer"
        assert protocol.model == "sonnet"

    def test_get_architect_protocol(self):
        """Architect protocol should be retrievable."""
        protocol = get_protocol("architect")
        assert protocol is not None
        assert protocol.name == "architect"
        assert protocol.model == "opus"

    def test_get_debugger_protocol(self):
        """Debugger protocol should be retrievable."""
        protocol = get_protocol("debugger")
        assert protocol is not None
        assert protocol.name == "debugger"
        assert protocol.model == "sonnet"

    def test_case_insensitive_lookup(self):
        """Protocol lookup should be case insensitive."""
        assert get_protocol("EXPLORER") == get_protocol("explorer")
        assert get_protocol("Implementer") == get_protocol("implementer")

    def test_unknown_agent_returns_none(self):
        """Unknown agent type should return None."""
        assert get_protocol("unknown") is None
        assert get_protocol("custom_agent") is None


class TestProtocolConstraints:
    """Test protocol constraint definitions."""

    def test_explorer_cannot_write(self):
        """Explorer should not be able to write files."""
        protocol = get_protocol("explorer")
        assert not protocol.can_write_files
        assert "Edit" in protocol.blocked_tools
        assert "Write" in protocol.blocked_tools

    def test_implementer_can_write(self):
        """Implementer should be able to write files."""
        protocol = get_protocol("implementer")
        assert protocol.can_write_files
        assert ToolCategory.FILE_WRITE in protocol.allowed_tool_categories

    def test_reviewer_cannot_write(self):
        """Reviewer should not be able to write files."""
        protocol = get_protocol("reviewer")
        assert not protocol.can_write_files
        assert "Edit" in protocol.blocked_tools

    def test_explorer_allowed_in_all_phases(self):
        """Explorer should be allowed in all phases."""
        protocol = get_protocol("explorer")
        assert len(protocol.allowed_phases) == 0  # Empty = all phases

    def test_implementer_phase_restrictions(self):
        """Implementer should be restricted to specific phases."""
        protocol = get_protocol("implementer")
        assert "implement" in protocol.allowed_phases
        assert "test_writing" in protocol.allowed_phases
        assert "review" not in protocol.allowed_phases

    def test_reviewer_phase_restrictions(self):
        """Reviewer should be restricted to review/coverage phases."""
        protocol = get_protocol("reviewer")
        assert "review" in protocol.allowed_phases
        assert "coverage" in protocol.allowed_phases
        assert "implement" not in protocol.allowed_phases


class TestModelValidation:
    """Test model validation in spawn requests."""

    def test_valid_explorer_model(self):
        """Explorer with haiku model should be valid."""
        valid, msg = validate_agent_spawn("explorer", "haiku", "implement")
        assert valid
        assert msg == "OK"

    def test_invalid_explorer_model(self):
        """Explorer with wrong model should be rejected."""
        valid, msg = validate_agent_spawn("explorer", "sonnet", "implement")
        assert not valid
        assert "haiku" in msg
        assert "sonnet" in msg

    def test_valid_implementer_model(self):
        """Implementer with sonnet model should be valid."""
        valid, msg = validate_agent_spawn("implementer", "sonnet", "implement")
        assert valid
        assert msg == "OK"

    def test_invalid_implementer_model(self):
        """Implementer with wrong model should be rejected."""
        valid, msg = validate_agent_spawn("implementer", "haiku", "implement")
        assert not valid
        assert "sonnet" in msg

    def test_architect_requires_opus(self):
        """Architect should require opus model."""
        valid, msg = validate_agent_spawn("architect", "sonnet", "design")
        assert not valid
        assert "opus" in msg


class TestPhaseValidation:
    """Test phase validation in spawn requests."""

    def test_implementer_valid_in_implement_phase(self):
        """Implementer should be valid in implement phase."""
        valid, msg = validate_agent_spawn("implementer", "sonnet", "implement")
        assert valid
        assert msg == "OK"

    def test_implementer_valid_in_test_writing_phase(self):
        """Implementer should be valid in test_writing phase."""
        valid, msg = validate_agent_spawn("implementer", "sonnet", "test_writing")
        assert valid
        assert msg == "OK"

    def test_implementer_invalid_in_review_phase(self):
        """Implementer should not be allowed in review phase."""
        valid, msg = validate_agent_spawn("implementer", "sonnet", "review")
        assert not valid
        assert "review" in msg

    def test_reviewer_valid_in_review_phase(self):
        """Reviewer should be valid in review phase."""
        valid, msg = validate_agent_spawn("reviewer", "sonnet", "review")
        assert valid
        assert msg == "OK"

    def test_reviewer_invalid_in_implement_phase(self):
        """Reviewer should not be allowed in implement phase."""
        valid, msg = validate_agent_spawn("reviewer", "sonnet", "implement")
        assert not valid
        assert "implement" in msg

    def test_explorer_valid_in_any_phase(self):
        """Explorer should be valid in any phase."""
        phases = ["test_writing", "implement", "test", "coverage", "review"]
        for phase in phases:
            valid, msg = validate_agent_spawn("explorer", "haiku", phase)
            assert valid, f"Explorer should be valid in {phase}"


class TestUnknownAgentHandling:
    """Test handling of unknown agent types."""

    def test_unknown_agent_allowed_any_model(self):
        """Unknown agent should be allowed with any model."""
        valid, msg = validate_agent_spawn("custom", "haiku", "implement")
        assert valid
        assert msg == "OK"

    def test_unknown_agent_allowed_any_phase(self):
        """Unknown agent should be allowed in any phase."""
        valid, msg = validate_agent_spawn("custom", "sonnet", "custom_phase")
        assert valid
        assert msg == "OK"

    def test_case_insensitive_validation(self):
        """Validation should be case insensitive."""
        valid1, _ = validate_agent_spawn("EXPLORER", "haiku", "implement")
        valid2, _ = validate_agent_spawn("explorer", "haiku", "implement")
        assert valid1 == valid2


class TestOutputLimits:
    """Test output character limits."""

    def test_explorer_has_smallest_limit(self):
        """Explorer should have the smallest output limit."""
        explorer = get_protocol("explorer")
        assert explorer.max_output_chars == 1500

    def test_implementer_output_limit(self):
        """Implementer should have standard output limit."""
        implementer = get_protocol("implementer")
        assert implementer.max_output_chars == 1500

    def test_architect_has_largest_limit(self):
        """Architect should have the largest output limit."""
        architect = get_protocol("architect")
        assert architect.max_output_chars == 3000

    def test_reviewer_output_limit(self):
        """Reviewer should have larger output limit for detailed feedback."""
        reviewer = get_protocol("reviewer")
        assert reviewer.max_output_chars == 2000
