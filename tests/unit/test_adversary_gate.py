"""Unit tests for adversary_gate module."""

import pytest

from lib.adversary_gate import (
    AdversaryGate,
    AdversaryObjection,
    ConfidenceLevel,
    ConfidenceScore,
    ObjectionResult,
)


class TestConfidenceScore:
    """Tests for ConfidenceScore dataclass."""

    def test_overall_perfect_score(self):
        """Perfect scores across all dimensions yield 100%."""
        score = ConfidenceScore(
            attack_survival=(10, 10),
            mutation_survival=(10, 10),
            dimension_coverage=(10, 10),
            specificity="high",
            mock_fidelity=(5, 5),
        )
        assert score.overall == 100.0

    def test_overall_zero_score(self):
        """Zero scores across all dimensions yield 0%."""
        score = ConfidenceScore(
            attack_survival=(0, 10),
            mutation_survival=(0, 10),
            dimension_coverage=(0, 10),
            specificity="low",
            mock_fidelity=(0, 5),
        )
        # low specificity = 40%, all others 0
        # 0*0.30 + 0*0.25 + 0*0.25 + 40*0.10 + 0*0.10 = 4.0
        assert score.overall == 4.0

    def test_overall_weighted_calculation(self):
        """Verify weights are applied correctly."""
        score = ConfidenceScore(
            attack_survival=(5, 10),      # 50% * 0.30 = 15
            mutation_survival=(8, 10),    # 80% * 0.25 = 20
            dimension_coverage=(6, 10),   # 60% * 0.25 = 15
            specificity="medium",          # 70% * 0.10 = 7
            mock_fidelity=(4, 5),          # 80% * 0.10 = 8
        )
        expected = 15 + 20 + 15 + 7 + 8  # = 65
        assert score.overall == expected

    def test_overall_handles_zero_total(self):
        """Division by zero is handled gracefully."""
        score = ConfidenceScore(
            attack_survival=(0, 0),
            mutation_survival=(0, 0),
            dimension_coverage=(0, 0),
            specificity="high",
            mock_fidelity=(0, 0),  # 0/0 defaults to 100%
        )
        # 0*0.30 + 0*0.25 + 0*0.25 + 100*0.10 + 100*0.10 = 20
        assert score.overall == 20.0

    def test_overall_unknown_specificity_defaults_to_50(self):
        """Unknown specificity value defaults to 50%."""
        score = ConfidenceScore(
            attack_survival=(10, 10),
            mutation_survival=(10, 10),
            dimension_coverage=(10, 10),
            specificity="unknown",
            mock_fidelity=(5, 5),
        )
        # 100*0.30 + 100*0.25 + 100*0.25 + 50*0.10 + 100*0.10 = 95
        assert score.overall == 95.0

    def test_has_redundancy_false_when_empty(self):
        """has_redundancy is False when no redundant tests."""
        score = ConfidenceScore(
            attack_survival=(10, 10),
            mutation_survival=(10, 10),
            dimension_coverage=(10, 10),
            specificity="high",
            mock_fidelity=(5, 5),
            redundant_tests=[],
        )
        assert score.has_redundancy is False

    def test_has_redundancy_true_when_populated(self):
        """has_redundancy is True when redundant tests exist."""
        score = ConfidenceScore(
            attack_survival=(10, 10),
            mutation_survival=(10, 10),
            dimension_coverage=(10, 10),
            specificity="high",
            mock_fidelity=(5, 5),
            redundant_tests=[{"test": "test_a", "overlaps_with": "test_b"}],
        )
        assert score.has_redundancy is True

    def test_format_report_contains_key_metrics(self):
        """Format report includes all key metrics."""
        score = ConfidenceScore(
            attack_survival=(8, 10),
            mutation_survival=(7, 10),
            dimension_coverage=(9, 10),
            specificity="high",
            mock_fidelity=(4, 5),
        )
        report = score.format_report()
        assert "Test Confidence:" in report
        assert "Attack survival" in report
        assert "8/10" in report
        assert "Mutation survival" in report
        assert "Dimension coverage" in report
        assert "Specificity" in report
        assert "high" in report
        assert "Mock fidelity" in report

    def test_format_report_with_redundant_tests(self):
        """Format report includes redundant tests when present."""
        score = ConfidenceScore(
            attack_survival=(10, 10),
            mutation_survival=(10, 10),
            dimension_coverage=(10, 10),
            specificity="high",
            mock_fidelity=(5, 5),
            redundant_tests=[
                {"test": "test_foo", "overlaps_with": "test_bar"},
            ],
        )
        report = score.format_report()
        assert "Redundancy:" in report
        assert "1 flagged" in report
        assert "test_foo" in report
        assert "overlaps with test_bar" in report


