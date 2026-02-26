#!/usr/bin/env python3
"""
Agent Recovery - Detection and handling of failed/bad-state subagents.

Provides functions to detect agent failures and mark them appropriately.
Does NOT auto-retry - retry decisions are manual orchestrator responsibility.

Usage:
    from agent_recovery import detect_failed_agent, handle_failed_agent, get_failed_agents

    # Detect if agent has failed
    if detect_failed_agent(agent_id):
        handle_failed_agent(agent_id, reason="Error detected")

    # Get all failed agents
    failed = get_failed_agents()
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from daemon_client import DaemonClient  # noqa: E402


# Error keywords that indicate failure
ERROR_KEYWORDS = ["Error:", "Exception:", "Failed:", "Traceback"]


def detect_failed_agent(agent_id: str) -> bool:
    """Check if agent is in failed/bad state."""
    with DaemonClient() as dc:
        state = dc.agent_get_state(agent_id)

    if state is None:
        return False

    status = state.get("status", "")
    if status in ["error", "failed"]:
        return True

    summary = state.get("summary", "")
    if summary:
        for keyword in ERROR_KEYWORDS:
            if keyword in summary:
                return True

    return False


def handle_failed_agent(agent_id: str, reason: str = "") -> dict:
    """Mark agent as failed and clean up state."""
    with DaemonClient() as dc:
        state = dc.agent_get_state(agent_id)

        if state is None:
            return {
                "success": False,
                "agent_id": agent_id,
                "error": f"Agent {agent_id} not found"
            }

        state["status"] = "failed"
        state["failed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        state["failure_reason"] = reason
        dc.agent_set_state(agent_id, state)

    return {
        "success": True,
        "agent_id": agent_id,
        "reason": reason
    }


def get_failed_agents() -> list[dict]:
    """Get list of all agents in failed state."""
    try:
        with DaemonClient() as dc:
            agent_ids = dc.agent_list()
            if not agent_ids:
                return []

            failed = []
            for agent_id in agent_ids:
                state = dc.agent_get_state(agent_id)
                if state is None:
                    continue
                if state.get("status") == "failed":
                    failed.append({
                        "agent_id": agent_id,
                        "reason": state.get("failure_reason", ""),
                        "failed_at": state.get("failed_at", "")
                    })

        return failed

    except Exception:
        return []
