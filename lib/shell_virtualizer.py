"""Shell virtualizer to redirect common shell commands to appropriate tools."""

import re
from typing import Dict, Tuple, Any

# Tool categories for suggestions - emphasize batch scripting for efficiency
TOOL_CATEGORIES = {
    "FILE_READ": (
        "Use a FILE_READ tool (Read, Serena get_symbols_overview, or Serena read_file). "
        "For multiple files: write a Python script with native_glob/regex to extract only what you need - "
        "turns 500k tokens into <200"
    ),
    "FILE_SEARCH": (
        "Use a FILE_SEARCH tool (Grep or Glob). "
        "For complex searches: write a script with MCPBridge to batch operations"
    ),
    "FILE_LIST": (
        "Use a FILE_LIST tool (list_directory or Serena list_dir). "
        "For recursive exploration: use Glob with pattern like '**/*.py'"
    ),
}

# Map of shell command patterns to tool categories
# Use word boundaries (\b) to detect commands anywhere in the string
# (handles piped commands and command substitution)
SHELL_REDIRECTS = {
    r'\bcat\s+': ("FILE_READ", TOOL_CATEGORIES["FILE_READ"]),
    r'\b(grep|rg)\s+': ("FILE_SEARCH", TOOL_CATEGORIES["FILE_SEARCH"]),
    r'\bfind\s+.*-name': ("FILE_SEARCH", TOOL_CATEGORIES["FILE_SEARCH"]),
    r'\bls\s+': ("FILE_LIST", TOOL_CATEGORIES["FILE_LIST"]),
    r'\bhead\s+': ("FILE_READ", "Use Read tool with limit parameter"),
    r'\btail\s+': ("FILE_READ", "Use Read tool with offset parameter"),
}

# Safe commands that should be allowed
SAFE_SHELL = [
    r'^git\s+',
    r'^python3?\s+',
    r'^poetry\s+',
    r'^pytest',
    r'^(mypy|ruff|black)',
    r'^gh\s+',
]


def categorize_command(command: str) -> Dict[str, Any]:
    """
    Categorize a shell command and determine if it should be blocked.

    Args:
        command: The shell command to categorize

    Returns:
        Dictionary with keys:
        - blocked (bool): True if command should be blocked
        - suggested_tool (str): Name of suggested tool category (if blocked)
        - message (str): Explanation message
    """
    # Handle empty or whitespace-only commands
    if not command or not command.strip():
        return {
            'blocked': False,
            'suggested_tool': None,
            'message': 'OK'
        }

    # Strip leading/trailing whitespace
    command = command.strip()

    # Check if command is in safe list first
    for safe_pattern in SAFE_SHELL:
        if re.match(safe_pattern, command):
            return {
                'blocked': False,
                'suggested_tool': None,
                'message': 'OK'
            }

    # Check for redirected commands in the entire command
    # This handles piped commands and command substitution
    for pattern, (tool, message) in SHELL_REDIRECTS.items():
        if re.search(pattern, command):
            return {
                'blocked': True,
                'suggested_tool': tool,
                'message': message
            }

    # Command not blocked
    return {
        'blocked': False,
        'suggested_tool': None,
        'message': 'OK'
    }


def check_command(command: str) -> Tuple[bool, str]:
    """
    Check if a command should be allowed.

    Args:
        command: The shell command to check

    Returns:
        Tuple of (allowed, message):
        - allowed (bool): True if command is allowed
        - message (str): "OK" if allowed, otherwise explanation
    """
    result = categorize_command(command)

    if result['blocked']:
        return (False, result['message'])
    else:
        return (True, 'OK')
