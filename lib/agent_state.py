"""Centralized state management for agent-swarm.

All state access goes through StateManager. This provides:
- File locking for concurrent access
- In-memory caching to reduce disk I/O
- Single source of truth for session state
"""
import json
import os
from pathlib import Path
from typing import Any, Callable, Optional

from filelock import FileLock
import copy

STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"


class StateManager:
    """Centralized state manager with in-memory caching and file locking."""

    _instances: dict[str, "StateManager"] = {}

    def __init__(self, agent_id: str = "main"):
        self.agent_id = agent_id
        self._cache: Optional[dict] = None
        self._dirty = False

    @classmethod
    def get(cls, agent_id: Optional[str] = None) -> "StateManager":
        """Get or create StateManager for agent_id."""
        if agent_id is None:
            agent_id = os.environ.get("CLAUDE_AGENT_ID", "main")
        if agent_id not in cls._instances:
            cls._instances[agent_id] = cls(agent_id)
        return cls._instances[agent_id]

    @classmethod
    def main(cls) -> "StateManager":
        """Get the main session's StateManager."""
        return cls.get("main")

    @property
    def state_file(self) -> Path:
        if self.agent_id == "main":
            return STATE_DIR / "session.json"
        return STATE_DIR / f"session.{self.agent_id}.json"

    @property
    def lock_file(self) -> Path:
        return self.state_file.parent / (self.state_file.name + ".lock")

    def load(self) -> dict:
        """Load state, using cache if available."""
        if self._cache is not None:
            return copy.deepcopy(self._cache)
        lock = FileLock(str(self.lock_file))
        with lock:
            if not self.state_file.exists():
                self._cache = {}
            else:
                try:
                    self._cache = json.loads(self.state_file.read_text())
                except (json.JSONDecodeError, OSError):
                    self._cache = {}
        return copy.deepcopy(self._cache)

    def save(self) -> None:
        """Save cached state to disk."""
        if self._cache is None:
            return
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(self.lock_file))
        with lock:
            self.state_file.write_text(json.dumps(self._cache, indent=2))
        self._dirty = False

    def get_value(self, key: str, default: Any = None) -> Any:
        """Get a value from state."""
        self.load()  # Ensure cache is loaded
        return self._cache.get(key, default)

    def set_value(self, key: str, value: Any, persist: bool = True) -> None:
        """Set a value in state."""
        self.load()  # Ensure cache is loaded
        self._cache[key] = value
        self._dirty = True
        if persist:
            self.save()

    def update(self, updater: Callable[[dict], dict]) -> dict:
        """Atomically update state with a function."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(self.lock_file))
        with lock:
            if self.state_file.exists():
                try:
                    state = json.loads(self.state_file.read_text())
                except (json.JSONDecodeError, OSError):
                    state = {}
            else:
                state = {}
            updated = updater(state)
            self.state_file.write_text(json.dumps(updated, indent=2))
            self._cache = updated
            self._dirty = False
            return updated

    def invalidate(self) -> None:
        """Clear cache, forcing next load from disk."""
        self._cache = None
        self._dirty = False

    def cleanup(self) -> bool:
        """Delete this agent's state file."""
        if self.agent_id == "main":
            return False
        if self.state_file.exists():
            self.state_file.unlink()
            self._cache = None
            if self.agent_id in self._instances:
                del self._instances[self.agent_id]
            return True
        return False

    @classmethod
    def clear_cache(cls) -> None:
        """Clear all cached instances. Use in tests."""
        cls._instances.clear()

    # Convenience properties for common state fields
    @property
    def phase(self) -> Optional[str]:
        return self.get_value("phase") or self.get_value("iterate_phase")

    @phase.setter
    def phase(self, value: str) -> None:
        self.set_value("phase", value)

    @property
    def active_agents(self) -> int:
        return self.get_value("active_agents", 0)

    @active_agents.setter
    def active_agents(self, value: int) -> None:
        self.set_value("active_agents", value)

    @property
    def workflow_invoked(self) -> bool:
        return self.get_value("workflow_invoked", False)

    @workflow_invoked.setter
    def workflow_invoked(self, value: bool) -> None:
        self.set_value("workflow_invoked", value)


# Legacy function interface for backward compatibility
def get_agent_id() -> str:
    return os.environ.get("CLAUDE_AGENT_ID", "main")

def get_state_file(agent_id: Optional[str] = None) -> Path:
    return StateManager.get(agent_id).state_file

def load_state(agent_id: Optional[str] = None) -> dict:
    return StateManager.get(agent_id).load()

def save_state(state: dict, agent_id: Optional[str] = None) -> None:
    mgr = StateManager.get(agent_id)
    mgr._cache = copy.deepcopy(state)
    mgr.save()

def update_state(updater: Callable[[dict], dict], agent_id: Optional[str] = None) -> dict:
    return StateManager.get(agent_id).update(updater)

def cleanup_agent_state(agent_id: str) -> bool:
    return StateManager.get(agent_id).cleanup()
