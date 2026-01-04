#!/usr/bin/env python3
"""
Batch search script - processes multiple patterns and returns summarized results.
Keeps results out of context by processing in code.

Usage:
    python3 batch_search.py '{"patterns": ["pattern1", "pattern2"], "path": ".", "type": "grep"}'
"""

import json
import sys
import subprocess
from pathlib import Path

def run_grep(pattern: str, path: str, file_type: str = None) -> list[dict]:
    """Run ripgrep and return structured results."""
    cmd = ["rg", "--json", pattern, path]
    if file_type:
        cmd.extend(["--type", file_type])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        matches = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    match_data = data.get("data", {})
                    matches.append({
                        "file": match_data.get("path", {}).get("text", ""),
                        "line": match_data.get("line_number", 0),
                        "text": match_data.get("lines", {}).get("text", "").strip()[:100]
                    })
            except json.JSONDecodeError:
                continue
        return matches
    except subprocess.TimeoutExpired:
        return [{"error": "timeout"}]
    except Exception as e:
        return [{"error": str(e)}]

def run_glob(pattern: str, path: str) -> list[str]:
    """Run glob and return file list."""
    base = Path(path)
    return [str(p) for p in base.glob(pattern)][:50]  # Limit results

def summarize_results(results: dict) -> str:
    """Create concise summary of search results."""
    lines = []
    for pattern, matches in results.items():
        if isinstance(matches, list) and len(matches) > 0:
            if isinstance(matches[0], dict):
                # Grep results
                files = set(m.get("file", "") for m in matches if "file" in m)
                lines.append(f"'{pattern}': {len(matches)} matches in {len(files)} files")
                for f in list(files)[:5]:
                    file_matches = [m for m in matches if m.get("file") == f]
                    lines.append(f"  {f}: lines {', '.join(str(m['line']) for m in file_matches[:3])}")
            else:
                # Glob results
                lines.append(f"'{pattern}': {len(matches)} files")
                for f in matches[:5]:
                    lines.append(f"  {f}")
        else:
            lines.append(f"'{pattern}': no matches")

    return '\n'.join(lines)

def main():
    if len(sys.argv) < 2:
        print("Usage: batch_search.py '{\"patterns\": [...], \"path\": \".\", \"type\": \"grep|glob\"}'")
        sys.exit(1)

    try:
        config = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        print("Error: Invalid JSON input")
        sys.exit(1)

    patterns = config.get("patterns", [])
    path = config.get("path", ".")
    search_type = config.get("type", "grep")
    file_type = config.get("file_type")

    results = {}
    for pattern in patterns:
        if search_type == "grep":
            results[pattern] = run_grep(pattern, path, file_type)
        else:
            results[pattern] = run_glob(pattern, path)

    # Output summary only (token-efficient)
    print(summarize_results(results))

if __name__ == "__main__":
    main()
