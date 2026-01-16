#!/usr/bin/env python3
"""
Native Tools - Agent interface to Claude's native tools via router.

Provides wrapped tool functions that route through MCPRouter to the native backend.
Agents use TOOLS registry to access these as configured tools.

Usage:
    from native_tools import TOOLS, call_tool

    # List available tools
    for name, tool in TOOLS.items():
        print(f"{name}: {tool['description']}")

    # Call a tool
    result = call_tool("grep", pattern="TODO", path="/project")

    # Direct function access (if needed)
    from native_tools import read_file, grep
    result = grep("TODO", "/project")
"""

import json
from pathlib import Path
from typing import Any, Optional

from mcp_router import MCPRouter, RouterResponse

# Singleton router instance - initialized on first use
_router: Optional[MCPRouter] = None


def _get_router() -> MCPRouter:
    """Get or create the singleton router instance."""
    global _router
    if _router is None:
        _router = MCPRouter()
        # Register native backend from config
        config_path = Path(__file__).parent.parent / "config" / "backends.json"
        if config_path.exists():
            config = json.loads(config_path.read_text())
            if "native" in config:
                native_config = config["native"]
                _router.register_server(
                    name="native",
                    command=native_config["command"],
                    tool_prefix=native_config.get("tool_prefix", "native")
                )
    return _router


# === Tool Wrappers ===


