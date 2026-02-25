"""JSON file-based state persistence with atomic writes."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _get_state_dir() -> Path:
    """Return the state directory, preferring env var override."""
    env_dir = os.environ.get("ORCHESTRATION_STATE_DIR")
    if env_dir:
        return Path(env_dir)
    # Default: <plugin_root>/.state/
    plugin_root = Path(__file__).parent.parent
    return plugin_root / ".state"


class OrchestrationState:
    """Manages orchestration state as a JSON file on disk.

    State is stored as a flat JSON object. Supports dotted key paths
    for nested access (e.g., "tasks.stack.status").
    """

    def __init__(self, project_name: str):
        self._project_name = project_name
        state_dir = _get_state_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        self._state_path = state_dir / f"{project_name}.json"
        self._data: dict[str, Any] = {}

    def exists(self) -> bool:
        return self._state_path.exists()

    def load(self) -> None:
        """Load state from disk. No-op if file doesn't exist."""
        if self._state_path.exists():
            self._data = json.loads(self._state_path.read_text())

    def save(self) -> None:
        """Atomically write state to disk via tempfile + rename."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._state_path.parent),
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self._data, f, indent=2)
            os.rename(tmp_path, str(self._state_path))
        except BaseException:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value by dotted key path. Returns default if missing."""
        parts = key.split(".")
        current = self._data
        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def set(self, key: str, value: Any) -> None:
        """Set a value by dotted key path, creating intermediate dicts."""
        parts = key.split(".")
        current = self._data
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    def update_task(self, task_name: str, **kwargs: Any) -> None:
        """Update a task's state, creating the tasks dict if needed."""
        if "tasks" not in self._data:
            self._data["tasks"] = {}
        if task_name not in self._data["tasks"]:
            self._data["tasks"][task_name] = {}
        self._data["tasks"][task_name].update(kwargs)

    def clear(self) -> None:
        """Remove the state file and reset in-memory data."""
        self._data = {}
        try:
            self._state_path.unlink()
        except FileNotFoundError:
            pass