class TestAdversaryObjection:
    """Tests for AdversaryObjection dataclass."""

    def test_is_valid_with_sufficient_evidence(self):
        """Objection is valid with evidence > 10 chars."""
        objection = AdversaryObjection(
            confidence=ConfidenceLevel.HIGH,
            concern="Tests are weak",
            evidence="No edge cases covered for boundary conditions",
        )
        assert objection.is_valid() is True

    def test_is_valid_with_empty_evidence(self):
        """Objection is invalid with empty evidence."""
        objection = AdversaryObjection(
            confidence=ConfidenceLevel.HIGH,
            concern="Tests are weak",
            evidence="",
        )
        assert objection.is_valid() is False

    def test_is_valid_with_short_evidence(self):
        """Objection is invalid with evidence <= 10 chars."""
        objection = AdversaryObjection(
            confidence=ConfidenceLevel.HIGH,
            concern="Tests are weak",
            evidence="short",  # 5 chars
        )
        assert objection.is_valid() is False

    def test_is_valid_boundary_exactly_10_chars(self):
        """Objection with exactly 10 chars is invalid."""
        objection = AdversaryObjection(
            confidence=ConfidenceLevel.LOW,
            concern="Minor issue",
            evidence="1234567890",  # Exactly 10 chars
        )
        assert objection.is_valid() is False

    def test_is_valid_boundary_11_chars(self):
        """Objection with 11 chars is valid."""
        objection = AdversaryObjection(
            confidence=ConfidenceLevel.LOW,
            concern="Minor issue",
            evidence="12345678901",  # 11 chars
        )
        assert objection.is_valid() is True


class TestObjectionResult:
    """Tests for ObjectionResult dataclass."""

    def test_defaults(self):
        """ObjectionResult has sensible defaults."""
        result = ObjectionResult(can_proceed=True)
        assert result.can_proceed is True
        assert result.requires_user_appeal is False
        assert result.message == ""

    def test_all_fields(self):
        """ObjectionResult stores all fields correctly."""
        result = ObjectionResult(
            can_proceed=False,
            requires_user_appeal=True,
            message="Need user approval",
        )
        assert result.can_proceed is False
        assert result.requires_user_appeal is True
        assert result.message == "Need user approval"


