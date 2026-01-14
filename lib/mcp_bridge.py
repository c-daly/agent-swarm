#!/usr/bin/env python3
"""
MCP Bridge - Native helper functions for fast file operations.

Provides native_glob and native_grep for fast local file operations
without spawning MCP tools.

Usage:
    from mcp_bridge import native_glob, native_grep

    # Find files
    files = native_glob("**/*.py", "/project")

    # Search content
    results = native_grep("pattern", "/project", output_mode="content")
"""

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


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
