"""Phase model for iterate workflow enforcement.

Defines phases and validation logic for the iterate workflow
to prevent agents from skipping phases or using inappropriate tools.
"""

from dataclasses import dataclass
from typing import FrozenSet, Optional

from lib.tool_categories import ToolCategory, TOOL_CATEGORIES


@dataclass(frozen=True)
class Phase:
    """Represents a workflow phase with tool restrictions."""
    name: str
    allowed_categories: FrozenSet[ToolCategory]
    blocked_tools: FrozenSet[str]
    requires_verification: bool


# Iterate workflow phases with tool restrictions
ITERATE_PHASES = {
    "orchestrate": Phase(
        name="orchestrate",
        allowed_categories=frozenset({
            ToolCategory.FILE_READ,
            ToolCategory.FILE_SEARCH,
            ToolCategory.CODE_QUERY,
            ToolCategory.SUBAGENT,
            ToolCategory.USER_INTERACTION,
        }),
        # Block native shell tools - orchestrator should use mcp__router__native__bash for gh commands
        blocked_tools=frozenset({"Edit", "Write", "NotebookEdit", "Bash"}),
        requires_verification=False,
    ),
    "test_writing": Phase(
        name="test_writing",
        allowed_categories=frozenset({
            ToolCategory.FILE_READ,
            ToolCategory.FILE_WRITE,  # For test files
            ToolCategory.CODE_QUERY,
            ToolCategory.FILE_SEARCH,
            ToolCategory.SHELL_SAFE,
        }),
        blocked_tools=frozenset(),
        requires_verification=False,
    ),
    "implement": Phase(
        name="implement",
        allowed_categories=frozenset({
            ToolCategory.FILE_READ,
            ToolCategory.FILE_WRITE,
            ToolCategory.CODE_QUERY,
            ToolCategory.CODE_EDIT,
            ToolCategory.FILE_SEARCH,
            ToolCategory.SHELL_SAFE,
            ToolCategory.SUBAGENT,
        }),
        blocked_tools=frozenset(),
        requires_verification=False,
    ),
    "test": Phase(
        name="test",
        allowed_categories=frozenset({
            ToolCategory.FILE_READ,
            ToolCategory.SHELL_SAFE,  # pytest
        }),
        blocked_tools=frozenset({"Edit", "Write"}),
        requires_verification=True,
    ),
    "coverage": Phase(
        name="coverage",
        allowed_categories=frozenset({
            ToolCategory.FILE_READ,
            ToolCategory.FILE_WRITE,  # Test files only
            ToolCategory.SHELL_SAFE,
            ToolCategory.WEB_RESEARCH,  # Greptile
        }),
        blocked_tools=frozenset(),
        requires_verification=True,
    ),
    "review": Phase(
        name="review",
        allowed_categories=frozenset({
            ToolCategory.FILE_READ,
            ToolCategory.WEB_RESEARCH,
        }),
        blocked_tools=frozenset({"Edit", "Write", "Bash"}),
        requires_verification=True,
    ),
}


def check_tool_allowed(tool_name: str, phase: str) -> tuple[bool, str]:
    """Check if a tool is allowed in the given phase.

    Args:
        tool_name: Name of the tool to check
        phase: Name of the phase (e.g., "test_writing", "implement")

    Returns:
        Tuple of (allowed: bool, reason: str)
        - If allowed: (True, "")
        - If blocked: (False, "reason for blocking")
    """
    # Get phase definition
    if phase not in ITERATE_PHASES:
        return True, ""  # Unknown phase, allow by default

    phase_def = ITERATE_PHASES[phase]

    # Check if tool is explicitly blocked
    if tool_name in phase_def.blocked_tools:
        return False, f"{tool_name} is blocked in {phase} phase"

    # Check tool category
    if tool_name not in TOOL_CATEGORIES:
        # Unknown tool, allow by default (defensive)
        return True, ""

    tool_category = TOOL_CATEGORIES[tool_name]

    # Bash/shell requires special handling
    if tool_category is None:
        # Will be handled by shell_virtualizer
        return True, ""

    # Check if category is allowed in this phase
    if tool_category not in phase_def.allowed_categories:
        return False, f"{tool_name} ({tool_category.name}) not allowed in {phase} phase"

    return True, ""


def get_phase_info(phase: str) -> Optional[Phase]:
    """Get phase definition by name.

    Args:
        phase: Name of the phase

    Returns:
        Phase definition or None if not found
    """
    return ITERATE_PHASES.get(phase)
