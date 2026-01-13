"""Phase model for iterate workflow enforcement.

Defines tool categories, phases, and validation logic for
the iterate workflow to prevent agents from skipping phases
or using inappropriate tools.
"""

from enum import Enum, auto
from dataclasses import dataclass
from typing import FrozenSet, Optional


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
    allowed_paths: FrozenSet[str] = frozenset()  # Regex patterns for FILE_READ restriction


# Iterate workflow phases with tool restrictions
ITERATE_PHASES = {
    "orchestrate": Phase(
        name="orchestrate",
        allowed_categories=frozenset({
            ToolCategory.SUBAGENT,
            ToolCategory.FILE_READ,
        }),
        blocked_tools=frozenset(),
        requires_verification=False,
        allowed_paths=frozenset({
            r".*SPEC\.md$",
            r".*\.spec$",
            r".*\.queue$",
        }),
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


def check_tool_allowed(tool_name: str, phase: str, file_path: str = "") -> tuple[bool, str]:
    """Check if a tool is allowed in the given phase."""
    import re

    if phase not in ITERATE_PHASES:
        return True, ""

    phase_def = ITERATE_PHASES[phase]

    if tool_name in phase_def.blocked_tools:
        return False, f"{tool_name} blocked in {phase} phase"

    if tool_name not in TOOL_CATEGORIES:
        return True, ""

    tool_category = TOOL_CATEGORIES[tool_name]

    if tool_category is None:
        return True, ""

    if tool_category not in phase_def.allowed_categories:
        return False, f"{tool_name} ({tool_category.name}) not allowed in {phase} phase"

    if phase_def.allowed_paths and file_path:
        if not any(re.match(p, file_path) for p in phase_def.allowed_paths):
            return False, f"Path not allowed in {phase} phase"

    return True, ""


def get_phase_info(phase: str) -> Optional[Phase]:
    """Get phase definition by name.

    Args:
        phase: Name of the phase

    Returns:
        Phase definition or None if not found
    """
    return ITERATE_PHASES.get(phase)


def verify_phase_completion(phase: str, cwd: str = ".") -> tuple[bool, str]:
    """Verify that phase completion requirements are met before advancing.
    
    Args:
        phase: Current phase to verify completion of
        cwd: Working directory for running commands
        
    Returns:
        (success, message) tuple
    """
    import subprocess
    
    phase_def = ITERATE_PHASES.get(phase)
    if not phase_def or not phase_def.requires_verification:
        return True, ""
    
    errors = []
    
    if phase == "test":
        # 1. Syntax check on modified Python files
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=AM", "*.py"],
                capture_output=True, text=True, cwd=cwd, timeout=10
            )
            py_files = [f for f in result.stdout.strip().split("\n") if f.endswith(".py")]
            
            for py_file in py_files:
                compile_result = subprocess.run(
                    ["python3", "-m", "py_compile", py_file],
                    capture_output=True, text=True, cwd=cwd, timeout=10
                )
                if compile_result.returncode != 0:
                    errors.append(f"Syntax error in {py_file}: {compile_result.stderr}")
        except Exception as e:
            errors.append(f"Syntax check failed: {e}")
        
        # 2. Lint check with ruff (if available)
        try:
            result = subprocess.run(
                ["ruff", "check", "--select=E9,F63,F7,F82", "."],  # Critical errors only
                capture_output=True, text=True, cwd=cwd, timeout=30
            )
            if result.returncode != 0 and result.stdout.strip():
                errors.append(f"Lint errors:\n{result.stdout[:500]}")
        except FileNotFoundError:
            pass  # ruff not installed, skip
        except Exception as e:
            pass  # Don't block on lint failures
        
        # 3. Run tests
        try:
            result = subprocess.run(
                ["python3", "-m", "pytest", "-x", "--tb=short", "-q"],
                capture_output=True, text=True, cwd=cwd, timeout=120
            )
            if result.returncode != 0:
                errors.append(f"Tests failed:\n{result.stdout[-500:]}")
        except Exception as e:
            errors.append(f"Test execution failed: {e}")
    
    if errors:
        return False, "\n".join(errors)
    
    return True, "All verification checks passed"
