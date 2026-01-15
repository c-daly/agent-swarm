"""Unified State Management for agent-swarm workflows.

Consolidates iterate.json, worker_pool.json, and review_gate state into
a single workflow.json file to reduce I/O and improve consistency.
"""

import json
import os
from pathlib import Path
from typing import Optional

# State format version - increment when structure changes
STATE_VERSION = 1


def _get_state_dir() -> Path:
    """Get state directory, allowing runtime override via environment."""
    override = os.environ.get("ITERATE_STATE_DIR")
    return Path(override) if override else Path.home() / ".claude/plugins/agent-swarm/.state"


def _get_unified_file() -> Path:
    """Get unified state file path."""
    return _get_state_dir() / "workflow.json"


def _get_legacy_files() -> dict:
    """Get legacy file paths for migration."""
    state_dir = _get_state_dir()
    return {
        "iterate": state_dir / "iterate.json",
        "worker_pool": state_dir / "worker_pool.json",
        "session": state_dir / "session.json",  # Contains review_gate
    }


def _default_state() -> dict:
    """Return default empty unified state."""
    return {
        "version": STATE_VERSION,
        "iterate": {},
        "worker_pool": {"active": False},
        "review_gate": {},
    }


def load_unified_state() -> dict:
    """Load unified workflow state from disk.

    Returns:
        Dict containing iterate, worker_pool, and review_gate state.
        Returns default state if no file exists.
    """
    state_dir = _get_state_dir()
    unified_file = _get_unified_file()
    legacy_files = _get_legacy_files()

    state_dir.mkdir(parents=True, exist_ok=True)

    # Try unified file first
    if unified_file.exists():
        try:
            state = json.loads(unified_file.read_text())
            # Ensure version is current
            if state.get("version", 0) < STATE_VERSION:
                state["version"] = STATE_VERSION
            return state
        except (json.JSONDecodeError, OSError):
            pass

    # Fall back to loading from legacy files
    state = _default_state()

    # Load iterate state
    if legacy_files["iterate"].exists():
        try:
            state["iterate"] = json.loads(legacy_files["iterate"].read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Load worker pool state
    if legacy_files["worker_pool"].exists():
        try:
            state["worker_pool"] = json.loads(legacy_files["worker_pool"].read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Load review gate from session.json
    if legacy_files["session"].exists():
        try:
            session = json.loads(legacy_files["session"].read_text())
            state["review_gate"] = session.get("review_gate", {})
        except (json.JSONDecodeError, OSError):
            pass

    return state


def save_unified_state(state: dict) -> None:
    """Save unified workflow state to disk atomically.

    Args:
        state: Dict containing iterate, worker_pool, and review_gate state.
    """
    state_dir = _get_state_dir()
    unified_file = _get_unified_file()

    state_dir.mkdir(parents=True, exist_ok=True)

    # Ensure version is set
    if "version" not in state:
        state["version"] = STATE_VERSION

    # Write atomically via temp file
    temp_file = unified_file.with_suffix(".tmp")
    temp_file.write_text(json.dumps(state, indent=2) + "\n")
    temp_file.rename(unified_file)


def migrate_to_unified(state_dir: Optional[Path] = None) -> dict:
    """Migrate from legacy split files to unified format.

    Args:
        state_dir: Directory containing state files (defaults to _get_state_dir()).

    Returns:
        Migrated unified state dict.
    """
    if state_dir is None:
        state_dir = _get_state_dir()

    # Update file paths for provided dir
    legacy_files = {
        "iterate": state_dir / "iterate.json",
        "worker_pool": state_dir / "worker_pool.json",
        "session": state_dir / "session.json",
    }

    state = _default_state()

    # Load from each legacy file
    for key, path in legacy_files.items():
        if path.exists():
            try:
                data = json.loads(path.read_text())
                if key == "session":
                    state["review_gate"] = data.get("review_gate", {})
                else:
                    state[key] = data
                # Backup original
                backup_path = path.with_suffix(".json.bak")
                path.rename(backup_path)
            except (json.JSONDecodeError, OSError):
                pass

    # Save unified state
    unified_file = state_dir / "workflow.json"
    unified_file.write_text(json.dumps(state, indent=2) + "\n")

    return state


# Convenience accessors for individual modules


def get_iterate_state() -> dict:
    """Get just the iterate workflow state."""
    return load_unified_state().get("iterate", {})


def set_iterate_state(iterate_state: dict) -> None:
    """Update just the iterate workflow state."""
    state = load_unified_state()
    state["iterate"] = iterate_state
    save_unified_state(state)


def get_worker_pool_state() -> dict:
    """Get just the worker pool state."""
    return load_unified_state().get("worker_pool", {"active": False})


def set_worker_pool_state(pool_state: dict) -> None:
    """Update just the worker pool state."""
    state = load_unified_state()
    state["worker_pool"] = pool_state
    save_unified_state(state)


def get_review_gate_state() -> dict:
    """Get just the review gate state."""
    return load_unified_state().get("review_gate", {})


def set_review_gate_state(gate_state: dict) -> None:
    """Update just the review gate state."""
    state = load_unified_state()
    state["review_gate"] = gate_state
    save_unified_state(state)