class TestAdversaryGate:
    """Tests for AdversaryGate class."""

    def test_init_default_threshold(self):
        """Default confidence threshold is 70%."""
        gate = AdversaryGate()
        assert gate.confidence_threshold == 70.0
        assert gate.user_overrides == 0

    def test_init_custom_threshold(self):
        """Custom confidence threshold is respected."""
        gate = AdversaryGate(confidence_threshold=85.0)
        assert gate.confidence_threshold == 85.0

    # --- evaluate_objection tests ---

    def test_evaluate_invalid_objection_proceeds(self):
        """Invalid objection (no evidence) allows proceeding."""
        gate = AdversaryGate()
        objection = AdversaryObjection(
            confidence=ConfidenceLevel.HIGH,
            concern="Something bad",
            evidence="",  # No evidence
        )
        result = gate.evaluate_objection(objection)
        assert result.can_proceed is True
        assert "lacks evidence" in result.message

    def test_evaluate_user_approved_always_proceeds(self):
        """User approval overrides any objection."""
        gate = AdversaryGate()
        objection = AdversaryObjection(
            confidence=ConfidenceLevel.HIGH,
            concern="Critical issue",
            evidence="This is detailed evidence about the issue",
        )
        result = gate.evaluate_objection(objection, user_approved=True)
        assert result.can_proceed is True
        assert "User approved" in result.message
        assert gate.user_overrides == 1

    def test_evaluate_user_approved_increments_counter(self):
        """User overrides counter increments with each approval."""
        gate = AdversaryGate()
        objection = AdversaryObjection(
            confidence=ConfidenceLevel.HIGH,
            concern="Issue",
            evidence="Sufficient evidence here",
        )
        gate.evaluate_objection(objection, user_approved=True)
        gate.evaluate_objection(objection, user_approved=True)
        assert gate.user_overrides == 2

    def test_evaluate_low_confidence_with_rationale_proceeds(self):
        """Low confidence objection can be overridden with any rationale."""
        gate = AdversaryGate()
        objection = AdversaryObjection(
            confidence=ConfidenceLevel.LOW,
            concern="Minor concern",
            evidence="Some evidence here",
        )
        result = gate.evaluate_objection(objection, override_rationale="Acknowledged")
        assert result.can_proceed is True
        assert "Low confidence overridden" in result.message

    def test_evaluate_low_confidence_without_rationale_blocks(self):
        """Low confidence objection blocks without rationale."""
        gate = AdversaryGate()
        objection = AdversaryObjection(
            confidence=ConfidenceLevel.LOW,
            concern="Minor concern",
            evidence="Some evidence here",
        )
        result = gate.evaluate_objection(objection)
        assert result.can_proceed is False
        assert "brief rationale" in result.message

    def test_evaluate_medium_confidence_with_long_rationale_proceeds(self):
        """Medium confidence can be overridden with detailed rationale (>20 chars)."""
        gate = AdversaryGate()
        objection = AdversaryObjection(
            confidence=ConfidenceLevel.MEDIUM,
            concern="Moderate concern",
            evidence="Detailed evidence here",
        )
        result = gate.evaluate_objection(
            objection,
            override_rationale="This is a detailed justification for why we can proceed"
        )
        assert result.can_proceed is True
        assert "Medium confidence overridden" in result.message

    def test_evaluate_medium_confidence_with_short_rationale_blocks(self):
        """Medium confidence blocks with short rationale (<=20 chars)."""
        gate = AdversaryGate()
        objection = AdversaryObjection(
            confidence=ConfidenceLevel.MEDIUM,
            concern="Moderate concern",
            evidence="Detailed evidence here",
        )
        result = gate.evaluate_objection(
            objection,
            override_rationale="Too short"  # < 20 chars
        )
        assert result.can_proceed is False
        assert result.requires_user_appeal is True

    def test_evaluate_medium_confidence_boundary_20_chars(self):
        """Medium confidence with exactly 20 char rationale blocks."""
        gate = AdversaryGate()
        objection = AdversaryObjection(
            confidence=ConfidenceLevel.MEDIUM,
            concern="Concern",
            evidence="Valid evidence here",
        )
        result = gate.evaluate_objection(
            objection,
            override_rationale="12345678901234567890"  # Exactly 20 chars
        )
        assert result.can_proceed is False

    def test_evaluate_medium_confidence_boundary_21_chars(self):
        """Medium confidence with 21 char rationale proceeds."""
        gate = AdversaryGate()
        objection = AdversaryObjection(
            confidence=ConfidenceLevel.MEDIUM,
            concern="Concern",
            evidence="Valid evidence here",
        )
        result = gate.evaluate_objection(
            objection,
            override_rationale="123456789012345678901"  # 21 chars
        )
        assert result.can_proceed is True

    def test_evaluate_high_confidence_always_blocks(self):
        """High confidence objection always blocks without user approval."""
        gate = AdversaryGate()
        objection = AdversaryObjection(
            confidence=ConfidenceLevel.HIGH,
            concern="Critical issue",
            evidence="This is detailed evidence about the critical issue",
        )
        result = gate.evaluate_objection(
            objection,
            override_rationale="Even a very long rationale will not help here"
        )
        assert result.can_proceed is False
        assert result.requires_user_appeal is True
        assert "High-confidence" in result.message

    def test_evaluate_high_confidence_user_appeal_required(self):
        """High confidence objection requires user appeal."""
        gate = AdversaryGate()
        objection = AdversaryObjection(
            confidence=ConfidenceLevel.HIGH,
            concern="Critical",
            evidence="Evidence provided here",
        )
        result = gate.evaluate_objection(objection)
        assert result.requires_user_appeal is True

    # --- check_confidence_threshold tests ---

    def test_check_threshold_passes_at_threshold(self):
        """Score exactly at threshold passes."""
        gate = AdversaryGate(confidence_threshold=70.0)
        score = ConfidenceScore(
            attack_survival=(7, 10),       # 70% * 0.30 = 21
            mutation_survival=(7, 10),     # 70% * 0.25 = 17.5
            dimension_coverage=(7, 10),    # 70% * 0.25 = 17.5
            specificity="medium",          # 70% * 0.10 = 7
            mock_fidelity=(7, 10),         # 70% * 0.10 = 7
        )
        # Total: 21 + 17.5 + 17.5 + 7 + 7 = 70
        result = gate.check_confidence_threshold(score)
        assert result.can_proceed is True

    def test_check_threshold_passes_above_threshold(self):
        """Score above threshold passes."""
        gate = AdversaryGate(confidence_threshold=70.0)
        score = ConfidenceScore(
            attack_survival=(10, 10),
            mutation_survival=(10, 10),
            dimension_coverage=(10, 10),
            specificity="high",
            mock_fidelity=(5, 5),
        )
        result = gate.check_confidence_threshold(score)
        assert result.can_proceed is True
        assert "meets threshold" in result.message

    def test_check_threshold_fails_below_threshold(self):
        """Score below threshold fails."""
        gate = AdversaryGate(confidence_threshold=70.0)
        score = ConfidenceScore(
            attack_survival=(5, 10),
            mutation_survival=(5, 10),
            dimension_coverage=(5, 10),
            specificity="low",
            mock_fidelity=(2, 5),
        )
        result = gate.check_confidence_threshold(score)
        assert result.can_proceed is False
        assert "below threshold" in result.message

    def test_check_threshold_message_includes_score(self):
        """Threshold check message includes actual score."""
        gate = AdversaryGate(confidence_threshold=80.0)
        score = ConfidenceScore(
            attack_survival=(6, 10),
            mutation_survival=(6, 10),
            dimension_coverage=(6, 10),
            specificity="medium",
            mock_fidelity=(3, 5),
        )
        result = gate.check_confidence_threshold(score)
        # Score calculation: 18 + 15 + 15 + 7 + 6 = 61
        assert "61%" in result.message or "61 %" in result.message


class TestConfidenceLevel:
    """Tests for ConfidenceLevel enum."""

    def test_enum_values_exist(self):
        """All expected confidence levels exist."""
        assert ConfidenceLevel.LOW
        assert ConfidenceLevel.MEDIUM
        assert ConfidenceLevel.HIGH

    def test_enum_values_are_distinct(self):
        """Confidence levels are distinct values."""
        assert ConfidenceLevel.LOW != ConfidenceLevel.MEDIUM
        assert ConfidenceLevel.MEDIUM != ConfidenceLevel.HIGH
        assert ConfidenceLevel.LOW != ConfidenceLevel.HIGH
