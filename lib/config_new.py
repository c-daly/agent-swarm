#!/usr/bin/env python3
"""Configuration loading for the daemon.

Loads and validates all configuration from:
- config/backends.json — External backend definitions
- config/workflow.json — Workflow phases, iteration modes, execution settings
- config/permissions.yaml — Permission rules (path only, parsed by permissions.py)
- agents/*.md — Agent definitions with YAML frontmatter
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """Raised when configuration loading or validation fails."""


# --- Dataclasses ---


@dataclass(frozen=True)
class BackendConfig:
    """Configuration for an external MCP backend."""

    name: str
    command: tuple[str, ...]
    tool_prefix: str = ""


@dataclass(frozen=True)
class PhaseConfig:
    """Configuration for a workflow phase."""

    name: str
    description: str = ""
    checkpoint: bool = False
    agents: tuple[str, ...] = ()
    model: str | None = None
    enforce_subagents: bool = False


@dataclass(frozen=True)
class WorkflowConfig:
    """Full workflow configuration."""

    phases: dict[str, PhaseConfig]
    orchestrator: dict[str, Any]
    checkpoints: dict[str, bool]
    execution: dict[str, Any]
    iteration_modes: dict[str, Any]
    enforcement: dict[str, Any]


@dataclass(frozen=True)
class AgentConfig:
    """Configuration for an agent type, parsed from frontmatter."""

    name: str
    description: str = ""
    tools: str = ""
    model: str | None = None
    prompt: str = ""


@dataclass(frozen=True)
class AllConfig:
    """Combined configuration from all sources."""

    backends: dict[str, BackendConfig]
    workflow: WorkflowConfig | None
    agents: dict[str, AgentConfig]
    permissions_path: Path | None


# --- Loaders ---

_INTERNAL_BACKENDS = frozenset({"native", "workflow"})


def load_backends(config_dir: Path) -> dict[str, BackendConfig]:
    """Load backend configurations from config/backends.json.

    Filters out internal backends (native, workflow).
    """
    path = config_dir / "backends.json"
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ConfigError(f"Failed to load {path}: {e}")

    if not isinstance(data, dict):
        raise ConfigError(f"Expected object in {path}, got {type(data).__name__}")

    backends: dict[str, BackendConfig] = {}
    for name, cfg in data.items():
        if name in _INTERNAL_BACKENDS:
            continue
        if not isinstance(cfg, dict) or "command" not in cfg:
            raise ConfigError(f"Backend '{name}' missing required field 'command'")

        command = cfg["command"]
        if not isinstance(command, list):
            raise ConfigError(f"Backend '{name}': command must be a list")

        backends[name] = BackendConfig(
            name=name,
            command=tuple(command),
            tool_prefix=cfg.get("tool_prefix", ""),
        )

    return backends


def load_workflow(config_dir: Path) -> WorkflowConfig | None:
    """Load workflow configuration from config/workflow.json."""
    path = config_dir / "workflow.json"
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ConfigError(f"Failed to load {path}: {e}")

    if not isinstance(data, dict):
        raise ConfigError(f"Expected object in {path}")

    phases: dict[str, PhaseConfig] = {}
    for name, phase_data in data.get("phases", {}).items():
        phases[name] = PhaseConfig(
            name=name,
            description=phase_data.get("description", ""),
            checkpoint=phase_data.get("checkpoint", False),
            agents=tuple(phase_data.get("agents", [])),
            model=phase_data.get("model"),
            enforce_subagents=phase_data.get("enforce_subagents", False),
        )

    return WorkflowConfig(
        phases=phases,
        orchestrator=data.get("orchestrator", {}),
        checkpoints=data.get("checkpoints", {}),
        execution=data.get("execution", {}),
        iteration_modes=data.get("iteration_modes", {}),
        enforcement=data.get("enforcement", {}),
    )


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse YAML-like frontmatter from a markdown file.

    Returns (frontmatter_dict, body).
    Simple key: value parsing — no nested structures.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    fm_text, body = match.group(1), match.group(2)
    fm: dict[str, str] = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip()

    return fm, body.strip()


def load_agents(agents_dir: Path) -> dict[str, AgentConfig]:
    """Load agent configurations from agents/*.md files.

    Each file has YAML frontmatter with name, tools, description, model.
    The body becomes the agent's prompt.
    """
    if not agents_dir.exists():
        return {}

    agents: dict[str, AgentConfig] = {}
    for md_file in sorted(agents_dir.glob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError:
            continue

        fm, body = _parse_frontmatter(text)
        name = fm.get("name", md_file.stem)

        agents[name] = AgentConfig(
            name=name,
            description=fm.get("description", ""),
            tools=fm.get("tools", ""),
            model=fm.get("model"),
            prompt=body,
        )

    return agents


def load_permissions(config_dir: Path) -> Path | None:
    """Return the path to permissions.yaml if it exists.

    Actual parsing is handled by lib/permissions.py.
    """
    path = config_dir / "permissions.yaml"
    return path if path.exists() else None


def load_all(base_dir: Path) -> AllConfig:
    """Load all configuration from standard locations.

    Args:
        base_dir: Project root (parent of config/ and agents/)
    """
    config_dir = base_dir / "config"
    agents_dir = base_dir / "agents"

    return AllConfig(
        backends=load_backends(config_dir),
        workflow=load_workflow(config_dir),
        agents=load_agents(agents_dir),
        permissions_path=load_permissions(config_dir),
    )
