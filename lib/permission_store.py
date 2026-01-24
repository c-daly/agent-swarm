"""Permission store - centralized tool/action permissions.

Stored in workflow state under the 'permissions' key.
Agent reads permissions at session/task start and self-enforces.
"""

from dataclasses import dataclass, field
from typing import FrozenSet, Optional
import fnmatch
from pathlib import Path

from lib.tool_categories import (
    ToolCategory,
    TOOL_CATEGORIES,  # noqa: F401 - re-exported for API compatibility
    FILE_WRITE_TOOLS,
    WORKFLOW_CONTROL_TOOLS,
    get_tool_category,
)


@dataclass(frozen=True)
class PhasePermissions:
    """Permissions for a specific workflow phase."""
    allowed_categories: FrozenSet[ToolCategory] = field(default_factory=frozenset)
    blocked_tools: FrozenSet[str] = field(default_factory=frozenset)
    allowed_file_patterns: FrozenSet[str] = field(default_factory=lambda: frozenset({"**/*"}))
    blocked_file_patterns: FrozenSet[str] = field(default_factory=frozenset)
    blocked_commands: FrozenSet[str] = field(default_factory=frozenset)


@dataclass
class TaskConstraints:
    """Constraints for Task tool usage."""
    require_background: bool = False
    max_agents: int = 5
    allowed_agent_types: FrozenSet[str] = field(default_factory=frozenset)


@dataclass
class SubagentRestrictions:
    """Restrictions specific to subagents."""
    can_modify_workflow_state: bool = False
    can_modify_own_agent_state: bool = True
    can_spawn_subagents: bool = False
    inherits_phase: bool = True


