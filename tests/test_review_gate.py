"""Tests for review gate module.

After state_manager migration, review_gate uses in-memory state via state_manager
instead of session.json file. Tests use autouse fixture to isolate state.
"""

import pytest
import sys
from pathlib import Path

# Ensure lib is in path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

import state_manager
from lib.review_gate import (
    ReviewState,
    load_review_state,
    save_review_state,
    on_push,
    check_review_allowed,
    on_review_complete,
)


@pytest.fixture(autouse=True)
def clean_state_manager():
    """Clean state_manager state before and after each test."""
    # Clear review_gate state before test
    state_manager.delete_state("review_gate")
    yield
    # Clear after test
    state_manager.delete_state("review_gate")




def test_review_state_default():
    """Test ReviewState defaults."""
    state = ReviewState()
    assert state.last_pushed_sha is None
    assert state.last_reviewed_sha is None
    assert state.review_pending is False


def test_load_review_state_no_state():
    """Test loading state when no state exists."""
    state = load_review_state()
    assert isinstance(state, ReviewState)
    assert state.last_pushed_sha is None
    assert state.review_pending is False


def test_save_and_load_review_state():
    """Test saving and loading review state."""
    state = ReviewState(
        last_pushed_sha="abc123",
        last_reviewed_sha="def456",
        review_pending=True
    )
    save_review_state(state)

    loaded = load_review_state()
    assert loaded.last_pushed_sha == "abc123"
    assert loaded.last_reviewed_sha == "def456"
    assert loaded.review_pending is True


def test_save_review_state_overwrites_cleanly():
    """Test that saving review state overwrites previous state cleanly."""
    # Save initial state
    state1 = ReviewState(last_pushed_sha="abc123", review_pending=True)
    save_review_state(state1)

    # Save different state
    state2 = ReviewState(last_pushed_sha="def456", review_pending=False)
    save_review_state(state2)

    # Load should return the second state
    loaded = load_review_state()
    assert loaded.last_pushed_sha == "def456"
    assert loaded.review_pending is False


def test_on_push():
    """Test on_push sets pending flag."""
    on_push("abc123def456")

    state = load_review_state()
    assert state.last_pushed_sha == "abc123def456"
    assert state.review_pending is True


def test_on_push_updates_existing_state():
    """Test on_push updates existing state."""
    # First push
    on_push("sha1")

    # Second push
    on_push("sha2")

    state = load_review_state()
    assert state.last_pushed_sha == "sha2"
    assert state.review_pending is True


def test_check_review_allowed_pending():
    """Test check blocks when review is pending."""
    on_push("abc123def")

    allowed, message = check_review_allowed()
    assert allowed is False
    assert "abc123de" in message  # First 8 chars
    assert "pending" in message.lower()


def test_check_review_allowed_stale():
    """Test check blocks when review is stale."""
    state = ReviewState(
        last_pushed_sha="new_sha",
        last_reviewed_sha="old_sha",
        review_pending=False
    )
    save_review_state(state)

    allowed, message = check_review_allowed()
    assert allowed is False
    assert "stale" in message.lower()


def test_check_review_allowed_ok():
    """Test check allows when review is current."""
    sha = "abc123"
    state = ReviewState(
        last_pushed_sha=sha,
        last_reviewed_sha=sha,
        review_pending=False
    )
    save_review_state(state)

    allowed, message = check_review_allowed()
    assert allowed is True
    assert message == "OK"


def test_on_review_complete():
    """Test on_review_complete clears pending flag."""
    on_push("abc123")
    on_review_complete("abc123")

    state = load_review_state()
    assert state.last_reviewed_sha == "abc123"
    assert state.review_pending is False


def test_full_workflow():
    """Test complete push-review-check workflow."""
    # Initial state - no push yet (both None)
    allowed, _ = check_review_allowed()
    assert allowed is True  # Initial state is OK

    # Push code
    sha = "abc123def456"
    on_push(sha)

    # Review pending - should block
    allowed, msg = check_review_allowed()
    assert allowed is False
    assert "pending" in msg.lower()

    # Review completes
    on_review_complete(sha)

    # Now allowed
    allowed, msg = check_review_allowed()
    assert allowed is True

    # New push - becomes stale
    on_push("new_sha")
    allowed, msg = check_review_allowed()
    assert allowed is False
    assert "pending" in msg.lower()


def test_load_empty_state():
    """Test loading when no state has been saved."""
    # state_manager is cleared by autouse fixture, so state should be empty
    state = load_review_state()
    assert isinstance(state, ReviewState)
    assert state.last_pushed_sha is None
    assert state.review_pending is False


def test_state_isolation():
    """Test that review_gate state is isolated from other state_manager keys."""
    # Set review_gate state
    state = ReviewState(last_pushed_sha="abc123")
    save_review_state(state)

    # Set unrelated state_manager key
    state_manager.set_state("other_key", {"foo": "bar"})

    # Review gate state should be unaffected
    loaded = load_review_state()
    assert loaded.last_pushed_sha == "abc123"

    # Other key should be unaffected
    other = state_manager.get_state("other_key")
    assert other == {"foo": "bar"}


def test_state_persistence_across_multiple_saves():
    """Test state persists correctly across multiple saves."""
    on_push("sha1")
    state1 = load_review_state()

    on_review_complete("sha1")
    state2 = load_review_state()

    on_push("sha2")
    state3 = load_review_state()

    assert state1.review_pending is True
    assert state2.review_pending is False
    assert state3.review_pending is True
    assert state3.last_pushed_sha == "sha2"
