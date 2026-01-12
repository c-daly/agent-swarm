"""Agent protocol specifications for swarm agents.

Defines machine-readable protocols that govern agent behavior,
tool access, and phase participation.
"""

from dataclasses import dataclass
from typing import FrozenSet
from lib.phase_model import ToolCategory


@dataclass(frozen=True)
class AgentProtocol:
    """Protocol specification for an agent type."""
    name: str
    model: str  # "haiku", "sonnet", "opus"
    allowed_tool_categories: FrozenSet[ToolCategory]
    blocked_tools: FrozenSet[str]
    allowed_phases: FrozenSet[str]  # empty = all phases
    max_output_chars: int
    can_write_files: bool


PROTOCOLS = {
    "explorer": AgentProtocol(
        name="explorer",
        model="haiku",
        allowed_tool_categories=frozenset({
            ToolCategory.FILE_READ,
            ToolCategory.FILE_SEARCH,
            ToolCategory.CODE_QUERY
        }),
        blocked_tools=frozenset({"Edit", "Write", "Bash"}),
        allowed_phases=frozenset(),  # All phases
        max_output_chars=1500,
        can_write_files=False,
    ),
    "implementer": AgentProtocol(
        name="implementer",
        model="sonnet",
        allowed_tool_categories=frozenset({
            ToolCategory.FILE_READ,
            ToolCategory.FILE_WRITE,
            ToolCategory.CODE_EDIT,
            ToolCategory.SHELL_SAFE
        }),
        blocked_tools=frozenset(),
        allowed_phases=frozenset({"implement", "test_writing"}),
        max_output_chars=1500,
        can_write_files=True,
    ),
    "reviewer": AgentProtocol(
        name="reviewer",
        model="sonnet",
        allowed_tool_categories=frozenset({
            ToolCategory.FILE_READ,
            ToolCategory.CODE_QUERY,
            ToolCategory.WEB_RESEARCH
        }),
        blocked_tools=frozenset({"Edit", "Write", "Bash"}),
        allowed_phases=frozenset({"review", "coverage"}),
        max_output_chars=2000,
        can_write_files=False,
    ),
    "architect": AgentProtocol(
        name="architect",
        model="opus",
        allowed_tool_categories=frozenset({
            ToolCategory.FILE_READ,
            ToolCategory.CODE_QUERY,
            ToolCategory.FILE_SEARCH,
            ToolCategory.WEB_RESEARCH,
            ToolCategory.MEMORY
        }),
        blocked_tools=frozenset({"Edit", "Write", "Bash"}),
        allowed_phases=frozenset(),  # All phases
        max_output_chars=3000,
        can_write_files=False,
    ),
    "debugger": AgentProtocol(
        name="debugger",
        model="sonnet",
        allowed_tool_categories=frozenset({
            ToolCategory.FILE_READ,
            ToolCategory.CODE_QUERY,
            ToolCategory.SHELL_SAFE,
            ToolCategory.FILE_SEARCH
        }),
        blocked_tools=frozenset({"Edit", "Write"}),
        allowed_phases=frozenset({"test", "coverage"}),
        max_output_chars=2000,
        can_write_files=False,
    ),
}


def get_protocol(agent_type: str) -> AgentProtocol | None:
    """Get protocol for agent type.

    Args:
        agent_type: Type of agent (e.g., "explorer", "implementer")

    Returns:
        AgentProtocol if found, None otherwise
    """
    return PROTOCOLS.get(agent_type.lower())


def validate_agent_spawn(agent_type: str, model: str, phase: str) -> tuple[bool, str]:
    """Validate agent spawn request against protocol.

    Args:
        agent_type: Type of agent being spawned
        model: Model requested for the agent
        phase: Current workflow phase

    Returns:
        Tuple of (is_valid: bool, message: str)
        - If valid: (True, "OK")
        - If invalid: (False, "reason for failure")
    """
    protocol = get_protocol(agent_type)
    if not protocol:
        return True, "OK"  # Unknown agent, allow

    if model != protocol.model:
        return False, f"{agent_type} requires model '{protocol.model}', got '{model}'"

    if protocol.allowed_phases and phase not in protocol.allowed_phases:
        return False, f"{agent_type} not allowed in phase '{phase}'"

    return True, "OK"
