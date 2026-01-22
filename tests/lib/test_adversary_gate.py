# tests/lib/test_adversary_gate.py
"""Tests for adversary gate with confidence scoring."""

import sys
from pathlib import Path

import pytest

# Ensure lib is in path
lib_dir = Path(__file__).parent.parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

from adversary_gate import (
    AdversaryObjection, ConfidenceLevel, ConfidenceScore,
    AdversaryGate, ObjectionResult
)


def test_confidence_score_calculation():
    """Confidence score should aggregate dimensions."""
    score = ConfidenceScore(
        attack_survival=(8, 10),      # 80%
        mutation_survival=(6, 10),    # 60%
        dimension_coverage=(4, 5),    # 80%
        specificity="medium",
        mock_fidelity=(2, 3),         # 2 verified, 1 assumed
        redundant_tests=[],           # No redundant tests flagged
    )

    # Overall should be weighted average
    assert 70 <= score.overall <= 75


def test_redundancy_analysis():
    """Adversary should flag redundant tests."""
    score = ConfidenceScore(
        attack_survival=(8, 10),
        mutation_survival=(6, 10),
        dimension_coverage=(4, 5),
        specificity="medium",
        mock_fidelity=(2, 3),
        redundant_tests=[
            {"test": "test_login_valid", "overlaps_with": "test_login_success", "reason": "same assertions"},
            {"test": "test_returns_token", "overlaps_with": "test_login_success", "reason": "covered by existing"},
        ],
    )

    assert len(score.redundant_tests) == 2
    assert score.has_redundancy is True


def test_adversary_objection_requires_evidence():
    """Objections must cite specific evidence."""
    # Valid objection with evidence
    objection = AdversaryObjection(
        confidence=ConfidenceLevel.HIGH,
        concern="Missing edge case",
        evidence="Function foo() at line 42 doesn't handle None input",
        suggestion="Add test for None input",
    )
    assert objection.is_valid() is True

    # Invalid objection without evidence
    objection = AdversaryObjection(
        confidence=ConfidenceLevel.HIGH,
        concern="I'm not convinced",
        evidence="",
        suggestion="",
    )
    assert objection.is_valid() is False


def test_adversary_gate_override_rules():
    """Override rules should vary by confidence level."""
    gate = AdversaryGate()

    # Low confidence can be overridden with brief rationale
    result = gate.evaluate_objection(
        AdversaryObjection(
            confidence=ConfidenceLevel.LOW,
            concern="Minor style issue",
            evidence="Line 10 uses single quotes",
        ),
        override_rationale="Project uses single quotes consistently"
    )
    assert result.can_proceed is True

    # High confidence requires user appeal
    result = gate.evaluate_objection(
        AdversaryObjection(
            confidence=ConfidenceLevel.HIGH,
            concern="Security vulnerability",
            evidence="SQL injection at line 25",
        ),
        override_rationale="I think it's fine"
    )
    assert result.can_proceed is False
    assert result.requires_user_appeal is True
