# lib/test_audit/decision_engine.py
"""Decision engine for test health scoring."""
import ast
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Set

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


@dataclass
class DecisionResult:
    keeps: Set[str] = field(default_factory=set)
    deletes: Set[str] = field(default_factory=set)
    needs_review: Set[str] = field(default_factory=set)
    scores: Dict[str, HealthScore] = field(default_factory=dict)


def process_decisions(
    tests: List[TestInfo],
    minimum_set: Set[str],
    confidence_threshold: float = 0.75,
) -> DecisionResult:
    """Process all tests and separate by confidence.

    Args:
        tests: List of TestInfo objects
        minimum_set: Set of test names in minimum covering set
        confidence_threshold: Minimum confidence for automatic decision

    Returns:
        DecisionResult with keeps, deletes, and needs_review sets
    """
    result = DecisionResult()

    for test in tests:
        is_in_minimum_set = test.name in minimum_set
        score = score_test_health(test, is_in_minimum_set)
        result.scores[test.name] = score

        if score.verdict == Verdict.REVIEW:
            result.needs_review.add(test.name)
        elif score.confidence >= confidence_threshold:
            if score.verdict == Verdict.KEEP:
                result.keeps.add(test.name)
            elif score.verdict == Verdict.DELETE:
                result.deletes.add(test.name)
        else:
            result.needs_review.add(test.name)

    return result


def delete_tests_from_file(code: str, tests_to_delete: Set[str]) -> str:
    """Remove specified test functions from source code.

    Args:
        code: Source code of the test file
        tests_to_delete: Set of test function names to remove

    Returns:
        Modified source code with tests removed
    """
    tree = ast.parse(code)
    lines = code.splitlines(keepends=True)

    # Find line ranges to delete (in reverse order to preserve indices)
    ranges_to_delete = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in tests_to_delete:
            # Get start and end lines (1-indexed)
            start = node.lineno - 1  # Convert to 0-indexed
            end = node.end_lineno  # Already 1-indexed, use as exclusive end
            ranges_to_delete.append((start, end))
        elif isinstance(node, ast.ClassDef):
            # Also check methods inside test classes
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name in tests_to_delete:
                    start = item.lineno - 1
                    end = item.end_lineno
                    ranges_to_delete.append((start, end))

    # Sort in reverse order so we can delete without affecting earlier indices
    ranges_to_delete.sort(reverse=True)

    for start, end in ranges_to_delete:
        del lines[start:end]
        # Also remove trailing blank lines after deletion point
        while start < len(lines) and lines[start].strip() == "":
            del lines[start]

    return "".join(lines)
