"""Tests for ToolCallEvent dataclass."""
from lib.stores.events import ToolCallEvent


def test_tool_call_event_required_fields():
    """ToolCallEvent requires core fields."""
    event = ToolCallEvent(
        timestamp="2026-01-21T10:00:00Z",
        session_id="abc123",
        agent_id="def456",
        tool="mcp__router__native__read_file",
        backend="router",
        duration_ms=150,
        status="success",
    )
    assert event.tool == "mcp__router__native__read_file"
    assert event.status == "success"


def test_tool_call_event_optional_fields():
    """ToolCallEvent has optional context fields."""
    event = ToolCallEvent(
        timestamp="2026-01-21T10:00:00Z",
        session_id="abc123",
        agent_id="def456",
        tool="Task",
        backend="native",
        duration_ms=5000,
        status="success",
        agent_type="Explore",
        task_summary="Find error handlers",
        workflow_id="wf-123",
        workflow_phase="implement",
    )
    assert event.agent_type == "Explore"
    assert event.workflow_phase == "implement"


def test_tool_call_event_to_dict():
    """ToolCallEvent serializes to dict for JSONL."""
    event = ToolCallEvent(
        timestamp="2026-01-21T10:00:00Z",
        session_id="abc123",
        agent_id="def456",
        tool="Read",
        backend="native",
        duration_ms=100,
        status="success",
        input_tokens=500,
        output_tokens=200,
    )
    d = event.to_dict()
    assert d["tool"] == "Read"
    assert d["input_tokens"] == 500
    assert "error_type" not in d  # None fields excluded
