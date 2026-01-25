# tests/test_audit/test_decision_engine.py
from lib.test_audit.decision_engine import (
    Verdict,
    process_decisions,
    score_test_health,
)
from lib.test_audit.test_parser import TestInfo


def test_score_healthy_test_keeps():
    """Healthy test with assertions covering important code should keep."""
    test = TestInfo(
        name="test_process",
        file_path="test_module.py",
        line_number=10,
        targets={"process", "validate"},
        assertions=3,
        mocks=0,
    )

    score = score_test_health(test, is_in_minimum_set=True)

    assert score.verdict == Verdict.KEEP
    assert score.confidence >= 0.8
    assert "covers" in score.reason.lower() or "assertion" in score.reason.lower()


def test_score_no_assertions_deletes():
    """Test with no assertions should be flagged for deletion."""
    test = TestInfo(
        name="test_no_check",
        file_path="test_module.py",
        line_number=20,
        targets={"process"},
        assertions=0,
        mocks=0,
    )

    score = score_test_health(test, is_in_minimum_set=False)

    assert score.verdict == Verdict.DELETE
    assert "assertion" in score.reason.lower()


def test_score_excessive_mocks_reviews():
    """Test with too many mocks should be flagged for review."""
    test = TestInfo(
        name="test_mock_heavy",
        file_path="test_module.py",
        line_number=30,
        targets={"process"},
        assertions=2,
        mocks=5,
    )

    score = score_test_health(test, is_in_minimum_set=True)

    assert score.verdict == Verdict.REVIEW
    assert "mock" in score.reason.lower()


def test_score_redundant_test_deletes():
    """Test not in minimum covering set should be deleted."""
    test = TestInfo(
        name="test_redundant",
        file_path="test_module.py",
        line_number=40,
        targets={"process"},
        assertions=2,
        mocks=0,
    )

    score = score_test_health(test, is_in_minimum_set=False)

    assert score.verdict == Verdict.DELETE
    assert "redundant" in score.reason.lower() or "cover" in score.reason.lower()


def test_process_decisions_separates_by_confidence():
    """Separate tests into confident keeps, deletes, and needs review."""
    tests = [
        TestInfo(
            name="test_healthy",
            file_path="test_a.py",
            line_number=1,
            targets={"process"},
            assertions=3,
            mocks=0,
        ),
        TestInfo(
            name="test_no_assert",
            file_path="test_b.py",
            line_number=1,
            targets={"transform"},
            assertions=0,
            mocks=0,
        ),
        TestInfo(
            name="test_mock_heavy",
            file_path="test_c.py",
            line_number=1,
            targets={"validate"},
            assertions=2,
            mocks=5,
        ),
    ]
    minimum_set = {"test_healthy", "test_mock_heavy"}

    result = process_decisions(tests, minimum_set, confidence_threshold=0.75)

    assert "test_healthy" in result.keeps
    assert "test_no_assert" in result.deletes
    assert "test_mock_heavy" in result.needs_review
