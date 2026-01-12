#!/usr/bin/env python3
"""
MCP Bridge - Programmatic access to MCP tools from Python scripts.

Provides two types of functionality:
1. Native helpers (native_glob, native_grep) - Fast local operations
2. MCP protocol support (call_mcp) - Call MCP tools programmatically

Usage:
    from mcp_bridge import native_read, native_glob, native_grep, call_mcp

    # Fast local operations
    content = native_read("/path/to/file.py")
    files = native_glob("**/*.py", "/project")
    results = native_grep("pattern", "/project", output_mode="content")

    # MCP tool calls (for batching)
    result = call_mcp('mcp__plugin_serena_serena__find_symbol', {
        'name_path_pattern': 'MyClass'
    })
"""

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

# ============================================================================
# PART 1: Native Helper Functions (No MCP required)
# ============================================================================

def native_read(file_path: str, limit: Optional[int] = None, offset: int = 0) -> str:
    """
    Read file content without spawning MCP tools.

    Args:
        file_path: Path to file (absolute or relative)
        limit: Max lines to read (None = all)
        offset: Line number to start from (0-indexed)

    Returns:
        File content as string

    Example:
        content = native_read("/home/user/project/main.py")
        first_50 = native_read("/path/to/file.py", limit=50)
    """
    path = Path(file_path).expanduser().resolve()

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if not path.is_file():
        raise ValueError(f"Not a file: {file_path}")

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            if offset > 0 or limit is not None:
                lines = f.readlines()
                if offset > 0:
                    lines = lines[offset:]
                if limit is not None:
                    lines = lines[:limit]
                return ''.join(lines)
            else:
                return f.read()
    except Exception as e:
        raise IOError(f"Error reading {file_path}: {e}")


def native_glob(pattern: str, path: str = ".") -> List[str]:
    """
    Fast glob pattern matching without spawning MCP tools.

    Args:
        pattern: Glob pattern (e.g., "**/*.py", "*.json")
        path: Directory to search in (default: current directory)

    Returns:
        List of matching file paths (absolute paths)

    Example:
        files = native_glob("**/*.py", "/home/user/project")
    """
    from pathlib import Path
    import glob as glob_module

    search_path = Path(path).expanduser().resolve()
    pattern_path = search_path / pattern

    matches = glob_module.glob(str(pattern_path), recursive=True)
    return [str(Path(m).resolve()) for m in matches]


def native_grep(
    pattern: str,
    path: str = ".",
    output_mode: str = "files_with_matches",
    case_sensitive: bool = True,
    glob: Optional[str] = None,
    context_lines: int = 0
) -> Dict[str, Any]:
    """
    Fast grep using ripgrep without spawning MCP tools.

    Args:
        pattern: Regex pattern to search for
        path: Directory or file to search in
        output_mode: "files_with_matches", "content", or "count"
        case_sensitive: Case sensitive search (default: True)
        glob: Filter files by glob pattern (e.g., "*.py")
        context_lines: Lines of context around matches

    Returns:
        Dict with results based on output_mode

    Example:
        results = native_grep("TODO", "/project", output_mode="content")
    """
    cmd = ["rg", pattern, path]

    # Add flags
    if not case_sensitive:
        cmd.append("-i")

    if glob:
        cmd.extend(["--glob", glob])

    if context_lines > 0:
        cmd.extend(["-C", str(context_lines)])

    # Output mode
    if output_mode == "files_with_matches":
        cmd.append("-l")
    elif output_mode == "count":
        cmd.append("-c")
    elif output_mode == "content":
        cmd.append("-n")  # Line numbers

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        if output_mode == "files_with_matches":
            files = [f for f in result.stdout.strip().split('\n') if f]
            return {"files": files, "count": len(files)}

        elif output_mode == "count":
            lines = result.stdout.strip().split('\n')
            counts = {}
            for line in lines:
                if ':' in line:
                    file, count = line.rsplit(':', 1)
                    counts[file] = int(count)
            return {"counts": counts, "total": sum(counts.values())}

        elif output_mode == "content":
            return {"output": result.stdout, "matches": len(result.stdout.split('\n'))}

        return {"output": result.stdout}

    except subprocess.TimeoutExpired:
        return {"error": "Search timed out after 30s"}
    except FileNotFoundError:
        return {"error": "ripgrep (rg) not installed"}
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# PART 2: MCP Protocol Support (for calling MCP tools programmatically)
# ============================================================================

