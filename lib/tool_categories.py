"""Centralized tool categories for permission enforcement.

Single source of truth for tool-to-category mappings used by
phase_model.py and permission_store.py.
"""

from enum import Enum, auto
from typing import Optional


class ToolCategory(Enum):
    """Categories of tools for permission grouping."""
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
    WORKFLOW_CONTROL = auto()


# Tool constants for quick checks
FILE_WRITE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})
WORKFLOW_CONTROL_TOOLS = frozenset({
    "workflow_set_state", "workflow_update", "workflow_start", "workflow_stop",
    "mcp__router__workflow__workflow_set_state",
    "mcp__router__workflow__workflow_update",
    "mcp__router__workflow__workflow_start",
    "mcp__router__workflow__workflow_stop",
})


# Tool to category mapping - comprehensive list
TOOL_CATEGORIES: dict[str, Optional[ToolCategory]] = {
    # ===================
    # FILE READ operations
    # ===================
    # Native Claude Code tools
    "Read": ToolCategory.FILE_READ,

    # MCP router native variants
    "mcp__router__native__read_file": ToolCategory.FILE_READ,
    "native__read_file": ToolCategory.FILE_READ,

    # Serena variants (both plugin and router)
    "mcp__plugin_serena_serena__read_file": ToolCategory.FILE_READ,
    "mcp__router__serena__read_file": ToolCategory.FILE_READ,

    # Filesystem MCP
    "mcp__filesystem__read_file": ToolCategory.FILE_READ,
    "mcp__filesystem__read_text_file": ToolCategory.FILE_READ,
    "mcp__filesystem__read_multiple_files": ToolCategory.FILE_READ,
    "mcp__filesystem__read_media_file": ToolCategory.FILE_READ,

    # ===================
    # FILE WRITE operations
    # ===================
    # Native Claude Code tools
    "Edit": ToolCategory.FILE_WRITE,
    "Write": ToolCategory.FILE_WRITE,
    "NotebookEdit": ToolCategory.FILE_WRITE,

    # MCP router native variants
    "mcp__router__native__edit_file": ToolCategory.FILE_WRITE,
    "mcp__router__native__write_file": ToolCategory.FILE_WRITE,
    "native__edit_file": ToolCategory.FILE_WRITE,
    "native__write_file": ToolCategory.FILE_WRITE,

    # Serena variants (both plugin and router)
    "mcp__plugin_serena_serena__create_text_file": ToolCategory.FILE_WRITE,
    "mcp__plugin_serena_serena__replace_content": ToolCategory.FILE_WRITE,
    "mcp__router__serena__create_text_file": ToolCategory.FILE_WRITE,
    "mcp__router__serena__replace_content": ToolCategory.FILE_WRITE,

    # Filesystem MCP
    "mcp__filesystem__write_file": ToolCategory.FILE_WRITE,
    "mcp__filesystem__edit_file": ToolCategory.FILE_WRITE,

    # ===================
    # FILE SEARCH operations
    # ===================
    # Native Claude Code tools
    "Glob": ToolCategory.FILE_SEARCH,
    "Grep": ToolCategory.FILE_SEARCH,

    # MCP router native variants
    "mcp__router__native__glob": ToolCategory.FILE_SEARCH,
    "mcp__router__native__grep": ToolCategory.FILE_SEARCH,
    "native__glob": ToolCategory.FILE_SEARCH,
    "native__grep": ToolCategory.FILE_SEARCH,

    # Serena variants (both plugin and router)
    "mcp__plugin_serena_serena__find_file": ToolCategory.FILE_SEARCH,
    "mcp__plugin_serena_serena__search_for_pattern": ToolCategory.FILE_SEARCH,
    "mcp__plugin_serena_serena__list_dir": ToolCategory.FILE_SEARCH,
    "mcp__router__serena__find_file": ToolCategory.FILE_SEARCH,
    "mcp__router__serena__search_for_pattern": ToolCategory.FILE_SEARCH,
    "mcp__router__serena__list_dir": ToolCategory.FILE_SEARCH,

    # Filesystem MCP
    "mcp__filesystem__search_files": ToolCategory.FILE_SEARCH,
    "mcp__filesystem__list_directory": ToolCategory.FILE_SEARCH,
    "mcp__filesystem__directory_tree": ToolCategory.FILE_SEARCH,

    # ===================
    # CODE QUERY operations (semantic/symbolic)
    # ===================
    # Serena variants (both plugin and router)
    "mcp__plugin_serena_serena__get_symbols_overview": ToolCategory.CODE_QUERY,
    "mcp__plugin_serena_serena__find_symbol": ToolCategory.CODE_QUERY,
    "mcp__plugin_serena_serena__find_referencing_symbols": ToolCategory.CODE_QUERY,
    "mcp__router__serena__get_symbols_overview": ToolCategory.CODE_QUERY,
    "mcp__router__serena__find_symbol": ToolCategory.CODE_QUERY,
    "mcp__router__serena__find_referencing_symbols": ToolCategory.CODE_QUERY,

    # ===================
    # CODE EDIT operations (semantic/symbolic)
    # ===================
    # Serena variants (both plugin and router)
    "mcp__plugin_serena_serena__replace_symbol_body": ToolCategory.CODE_EDIT,
    "mcp__plugin_serena_serena__insert_after_symbol": ToolCategory.CODE_EDIT,
    "mcp__plugin_serena_serena__insert_before_symbol": ToolCategory.CODE_EDIT,
    "mcp__plugin_serena_serena__rename_symbol": ToolCategory.CODE_EDIT,
    "mcp__router__serena__replace_symbol_body": ToolCategory.CODE_EDIT,
    "mcp__router__serena__insert_after_symbol": ToolCategory.CODE_EDIT,
    "mcp__router__serena__insert_before_symbol": ToolCategory.CODE_EDIT,
    "mcp__router__serena__rename_symbol": ToolCategory.CODE_EDIT,

    # ===================
    # SHELL operations
    # ===================
    # Native Claude Code tools - requires special handling
    "Bash": None,  # Handled by shell_virtualizer

    # MCP router native variants
    "mcp__router__native__bash": ToolCategory.SHELL_DANGEROUS,
    "native__bash": ToolCategory.SHELL_DANGEROUS,

    # Serena shell (both plugin and router)
    "mcp__plugin_serena_serena__execute_shell_command": None,  # Handled by shell_virtualizer
    "mcp__router__serena__execute_shell_command": ToolCategory.SHELL_DANGEROUS,

    # ===================
    # SUBAGENT operations
    # ===================
    "Task": ToolCategory.SUBAGENT,

    # ===================
    # WEB RESEARCH operations
    # ===================
    "WebSearch": ToolCategory.WEB_RESEARCH,
    "WebFetch": ToolCategory.WEB_RESEARCH,
    "mcp__plugin_greptile_greptile__list_merge_requests": ToolCategory.WEB_RESEARCH,
    "mcp__plugin_greptile_greptile__get_merge_request": ToolCategory.WEB_RESEARCH,
    "mcp__plugin_greptile_greptile__trigger_code_review": ToolCategory.WEB_RESEARCH,

    # ===================
    # MEMORY operations
    # ===================
    "mcp__memory__create_entities": ToolCategory.MEMORY,
    "mcp__memory__add_observations": ToolCategory.MEMORY,
    "mcp__memory__search_nodes": ToolCategory.MEMORY,
    "mcp__plugin_episodic-memory_episodic-memory__search": ToolCategory.MEMORY,
    "mcp__plugin_serena_serena__read_memory": ToolCategory.MEMORY,
    "mcp__plugin_serena_serena__write_memory": ToolCategory.MEMORY,
    "mcp__router__serena__read_memory": ToolCategory.MEMORY,
    "mcp__router__serena__write_memory": ToolCategory.MEMORY,

    # ===================
    # USER INTERACTION
    # ===================
    "AskUserQuestion": ToolCategory.USER_INTERACTION,

    # ===================
    # WORKFLOW CONTROL
    # ===================
    "mcp__router__workflow__workflow_set_state": ToolCategory.WORKFLOW_CONTROL,
    "mcp__router__workflow__workflow_update": ToolCategory.WORKFLOW_CONTROL,
    "mcp__router__workflow__workflow_start": ToolCategory.WORKFLOW_CONTROL,
    "mcp__router__workflow__workflow_stop": ToolCategory.WORKFLOW_CONTROL,
    "mcp__router__workflow__workflow_get_state": ToolCategory.WORKFLOW_CONTROL,
    "mcp__router__workflow__workflow_get_value": ToolCategory.WORKFLOW_CONTROL,
    "mcp__router__workflow__workflow_set_value": ToolCategory.WORKFLOW_CONTROL,
}


def get_tool_category(tool_name: str) -> Optional[ToolCategory]:
    """Get the category for a tool, or None if unknown/special handling."""
    return TOOL_CATEGORIES.get(tool_name)


def is_file_write_tool(tool_name: str) -> bool:
    """Check if tool is a file write tool."""
    return tool_name in FILE_WRITE_TOOLS


def is_workflow_control_tool(tool_name: str) -> bool:
    """Check if tool controls workflow state."""
    return tool_name in WORKFLOW_CONTROL_TOOLS
