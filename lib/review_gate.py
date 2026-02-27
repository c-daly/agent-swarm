"""Review gate module to prevent acting on stale Greptile reviews.

This module tracks push SHAs and review SHAs to ensure reviews are only acted
upon when they correspond to the current pushed state.

Uses DaemonClient for in-memory state via MCP router.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

lib_dir = Path(__file__).parent
if str(lib_dir) not in sys.path:
    sys.path.insert(0, str(lib_dir))

from daemon_client import DaemonClient  # noqa: E402


@dataclass(frozen=True)
class ReviewState:
    """State tracking for review gate."""
    last_pushed_sha: Optional[str] = None
    last_reviewed_sha: Optional[str] = None
    review_pending: bool = False


def load_review_state() -> ReviewState:
    """Load review state from workflow server."""
    with DaemonClient() as dc:
        data = dc.workflow_get_state("review_gate")
    if not data:
        return ReviewState()

    return ReviewState(
        last_pushed_sha=data.get("last_pushed_sha"),
        last_reviewed_sha=data.get("last_reviewed_sha"),
        review_pending=data.get("review_pending", False)
    )


def save_review_state(state: ReviewState) -> None:
    """Save review state to workflow server via granular set_value calls."""
    with DaemonClient() as dc:
        dc.workflow_set_value("review_gate", "last_pushed_sha", state.last_pushed_sha)
        dc.workflow_set_value("review_gate", "last_reviewed_sha", state.last_reviewed_sha)
        dc.workflow_set_value("review_gate", "review_pending", state.review_pending)


def on_push(sha: str) -> None:
    """Record push, set pending flag."""
    with DaemonClient() as dc:
        dc.workflow_set_value("review_gate", "last_pushed_sha", sha)
        dc.workflow_set_value("review_gate", "review_pending", True)


def check_review_allowed() -> tuple[bool, str]:
    """Check if review checks are allowed."""
    state = load_review_state()

    if state.review_pending:
        sha_short = state.last_pushed_sha[:8] if state.last_pushed_sha else "unknown"
        return False, f"Review pending for {sha_short}"

    if state.last_pushed_sha is None and state.last_reviewed_sha is None:
        return True, "OK"

    if state.last_reviewed_sha != state.last_pushed_sha:
        return False, "Review stale - push again or wait"

    return True, "OK"


def on_review_complete(sha: str) -> None:
    """Mark review complete for SHA."""
    with DaemonClient() as dc:
        dc.workflow_set_value("review_gate", "last_reviewed_sha", sha)
        dc.workflow_set_value("review_gate", "review_pending", False)
