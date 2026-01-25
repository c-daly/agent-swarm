# tests/test_audit/test_optimizer.py
from lib.test_audit.optimizer import map_test_coverage
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
