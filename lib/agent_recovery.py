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
from typing import Optional

# Ensure workflow_client is importable
sys.path.insert(0, str(Path(__file__).parent))
from workflow_client import agent_get_state, agent_set_state, list_agents


# Error keywords that indicate failure
ERROR_KEYWORDS = ["Error:", "Exception:", "Failed:", "Traceback"]


def detect_failed_agent(agent_id: str) -> bool:
    """Check if agent is in failed/bad state.
    
    Detection criteria:
    - Agent state has status="error" or status="failed"
    - Agent output/summary contains error keywords
    - Missing required fields (returns False, not failure)
    
    Args:
        agent_id: Agent identifier
        
    Returns:
        True if agent has failed, False if healthy or not found
    """
    # Get agent state
    state = agent_get_state(agent_id)
    
    # Agent not found - not considered a failure
    if state is None:
        return False
    
    # Check status field
    status = state.get("status", "")
    if status in ["error", "failed"]:
        return True
    
    # Check summary for error keywords
    summary = state.get("summary", "")
    if summary:
        for keyword in ERROR_KEYWORDS:
            if keyword in summary:
                return True
    
    # No failure detected
    return False


def handle_failed_agent(agent_id: str, reason: str = "") -> dict:
    """Mark agent as failed and clean up state.
    
    - Sets status="failed"
    - Adds failed_at timestamp
    - Preserves state for debugging (does NOT delete)
    - Does NOT retry (manual orchestrator decision)
    
    Args:
        agent_id: Agent identifier
        reason: Optional failure reason
        
    Returns:
        dict with success, agent_id, reason (or error info if agent not found)
    """
    # Get current agent state
    state = agent_get_state(agent_id)
    
    # Handle agent not found
    if state is None:
        return {
            "success": False,
            "agent_id": agent_id,
            "error": f"Agent {agent_id} not found"
        }
    
    # Update state to mark as failed
    state["status"] = "failed"
    state["failed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    state["failure_reason"] = reason
    
    # Save updated state (does NOT delete)
    agent_set_state(agent_id, state)
    
    return {
        "success": True,
        "agent_id": agent_id,
        "reason": reason
    }


def get_failed_agents() -> list[dict]:
    """Get list of all agents in failed state.
    
    Returns:
        List of dicts with agent_id, reason, failed_at
        Empty list if no failed agents or if list_agents fails
    """
    try:
        # Get all agent IDs
        agent_ids = list_agents()
        
        if not agent_ids:
            return []
        
        failed = []
        
        # Check each agent
        for agent_id in agent_ids:
            state = agent_get_state(agent_id)
            
            # Skip if state not found or status not failed
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
        # If anything goes wrong, return empty list
        return []
