"""Event schema for telemetry v3.

Defines ToolCallEvent dataclass matching the design spec.
All tool calls are captured with these fields for DuckDB querying.
"""
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class ToolCallEvent:
    """A single tool call event for telemetry tracking.

    Core fields are always present. Token and context fields
    are optional and may be None if not available.
    """
    # Core fields (always captured)
    timestamp: str  # ISO datetime
    session_id: str
    agent_id: str
    tool: str
    backend: str
    duration_ms: int
    status: str  # "success" | "error"

    # Error details (only when status="error")
    error_type: Optional[str] = None

    # Token data (from message.usage when available)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    # Context fields (enhancement from hooks)
    agent_type: Optional[str] = None  # From Task tool's subagent_type
    task_summary: Optional[str] = None  # First 100 chars of task prompt
    workflow_id: Optional[str] = None  # From workflow MCP
    workflow_phase: Optional[str] = None  # Current phase (generic string)

    def to_dict(self) -> dict:
        """Serialize to dict, excluding None values for compact JSONL."""
        return {k: v for k, v in asdict(self).items() if v is not None}
