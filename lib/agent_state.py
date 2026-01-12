"""Per-agent state management for isolated subagent execution."""
import json
import os
from pathlib import Path
from typing import Optional

from filelock import FileLock

STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"

def get_agent_id() -> str:
    return os.environ.get("CLAUDE_AGENT_ID", "main")

def get_state_file(agent_id: Optional[str] = None) -> Path:
    if agent_id is None:
        agent_id = get_agent_id()
    if agent_id == "main":
        return STATE_DIR / "session.json"
    return STATE_DIR / f"session.{agent_id}.json"

def load_state(agent_id: Optional[str] = None) -> dict:
    state_file = get_state_file(agent_id)
    lock_file = state_file.parent / (state_file.name + ".lock")
    lock = FileLock(str(lock_file))
    with lock:
        if not state_file.exists():
            return {}
        try:
            return json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

def save_state(state: dict, agent_id: Optional[str] = None) -> None:
    state_file = get_state_file(agent_id)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = state_file.parent / (state_file.name + ".lock")
    lock = FileLock(str(lock_file))
    with lock:
        state_file.write_text(json.dumps(state, indent=2))

def update_state(updater, agent_id: Optional[str] = None) -> dict:
    """Atomically read-modify-write state.

    Args:
        updater: Function that takes current state dict and returns updated state
        agent_id: Optional agent ID for per-agent state

    Returns:
        The updated state dict
    """
    state_file = get_state_file(agent_id)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = state_file.parent / (state_file.name + ".lock")
    lock = FileLock(str(lock_file))
    with lock:
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text())
            except (json.JSONDecodeError, OSError):
                state = {}
        else:
            state = {}
        updated = updater(state)
        state_file.write_text(json.dumps(updated, indent=2))
        return updated


def cleanup_agent_state(agent_id: str) -> bool:
    if agent_id == "main":
        return False
    state_file = get_state_file(agent_id)
    if state_file.exists():
        state_file.unlink()
        return True
    return False
