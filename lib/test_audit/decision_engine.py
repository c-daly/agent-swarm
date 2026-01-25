# lib/test_audit/decision_engine.py
"""Decision engine for test health scoring."""
import ast
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set

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


@dataclass
class CoverageInfo:
    """Coverage information for a test from actual pytest coverage data."""
    is_in_minimum_set: bool
    is_truly_redundant: bool  # All lines covered by minimum set
    unique_lines: int  # Lines only this test covers


def score_test_health(
    test: TestInfo,
    is_in_minimum_set: bool,
    coverage_info: Optional[CoverageInfo] = None,
) -> HealthScore:
    """Score a test's health and return a verdict.

    Args:
        test: TestInfo with assertions, mocks, targets
        is_in_minimum_set: Whether this test is needed for coverage (static analysis)
        coverage_info: Optional coverage data from actual pytest run

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

    # Use coverage-based analysis if available (more accurate)
    if coverage_info is not None:
        if coverage_info.is_in_minimum_set:
            confidence = min(0.95, 0.8 + (test.assertions * 0.03))
            return HealthScore(
                verdict=Verdict.KEEP,
                confidence=confidence,
                reason=f"In minimum coverage set with {test.assertions} assertion(s)",
            )
        elif coverage_info.is_truly_redundant:
            return HealthScore(
                verdict=Verdict.DELETE,
                confidence=0.9,  # High confidence - actual coverage data
                reason="Truly redundant - all lines covered by other tests",
            )
        else:
            # Not in minimum set but adds unique coverage
            return HealthScore(
                verdict=Verdict.KEEP,
                confidence=0.85,
                reason=f"Adds {coverage_info.unique_lines} unique line(s) of coverage",
            )

    # Fall back to static analysis (less accurate)
    if not is_in_minimum_set:
        return HealthScore(
            verdict=Verdict.DELETE,
            confidence=0.6,  # Lower confidence for static analysis
            reason="Redundant (static analysis) - coverage may be provided by other tests",
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
    coverage_data: Optional[Dict[str, CoverageInfo]] = None,
) -> DecisionResult:
    """Process all tests and separate by confidence.

    Args:
        tests: List of TestInfo objects
        minimum_set: Set of test names in minimum covering set (static analysis)
        confidence_threshold: Minimum confidence for automatic decision
        coverage_data: Optional dict of test_name -> CoverageInfo from actual coverage

    Returns:
        DecisionResult with keeps, deletes, and needs_review sets
    """
    result = DecisionResult()

    for test in tests:
        is_in_minimum_set = test.name in minimum_set
        coverage_info = coverage_data.get(test.name) if coverage_data else None
        score = score_test_health(test, is_in_minimum_set, coverage_info)
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
            # Check if ALL test methods in the class are being deleted
            test_methods = [
                item for item in node.body
                if isinstance(item, ast.FunctionDef) and item.name.startswith("test_")
            ]
            methods_to_delete = [m for m in test_methods if m.name in tests_to_delete]

            if test_methods and len(methods_to_delete) == len(test_methods):
                # All test methods deleted - remove entire class
                start = node.lineno - 1
                end = node.end_lineno
                ranges_to_delete.append((start, end))
            else:
                # Only delete individual methods
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
