#!/usr/bin/env python3
"""Tests for agent_recovery.py - failed agent detection and handling.

Tests the agent recovery module that detects and handles failed/bad-state subagents.
Uses workflow_client for state management via MCP router.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

import pytest

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

import workflow_client  # noqa: E402
from agent_recovery import detect_failed_agent, handle_failed_agent, get_failed_agents  # noqa: E402


@pytest.fixture(autouse=True)
def clean_agent_state():
    """Clean agent state before and after each test."""
    # Clean up all agents before test
    for agent_id in workflow_client.list_agents():
        workflow_client.agent_delete(agent_id)
    yield
    # Clean up all agents after test
    for agent_id in workflow_client.list_agents():
        workflow_client.agent_delete(agent_id)


class TestDetectFailedAgent:
    """Tests for detect_failed_agent() function."""

    def test_detect_failed_agent_with_error_status(self):
        """detect_failed_agent() returns True when agent has status='error'."""
        agent_id = "test-agent-001"
        workflow_client.agent_set_state(agent_id, {
            "agent_id": agent_id,
            "status": "error",
            "summary": "Some work was done",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        assert detect_failed_agent(agent_id) is True

    def test_detect_failed_agent_with_failed_status(self):
        """detect_failed_agent() returns True when agent has status='failed'."""
        agent_id = "test-agent-002"
        workflow_client.agent_set_state(agent_id, {
            "agent_id": agent_id,
            "status": "failed",
            "summary": "Task failed",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        assert detect_failed_agent(agent_id) is True

    def test_detect_failed_agent_with_error_in_summary(self):
        """detect_failed_agent() returns True when summary contains 'Error:'."""
        agent_id = "test-agent-003"
        workflow_client.agent_set_state(agent_id, {
            "agent_id": agent_id,
            "status": "completed",
            "summary": "Error: Connection timeout while processing",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        assert detect_failed_agent(agent_id) is True

    def test_detect_failed_agent_with_exception_in_summary(self):
        """detect_failed_agent() returns True when summary contains 'Exception:'."""
        agent_id = "test-agent-004"
        workflow_client.agent_set_state(agent_id, {
            "agent_id": agent_id,
            "status": "completed",
            "summary": "Exception: ValueError in parse_config()",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        assert detect_failed_agent(agent_id) is True

    def test_detect_failed_agent_with_traceback_in_summary(self):
        """detect_failed_agent() returns True when summary contains 'Traceback'."""
        agent_id = "test-agent-005"
        workflow_client.agent_set_state(agent_id, {
            "agent_id": agent_id,
            "status": "completed",
            "summary": "Traceback (most recent call last):\n  File test.py...",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        assert detect_failed_agent(agent_id) is True

    def test_detect_failed_agent_healthy_returns_false(self):
        """detect_failed_agent() returns False for healthy agent."""
        agent_id = "test-agent-006"
        workflow_client.agent_set_state(agent_id, {
            "agent_id": agent_id,
            "status": "completed",
            "summary": "Successfully implemented feature X",
            "files_modified": ["lib/module.py"],
            "tests_passed": True,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        assert detect_failed_agent(agent_id) is False

    def test_detect_failed_agent_not_found_returns_false(self):
        """detect_failed_agent() returns False when agent doesn't exist."""
        assert detect_failed_agent("nonexistent-agent") is False

    def test_detect_failed_agent_with_failed_keyword_in_summary(self):
        """detect_failed_agent() returns True when summary contains 'Failed:'."""
        agent_id = "test-agent-007"
        workflow_client.agent_set_state(agent_id, {
            "agent_id": agent_id,
            "status": "completed",
            "summary": "Failed: Unable to complete task due to missing dependency",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        assert detect_failed_agent(agent_id) is True


class TestHandleFailedAgent:
    """Tests for handle_failed_agent() function."""

    def test_handle_failed_agent_marks_as_failed(self):
        """handle_failed_agent() sets status='failed' and adds failed_at timestamp."""
        agent_id = "test-agent-101"
        workflow_client.agent_set_state(agent_id, {
            "agent_id": agent_id,
            "status": "error",
            "summary": "Error occurred",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        result = handle_failed_agent(agent_id, reason="Detection triggered")

        # Check return value
        assert result["success"] is True
        assert result["agent_id"] == agent_id
        assert result["reason"] == "Detection triggered"

        # Check state was updated
        state = workflow_client.agent_get_state(agent_id)
        assert state is not None
        assert state["status"] == "failed"
        assert "failed_at" in state
        assert "failure_reason" in state
        assert state["failure_reason"] == "Detection triggered"

    def test_handle_failed_agent_preserves_state(self):
        """handle_failed_agent() preserves existing agent state fields."""
        agent_id = "test-agent-102"
        original_state = {
            "agent_id": agent_id,
            "status": "error",
            "summary": "Task had issues",
            "files_modified": ["lib/test.py"],
            "tests_passed": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_type": "implementer"
        }
        workflow_client.agent_set_state(agent_id, original_state)

        handle_failed_agent(agent_id, reason="Tests failed")

        # Check state still exists and original fields preserved
        state = workflow_client.agent_get_state(agent_id)
        assert state is not None
        assert state["summary"] == "Task had issues"
        assert state["files_modified"] == ["lib/test.py"]
        assert state["tests_passed"] is False
        assert state["agent_type"] == "implementer"
        # New fields added
        assert state["status"] == "failed"
        assert "failed_at" in state

    def test_handle_failed_agent_does_not_delete_state(self):
        """handle_failed_agent() does NOT delete agent state (preserves for debugging)."""
        agent_id = "test-agent-103"
        workflow_client.agent_set_state(agent_id, {
            "agent_id": agent_id,
            "status": "error",
            "summary": "Error occurred"
        })

        handle_failed_agent(agent_id, reason="For testing")

        # Agent should still exist
        state = workflow_client.agent_get_state(agent_id)
        assert state is not None
        assert state["agent_id"] == agent_id

    def test_handle_failed_agent_nonexistent_agent(self):
        """handle_failed_agent() handles nonexistent agent gracefully."""
        result = handle_failed_agent("nonexistent-agent", reason="Test")

        assert result["success"] is False
        assert "error" in result or "message" in result

    def test_handle_failed_agent_adds_timestamp(self):
        """handle_failed_agent() adds ISO timestamp to failed_at field."""
        agent_id = "test-agent-104"
        workflow_client.agent_set_state(agent_id, {
            "agent_id": agent_id,
            "status": "error",
            "summary": "Error"
        })

        before_time = datetime.now(timezone.utc)
        handle_failed_agent(agent_id, reason="Test")
        after_time = datetime.now(timezone.utc)

        state = workflow_client.agent_get_state(agent_id)
        failed_at = datetime.fromisoformat(state["failed_at"].replace("Z", "+00:00"))

        # Timestamp should be between before and after
        assert before_time <= failed_at <= after_time


class TestGetFailedAgents:
    """Tests for get_failed_agents() function."""

    def test_get_failed_agents_returns_failed_list(self):
        """get_failed_agents() returns list of all agents with status='failed'."""
        # Create mix of agents
        workflow_client.agent_set_state("agent-ok-1", {
            "agent_id": "agent-ok-1",
            "status": "completed",
            "summary": "Success"
        })
        workflow_client.agent_set_state("agent-failed-1", {
            "agent_id": "agent-failed-1",
            "status": "failed",
            "summary": "Error occurred",
            "failure_reason": "Tests failed",
            "failed_at": datetime.now(timezone.utc).isoformat()
        })
        workflow_client.agent_set_state("agent-failed-2", {
            "agent_id": "agent-failed-2",
            "status": "failed",
            "summary": "Exception raised",
            "failure_reason": "Crash",
            "failed_at": datetime.now(timezone.utc).isoformat()
        })
        workflow_client.agent_set_state("agent-ok-2", {
            "agent_id": "agent-ok-2",
            "status": "completed",
            "summary": "Done"
        })

        failed = get_failed_agents()

        # Should return only failed agents
        assert len(failed) == 2
        agent_ids = [a["agent_id"] for a in failed]
        assert "agent-failed-1" in agent_ids
        assert "agent-failed-2" in agent_ids
        assert "agent-ok-1" not in agent_ids
        assert "agent-ok-2" not in agent_ids

    def test_get_failed_agents_includes_metadata(self):
        """get_failed_agents() includes agent_id, reason, and failed_at in results."""
        agent_id = "agent-failed-meta"
        workflow_client.agent_set_state(agent_id, {
            "agent_id": agent_id,
            "status": "failed",
            "summary": "Failed task",
            "failure_reason": "Connection timeout",
            "failed_at": "2026-01-20T10:00:00Z"
        })

        failed = get_failed_agents()

        assert len(failed) == 1
        agent = failed[0]
        assert agent["agent_id"] == agent_id
        assert agent["reason"] == "Connection timeout"
        assert agent["failed_at"] == "2026-01-20T10:00:00Z"

    def test_get_failed_agents_empty_when_none(self):
        """get_failed_agents() returns empty list when no failed agents."""
        # Create only successful agents
        workflow_client.agent_set_state("agent-ok-1", {
            "agent_id": "agent-ok-1",
            "status": "completed",
            "summary": "Success"
        })
        workflow_client.agent_set_state("agent-ok-2", {
            "agent_id": "agent-ok-2",
            "status": "completed",
            "summary": "Done"
        })

        failed = get_failed_agents()

        assert failed == []

    def test_get_failed_agents_empty_when_no_agents(self):
        """get_failed_agents() returns empty list when no agents exist."""
        failed = get_failed_agents()
        assert failed == []