def read_file(
    file_path: str,
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> RouterResponse:
    """Read file contents with optional line offset and limit.

    Args:
        file_path: Absolute path to the file
        offset: Line offset to start reading from (0-indexed)
        limit: Maximum number of lines to read

    Returns:
        RouterResponse with summary and full content
    """
    args: dict[str, Any] = {"file_path": file_path}
    if offset is not None:
        args["offset"] = offset
    if limit is not None:
        args["limit"] = limit

    return _get_router().route("native", "read_file", args)


def write_file(file_path: str, content: str) -> RouterResponse:
    """Write content to a file.

    Creates parent directories if needed. Overwrites existing files.

    Args:
        file_path: Absolute path to the file
        content: Content to write

    Returns:
        RouterResponse with success status
    """
    return _get_router().route("native", "write_file", {
        "file_path": file_path,
        "content": content
    })


def edit_file(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False
) -> RouterResponse:
    """Edit a file by replacing string occurrences.

    Args:
        file_path: Absolute path to the file
        old_string: String to find and replace
        new_string: Replacement string
        replace_all: Whether to replace all occurrences (default: False)

    Returns:
        RouterResponse with success status
    """
    return _get_router().route("native", "edit_file", {
        "file_path": file_path,
        "old_string": old_string,
        "new_string": new_string,
        "replace_all": replace_all
    })


def glob(pattern: str, path: Optional[str] = None) -> RouterResponse:
    """Find files matching a glob pattern.

    Args:
        pattern: Glob pattern (e.g., '*.py', '**/*.txt')
        path: Directory to search in (default: current directory)

    Returns:
        RouterResponse with file list
    """
    args: dict[str, Any] = {"pattern": pattern}
    if path is not None:
        args["path"] = path

    return _get_router().route("native", "glob", args)


def grep(
    pattern: str,
    path: Optional[str] = None,
    output_mode: str = "files",
    case_insensitive: bool = False,
    file_glob: Optional[str] = None
) -> RouterResponse:
    """Search for a pattern in files.

    Args:
        pattern: Regex pattern to search for
        path: Directory or file to search in
        output_mode: 'files' for file paths, 'content' for matching lines
        case_insensitive: Whether to ignore case
        file_glob: Filter files by glob pattern (e.g., '*.py')

    Returns:
        RouterResponse with matching files/content
    """
    args: dict[str, Any] = {"pattern": pattern}
    if path is not None:
        args["path"] = path
    if output_mode != "files":
        args["output_mode"] = output_mode
    if case_insensitive:
        args["case_insensitive"] = True
    if file_glob is not None:
        args["file_glob"] = file_glob

    return _get_router().route("native", "grep", args)


def bash(
    command: str,
    timeout: int = 120,
    cwd: Optional[str] = None
) -> RouterResponse:
    """Execute a shell command.

    Args:
        command: Shell command to execute
        timeout: Timeout in seconds (default: 120)
        cwd: Working directory for command execution

    Returns:
        RouterResponse with stdout, stderr, exit_code
    """
    args: dict[str, Any] = {"command": command}
    if timeout != 120:
        args["timeout"] = timeout
    if cwd is not None:
        args["cwd"] = cwd

    return _get_router().route("native", "bash", args)


# === Convenience Functions ===


def read_file_content(file_path: str) -> str:
    """Read file and return content directly (convenience wrapper).

    Args:
        file_path: Absolute path to the file

    Returns:
        File content as string, or error message

    Raises:
        RuntimeError: If file read fails
    """
    result = read_file(file_path)
    full = result.full

    # Extract content from response
    if isinstance(full, dict):
        if "error" in full:
            raise RuntimeError(full["error"])
        if "result" in full:
            inner = full["result"]
            if isinstance(inner, dict) and "content" in inner:
                # MCP response format
                content_list = inner["content"]
                if content_list and isinstance(content_list[0], dict):
                    return content_list[0].get("text", "")
            return str(inner)
        if "content" in full:
            return full["content"]

    return str(full)


def run_command(command: str, cwd: Optional[str] = None) -> tuple[str, int]:
    """Run command and return (output, exit_code) (convenience wrapper).

    Args:
        command: Shell command to execute
        cwd: Working directory

    Returns:
        Tuple of (combined stdout+stderr, exit_code)
    """
    result = bash(command, cwd=cwd)
    full = result.full

    if isinstance(full, dict):
        if "error" in full:
            return str(full["error"]), -1
        if "result" in full:
            inner = full["result"]
            if isinstance(inner, dict):
                # MCP response format: content[0].text
                content_list = inner.get("content", [])
                if content_list and isinstance(content_list[0], dict):
                    text = content_list[0].get("text", "")
                    # Check for isError flag
                    is_error = inner.get("isError", False)
                    return text, 1 if is_error else 0
                # Fallback to stdout/stderr format
                stdout = inner.get("stdout", "")
                stderr = inner.get("stderr", "")
                exit_code = inner.get("exit_code", 0)
                output = stdout
                if stderr:
                    output += f"\n[stderr]\n{stderr}"
                return output, exit_code

    return str(full), 0


# === Tool Registry ===

TOOLS: dict[str, dict[str, Any]] = {
    "read_file": {
        "name": "read_file",
        "description": "Read the contents of a file. Supports line offset and limit for large files.",
        "function": read_file,
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path to the file to read"
                },
                "offset": {
                    "type": "integer",
                    "description": "Line offset to start reading from (0-indexed)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read"
                }
            },
            "required": ["file_path"]
        }
    },
    "write_file": {
        "name": "write_file",
        "description": "Write content to a file. Creates parent directories if needed. Overwrites existing files.",
        "function": write_file,
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path to the file to write"
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file"
                }
            },
            "required": ["file_path", "content"]
        }
    },
    "edit_file": {
        "name": "edit_file",
        "description": "Edit a file by replacing occurrences of a string. Can replace first or all occurrences.",
        "function": edit_file,
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path to the file to edit"
                },
                "old_string": {
                    "type": "string",
                    "description": "The string to find and replace"
                },
                "new_string": {
                    "type": "string",
                    "description": "The replacement string"
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Whether to replace all occurrences (default: false)"
                }
            },
            "required": ["file_path", "old_string", "new_string"]
        }
    },
    "glob": {
        "name": "glob",
        "description": "Find files matching a glob pattern. Supports recursive patterns with **.",
        "function": glob,
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The glob pattern to match files (e.g., '*.py', '**/*.txt')"
                },
                "path": {
                    "type": "string",
                    "description": "The directory to search in (default: current directory)"
                }
            },
            "required": ["pattern"]
        }
    },
    "grep": {
        "name": "grep",
        "description": "Search for a pattern in files. Returns matching file paths or content lines.",
        "function": grep,
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The regex pattern to search for"
                },
                "path": {
                    "type": "string",
                    "description": "The directory or file to search in"
                },
                "output_mode": {
                    "type": "string",
                    "description": "Output mode: 'files' for file paths, 'content' for matching lines",
                    "enum": ["files", "content"]
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Whether to ignore case when matching"
                },
                "file_glob": {
                    "type": "string",
                    "description": "Filter files by glob pattern (e.g., '*.py')"
                }
            },
            "required": ["pattern"]
        }
    },
    "bash": {
        "name": "bash",
        "description": "Execute a shell command and return output. Supports timeout and working directory.",
        "function": bash,
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 120)"
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for command execution"
                }
            },
            "required": ["command"]
        }
    }
}


def call_tool(name: str, **kwargs: Any) -> RouterResponse:
    """Call a tool by name with keyword arguments.

    Args:
        name: Tool name (read_file, write_file, edit_file, glob, grep, bash)
        **kwargs: Tool arguments

    Returns:
        RouterResponse with summary and full response

    Raises:
        ValueError: If tool name is unknown
    """
    if name not in TOOLS:
        raise ValueError(f"Unknown tool: {name}. Available: {list(TOOLS.keys())}")

    return TOOLS[name]["function"](**kwargs)


def list_tools() -> list[dict[str, Any]]:
    """List all available tools with their schemas (MCP format).

    Returns:
        List of tool definitions suitable for MCP tools/list response
    """
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "inputSchema": tool["inputSchema"]
        }
        for tool in TOOLS.values()
    ]
