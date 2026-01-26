"""MCP Router Permission Checker.

Enforces tool access control based on layered permission rules.
Layers: global -> roles -> agents -> workflow/phase (more specific wins)
"""

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Optional
import yaml


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


@dataclass
class AllowedResponse:
    """Response when a tool call is allowed."""
    blocked: bool = False


@dataclass
class AgentInfo:
    """Information about a registered agent."""
    agent_id: str
    agent_type: str
    roles: list[str] = field(default_factory=list)
    workflow: Optional[str] = None
    phase: Optional[str] = None


class AgentRegistry:
    """Registry of active agents and their metadata."""
    
    def __init__(self):
        self._agents: dict[str, AgentInfo] = {}
    
    def register(self, agent_id: str, agent_type: str, roles: list[str] = None) -> AgentInfo:
        """Register a new agent."""
        info = AgentInfo(
            agent_id=agent_id,
            agent_type=agent_type,
            roles=roles or [],
        )
        self._agents[agent_id] = info
        return info
    
    def get(self, agent_id: str) -> Optional[AgentInfo]:
        """Get agent info by ID."""
        return self._agents.get(agent_id)
    
    def update_phase(self, agent_id: str, workflow: str, phase: str):
        """Update agent's current workflow phase."""
        if agent_id in self._agents:
            self._agents[agent_id].workflow = workflow
            self._agents[agent_id].phase = phase
    
    def remove(self, agent_id: str):
        """Remove an agent from the registry."""
        self._agents.pop(agent_id, None)
    
    def list_agents(self) -> list[str]:
        """List all registered agent IDs."""
        return list(self._agents.keys())


