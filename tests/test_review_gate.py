"""Tests for review gate module."""

import json
import pytest
from pathlib import Path

from lib.review_gate import (
    ReviewState,
    load_review_state,
    save_review_state,
    on_push,
    check_review_allowed,
    on_review_complete,
)


@pytest.fixture
def temp_session_file(tmp_path, monkeypatch):
    """Create a temporary session file for testing."""
    state_dir = tmp_path / ".state"
    state_dir.mkdir()
    session_file = state_dir / "session.json"

    # Patch the module-level variables
    import lib.review_gate
    monkeypatch.setattr(lib.review_gate, "STATE_DIR", state_dir)
    monkeypatch.setattr(lib.review_gate, "SESSION_FILE", session_file)

    return session_file


def test_review_state_default():
    """Test ReviewState defaults."""
    state = ReviewState()
    assert state.last_pushed_sha is None
    assert state.last_reviewed_sha is None
    assert state.review_pending is False


def test_load_review_state_no_file(temp_session_file):
    """Test loading state when file doesn't exist."""
    state = load_review_state()
    assert isinstance(state, ReviewState)
    assert state.last_pushed_sha is None
    assert state.review_pending is False


def test_save_and_load_review_state(temp_session_file):
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


def test_save_review_state_preserves_other_keys(temp_session_file):
    """Test that saving review state preserves other session data."""
    # Write some other data first
    temp_session_file.write_text(json.dumps({
        "other_key": "other_value",
        "nested": {"data": 123}
    }))

    state = ReviewState(last_pushed_sha="abc123")
    save_review_state(state)

    data = json.loads(temp_session_file.read_text())
    assert "review_gate" in data
    assert data["other_key"] == "other_value"
    assert data["nested"]["data"] == 123


def test_on_push(temp_session_file):
    """Test on_push sets pending flag."""
    on_push("abc123def456")

    state = load_review_state()
    assert state.last_pushed_sha == "abc123def456"
    assert state.review_pending is True


def test_on_push_updates_existing_state(temp_session_file):
    """Test on_push updates existing state."""
    # First push
    on_push("sha1")

    # Second push
    on_push("sha2")

    state = load_review_state()
    assert state.last_pushed_sha == "sha2"
    assert state.review_pending is True


def test_check_review_allowed_pending(temp_session_file):
    """Test check blocks when review is pending."""
    on_push("abc123def")

    allowed, message = check_review_allowed()
    assert allowed is False
    assert "abc123de" in message  # First 8 chars
    assert "pending" in message.lower()


def test_check_review_allowed_stale(temp_session_file):
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


def test_check_review_allowed_ok(temp_session_file):
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


def test_on_review_complete(temp_session_file):
    """Test on_review_complete clears pending flag."""
    on_push("abc123")
    on_review_complete("abc123")

    state = load_review_state()
    assert state.last_reviewed_sha == "abc123"
    assert state.review_pending is False


def test_full_workflow(temp_session_file):
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


def test_load_corrupted_file(temp_session_file):
    """Test loading from corrupted JSON file."""
    temp_session_file.write_text("invalid json {{{")

    state = load_review_state()
    assert isinstance(state, ReviewState)
    assert state.last_pushed_sha is None


def test_save_with_corrupted_existing_file(temp_session_file):
    """Test saving when existing session file is corrupted JSON."""
    # Write corrupted JSON first
    temp_session_file.write_text("invalid json {{{")

    # Saving should succeed by replacing corrupted data
    state = ReviewState(last_pushed_sha="abc123")
    save_review_state(state)

    # Verify it was saved correctly
    loaded = load_review_state()
    assert loaded.last_pushed_sha == "abc123"


def test_state_persistence_across_multiple_saves(temp_session_file):
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
