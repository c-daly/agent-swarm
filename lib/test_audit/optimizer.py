# lib/test_audit/optimizer.py
"""Calculate optimal test distribution."""
from typing import Dict, List, Set

from lib.test_audit.test_parser import TestInfo


def map_test_coverage(tests: List[TestInfo]) -> Dict[str, Set[str]]:
    """Map each test to the functions it covers."""
    return {test.name: test.targets for test in tests}


def find_minimum_covering_set(
    coverage: Dict[str, Set[str]], required: Set[str]
) -> Set[str]:
    """Find minimum set of tests that covers all required functions.

    Uses greedy set cover algorithm: repeatedly pick the test that covers
    the most uncovered functions until all are covered.
    """
    selected: Set[str] = set()
    uncovered = required.copy()

    while uncovered:
        # Find test that covers most uncovered functions
        best_test = None
        best_count = 0

        for test_name, covers in coverage.items():
            if test_name in selected:
                continue
            count = len(covers & uncovered)
            if count > best_count:
                best_count = count
                best_test = test_name

        if best_test is None:
            # No more tests can cover remaining functions
            break

        selected.add(best_test)
        uncovered -= coverage[best_test]

    return selected


def find_coverage_gaps(
    coverage: Dict[str, Set[str]], all_functions: Set[str]
) -> Set[str]:
    """Find functions that have no test coverage.

    Args:
        coverage: Mapping of test names to functions they cover
        all_functions: Set of all functions that should be tested

    Returns:
        Set of function names with no test coverage
    """
    covered: Set[str] = set()
    for functions in coverage.values():
        covered |= functions
    return all_functions - covered
