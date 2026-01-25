# lib/test_audit/optimizer.py
"""Calculate optimal test distribution."""
from typing import Dict, List, Set

from lib.test_audit.test_parser import TestInfo


def map_test_coverage(tests: List[TestInfo]) -> Dict[str, Set[str]]:
    """Map each test to the functions it covers."""
    return {test.name: test.targets for test in tests}
