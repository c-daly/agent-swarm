"""Review gate module to prevent acting on stale Greptile reviews.

This module tracks push SHAs and review SHAs to ensure reviews are only acted
upon when they correspond to the current pushed state.

After state_manager migration, uses in-memory state via state_manager
instead of session.json file.
"""

import sys
from dataclasses import dataclass, asdict, replace
from pathlib import Path
from typing import Optional

# Ensure lib is in path for state_manager import
lib_dir = Path(__file__).parent
if str(lib_dir) not in sys.path:
    sys.path.insert(0, str(lib_dir))

import state_manager


@dataclass(frozen=True)
class ReviewState:
    """State tracking for review gate."""
    last_pushed_sha: Optional[str] = None
    last_reviewed_sha: Optional[str] = None
    review_pending: bool = False


def load_review_state() -> ReviewState:
    """Load review state from in-memory state manager."""
    data = state_manager.get_state("review_gate")
    if not data:
        return ReviewState()

    return ReviewState(
        last_pushed_sha=data.get("last_pushed_sha"),
        last_reviewed_sha=data.get("last_reviewed_sha"),
        review_pending=data.get("review_pending", False)
    )


def save_review_state(state: ReviewState) -> None:
    """Save review state to in-memory state manager."""
    state_manager.set_state("review_gate", asdict(state))


def on_push(sha: str) -> None:
    """Record push, set pending flag.

    Args:
        sha: The git SHA that was just pushed
    """
    state = load_review_state()
    new_state = replace(state, last_pushed_sha=sha, review_pending=True)
    save_review_state(new_state)


def check_review_allowed() -> tuple[bool, str]:
    """Check if review checks are allowed.

    Block review checks if current SHA has not yet been reviewed.

    Returns:
        Tuple of (allowed: bool, message: str)
    """
    state = load_review_state()

    if state.review_pending:
        sha_short = state.last_pushed_sha[:8] if state.last_pushed_sha else "unknown"
        return False, f"Review pending for {sha_short}"

    # If both are None (initial state), allow
    if state.last_pushed_sha is None and state.last_reviewed_sha is None:
        return True, "OK"

    # If they don't match, review is stale
    if state.last_reviewed_sha != state.last_pushed_sha:
        return False, "Review stale - push again or wait"

    return True, "OK"


def on_review_complete(sha: str) -> None:
    """Mark review complete for SHA.

    Args:
        sha: The git SHA that was reviewed
    """
    state = load_review_state()
    new_state = replace(state, last_reviewed_sha=sha, review_pending=False)
    save_review_state(new_state)
