"""Post-push verification for workflows.

Checks CI status and review comments after pushing changes.
Used by debug, PR comment, and iterate workflows.
"""

import subprocess
import json
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class CIStatus(Enum):
    """CI pipeline status."""
    PASSING = auto()
    FAILED = auto()
    PENDING = auto()
    UNKNOWN = auto()


@dataclass
class CICheckResult:
    """Result of CI status check."""
    passed: bool
    status: CIStatus
    reason: str = ""
    details: Optional[dict] = None


@dataclass
class ReviewCheckResult:
    """Result of review comments check."""
    has_new_comments: bool
    comments: Optional[list] = None
    reason: str = ""


@dataclass
class CheckStatusResult:
    """Combined status check result."""
    can_proceed: bool
    ci_result: Optional[CICheckResult] = None
    review_result: Optional[ReviewCheckResult] = None
    kickback_reason: Optional[str] = None


def check_ci_status(
    pr_number: int,
    mock_status: Optional[CIStatus] = None
) -> CICheckResult:
    """Check CI status for a PR.

    Args:
        pr_number: GitHub PR number
        mock_status: For testing, override actual check
    """
    if mock_status is not None:
        return CICheckResult(
            passed=mock_status == CIStatus.PASSING,
            status=mock_status,
            reason="" if mock_status == CIStatus.PASSING else "CI checks failed"
        )

    try:
        result = subprocess.run(
            ["gh", "pr", "checks", str(pr_number), "--json", "state,name"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            return CICheckResult(
                passed=False,
                status=CIStatus.UNKNOWN,
                reason=f"Failed to get CI status: {result.stderr}"
            )

        checks = json.loads(result.stdout)
        failed = [c for c in checks if c.get("state") == "FAILURE"]
        pending = [c for c in checks if c.get("state") == "PENDING"]

        if failed:
            return CICheckResult(
                passed=False,
                status=CIStatus.FAILED,
                reason=f"CI failed: {', '.join(c['name'] for c in failed)}",
                details={"failed_checks": failed}
            )

        if pending:
            return CICheckResult(
                passed=False,
                status=CIStatus.PENDING,
                reason=f"CI pending: {', '.join(c['name'] for c in pending)}"
            )

        return CICheckResult(passed=True, status=CIStatus.PASSING)

    except Exception as e:
        return CICheckResult(
            passed=False,
            status=CIStatus.UNKNOWN,
            reason=f"Error checking CI: {e}"
        )


def check_review_comments(
    pr_number: int,
    since_push: bool = True,
    mock_comments: Optional[list] = None
) -> ReviewCheckResult:
    """Check for new review comments on a PR.

    Args:
        pr_number: GitHub PR number
        since_push: Only check comments since last push
        mock_comments: For testing, override actual check
    """
    if mock_comments is not None:
        return ReviewCheckResult(
            has_new_comments=len(mock_comments) > 0,
            comments=mock_comments,
            reason="" if not mock_comments else f"{len(mock_comments)} new comment(s)"
        )

    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--json", "reviews,comments"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            return ReviewCheckResult(
                has_new_comments=False,
                reason=f"Failed to get comments: {result.stderr}"
            )

        data = json.loads(result.stdout)
        # Extract unresolved comments
        comments = []
        for review in data.get("reviews", []):
            for comment in review.get("comments", []):
                if not comment.get("isResolved", False):
                    comments.append(comment)

        return ReviewCheckResult(
            has_new_comments=len(comments) > 0,
            comments=comments,
            reason=f"{len(comments)} unresolved comment(s)" if comments else ""
        )

    except Exception as e:
        return ReviewCheckResult(
            has_new_comments=False,
            reason=f"Error checking comments: {e}"
        )


class CheckStatusGate:
    """Gate that checks CI and review status before proceeding."""

    def __init__(self, pr_number: int):
        self.pr_number = pr_number

    def check(
        self,
        mock_ci: Optional[CIStatus] = None,
        mock_comments: Optional[list] = None
    ) -> CheckStatusResult:
        """Run all status checks.

        Returns CheckStatusResult with can_proceed=True only if
        CI passes AND no new review comments.
        """
        ci_result = check_ci_status(self.pr_number, mock_status=mock_ci)
        review_result = check_review_comments(self.pr_number, mock_comments=mock_comments)

        can_proceed = ci_result.passed and not review_result.has_new_comments
        kickback_reason = None

        if not ci_result.passed:
            kickback_reason = f"CI: {ci_result.reason}"
        elif review_result.has_new_comments:
            kickback_reason = f"Reviews: {review_result.reason}"

        return CheckStatusResult(
            can_proceed=can_proceed,
            ci_result=ci_result,
            review_result=review_result,
            kickback_reason=kickback_reason
        )
