"""Review gate module to prevent acting on stale Greptile reviews.

This module tracks push SHAs and review SHAs to ensure reviews are only acted
upon when they correspond to the current pushed state.
"""

import json
from dataclasses import dataclass, asdict, replace
from pathlib import Path
from typing import Optional

STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"
SESSION_FILE = STATE_DIR / "session.json"


@dataclass(frozen=True)
class ReviewState:
    """State tracking for review gate."""
    last_pushed_sha: Optional[str] = None
    last_reviewed_sha: Optional[str] = None
    review_pending: bool = False


def load_review_state() -> ReviewState:
    """Load review state from session.json under 'review_gate' key."""
    if not SESSION_FILE.exists():
        return ReviewState()

    try:
        data = json.loads(SESSION_FILE.read_text())
        gate_data = data.get("review_gate", {})
        return ReviewState(
            last_pushed_sha=gate_data.get("last_pushed_sha"),
            last_reviewed_sha=gate_data.get("last_reviewed_sha"),
            review_pending=gate_data.get("review_pending", False)
        )
    except (json.JSONDecodeError, KeyError):
        return ReviewState()


def save_review_state(state: ReviewState) -> None:
    """Save review state to session.json under 'review_gate' key."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing state
    if SESSION_FILE.exists():
        try:
            data = json.loads(SESSION_FILE.read_text())
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}

    # Update review_gate key
    data["review_gate"] = asdict(state)

    # Save back
    SESSION_FILE.write_text(json.dumps(data, indent=2) + "\n")


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
