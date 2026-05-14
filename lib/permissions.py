#!/usr/bin/env python3
"""Daemon-side permission checker.

Evaluates tool access rules from permissions.yaml based on agent type,
roles, and workflow phase. Thread-safe for concurrent checks.

Precedence (highest first):
    Level 0: SUPERBLOCK — immediate reject, no override
    Level 1: Workflow/Phase rules
    Level 2: Agent-type rules
    Level 3: Role-based rules
    Level 4: Global rules
    Level 5: Default BLOCK
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

from lib.errors import RouterError


@dataclass
class AgentInfo:
    """Information about a registered agent."""

    agent_id: str
    agent_type: str
    roles: list[str] = field(default_factory=list)
    workflow: str | None = None
    phase: str | None = None
    session_id: str = ""


@dataclass
class BlockedResponse:
    """Response when a tool call is blocked."""

    blocked: bool = True
    reason: str = ""
    tool: str = ""
    agent_type: str = ""
    agent_id: str = ""
    phase: str = ""
    rule_that_blocked: str = ""
    guidance: str = ""

    def to_dict(self) -> dict:
        return {
            "blocked": self.blocked,
            "reason": self.reason,
            "tool": self.tool,
            "agent_type": self.agent_type,
            "agent_id": self.agent_id,
            "phase": self.phase,
            "rule_that_blocked": self.rule_that_blocked,
            "guidance": self.guidance,
        }


# Guidance templates for different block types
_GUIDANCE = {
    "superblocked": "This action is never permitted. Find an alternative approach.",
    "phase_blocked": (
        "Tool {tool} blocked in {phase} phase. "
        "Transition to appropriate phase or delegate to another agent."
    ),
    "agent_blocked": (
        "Your agent type ({agent_type}) cannot use {tool}. "
        "Delegate to an appropriate agent type."
    ),
    "role_blocked": "Tool {tool} is blocked by your role permissions.",
    "not_allowed": (
        "Tool {tool} not in your allowed list. "
        "Check if a router-prefixed version exists (mcp__router__*)."
    ),
    "blocked": "Tool {tool} is blocked by current permissions.",
}


def _matches_pattern(pattern: str, tool: str, args: dict) -> bool:
    """Check if a tool call matches a permission pattern.

    Pattern formats:
        "Edit"              — exact tool name
        "serena__*"         — fnmatch glob on tool name
        "native__bash(pytest*)" — tool match + fnmatch on args["command"]
        "native__edit_file(tests/**)" — tool + file_path arg glob
    """
    if "(" in pattern:
        tool_part, arg_pattern = pattern.rstrip(")").split("(", 1)
        if not fnmatch(tool, tool_part):
            return False
        if "bash" in tool_part.lower():
            arg_value = args.get("command", "")
        else:
            arg_value = (
                args.get("file_path")
                or args.get("relative_path")
                or args.get("path")
                or ""
            )
        return fnmatch(str(arg_value), arg_pattern)
    return fnmatch(tool, pattern)


def _matches_any(tool: str, args: dict, patterns: list[str]) -> tuple[bool, str]:
    """Check if tool matches any pattern in list. Returns (matched, pattern)."""
    for pattern in patterns:
        if _matches_pattern(pattern, tool, args):
            return True, pattern
    return False, ""


class PermissionChecker:
    """Evaluates tool access rules from permissions.yaml.

    Thread-safe. Agent registration protected by RLock; rule evaluation
    is read-only on immutable config snapshot.
    """

    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path
        self._lock = threading.RLock()
        self._agents: dict[str, AgentInfo] = {}
        self._rules = self._load_config()

    def _load_config(self) -> dict:
        if not self._config_path.exists():
            return {"global": {"allowed": [], "blocked": [], "superblocked": []}}
        with open(self._config_path) as f:
            return yaml.safe_load(f) or {}

    def check(
        self,
        tool: str,
        args: dict,
        agent: AgentInfo | None = None,
    ) -> tuple[bool, BlockedResponse | None]:
        """Check if a tool call is allowed.

        Returns:
            (True, None) if allowed.
            (False, BlockedResponse) if blocked.
        """
        rules = self._rules
        global_rules = rules.get("global", {})
        agent_type = agent.agent_type if agent else ""
        agent_id = agent.agent_id if agent else ""
        roles = agent.roles if agent else []
        workflow = agent.workflow if agent else None
        phase = agent.phase if agent else None
        phase_str = f"{workflow}/{phase}" if workflow and phase else ""

        ctx = {
            "tool": tool,
            "agent_type": agent_type,
            "agent_id": agent_id,
            "phase": phase_str,
        }

        # Level 0: Superblock — immediate reject, no override
        superblocked = global_rules.get("superblocked", [])
        matched, pattern = _matches_any(tool, args, superblocked)
        if matched:
            return False, BlockedResponse(
                reason="superblocked - cannot override",
                tool=tool,
                agent_type=agent_type,
                agent_id=agent_id,
                phase=phase_str,
                rule_that_blocked=f"global.superblocked: {pattern}",
                guidance=_GUIDANCE["superblocked"],
            )

        # Level 1: Workflow/Phase rules
        if workflow and phase:
            wf_config = rules.get("workflows", {})
            if workflow in wf_config and phase in wf_config[workflow]:
                result = self._check_level(
                    tool, args, wf_config[workflow][phase], "phase_blocked", ctx
                )
                if result is not None:
                    return result

        # Level 2: Agent-type rules
        if agent_type:
            agents_config = rules.get("agents", {})
            if agent_type in agents_config:
                result = self._check_level(
                    tool, args, agents_config[agent_type], "agent_blocked", ctx
                )
                if result is not None:
                    return result

        # Level 3: Role-based rules (checked in order)
        roles_config = rules.get("roles", {})
        for role in roles:
            if role in roles_config:
                result = self._check_level(
                    tool, args, roles_config[role], "role_blocked", ctx
                )
                if result is not None:
                    return result

        # Level 4: Global rules
        result = self._check_level(tool, args, global_rules, "not_allowed", ctx)
        if result is not None:
            return result

        # Level 5: Default deny
        return False, BlockedResponse(
            reason="not in allowed list",
            tool=tool,
            agent_type=agent_type,
            agent_id=agent_id,
            phase=phase_str,
            rule_that_blocked="(no matching rule)",
            guidance=_GUIDANCE["not_allowed"].format(**ctx),
        )

    def _check_level(
        self,
        tool: str,
        args: dict,
        level_rules: dict,
        block_type: str,
        ctx: dict[str, str],
    ) -> tuple[bool, BlockedResponse | None] | None:
        """Check blocked then allowed at a single precedence level.

        Returns:
            (False, BlockedResponse) if blocked at this level.
            (True, None) if allowed at this level.
            None if no match (fall through to lower levels).
        """
        blocked = level_rules.get("blocked", [])
        allowed = level_rules.get("allowed", [])

        matched_blocked, pattern = _matches_any(tool, args, blocked)
        if matched_blocked:
            guidance_key = block_type if block_type in _GUIDANCE else "blocked"
            return False, BlockedResponse(
                reason=f"blocked by {block_type.replace('_', ' ')}",
                tool=ctx["tool"],
                agent_type=ctx["agent_type"],
                agent_id=ctx["agent_id"],
                phase=ctx["phase"],
                rule_that_blocked=pattern,
                guidance=_GUIDANCE[guidance_key].format(**ctx),
            )

        matched_allowed, _ = _matches_any(tool, args, allowed)
        if matched_allowed:
            return True, None

        return None

    # --- Agent registry ---

    def register_agent(
        self,
        agent_id: str,
        agent_type: str,
        roles: list[str] | None = None,
    ) -> AgentInfo:
        """Register an agent for permission tracking. Thread-safe."""
        info = AgentInfo(
            agent_id=agent_id,
            agent_type=agent_type,
            roles=roles or [],
        )
        with self._lock:
            self._agents[agent_id] = info
        return info

    def update_agent_phase(
        self,
        agent_id: str,
        workflow: str,
        phase: str,
    ) -> None:
        """Update an agent's workflow and phase. Thread-safe."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                raise RouterError(f"Agent not registered: {agent_id}")
            agent.workflow = workflow
            agent.phase = phase

    def propagate_phase(self, workflow: str, phase: str) -> int:
        """Update bound phase for every agent registered against `workflow`.

        Returns the number of agents updated. Called by the controller when a
        workflow advances phase, so bound agents do not keep a stale phase
        snapshot for the rest of the session.
        """
        updated = 0
        with self._lock:
            for agent in self._agents.values():
                if agent.workflow == workflow:
                    agent.phase = phase
                    updated += 1
        return updated

    def get_agent(self, agent_id: str) -> AgentInfo | None:
        """Return registered agent info, or None."""
        with self._lock:
            return self._agents.get(agent_id)

    def remove_agent(self, agent_id: str) -> None:
        """Remove an agent from the registry. Thread-safe."""
        with self._lock:
            self._agents.pop(agent_id, None)

    def get_allowed_tools(self, agent_type: str | None = None) -> list[str]:
        """Return tool patterns allowed for the given agent type.

        If agent_type is None, returns global allowed list.
        """
        if agent_type:
            agents_config = self._rules.get("agents", {})
            if agent_type in agents_config:
                return list(agents_config[agent_type].get("allowed", []))
        return list(self._rules.get("global", {}).get("allowed", []))

    def reload(self) -> None:
        """Re-read permissions.yaml from disk. Thread-safe."""
        new_rules = self._load_config()
        with self._lock:
            self._rules = new_rules
