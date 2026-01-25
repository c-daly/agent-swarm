# lib/test_audit/decision_engine.py
"""Decision engine for test health scoring."""
from dataclasses import dataclass
from enum import Enum

from lib.test_audit.test_parser import TestInfo


class Verdict(Enum):
    KEEP = "keep"
    DELETE = "delete"
    REVIEW = "review"


@dataclass
class HealthScore:
    verdict: Verdict
    confidence: float  # 0.0 to 1.0
    reason: str


def score_test_health(test: TestInfo, is_in_minimum_set: bool) -> HealthScore:
    """Score a test's health and return a verdict.

    Args:
        test: TestInfo with assertions, mocks, targets
        is_in_minimum_set: Whether this test is needed for coverage

    Returns:
        HealthScore with verdict, confidence, and reason
    """
    # No assertions = definitely delete
    if test.assertions == 0:
        return HealthScore(
            verdict=Verdict.DELETE,
            confidence=0.95,
            reason="No assertions - test never checks anything",
        )

    # Too many mocks = review needed
    if test.mocks >= 4:
        return HealthScore(
            verdict=Verdict.REVIEW,
            confidence=0.7,
            reason=f"Excessive mocks ({test.mocks}) - may be testing implementation not behavior",
        )

    # Not in minimum set = redundant
    if not is_in_minimum_set:
        return HealthScore(
            verdict=Verdict.DELETE,
            confidence=0.8,
            reason="Redundant - coverage provided by other tests",
        )

    # Healthy test - keep it
    confidence = min(0.9, 0.7 + (test.assertions * 0.05))
    return HealthScore(
        verdict=Verdict.KEEP,
        confidence=confidence,
        reason=f"Covers {len(test.targets)} function(s) with {test.assertions} assertion(s)",
    )
