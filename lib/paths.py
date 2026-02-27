"""Centralized path resolution for agent-swarm.

All paths in the plugin should be derived from two anchors:

  PLUGIN_ROOT  - The root directory of the agent-swarm plugin.
                 Default: resolved from this file's location.
                 Override: AGENT_SWARM_ROOT env var.

  CLAUDE_HOME  - The user's .claude configuration directory.
                 Default: ~/.claude
                 Override: CLAUDE_HOME env var.

Usage:
    from lib.paths import PLUGIN_ROOT, STATE_DIR, CLAUDE_HOME
    # or for config files with {{PLUGIN_ROOT}} placeholders:
    from lib.paths import resolve_config_paths
"""

import os
from pathlib import Path
from typing import Any

# ── Anchors ──────────────────────────────────────────────────────────

_env_root = os.environ.get("AGENT_SWARM_ROOT")
PLUGIN_ROOT: Path = Path(_env_root) if _env_root else Path(__file__).resolve().parent.parent

_env_claude = os.environ.get("CLAUDE_HOME")
CLAUDE_HOME: Path = Path(_env_claude) if _env_claude else Path.home() / ".claude"

# ── Derived paths ────────────────────────────────────────────────────

STATE_DIR: Path = PLUGIN_ROOT / ".state"
CONFIG_DIR: Path = PLUGIN_ROOT / "config"
LIB_DIR: Path = PLUGIN_ROOT / "lib"
HOOKS_DIR: Path = PLUGIN_ROOT / "hooks"
SCRIPTS_DIR: Path = PLUGIN_ROOT / "scripts"

CLAUDE_PROJECTS: Path = CLAUDE_HOME / "projects"

# ── Placeholder resolution ───────────────────────────────────────────

_PLACEHOLDERS = {
    "{{PLUGIN_ROOT}}": lambda: str(PLUGIN_ROOT),
    "${AGENT_SWARM_ROOT}": lambda: str(PLUGIN_ROOT),
    "{{CLAUDE_HOME}}": lambda: str(CLAUDE_HOME),
    "${CLAUDE_HOME}": lambda: str(CLAUDE_HOME),
}


def resolve_plugin_path(s: str) -> str:
    """Replace {{PLUGIN_ROOT}} and {{CLAUDE_HOME}} placeholders in a string."""
    for placeholder, resolver in _PLACEHOLDERS.items():
        if placeholder in s:
            s = s.replace(placeholder, resolver())
    return s


def resolve_config_paths(data: Any) -> Any:
    """Recursively resolve placeholders in config data (dicts, lists, strings)."""
    if isinstance(data, str):
        return resolve_plugin_path(data)
    if isinstance(data, list):
        return [resolve_config_paths(item) for item in data]
    if isinstance(data, dict):
        return {k: resolve_config_paths(v) for k, v in data.items()}
    return data
