#!/usr/bin/env python3
"""Workflow state machine with explicit state transitions and recovery."""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import json
from pathlib import Path
from datetime import datetime, timedelta

class WorkflowState(Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    AWAITING_APPROVAL = "awaiting_approval"
    BLOCKED = "blocked"
    PARALLEL_WAVE = "parallel_wave"

@dataclass
class WorkflowContext:
    state: WorkflowState = WorkflowState.IDLE
    active_tasks: List[str] = field(default_factory=list)
    pending_approvals: List[Dict[str, Any]] = field(default_factory=list)
    violation_count: int = 0
    last_violation: Optional[str] = None
    violation_decay_at: Optional[str] = None  # ISO timestamp

    def can_proceed(self) -> tuple[bool, str]:
        """Check if workflow can proceed or needs intervention."""
        # Check violation decay
        if self.violation_decay_at:
            decay_time = datetime.fromisoformat(self.violation_decay_at)
            if datetime.now() > decay_time:
                self.clear_violations()

        if self.state == WorkflowState.AWAITING_APPROVAL:
            return False, f"Approval needed: {self.pending_approvals}"
        if self.state == WorkflowState.BLOCKED and self.violation_count >= 3:
            return False, f"Blocked (3+ violations): {self.last_violation}"
        return True, "OK"

    def add_violation(self, reason: str):
        """Record a violation with decay timer."""
        self.violation_count += 1
        self.last_violation = reason
        # Violations decay after 10 minutes
        decay = datetime.now() + timedelta(minutes=10)
        self.violation_decay_at = decay.isoformat()
        if self.violation_count >= 3:
            self.state = WorkflowState.BLOCKED

    def clear_violations(self):
        """Reset violation state."""
        self.violation_count = 0
        self.last_violation = None
        self.violation_decay_at = None
        if self.state == WorkflowState.BLOCKED:
            self.state = WorkflowState.IDLE

    def require_approval(self, item: Dict[str, Any]):
        """Add an item requiring user approval."""
        self.pending_approvals.append(item)
        self.state = WorkflowState.AWAITING_APPROVAL

    def approve(self, item_id: str):
        """Mark an approval item as approved."""
        self.pending_approvals = [p for p in self.pending_approvals if p.get("id") != item_id]
        if not self.pending_approvals:
            self.state = WorkflowState.EXECUTING

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "active_tasks": self.active_tasks,
            "pending_approvals": self.pending_approvals,
            "violation_count": self.violation_count,
            "last_violation": self.last_violation,
            "violation_decay_at": self.violation_decay_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowContext":
        return cls(
            state=WorkflowState(data.get("state", "idle")),
            active_tasks=data.get("active_tasks", []),
            pending_approvals=data.get("pending_approvals", []),
            violation_count=data.get("violation_count", 0),
            last_violation=data.get("last_violation"),
            violation_decay_at=data.get("violation_decay_at"),
        )

STATE_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/workflow.json"

def load_state() -> WorkflowContext:
    """Load workflow state from file."""
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            return WorkflowContext.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            pass
    return WorkflowContext()

def save_state(ctx: WorkflowContext):
    """Save workflow state to file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(ctx.to_dict(), indent=2))

def reset_state():
    """Reset workflow state completely."""
    ctx = WorkflowContext()
    save_state(ctx)
    return ctx

# Approval gate thresholds
APPROVAL_GATES = {
    "pr_quality": {
        "threshold": 4,
        "action": "REQUIRE_APPROVAL",
        "message": "PR quality {rating}/5 below threshold 4/5. Approve to proceed?",
    },
    "unaddressed_comments": {
        "threshold": 0,
        "action": "BLOCK",
        "message": "{count} unaddressed review comments. Cannot mark complete.",
    },
}

def check_gate(gate_name: str, value: float, context: dict | None = None) -> dict:
    """Check if an approval gate passes."""
    context = context or {}
    gate = APPROVAL_GATES.get(gate_name)
    if not gate:
        return {"status": "PASS"}

    if value >= gate["threshold"]:
        return {"status": "PASS"}

    return {
        "status": gate["action"],
        "message": gate["message"].format(**{**context, "value": value}),
        "requires_user": gate["action"] in ("REQUIRE_APPROVAL", "BLOCK"),
    }