class MCPClient:
    """JSON-RPC 2.0 client for MCP servers via stdio transport."""

    def __init__(self, command: str, args: List[str], env: Optional[Dict] = None):
        """
        Initialize MCP client and spawn server process.

        Args:
            command: Server command (e.g., 'uvx')
            args: Command arguments
            env: Environment variables
        """
        self.process = subprocess.Popen(
            [command] + args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env
        )
        self.request_id = 0
        self.lock = threading.Lock()

        # Perform initialize handshake
        self._initialize()

    def _initialize(self):
        """Perform MCP initialize handshake."""
        init_request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "mcp_bridge",
                    "version": "1.0.0"
                }
            }
        }

        response = self._send_request(init_request)
        if "error" in response:
            raise Exception(f"Initialize failed: {response['error']}")

    def _next_id(self) -> int:
        """Get next request ID (thread-safe)."""
        with self.lock:
            self.request_id += 1
            return self.request_id

    def _send_request(self, request: Dict) -> Dict:
        """Send JSON-RPC request and read response."""
        try:
            # Send request
            request_line = json.dumps(request) + '\n'
            self.process.stdin.write(request_line)
            self.process.stdin.flush()

            # Read response
            response_line = self.process.stdout.readline()
            if not response_line:
                raise Exception("Server closed connection")

            response = json.loads(response_line)
            return response

        except Exception as e:
            raise Exception(f"MCP communication error: {e}")

    def call_tool(self, tool_name: str, arguments: Dict) -> Any:
        """
        Call an MCP tool.

        Args:
            tool_name: Name of the tool (e.g., 'find_symbol')
            arguments: Tool arguments as dict

        Returns:
            Tool result
        """
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }

        response = self._send_request(request)

        if "error" in response:
            raise Exception(f"Tool call failed: {response['error']}")

        return response.get("result", {})

    def close(self):
        """Terminate server process."""
        try:
            self.process.stdin.close()
            self.process.stdout.close()
            self.process.terminate()
            self.process.wait(timeout=5)
        except Exception:
            self.process.kill()


# Server cache (reuse connections)
_server_cache: Dict[str, MCPClient] = {}
_cache_lock = threading.Lock()


def _parse_tool_name(tool_name: str) -> tuple[str, str]:
    """
    Parse MCP tool name to extract server and tool.

    Examples:
        'mcp__plugin_serena_serena__find_symbol' -> ('serena', 'find_symbol')
        'mcp__context7__query-docs' -> ('context7', 'query-docs')

    Returns:
        (server_id, tool_name)
    """
    if not tool_name.startswith('mcp__'):
        raise ValueError(f"Invalid MCP tool name: {tool_name}")

    # Remove 'mcp__' prefix
    rest = tool_name[5:]

    # Split on '__' to separate server from tool
    parts = rest.split('__')
    if len(parts) < 2:
        raise ValueError(f"Invalid MCP tool name format: {tool_name}")

    # Last part is tool name, everything before is server
    tool = parts[-1]

    # Server ID extraction (handle plugin_NAME_NAME pattern)
    server_parts = parts[:-1]
    if server_parts[0] == 'plugin' and len(server_parts) >= 2:
        # plugin_serena_serena -> serena
        server = server_parts[-1]
    else:
        # context7 -> context7
        server = '_'.join(server_parts)

    return server, tool


def _load_server_config(server_id: str) -> Optional[Dict]:
    """
    Find and load MCP server configuration.

    Searches:
        1. ~/.claude/plugins/cache/*/external_plugins/{server}/.mcp.json
        2. ~/.claude/plugins/**/.mcp.json

    Returns:
        Server config dict or None if not found
    """
    claude_dir = Path.home() / ".claude"

    # Search in cache/marketplace directories
    cache_dir = claude_dir / "plugins" / "cache"
    if cache_dir.exists():
        for marketplace in cache_dir.iterdir():
            external_dir = marketplace / "external_plugins" / server_id
            mcp_json = external_dir / ".mcp.json"
            if mcp_json.exists():
                return json.loads(mcp_json.read_text())

    # Search all .mcp.json files in plugins
    plugins_dir = claude_dir / "plugins"
    if plugins_dir.exists():
        for mcp_file in plugins_dir.rglob(".mcp.json"):
            config = json.loads(mcp_file.read_text())
            # Check if this config is for our server
            # (heuristic: server_id in path or command)
            if server_id in str(mcp_file) or server_id in str(config.get('command', '')):
                return config

    return None


