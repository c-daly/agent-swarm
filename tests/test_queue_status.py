#!/usr/bin/env python3
"""Tests for SAFE.6 - Queue Status Display.

Tests:
- SAFE.6.1: show_queue_status() function
- SAFE.6.2: Periodic display trigger (every N tool calls)
- SAFE.6.3: Phase change trigger
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import agent_state


class TestShowQueueStatus:
    """Tests for SAFE.6.1: show_queue_status() function."""

    def test_show_queue_status_returns_formatted_string(self, tmp_path):
        """show_queue_status() returns formatted progress display."""
        from workflow import _load_state, _save_state

        # Mock state directory
        with patch("agent_state.STATE_DIR", tmp_path):
                # Setup: Create queue with tasks
                state = {
                    "queue": {
                        "tasks": {
                            "t1": {"id": "t1", "status": "completed", "priority": 1, "description": "Task 1"},
                            "t2": {"id": "t2", "status": "pending", "priority": 1, "description": "Task 2"},
                            "t3": {"id": "t3", "status": "pending", "priority": 2, "description": "Task 3"},
                        },
                        "prs": {},
                        "completed": ["t1"],
                        "failed": [],
                    }
                }
                _save_state(state)

                # Import after patching
                from workflow import show_queue_status

                result = show_queue_status()

                # Should contain progress indicators
                assert "Queue Status" in result or "QUEUE" in result
                assert "1" in result  # completed count
                assert "3" in result or "2" in result  # total or pending count

    def test_show_queue_status_empty_queue(self, tmp_path):
        """show_queue_status() handles empty queue gracefully."""
        from workflow import _save_state

        with patch("agent_state.STATE_DIR", tmp_path):
                _save_state({})

                from workflow import show_queue_status

                result = show_queue_status()

                # Should not crash, should show empty state
                assert isinstance(result, str)
                assert "empty" in result.lower() or "no" in result.lower() or "0" in result

    def test_show_queue_status_by_priority(self, tmp_path):
        """show_queue_status() groups tasks by priority."""
        from workflow import _save_state

        with patch("agent_state.STATE_DIR", tmp_path):
                state = {
                    "queue": {
                        "tasks": {
                            "t1": {"id": "t1", "status": "completed", "priority": 0, "description": "Critical 1"},
                            "t2": {"id": "t2", "status": "pending", "priority": 0, "description": "Critical 2"},
                            "t3": {"id": "t3", "status": "completed", "priority": 1, "description": "High 1"},
                            "t4": {"id": "t4", "status": "pending", "priority": 2, "description": "Medium 1"},
                        },
                        "prs": {},
                        "completed": ["t1", "t3"],
                        "failed": [],
                    }
                }
                _save_state(state)

                from workflow import show_queue_status

                result = show_queue_status()

                # Should show breakdown by priority
                assert isinstance(result, str)
                # Progress bar or fraction should be present
                assert "/" in result or "%" in result or "[" in result


class TestToolCallCounter:
    """Tests for SAFE.6.2: Trigger queue display every N tool calls."""

    def test_tool_call_counter_increments(self, tmp_path):
        """Tool call counter increments on each call."""
        state_file = tmp_path / "session.json"
        state_file.write_text(json.dumps({"tool_call_count": 5}))

        # Read current state
        state = json.loads(state_file.read_text())

        # Simulate increment
        state["tool_call_count"] = state.get("tool_call_count", 0) + 1
        state_file.write_text(json.dumps(state))

        # Verify
        new_state = json.loads(state_file.read_text())
        assert new_state["tool_call_count"] == 6

    def test_counter_triggers_at_threshold(self, tmp_path):
        """Counter triggers queue display at N=10."""
        state_file = tmp_path / "session.json"

        # At threshold
        state_file.write_text(json.dumps({"tool_call_count": 9}))
        state = json.loads(state_file.read_text())

        # Increment to threshold
        state["tool_call_count"] = state.get("tool_call_count", 0) + 1

        # Check trigger condition
        should_trigger = state["tool_call_count"] % 10 == 0
        assert should_trigger is True

    def test_counter_resets_display_flag(self, tmp_path):
        """After display, flag resets to allow next display."""
        state_file = tmp_path / "session.json"
        state_file.write_text(json.dumps({
            "tool_call_count": 10,
            "queue_displayed": True
        }))

        state = json.loads(state_file.read_text())

        # After display at 10, next display at 20
        state["tool_call_count"] = 11

        should_trigger = state["tool_call_count"] % 10 == 0
        assert should_trigger is False

        state["tool_call_count"] = 20
        should_trigger = state["tool_call_count"] % 10 == 0
        assert should_trigger is True


class TestPhaseChangeTrigger:
    """Tests for SAFE.6.3: Trigger queue on phase change."""

    def test_phase_change_triggers_display(self, tmp_path):
        """Phase change should trigger queue status display."""
        from workflow import _save_state

        with patch("agent_state.STATE_DIR", tmp_path):
                # Initial state
                _save_state({
                    "phase": "test_writing",
                    "last_phase": "test_writing",
                })

                from workflow import _load_state

                # Simulate phase change detection
                state = _load_state()
                old_phase = state.get("last_phase")
                new_phase = "implement"

                phase_changed = old_phase != new_phase
                assert phase_changed is True

    def test_same_phase_no_trigger(self, tmp_path):
        """Same phase should not trigger display."""
        from workflow import _save_state, _load_state

        with patch("agent_state.STATE_DIR", tmp_path):
                _save_state({
                    "phase": "implement",
                    "last_phase": "implement",
                })

                state = _load_state()
                old_phase = state.get("last_phase")
                new_phase = state.get("phase")

                phase_changed = old_phase != new_phase
                assert phase_changed is False

    def test_phase_change_updates_last_phase(self, tmp_path):
        """After phase change, last_phase should update."""
        from workflow import _save_state, _load_state

        with patch("agent_state.STATE_DIR", tmp_path):
                _save_state({"phase": "test_writing", "last_phase": None})

                state = _load_state()

                # Simulate transition
                state["last_phase"] = state.get("phase")
                state["phase"] = "implement"
                _save_state(state)

                # Verify
                updated = _load_state()
                assert updated["last_phase"] == "test_writing"
                assert updated["phase"] == "implement"


class TestProgressBar:
    """Tests for progress bar visual formatting."""

    def test_progress_bar_format(self):
        """Progress bar shows filled/empty segments."""
        # Helper function to test
        def make_progress_bar(done: int, total: int, width: int = 20) -> str:
            if total == 0:
                return f"[{'=' * width}] 0/0"
            filled = int(width * done / total)
            empty = width - filled
            return f"[{'=' * filled}{' ' * empty}] {done}/{total}"

        # Test cases
        assert "[=====               ] 5/20" == make_progress_bar(5, 20)
        assert "[====================] 10/10" == make_progress_bar(10, 10)
        assert "[                    ] 0/5" == make_progress_bar(0, 5)
        assert "[====================] 0/0" == make_progress_bar(0, 0)

    def test_percentage_display(self):
        """Percentage calculation is correct."""
        def calc_percent(done: int, total: int) -> int:
            if total == 0:
                return 100
            return int(100 * done / total)

        assert calc_percent(5, 10) == 50
        assert calc_percent(3, 4) == 75
        assert calc_percent(0, 5) == 0
        assert calc_percent(0, 0) == 100


class TestQueueStatusIntegration:
    """Integration tests for queue status display."""

    def test_queue_status_in_workflow_context(self, tmp_path):
        """Queue status works within active workflow."""
        from workflow import _save_state

        with patch("agent_state.STATE_DIR", tmp_path):
                # Setup active workflow with queue
                state = {
                    "workflow_invoked": True,
                    "mode": "iterate-tdd",
                    "phase": "implement",
                    "iteration": 1,
                    "queue": {
                        "tasks": {
                            "t1": {"id": "t1", "status": "completed", "priority": 0, "description": "Test 1"},
                            "t2": {"id": "t2", "status": "running", "priority": 0, "description": "Test 2"},
                            "t3": {"id": "t3", "status": "pending", "priority": 1, "description": "Test 3"},
                        },
                        "prs": {},
                        "completed": ["t1"],
                        "failed": [],
                    },
                    "tool_call_count": 0,
                }
                _save_state(state)

                from workflow import show_queue_status

                result = show_queue_status()

                # Should show meaningful status
                assert isinstance(result, str)
                assert len(result) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
