# tests/lib/test_check_status.py
"""Tests for post-push verification (CI and review comments)."""

import sys
from pathlib import Path


# Ensure lib is in path
lib_dir = Path(__file__).parent.parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

from check_status import (  # noqa: E402
    CIStatus, check_ci_status, check_review_comments, CheckStatusGate
)


def test_ci_status_check():
    """Should detect CI failures."""
    # Mock successful CI
    result = check_ci_status(pr_number=123, mock_status=CIStatus.PASSING)
    assert result.passed is True

    # Mock failed CI
    result = check_ci_status(pr_number=123, mock_status=CIStatus.FAILED)
    assert result.passed is False
    assert "ci" in result.reason.lower()


def test_review_comments_check():
    """Should detect new review comments."""
    # No new comments
    result = check_review_comments(
        pr_number=123,
        since_push=True,
        mock_comments=[]
    )
    assert result.has_new_comments is False

    # New comments found
    result = check_review_comments(
        pr_number=123,
        since_push=True,
        mock_comments=[{"id": 1, "body": "Please fix this"}]
    )
    assert result.has_new_comments is True


def test_check_status_gate():
    """Gate should combine CI and review checks."""
    gate = CheckStatusGate(pr_number=123)

    # All clear
    result = gate.check(mock_ci=CIStatus.PASSING, mock_comments=[])
    assert result.can_proceed is True

    # CI failed
    result = gate.check(mock_ci=CIStatus.FAILED, mock_comments=[])
    assert result.can_proceed is False
    assert result.kickback_reason is not None