class PermissionChecker:
    """Check tool permissions based on layered rules."""
    
    # Guidance templates for different block types
    GUIDANCE_TEMPLATES = {
        "superblocked": "This action is never permitted. Find an alternative approach.",
        "phase_blocked": "Tool {tool} blocked in {phase} phase. Transition to appropriate phase or delegate to another agent.",
        "agent_blocked": "Your agent type ({agent_type}) cannot use {tool}. Delegate to an appropriate agent type.",
        "not_allowed": "Tool {tool} not in your allowed list. Check if a router-prefixed version exists (mcp__router__*).",
        "blocked": "Tool {tool} is blocked by current permissions.",
    }
    
    def __init__(self, config_path: Optional[Path] = None):
        """Initialize with optional config path."""
        self.config_path = config_path or Path(__file__).parent.parent / "config" / "permissions.yaml"
        self.config = self._load_config()
    
    def _load_config(self) -> dict:
        """Load permissions config from YAML."""
        if not self.config_path.exists():
            return {"global": {"allowed": [], "blocked": [], "superblocked": []}}
        
        with open(self.config_path) as f:
            return yaml.safe_load(f) or {}
    
    def reload_config(self):
        """Reload configuration from disk."""
        self.config = self._load_config()
    
    def _matches_pattern(self, pattern: str, tool: str, args: dict) -> bool:
        """Check if a tool call matches a permission pattern.
        
        Pattern formats:
        - "Edit" - exact tool name
        - "mcp__router__*" - glob pattern on tool name
        - "Bash(mcp-call*)" - tool name + argument glob
        - "Edit(tests/**)" - tool name + file_path arg glob
        """
        if "(" in pattern:
            # Tool with argument pattern: Bash(mcp-call*)
            tool_part, arg_pattern = pattern.rstrip(")").split("(", 1)
            if not fnmatch(tool, tool_part):
                return False
            # Check relevant argument based on tool type
            if "Bash" in tool_part or "bash" in tool_part:
                arg_value = args.get("command", "")
            else:
                # For file tools, check file_path or relative_path
                arg_value = args.get("file_path") or args.get("relative_path") or args.get("path") or ""
            return fnmatch(str(arg_value), arg_pattern)
        else:
            # Simple tool name or glob
            return fnmatch(tool, pattern)
    
    def _matches_any(self, tool: str, args: dict, patterns: list) -> tuple[bool, str]:
        """Check if tool matches any pattern in list. Returns (matched, pattern)."""
        for pattern in patterns:
            if self._matches_pattern(pattern, tool, args):
                return True, pattern
        return False, ""
    
    def _apply_rules(self, effective: dict, rules: dict):
        """Apply a layer's rules to effective permissions.
        
        More specific layers override less specific ones:
        - If this layer allows a tool, remove it from blocked
        - If this layer blocks a tool, remove it from allowed
        """
        if not rules:
            return
        
        allowed = rules.get("allowed", [])
        blocked = rules.get("blocked", [])
        
        # Adding to allowed removes from blocked (more specific wins)
        for pattern in allowed:
            effective["allowed"].add(pattern)
            effective["blocked"].discard(pattern)
        
        # Adding to blocked removes from allowed (more specific wins)
        for pattern in blocked:
            effective["blocked"].add(pattern)
            effective["allowed"].discard(pattern)
    
    def _get_guidance(self, block_type: str, **kwargs) -> str:
        """Get guidance message for a block type."""
        template = self.GUIDANCE_TEMPLATES.get(block_type, self.GUIDANCE_TEMPLATES["blocked"])
        return template.format(**kwargs)
    
    def check(
        self,
        tool: str,
        args: dict,
        agent_id: str = "",
        agent_type: str = "",
        roles: list[str] = None,
        workflow: str = "",
        phase: str = "",
    ) -> tuple[bool, Optional[BlockedResponse]]:
        """Check if a tool call is permitted.
        
        Args:
            tool: Tool name being called
            args: Tool arguments
            agent_id: ID of the calling agent
            agent_type: Type of the calling agent
            roles: List of roles assigned to the agent
            workflow: Current workflow (e.g., "iterate", "debug")
            phase: Current phase within workflow (e.g., "orchestrate", "implement")
        
        Returns:
            (allowed: bool, response: BlockedResponse or None)
        """
        roles = roles or []
        global_rules = self.config.get("global", {})
        
        # 1. Check superblocked (global only) - immediate reject
        superblocked = global_rules.get("superblocked", [])
        matched, pattern = self._matches_any(tool, args, superblocked)
        if matched:
            return False, BlockedResponse(
                reason="superblocked - cannot override",
                tool=tool,
                agent_type=agent_type,
                agent_id=agent_id,
                phase=f"{workflow}/{phase}" if workflow else "",
                rule_that_blocked=f"global.superblocked: {pattern}",
                guidance=self._get_guidance("superblocked"),
            )
        
        # 2. Build effective permissions by layer
        effective = {"allowed": set(), "blocked": set()}
        
        # Layer 1: Global
        self._apply_rules(effective, global_rules)
        
        # Layer 2: Roles
        roles_config = self.config.get("roles", {})
        for role in roles:
            if role in roles_config:
                self._apply_rules(effective, roles_config[role])
        
        # Layer 3: Agent type
        agents_config = self.config.get("agents", {})
        if agent_type and agent_type in agents_config:
            self._apply_rules(effective, agents_config[agent_type])
        
        # Layer 4: Workflow/phase
        if workflow and phase:
            workflows_config = self.config.get("workflows", {})
            if workflow in workflows_config:
                workflow_phases = workflows_config[workflow]
                if phase in workflow_phases:
                    self._apply_rules(effective, workflow_phases[phase])
        
        # 3. Check blocked first (more specific blocks override less specific allows)
        matched, pattern = self._matches_any(tool, args, list(effective["blocked"]))
        if matched:
            # Determine block source for better guidance
            if workflow and phase:
                block_type = "phase_blocked"
                phase_str = f"{workflow}/{phase}"
            elif agent_type:
                block_type = "agent_blocked"
                phase_str = ""
            else:
                block_type = "blocked"
                phase_str = ""
            
            return False, BlockedResponse(
                reason=f"blocked by {block_type.replace('_', ' ')}",
                tool=tool,
                agent_type=agent_type,
                agent_id=agent_id,
                phase=phase_str,
                rule_that_blocked=pattern,
                guidance=self._get_guidance(
                    block_type, 
                    tool=tool, 
                    agent_type=agent_type,
                    phase=phase_str,
                ),
            )
        
        # 4. Must be explicitly allowed
        matched, _ = self._matches_any(tool, args, list(effective["allowed"]))
        if matched:
            return True, None
        
        # 5. Default deny
        return False, BlockedResponse(
            reason="not in allowed list",
            tool=tool,
            agent_type=agent_type,
            agent_id=agent_id,
            phase=f"{workflow}/{phase}" if workflow else "",
            rule_that_blocked="(no matching allow rule)",
            guidance=self._get_guidance("not_allowed", tool=tool),
        )


# Convenience function for simple checks
def check_permission(
    tool: str,
    args: dict = None,
    agent_type: str = "",
    roles: list[str] = None,
    workflow: str = "",
    phase: str = "",
    config_path: Path = None,
) -> tuple[bool, Optional[dict]]:
    """Convenience function to check a single permission.
    
    Returns (allowed, blocked_response_dict or None)
    """
    checker = PermissionChecker(config_path)
    allowed, response = checker.check(
        tool=tool,
        args=args or {},
        agent_type=agent_type,
        roles=roles,
        workflow=workflow,
        phase=phase,
    )
    if response:
        return allowed, response.to_dict()
    return allowed, None
