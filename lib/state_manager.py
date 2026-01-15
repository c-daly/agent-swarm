"""State manager for iterate workflow.

Manages agent workflow states:
- Orchestrator state (persisted to file, with file locking)
- Subagent states (in-memory, keyed by agent ID)

Thread-safe for both in-memory and file operations.
"""

import fcntl
import json
from pathlib import Path
from threading import Lock
from typing import Optional

STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"
ORCHESTRATOR_STATE_FILE = STATE_DIR / "iterate.json"
ORCHESTRATOR_LOCK_FILE = STATE_DIR / "iterate.lock"

# Thread-safe storage for in-memory agent states
_states: dict[str, dict] = {}
_memory_lock = Lock()


def get_state(agent_id: str) -> Optional[dict]:
    """Get state for an agent by ID.

    Args:
        agent_id: Agent identifier. Use "orchestrator" for persisted state.

    Returns:
        State dict or None if not found.
    """
    if agent_id == "orchestrator":
        return _load_orchestrator_state()

    with _memory_lock:
        # Return a copy to prevent external mutation
        state = _states.get(agent_id)
        return dict(state) if state else None


def set_state(agent_id: str, state: dict) -> None:
    """Set state for an agent.

    Args:
        agent_id: Agent identifier. Use "orchestrator" for persisted state.
        state: Full state dict to store.
    """
    if agent_id == "orchestrator":
        _save_orchestrator_state(state)
    else:
        with _memory_lock:
            _states[agent_id] = dict(state)  # Store a copy


def update_state(agent_id: str, updates: dict) -> dict:
    """Partial update of agent state (atomic read-modify-write).

    Args:
        agent_id: Agent identifier.
        updates: Dict of fields to update.

    Returns:
        Updated state dict.
    """
    if agent_id == "orchestrator":
        # Atomic read-modify-write with file lock
        return _atomic_update_orchestrator(updates)
    else:
        with _memory_lock:
            state = _states.get(agent_id, {})
            state.update(updates)
            _states[agent_id] = state
            return dict(state)


def delete_state(agent_id: str) -> None:
    """Remove state for an agent (cleanup on completion)."""
    if agent_id == "orchestrator":
        with _file_lock():
            if ORCHESTRATOR_STATE_FILE.exists():
                ORCHESTRATOR_STATE_FILE.unlink()
    else:
        with _memory_lock:
            _states.pop(agent_id, None)


def list_agents() -> list[str]:
    """List all agent IDs with active state."""
    agents = []
    if ORCHESTRATOR_STATE_FILE.exists():
        agents.append("orchestrator")
    with _memory_lock:
        agents.extend(_states.keys())
    return agents


class _file_lock:
    """Context manager for cross-process file locking."""

    def __init__(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._lock_file = None

    def __enter__(self):
        self._lock_file = open(ORCHESTRATOR_LOCK_FILE, "w")
        fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._lock_file:
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            self._lock_file.close()
        return False


def _load_orchestrator_state() -> Optional[dict]:
    """Load persisted orchestrator state from file (with locking)."""
    with _file_lock():
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if ORCHESTRATOR_STATE_FILE.exists():
            try:
                return json.loads(ORCHESTRATOR_STATE_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                return None
        return None


def _save_orchestrator_state(state: dict) -> None:
    """Save orchestrator state to file (with locking)."""
    with _file_lock():
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        ORCHESTRATOR_STATE_FILE.write_text(json.dumps(state, indent=2))


def _atomic_update_orchestrator(updates: dict) -> dict:
    """Atomically update orchestrator state (read-modify-write under lock)."""
    with _file_lock():
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if ORCHESTRATOR_STATE_FILE.exists():
            try:
                state = json.loads(ORCHESTRATOR_STATE_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                state = {}
        else:
            state = {}

        state.update(updates)
        ORCHESTRATOR_STATE_FILE.write_text(json.dumps(state, indent=2))
        return dict(state)