@dataclass
class PermissionStore:
    """Complete permission context for an agent."""

    # Workflow context
    workflow_active: bool = False
    workflow_type: Optional[str] = None
    workflow_id: Optional[str] = None

    # Phase permissions
    phase: str = "none"
    phase_permissions: Optional[PhasePermissions] = None

    # Task constraints
    task_constraints: TaskConstraints = field(default_factory=TaskConstraints)

    # Subagent context
    is_subagent: bool = False
    agent_id: Optional[str] = None
    subagent_restrictions: SubagentRestrictions = field(default_factory=SubagentRestrictions)

    # Protected paths (always enforced)
    protected_paths: FrozenSet[str] = field(default_factory=lambda: frozenset({".state/", ".env"}))

    # Runtime tracking
    current_agents: int = 0
    verification_state: dict = field(default_factory=dict)

    def is_tool_allowed(self, tool_name: str, **context) -> tuple[bool, str]:
        """Check if tool is allowed given current permissions.

        Args:
            tool_name: Name of the tool to check
            **context: Additional context (file_path, command, etc.)

        Returns:
            (allowed, reason) tuple
        """
        # Check workflow requirement for write tools
        if not self.workflow_active and tool_name in FILE_WRITE_TOOLS:
            return False, "No active workflow - editing blocked"

        # Check phase permissions
        if self.phase_permissions:
            # Check blocked tools list
            if tool_name in self.phase_permissions.blocked_tools:
                return False, f"Tool {tool_name} blocked in {self.phase} phase"

            # Check category restrictions if allowed_categories is set
            if self.phase_permissions.allowed_categories:
                tool_category = get_tool_category(tool_name)
                if tool_category and tool_category not in self.phase_permissions.allowed_categories:
                    return False, f"Category {tool_category.name} not allowed in {self.phase} phase"

        # Check file patterns
        file_path = context.get("file_path")
        if file_path:
            if self._is_protected_path(file_path):
                return False, f"Path {file_path} is protected"

            # Check blocked file patterns
            if self.phase_permissions and self.phase_permissions.blocked_file_patterns:
                for pattern in self.phase_permissions.blocked_file_patterns:
                    if fnmatch.fnmatch(file_path, pattern):
                        return False, f"File {file_path} matches blocked pattern {pattern}"

            # Check allowed file patterns for write tools
            if tool_name in FILE_WRITE_TOOLS and self.phase_permissions:
                # Only check if patterns are set and not the default "allow all"
                patterns = self.phase_permissions.allowed_file_patterns
                if patterns and patterns != frozenset({"**/*"}):
                    path = Path(file_path)
                    allowed = any(
                        fnmatch.fnmatch(str(path), pattern) or
                        fnmatch.fnmatch(path.name, pattern)
                        for pattern in patterns
                    )
                    if not allowed:
                        return False, f"File {file_path} does not match allowed patterns for {self.phase} phase"

        # Check subagent restrictions
        if self.is_subagent:
            if tool_name in WORKFLOW_CONTROL_TOOLS:
                if not self.subagent_restrictions.can_modify_workflow_state:
                    return False, "Subagents cannot modify workflow state"
            if tool_name == "Task":
                if not self.subagent_restrictions.can_spawn_subagents:
                    return False, "Subagents cannot spawn additional agents"

        # Check task constraints
        if tool_name == "Task":
            if self.current_agents >= self.task_constraints.max_agents:
                return False, f"Max agents ({self.task_constraints.max_agents}) reached"
            if self.task_constraints.require_background:
                run_in_background = context.get("run_in_background", False)
                if not run_in_background:
                    return False, "Task tool must use run_in_background=true"

        # Check command restrictions for shell tools
        command = context.get("command")
        if command and self.phase_permissions and self.phase_permissions.blocked_commands:
            cmd_lower = command.lower().split()[0] if command.split() else ""
            if cmd_lower in self.phase_permissions.blocked_commands:
                return False, f"Command {cmd_lower} blocked in {self.phase} phase"

        return True, ""

    def _is_protected_path(self, path: str) -> bool:
        """Check if path is in protected paths."""
        return any(path.startswith(p.rstrip('/')) for p in self.protected_paths)

    def to_dict(self) -> dict:
        """Serialize to dict for storage in workflow state."""
        return {
            "workflow_active": self.workflow_active,
            "workflow_type": self.workflow_type,
            "workflow_id": self.workflow_id,
            "phase": self.phase,
            "phase_permissions": {
                "allowed_categories": [c.name for c in self.phase_permissions.allowed_categories] if self.phase_permissions else [],
                "blocked_tools": list(self.phase_permissions.blocked_tools) if self.phase_permissions else [],
                "allowed_file_patterns": list(self.phase_permissions.allowed_file_patterns) if self.phase_permissions else [],
                "blocked_file_patterns": list(self.phase_permissions.blocked_file_patterns) if self.phase_permissions else [],
                "blocked_commands": list(self.phase_permissions.blocked_commands) if self.phase_permissions else [],
            } if self.phase_permissions else None,
            "task_constraints": {
                "require_background": self.task_constraints.require_background,
                "max_agents": self.task_constraints.max_agents,
                "allowed_agent_types": list(self.task_constraints.allowed_agent_types),
            },
            "is_subagent": self.is_subagent,
            "agent_id": self.agent_id,
            "subagent_restrictions": {
                "can_modify_workflow_state": self.subagent_restrictions.can_modify_workflow_state,
                "can_modify_own_agent_state": self.subagent_restrictions.can_modify_own_agent_state,
                "can_spawn_subagents": self.subagent_restrictions.can_spawn_subagents,
                "inherits_phase": self.subagent_restrictions.inherits_phase,
            },
            "protected_paths": list(self.protected_paths),
            "current_agents": self.current_agents,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PermissionStore":
        """Deserialize from dict."""
        phase_perms_data = data.get("phase_permissions")
        if phase_perms_data:
            # Convert category names back to enum
            allowed_cats = frozenset(
                ToolCategory[name] for name in phase_perms_data.get("allowed_categories", [])
                if name in ToolCategory.__members__
            )
            phase_permissions = PhasePermissions(
                allowed_categories=allowed_cats,
                blocked_tools=frozenset(phase_perms_data.get("blocked_tools", [])),
                allowed_file_patterns=frozenset(phase_perms_data.get("allowed_file_patterns", ["**/*"])),
                blocked_file_patterns=frozenset(phase_perms_data.get("blocked_file_patterns", [])),
                blocked_commands=frozenset(phase_perms_data.get("blocked_commands", [])),
            )
        else:
            phase_permissions = None

        task_data = data.get("task_constraints", {})
        task_constraints = TaskConstraints(
            require_background=task_data.get("require_background", False),
            max_agents=task_data.get("max_agents", 5),
            allowed_agent_types=frozenset(task_data.get("allowed_agent_types", [])),
        )

        subagent_data = data.get("subagent_restrictions", {})
        subagent_restrictions = SubagentRestrictions(
            can_modify_workflow_state=subagent_data.get("can_modify_workflow_state", False),
            can_modify_own_agent_state=subagent_data.get("can_modify_own_agent_state", True),
            can_spawn_subagents=subagent_data.get("can_spawn_subagents", False),
            inherits_phase=subagent_data.get("inherits_phase", True),
        )

        return cls(
            workflow_active=data.get("workflow_active", False),
            workflow_type=data.get("workflow_type"),
            workflow_id=data.get("workflow_id"),
            phase=data.get("phase", "none"),
            phase_permissions=phase_permissions,
            task_constraints=task_constraints,
            is_subagent=data.get("is_subagent", False),
            agent_id=data.get("agent_id"),
            subagent_restrictions=subagent_restrictions,
            protected_paths=frozenset(data.get("protected_paths", [".state/", ".env"])),
            current_agents=data.get("current_agents", 0),
        )
