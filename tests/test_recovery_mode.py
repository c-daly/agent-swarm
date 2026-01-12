"""Tests for recovery mode bypass mechanism.

Recovery mode allows fixing enforcement code when locked out.
"""

import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime

import agent_state
from lib.recovery_mode import (
    is_recovery_mode,
    enter_recovery,
    exit_recovery,
    get_recovery_state,
    RECOVERY_TIMEOUT_MINUTES,
)


@pytest.fixture
def temp_state_dir(tmp_path):
    """Use a temporary directory for state files."""
    agent_state.StateManager.clear_cache()
    with patch.object(agent_state, "STATE_DIR", tmp_path):
        yield tmp_path
    agent_state.StateManager.clear_cache()


class TestIsRecoveryMode:
    """Test recovery mode detection."""

    def test_returns_false_by_default(self, temp_state_dir):
        """No recovery mode when nothing set."""
        assert is_recovery_mode() is False

    def test_returns_true_when_env_var_set(self, temp_state_dir):
        """AGENT_RECOVERY=1 enables recovery mode."""
        with patch.dict(os.environ, {"AGENT_RECOVERY": "1"}):
            assert is_recovery_mode() is True

    def test_returns_true_when_state_flag_set(self, temp_state_dir):
        """recovery_mode: true in state enables recovery."""
        state_file = temp_state_dir / "session.json"
        state_file.write_text(json.dumps({
            "recovery_mode": True,
            "recovery_entered": datetime.now().isoformat()
        }))
        assert is_recovery_mode() is True

    def test_env_var_takes_precedence(self, temp_state_dir):
        """Env var works even if state says false."""
        state_file = temp_state_dir / "session.json"
        state_file.write_text(json.dumps({"recovery_mode": False}))
        with patch.dict(os.environ, {"AGENT_RECOVERY": "1"}):
            assert is_recovery_mode() is True


class TestEnterRecovery:
    """Test entering recovery mode."""

    def test_sets_recovery_flag(self, temp_state_dir):
        """enter_recovery sets the flag in state."""
        enter_recovery("Testing enforcement fix")
        state_file = temp_state_dir / "session.json"
        state = json.loads(state_file.read_text())
        assert state["recovery_mode"] is True

    def test_records_reason(self, temp_state_dir):
        """Reason is stored for audit."""
        enter_recovery("Fixing phase enforcement bug")
        state_file = temp_state_dir / "session.json"
        state = json.loads(state_file.read_text())
        assert state["recovery_reason"] == "Fixing phase enforcement bug"

    def test_records_timestamp(self, temp_state_dir):
        """Entry time recorded for timeout."""
        before = datetime.now().isoformat()
        enter_recovery("Test")
        after = datetime.now().isoformat()
        state_file = temp_state_dir / "session.json"
        state = json.loads(state_file.read_text())
        assert "recovery_entered" in state
        assert before <= state["recovery_entered"] <= after


class TestExitRecovery:
    """Test exiting recovery mode."""

    def test_clears_recovery_flag(self, temp_state_dir):
        """exit_recovery clears the flag."""
        state_file = temp_state_dir / "session.json"
        state_file.write_text(json.dumps({
            "recovery_mode": True,
            "recovery_reason": "Test",
            "recovery_entered": datetime.now().isoformat(),
        }))
        exit_recovery()
        state = json.loads(state_file.read_text())
        assert state.get("recovery_mode") is False

    def test_records_exit_timestamp(self, temp_state_dir):
        """Exit time recorded for audit log."""
        state_file = temp_state_dir / "session.json"
        state_file.write_text(json.dumps({
            "recovery_mode": True,
            "recovery_reason": "Test",
            "recovery_entered": datetime.now().isoformat(),
        }))
        exit_recovery()
        state = json.loads(state_file.read_text())
        assert "recovery_exited" in state


class TestRecoveryTimeout:
    """Test automatic recovery timeout."""

    def test_recovery_times_out_after_limit(self, temp_state_dir):
        """Recovery mode auto-expires after RECOVERY_TIMEOUT_MINUTES."""
        state_file = temp_state_dir / "session.json"
        old_time = "2020-01-12T06:00:00"
        state_file.write_text(json.dumps({
            "recovery_mode": True,
            "recovery_reason": "Old test",
            "recovery_entered": old_time,
        }))
        assert is_recovery_mode() is False

    def test_recent_recovery_still_active(self, temp_state_dir):
        """Recovery mode active if within timeout."""
        state_file = temp_state_dir / "session.json"
        recent_time = datetime.now().isoformat()
        state_file.write_text(json.dumps({
            "recovery_mode": True,
            "recovery_reason": "Recent test",
            "recovery_entered": recent_time,
        }))
        assert is_recovery_mode() is True


class TestGetRecoveryState:
    """Test getting full recovery state for display."""

    def test_returns_none_when_not_in_recovery(self, temp_state_dir):
        """Returns None when recovery not active."""
        state_file = temp_state_dir / "session.json"
        state_file.write_text(json.dumps({}))
        assert get_recovery_state() is None

    def test_returns_state_dict_when_active(self, temp_state_dir):
        """Returns full state when recovery active."""
        state_file = temp_state_dir / "session.json"
        entered = datetime.now().isoformat()
        state_file.write_text(json.dumps({
            "recovery_mode": True,
            "recovery_reason": "Test reason",
            "recovery_entered": entered,
        }))
        result = get_recovery_state()
        assert result is not None
        assert result["reason"] == "Test reason"
        assert result["entered"] == entered
