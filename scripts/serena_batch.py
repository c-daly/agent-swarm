#!/usr/bin/env python3
"""
Serena batch operations - semantic code analysis without reading full files.

Usage:
    python3 serena_batch.py symbols '{"path": "src/", "pattern": "auth"}'
    python3 serena_batch.py references '{"symbol": "handleLogin", "file": "src/auth.ts"}'
    python3 serena_batch.py structure '{"path": "src/components/"}'
"""

import json
import sys
import subprocess

def call_mcp(server: str, tool: str, params: dict) -> dict:
    """Call MCP tool via claude mcp command or direct."""
    # This would integrate with the MCP bridge
    # For now, output the command to run
    return {
        "tool": f"mcp__plugin_serena_serena__{tool}",
        "params": params
    }

def get_symbols(path: str, pattern: str = None) -> str:
    """Get symbols from path using Serena."""
    cmd = {
        "action": "find_symbols",
        "path": path,
        "pattern": pattern
    }
    return f"""Use Serena tool:
  mcp__plugin_serena_serena__find_symbol
  pattern: "{pattern or '*'}"
  path: "{path}"

Returns: symbol names with locations, NOT file contents"""

def get_references(symbol: str, file: str = None) -> str:
    """Find all references to a symbol."""
    return f"""Use Serena tool:
  mcp__plugin_serena_serena__find_references
  symbol: "{symbol}"
  file: "{file or ''}"

Returns: locations where symbol is used, NOT file contents"""

def get_structure(path: str) -> str:
    """Get code structure without reading files."""
    return f"""Use Serena tool:
  mcp__plugin_serena_serena__list_dir (for structure)
  mcp__plugin_serena_serena__get_symbols (for definitions)

Returns: directory tree + symbol list, NOT file contents"""

def get_definition(symbol: str) -> str:
    """Get symbol definition."""
    return f"""Use Serena tool:
  mcp__plugin_serena_serena__get_definition
  symbol: "{symbol}"

Returns: definition signature + docstring, NOT full implementation"""

def main():
    if len(sys.argv) < 3:
        print("""Usage: serena_batch.py <command> '<json_params>'

Commands:
  symbols    - Find symbols matching pattern
  references - Find all references to symbol
  structure  - Get code structure
  definition - Get symbol definition

Example:
  serena_batch.py symbols '{"path": "src/", "pattern": "handle"}'
""")
        sys.exit(1)

    cmd = sys.argv[1]
    try:
        params = json.loads(sys.argv[2])
    except json.JSONDecodeError:
        print("Error: Invalid JSON")
        sys.exit(1)

    if cmd == "symbols":
        print(get_symbols(params.get("path", "."), params.get("pattern")))
    elif cmd == "references":
        print(get_references(params.get("symbol", ""), params.get("file")))
    elif cmd == "structure":
        print(get_structure(params.get("path", ".")))
    elif cmd == "definition":
        print(get_definition(params.get("symbol", "")))
    else:
        print(f"Unknown command: {cmd}")

if __name__ == "__main__":
    main()
