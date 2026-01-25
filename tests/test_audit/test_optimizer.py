# tests/test_audit/test_optimizer.py
from lib.test_audit.optimizer import find_minimum_covering_set, map_test_coverage
from lib.test_audit.test_parser import TestInfo


def test_map_test_coverage():
    """Map which functions each test covers."""
    tests = [
        TestInfo(
            name="test_process",
            file_path="test_a.py",
            line_number=1,
            targets={"process", "validate"},
        ),
        TestInfo(
            name="test_transform",
            file_path="test_a.py",
            line_number=10,
            targets={"transform"},
        ),
    ]

    coverage = map_test_coverage(tests)

    assert coverage["test_process"] == {"process", "validate"}
    assert coverage["test_transform"] == {"transform"}


def test_find_minimum_covering_set():
    """Find smallest test set that covers all required functions."""
    # test_a covers: process, validate
    # test_b covers: transform, validate
    # test_c covers: process
    # Minimum set to cover {process, validate, transform} is {test_a, test_b}
    coverage = {
        "test_a": {"process", "validate"},
        "test_b": {"transform", "validate"},
        "test_c": {"process"},
    }
    required = {"process", "validate", "transform"}

    result = find_minimum_covering_set(coverage, required)

    # Should pick test_a (covers 2) and test_b (covers remaining 1)
    assert result == {"test_a", "test_b"}