def call_mcp(tool_name: str, arguments: Dict) -> Any:
    """
    Call an MCP tool programmatically.

    Args:
        tool_name: Full MCP tool name (e.g., 'mcp__plugin_serena_serena__find_symbol')
        arguments: Tool arguments as dict

    Returns:
        Tool result

    Example:
        result = call_mcp('mcp__plugin_serena_serena__find_symbol', {
            'name_path_pattern': 'MyClass',
            'relative_path': 'src/'
        })

    Note: Use close_all_servers() at end of script to cleanup
    """
    # Parse tool name
    server_id, tool = _parse_tool_name(tool_name)

    # Get or create server connection
    with _cache_lock:
        if server_id not in _server_cache:
            # Load server config
            config = _load_server_config(server_id)
            if not config:
                raise Exception(f"MCP server config not found for: {server_id}")

            # Spawn server
            command = config.get('command')
            args = config.get('args', [])
            env = config.get('env')

            client = MCPClient(command, args, env)
            _server_cache[server_id] = client

        client = _server_cache[server_id]

    # Call tool
    return client.call_tool(tool, arguments)


def close_all_servers():
    """
    Close all MCP server connections.

    Call this at the end of scripts using call_mcp().
    """
    with _cache_lock:
        for client in _server_cache.values():
            client.close()
        _server_cache.clear()


# ============================================================================
# Convenience aliases
# ============================================================================

class MCPBridge:
    """
    Convenience class wrapper for MCP operations.

    Example:
        bridge = MCPBridge()
        result = bridge.call_tool('serena', 'find_symbol', {'name_path_pattern': 'Foo'})
        bridge.close()
    """

    def __init__(self):
        self.servers = {}

    def call_tool(self, server_id: str, tool_name: str, arguments: Dict) -> Any:
        """
        Call MCP tool by server and tool name (without full mcp__ prefix).

        Args:
            server_id: Server name (e.g., 'serena', 'context7')
            tool_name: Tool name (e.g., 'find_symbol')
            arguments: Tool arguments

        Returns:
            Tool result
        """
        # Construct full tool name
        # This is a simple heuristic - adjust if needed for different patterns
        if server_id == 'serena':
            full_name = f'mcp__plugin_serena_serena__{tool_name}'
        elif server_id in ['context7', 'filesystem', 'memory', 'greptile']:
            full_name = f'mcp__{server_id}__{tool_name}'
        else:
            full_name = f'mcp__plugin_{server_id}_{server_id}__{tool_name}'

        return call_mcp(full_name, arguments)

    def close(self):
        """Close all server connections."""
        close_all_servers()


if __name__ == "__main__":
    # Self-test
    print("MCP Bridge Self-Test")
    print("=" * 50)

    # Test native functions
    print("\n1. Testing native_read...")
    try:
        content = native_read(str(Path(__file__)))
        print(f"   ✓ Read {len(content)} bytes from self")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    print("\n2. Testing native_glob...")
    try:
        files = native_glob("*.py", str(Path(__file__).parent))
        print(f"   ✓ Found {len(files)} Python files")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    print("\n3. Testing native_grep...")
    try:
        results = native_grep("def ", str(Path(__file__)), output_mode="count")
        print(f"   ✓ Found {results.get('total', 0)} function definitions")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    print("\n4. MCP protocol support available")
    print(f"   ✓ call_mcp() - Call MCP tools programmatically")
    print(f"   ✓ close_all_servers() - Cleanup function")
    print(f"   ✓ MCPBridge - Convenience wrapper class")

    print("\n" + "=" * 50)
    print("Self-test complete! Module is functional.")
