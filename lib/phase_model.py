"""Phase model for iterate workflow enforcement.

Defines tool categories, phases, and validation logic for
the iterate workflow to prevent agents from skipping phases
or using inappropriate tools.
"""

from enum import Enum, auto
from dataclasses import dataclass
from typing import FrozenSet, Optional

# Git/gh commands blocked in orchestrate phase
GIT_COMMAND_PREFIXES = ("git ", "git\t", "git;", "gh ", "gh\t", "gh;")


class ToolCategory(Enum):
    """Categories of tools available to agents."""
    FILE_READ = auto()
    FILE_WRITE = auto()
    CODE_QUERY = auto()
    CODE_EDIT = auto()
    FILE_SEARCH = auto()
    SHELL_SAFE = auto()
    SHELL_DANGEROUS = auto()
    WEB_RESEARCH = auto()
    SUBAGENT = auto()
    MEMORY = auto()
    USER_INTERACTION = auto()


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
        blocked_tools=frozenset({"Edit", "Write", "NotebookEdit"}),
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


# Tool to category mapping
TOOL_CATEGORIES = {
    # File operations
    "Read": ToolCategory.FILE_READ,
    "Edit": ToolCategory.FILE_WRITE,
    "Write": ToolCategory.FILE_WRITE,
    "mcp__plugin_serena_serena__read_file": ToolCategory.FILE_READ,
    "mcp__plugin_serena_serena__create_text_file": ToolCategory.FILE_WRITE,
    "mcp__plugin_serena_serena__replace_content": ToolCategory.FILE_WRITE,
    "mcp__filesystem__read_file": ToolCategory.FILE_READ,
    "mcp__filesystem__read_text_file": ToolCategory.FILE_READ,
    "mcp__filesystem__write_file": ToolCategory.FILE_WRITE,
    "mcp__filesystem__edit_file": ToolCategory.FILE_WRITE,

    # Search operations
    "Glob": ToolCategory.FILE_SEARCH,
    "Grep": ToolCategory.FILE_SEARCH,
    "mcp__plugin_serena_serena__find_file": ToolCategory.FILE_SEARCH,
    "mcp__plugin_serena_serena__search_for_pattern": ToolCategory.FILE_SEARCH,
    "mcp__filesystem__search_files": ToolCategory.FILE_SEARCH,

    # Code query operations
    "mcp__plugin_serena_serena__get_symbols_overview": ToolCategory.CODE_QUERY,
    "mcp__plugin_serena_serena__find_symbol": ToolCategory.CODE_QUERY,
    "mcp__plugin_serena_serena__find_referencing_symbols": ToolCategory.CODE_QUERY,

    # Code edit operations
    "mcp__plugin_serena_serena__replace_symbol_body": ToolCategory.CODE_EDIT,
    "mcp__plugin_serena_serena__insert_after_symbol": ToolCategory.CODE_EDIT,
    "mcp__plugin_serena_serena__insert_before_symbol": ToolCategory.CODE_EDIT,
    "mcp__plugin_serena_serena__rename_symbol": ToolCategory.CODE_EDIT,

    # Subagents
    "Task": ToolCategory.SUBAGENT,

    # Web research
    "WebSearch": ToolCategory.WEB_RESEARCH,
    "WebFetch": ToolCategory.WEB_RESEARCH,
    "mcp__plugin_greptile_greptile__list_merge_requests": ToolCategory.WEB_RESEARCH,
    "mcp__plugin_greptile_greptile__get_merge_request": ToolCategory.WEB_RESEARCH,
    "mcp__plugin_greptile_greptile__trigger_code_review": ToolCategory.WEB_RESEARCH,

    # Memory
    "mcp__memory__create_entities": ToolCategory.MEMORY,
    "mcp__memory__add_observations": ToolCategory.MEMORY,
    "mcp__plugin_episodic-memory_episodic-memory__search": ToolCategory.MEMORY,

    # Shell - requires special handling via shell_virtualizer
    "Bash": None,
    "mcp__plugin_serena_serena__execute_shell_command": None,
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


def check_bash_git_blocked(command: str, phase: str) -> tuple[bool, str]:
    """Check if a Bash command containing git/gh should be blocked.

    In the orchestrate phase, git and gh commands are blocked because
    the review phase handles git operations.

    Args:
        command: The bash command to check
        phase: Current workflow phase

    Returns:
        Tuple of (blocked: bool, reason: str)
        - If blocked: (True, "reason for blocking")
        - If allowed: (False, "")
    """
    if phase != "orchestrate":
        return False, ""

    # Normalize command - strip leading whitespace and check
    cmd = command.lstrip()

    # Check if command starts with git or gh
    if cmd.startswith(GIT_COMMAND_PREFIXES):
        return True, "[ORCHESTRATE] Git operations blocked. Review phase handles git."

    # Check for piped/chained commands containing git/gh
    # Look for patterns like "... | git", "... && git", "... ; git"
    for pattern in (" git ", "\tgit ", ";git ", "&git ", "|git ",
                    " gh ", "\tgh ", ";gh ", "&gh ", "|gh "):
        if pattern in command:
            return True, "[ORCHESTRATE] Git operations blocked. Review phase handles git."

    return False, ""
