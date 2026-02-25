#!/usr/bin/env python3
"""
MCP Native Tools Server - Wraps Claude Code's native tools as MCP tools.

Provides MCP-compliant access to:
- read_file: Read file contents
- write_file: Write/create files
- edit_file: Edit files with string replacement
- glob: Find files by pattern
- grep: Search file contents
- bash: Execute shell commands

Usage:
    from mcp_native import MCPNativeServer, read_file, write_file, edit_file

    # Direct function usage
    result = read_file("/path/to/file.txt")

    # MCP server usage
    server = MCPNativeServer()
    response = server.call_tool("read_file", {"file_path": "/path/to/file.txt"})
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


# === Tool Schemas ===

TOOL_SCHEMAS = {
    "read_file": {
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
    },
    "write_file": {
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
    },
    "edit_file": {
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
    },
    "glob": {
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
    },
    "grep": {
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
    },
    "bash": {
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
    },
    "task": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The task for the agent to perform"
            },
            "subagent_type": {
                "type": "string",
                "description": "Type of subagent (e.g. 'implementer', 'explorer', 'researcher')"
            },
            "system_prompt": {
                "type": "string",
                "description": "Optional override system prompt"
            },
            "max_turns": {
                "type": "integer",
                "description": "Maximum number of agent turns (default: 50)"
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for the agent"
            }
        },
        "required": ["prompt"]
    }
}

TOOL_DESCRIPTIONS = {
    "read_file": "Read the contents of a file. Supports line offset and limit for large files.",
    "write_file": "Write content to a file. Creates parent directories if needed. Overwrites existing files.",
    "edit_file": "Edit a file by replacing occurrences of a string. Can replace first or all occurrences.",
    "glob": "Find files matching a glob pattern. Supports recursive patterns with **.",
    "grep": "Search for a pattern in files. Returns matching file paths or content lines.",
    "bash": "Execute a shell command and return output. Supports timeout and working directory.",
    "task": "Spawn an SDK subprocess agent with router-mediated tool access."
}


# === Tool Functions ===

def read_file(
    path: str,
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> dict:
    """Read file contents with optional line offset and limit.

    Args:
        path: Path to the file
        offset: Line offset to start reading from (0-indexed)
        limit: Maximum number of lines to read

    Returns:
        Dict with 'success', 'content' or 'error'
    """
    try:
        file_path = Path(path)
        if not file_path.exists():
            return {"success": False, "error": f"File not found: {path}"}

        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            if offset is not None or limit is not None:
                lines = f.readlines()
                start = offset or 0
                end = start + limit if limit else None
                content = ''.join(lines[start:end])
            else:
                content = f.read()

        return {"success": True, "content": content}
    except PermissionError:
        return {"success": False, "error": f"Permission denied: {path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def write_file(path: str, content: str) -> dict:
    """Write content to a file, creating parent directories if needed.

    Args:
        path: Path to the file
        content: Content to write

    Returns:
        Dict with 'success' and optional 'error'
    """
    try:
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding='utf-8')
        return {"success": True}
    except PermissionError:
        return {"success": False, "error": f"Permission denied: {path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def edit_file(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False
) -> dict:
    """Edit a file by replacing string occurrences.

    Args:
        path: Path to the file
        old_string: String to find
        new_string: Replacement string
        replace_all: Whether to replace all occurrences

    Returns:
        Dict with 'success' and optional 'error'
    """
    try:
        file_path = Path(path)
        if not file_path.exists():
            return {"success": False, "error": f"File not found: {path}"}

        content = file_path.read_text(encoding='utf-8')

        if old_string not in content:
            return {"success": False, "error": f"String not found in file: {old_string[:50]}..."}

        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)

        file_path.write_text(new_content, encoding='utf-8')
        return {"success": True}
    except PermissionError:
        return {"success": False, "error": f"Permission denied: {path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def glob_files(pattern: str, path: Optional[str] = None) -> dict:
    """Find files matching a glob pattern.

    Args:
        pattern: Glob pattern (e.g., '*.py', '**/*.txt')
        path: Directory to search in (default: current directory)

    Returns:
        Dict with 'success', 'files' list
    """
    try:
        search_path = Path(path) if path else Path.cwd()

        if "**" in pattern:
            # Recursive glob
            matches = list(search_path.glob(pattern))
        else:
            matches = list(search_path.glob(pattern))

        # Convert to strings and filter out directories
        files = [str(m) for m in matches if m.is_file()]
        return {"success": True, "files": files}
    except Exception as e:
        return {"success": False, "error": str(e), "files": []}


def grep_files(
    pattern: str,
    path: Optional[str] = None,
    output_mode: str = "files",
    case_insensitive: bool = False,
    file_glob: Optional[str] = None
) -> dict:
    """Search for a pattern in files.

    Args:
        pattern: Regex pattern to search for
        path: Directory or file to search in
        output_mode: 'files' for file paths, 'content' for matching lines
        case_insensitive: Whether to ignore case
        file_glob: Filter files by glob pattern

    Returns:
        Dict with 'success', 'files' list, and optionally 'output'
    """
    try:
        search_path = Path(path) if path else Path.cwd()
        flags = re.IGNORECASE if case_insensitive else 0
        regex = re.compile(pattern, flags)

        matching_files = []
        output_lines = []

        # Determine files to search
        if search_path.is_file():
            files_to_search = [search_path]
        else:
            if file_glob:
                files_to_search = list(search_path.rglob(file_glob))
            else:
                files_to_search = list(search_path.rglob("*"))
            files_to_search = [f for f in files_to_search if f.is_file()]

        for file in files_to_search:
            try:
                content = file.read_text(encoding='utf-8', errors='replace')
                if regex.search(content):
                    matching_files.append(str(file))
                    if output_mode == "content":
                        for linenum, line in enumerate(content.splitlines(), 1):
                            if regex.search(line):
                                output_lines.append(f"{file}:{linenum}:{line}")
            except (PermissionError, OSError):
                continue  # Skip unreadable files

        result = {"success": True, "files": matching_files}
        if output_mode == "content":
            result["output"] = "\n".join(output_lines)
        return result
    except re.error as e:
        return {"success": False, "error": f"Invalid regex: {e}", "files": []}
    except Exception as e:
        return {"success": False, "error": str(e), "files": []}


def run_bash(
    command: str,
    timeout: int = 120,
    cwd: Optional[str] = None
) -> dict:
    """Execute a shell command.

    Args:
        command: Shell command to execute
        timeout: Timeout in seconds
        cwd: Working directory

    Returns:
        Dict with 'success', 'stdout', 'stderr', 'exit_code'
    """
    try:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Timeout: command exceeded {timeout} seconds",
            "stdout": "",
            "stderr": "",
            "exit_code": -1
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "stdout": "",
            "stderr": "",
            "exit_code": -1
        }


# === Tool Registry ===

class NativeToolRegistry:
    """Registry of native tools with schemas and descriptions."""

    def __init__(self):
        self._tools = list(TOOL_SCHEMAS.keys())

    def list_tools(self) -> list[str]:
        """Return list of available tool names."""
        return self._tools.copy()

    def get_schema(self, tool_name: str) -> Optional[dict]:
        """Get JSON schema for a tool."""
        return TOOL_SCHEMAS.get(tool_name)

    def get_description(self, tool_name: str) -> Optional[str]:
        """Get description for a tool."""
        return TOOL_DESCRIPTIONS.get(tool_name)


# === MCP Server ===

class MCPNativeServer:
    """MCP-compliant server wrapping native tools.

    Handles JSON-RPC requests for MCP protocol:
    - initialize: Server handshake
    - tools/list: List available tools
    - tools/call: Execute a tool
    """

    VERSION = "1.0.0"

    def __init__(
        self,
        name: str = "native",
        timeout: int = 120,
        working_dir: Optional[str] = None
    ):
        """Initialize MCP Native Server.

        Args:
            name: Server name for identification
            timeout: Default timeout for bash commands
            working_dir: Default working directory
        """
        self._name = name
        self._timeout = timeout
        self._working_dir = working_dir
        self._registry = NativeToolRegistry()

        # Map tool names to functions
        self._tool_functions = {
            "read_file": self._handle_read_file,
            "write_file": self._handle_write_file,
            "edit_file": self._handle_edit_file,
            "glob": self._handle_glob,
            "grep": self._handle_grep,
            "bash": self._handle_bash,
            "task": self._handle_task,
        }

    @property
    def name(self) -> str:
        """Server name."""
        return self._name

    @property
    def version(self) -> str:
        """Server version."""
        return self.VERSION

    @property
    def timeout(self) -> int:
        """Default timeout."""
        return self._timeout

    @property
    def working_dir(self) -> Optional[str]:
        """Default working directory."""
        return self._working_dir

    @property
    def tools(self) -> list[dict]:
        """List of available tools in MCP format."""
        result = []
        for tool_name in self._registry.list_tools():
            result.append({
                "name": tool_name,
                "description": self._registry.get_description(tool_name),
                "inputSchema": self._registry.get_schema(tool_name)
            })
        return result

    def get_command(self) -> list[str]:
        """Return command list for subprocess spawning."""
        return [sys.executable, __file__]

    def handle_raw_request(self, raw_json: str) -> dict:
        """Parse JSON and handle request.

        Args:
            raw_json: Raw JSON string

        Returns:
            JSON-RPC response dict
        """
        try:
            request = json.loads(raw_json)
            return self.handle_request(request)
        except json.JSONDecodeError as e:
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": f"Parse error: {e}"
                }
            }

    def handle_request(self, request: dict) -> dict:
        """Handle an MCP JSON-RPC request.

        Args:
            request: JSON-RPC request dict

        Returns:
            JSON-RPC response dict
        """
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        # Validate request
        if not method:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32600,
                    "message": "Invalid request: missing method"
                }
            }

        try:
            # Handle different methods
            if method == "initialize":
                result = self._handle_initialize(params)
            elif method == "tools/list":
                result = self._handle_tools_list()
            elif method == "tools/call":
                result = self._handle_tools_call(params)
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}"
                    }
                }

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {e}"
                }
            }

    def _handle_initialize(self, params: dict) -> dict:
        """Handle initialize method."""
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": self._name,
                "version": self.VERSION
            }
        }

    def _handle_tools_list(self) -> dict:
        """Handle tools/list method."""
        return {"tools": self.tools}

    def _handle_tools_call(self, params: dict) -> dict:
        """Handle tools/call method."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            return {
                "content": [{"type": "text", "text": "Error: missing tool name"}],
                "isError": True
            }

        return self.call_tool(tool_name, arguments)

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Call a tool directly.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            MCP-formatted response with content array
        """
        if name not in self._tool_functions:
            return {
                "content": [{"type": "text", "text": f"Error: Unknown tool: {name}"}],
                "isError": True
            }

        try:
            result = self._execute_tool(name, arguments)
            return self._format_mcp_response(result)
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Error: {e}"}],
                "isError": True
            }

    def _execute_tool(self, name: str, arguments: dict) -> dict:
        """Execute a tool and return raw result."""
        handler = self._tool_functions.get(name)
        if not handler:
            raise ValueError(f"Unknown tool: {name}")
        return handler(arguments)

    def _format_mcp_response(self, result: dict) -> dict:
        """Format result as MCP response with content array."""
        if result.get("success"):
            # Format successful response
            if "content" in result:
                text = result["content"]
            elif "output" in result:
                # Grep content mode: include output with line numbers
                text = result["output"]
            elif "files" in result:
                text = json.dumps({"files": result["files"]}, indent=2)
            elif "stdout" in result:
                text = result["stdout"]
                if result.get("stderr"):
                    text += f"\n[stderr]\n{result['stderr']}"
            else:
                text = json.dumps(result, indent=2)

            return {
                "content": [{"type": "text", "text": text}]
            }
        else:
            # Format error response - prefer stderr over generic error for better debugging
            error_msg = result.get('stderr') or result.get('error') or 'Unknown error'
            return {
                "content": [{"type": "text", "text": f"Error: {error_msg}"}],
                "isError": True
            }

    # === Tool Handlers ===

    def _handle_read_file(self, args: dict) -> dict:
        """Handle read_file tool."""
        file_path = args.get("file_path")
        if not file_path:
            return {"success": False, "error": "Missing required parameter: file_path"}
        return read_file(
            file_path,
            offset=args.get("offset"),
            limit=args.get("limit")
        )

    def _handle_write_file(self, args: dict) -> dict:
        """Handle write_file tool."""
        file_path = args.get("file_path")
        content = args.get("content")
        if not file_path:
            return {"success": False, "error": "Missing required parameter: file_path"}
        if content is None:
            return {"success": False, "error": "Missing required parameter: content"}
        return write_file(file_path, content)

    def _handle_edit_file(self, args: dict) -> dict:
        """Handle edit_file tool."""
        file_path = args.get("file_path")
        old_string = args.get("old_string")
        new_string = args.get("new_string")

        if not file_path:
            return {"success": False, "error": "Missing required parameter: file_path"}
        if old_string is None:
            return {"success": False, "error": "Missing required parameter: old_string"}
        if new_string is None:
            return {"success": False, "error": "Missing required parameter: new_string"}

        return edit_file(
            file_path,
            old_string,
            new_string,
            replace_all=args.get("replace_all", False)
        )

    def _handle_glob(self, args: dict) -> dict:
        """Handle glob tool."""
        pattern = args.get("pattern")
        if not pattern:
            return {"success": False, "error": "Missing required parameter: pattern", "files": []}
        return glob_files(pattern, path=args.get("path"))

    def _handle_grep(self, args: dict) -> dict:
        """Handle grep tool."""
        pattern = args.get("pattern")
        if not pattern:
            return {"success": False, "error": "Missing required parameter: pattern", "files": []}
        return grep_files(
            pattern,
            path=args.get("path"),
            output_mode=args.get("output_mode", "files"),
            case_insensitive=args.get("case_insensitive", False),
            file_glob=args.get("file_glob")
        )

    def _handle_bash(self, args: dict) -> dict:
        """Handle bash tool."""
        command = args.get("command")
        if not command:
            return {"success": False, "error": "Missing required parameter: command", "stdout": "", "stderr": "", "exit_code": -1}
        return run_bash(
            command,
            timeout=args.get("timeout", self._timeout),
            cwd=args.get("cwd", self._working_dir)
        )

    def _handle_task(self, args: dict) -> dict:
        """Handle task tool. Passthrough — actual execution handled by controller."""
        prompt = args.get("prompt")
        if not prompt:
            return {"success": False, "error": "Missing required parameter: prompt"}
        # Return args as-is; the controller intercepts native__task
        # before it reaches this handler.
        return {"success": True, "content": "task dispatched to controller"}


# === stdio Server ===

def start_stdio_server():
    """Run stdio-based MCP server loop."""
    server = MCPNativeServer()

    def send(msg: dict) -> None:
        print(json.dumps(msg), flush=True)

    for line in sys.stdin:
        try:
            request = json.loads(line.strip())
            response = server.handle_request(request)

            # Only send response if there's an ID (not a notification)
            if request.get("id") is not None:
                send(response)

        except json.JSONDecodeError as e:
            send({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"}
            })
        except Exception as e:
            send({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": str(e)}
            })


if __name__ == "__main__":
    start_stdio_server()
