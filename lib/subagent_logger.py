"""Logging infrastructure for subagent execution tracking."""
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

LOG_DIR = Path.home() / ".claude/plugins/agent-swarm/.logs"

def log_subagent_event(agent_id: str, event: str, data: Optional[dict] = None) -> None:
    """Log a subagent event with timestamp."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"subagent.{agent_id}.log"
    
    entry = {
        "timestamp": datetime.now().isoformat(),
        "agent_id": agent_id,
        "event": event,
        "data": data or {}
    }
    
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")

def log_phase_transition(agent_id: str, from_phase: str, to_phase: str) -> None:
    log_subagent_event(agent_id, "phase_transition", {"from": from_phase, "to": to_phase})

def log_tool_use(agent_id: str, tool: str, success: bool, detail: str = "") -> None:
    log_subagent_event(agent_id, "tool_use", {"tool": tool, "success": success, "detail": detail})

def log_completion(agent_id: str, phase: str, success: bool, reason: str = "") -> None:
    log_subagent_event(agent_id, "completion", {"phase": phase, "success": success, "reason": reason})

def read_agent_log(agent_id: str) -> list[dict]:
    """Read all log entries for an agent."""
    log_file = LOG_DIR / f"subagent.{agent_id}.log"
    if not log_file.exists():
        return []
    entries = []
    for line in log_file.read_text().strip().split("\n"):
        if line:
            entries.append(json.loads(line))
    return entries
