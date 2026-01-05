#!/usr/bin/env python3
"""
GitHub CLI wrapper - processes gh output and returns summarized results.
Keeps verbose API responses out of context.

Usage:
    python3 gh_wrapper.py <command> [args...]

Examples:
    python3 gh_wrapper.py pr list
    python3 gh_wrapper.py issue list --state open
    python3 gh_wrapper.py pr view 123
    python3 gh_wrapper.py repo view
"""

import json
import sys
import subprocess

def run_gh(args: list[str]) -> dict:
    """Run gh command and return parsed output."""
    cmd = ["gh"] + args

    # Try JSON output first
    if "--json" not in args and "-q" not in args:
        # Add JSON output for supported commands
        json_commands = ["pr list", "issue list", "pr view", "issue view", "repo view"]
        cmd_str = " ".join(args[:2]) if len(args) >= 2 else args[0]

        if any(cmd_str.startswith(jc) for jc in json_commands):
            if "list" in args:
                cmd.extend(["--json", "number,title,state,author,createdAt"])
            elif "view" in args:
                cmd.extend(["--json", "number,title,state,body,author,createdAt,comments"])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return {"error": result.stderr.strip(), "command": " ".join(cmd)}

        # Try to parse as JSON
        try:
            return {"data": json.loads(result.stdout), "format": "json"}
        except json.JSONDecodeError:
            return {"data": result.stdout.strip(), "format": "text"}

    except subprocess.TimeoutExpired:
        return {"error": "Command timed out"}
    except Exception as e:
        return {"error": str(e)}

def summarize_pr_list(data: list) -> str:
    """Summarize PR list."""
    if not data:
        return "No PRs found"

    lines = [f"Found {len(data)} PRs:"]
    for pr in data[:10]:
        lines.append(f"  #{pr.get('number', '?')} [{pr.get('state', '?')}] {pr.get('title', 'No title')[:60]}")

    if len(data) > 10:
        lines.append(f"  ... and {len(data) - 10} more")

    return '\n'.join(lines)

def summarize_issue_list(data: list) -> str:
    """Summarize issue list."""
    if not data:
        return "No issues found"

    lines = [f"Found {len(data)} issues:"]
    for issue in data[:10]:
        lines.append(f"  #{issue.get('number', '?')} [{issue.get('state', '?')}] {issue.get('title', 'No title')[:60]}")

    if len(data) > 10:
        lines.append(f"  ... and {len(data) - 10} more")

    return '\n'.join(lines)

def summarize_pr_view(data: dict) -> str:
    """Summarize single PR."""
    lines = [
        f"PR #{data.get('number', '?')}: {data.get('title', 'No title')}",
        f"State: {data.get('state', '?')}",
        f"Author: {data.get('author', {}).get('login', '?')}",
        f"Body: {(data.get('body', '') or 'No description')[:200]}...",
    ]

    comments = data.get('comments', [])
    if comments:
        lines.append(f"Comments: {len(comments)}")

    return '\n'.join(lines)

def summarize_repo_view(data: dict) -> str:
    """Summarize repo info."""
    return f"""Repository: {data.get('nameWithOwner', '?')}
Description: {data.get('description', 'No description')}
Stars: {data.get('stargazerCount', 0)} | Forks: {data.get('forkCount', 0)}
Default branch: {data.get('defaultBranchRef', {}).get('name', 'main')}"""

def summarize(result: dict, args: list[str]) -> str:
    """Create concise summary based on command type."""
    if "error" in result:
        return f"Error: {result['error']}"

    data = result.get("data")

    if result.get("format") == "text":
        # Truncate text output
        text = str(data)
        if len(text) > 500:
            return text[:500] + "\n... (truncated)"
        return text

    # JSON output - summarize based on command
    cmd = " ".join(args[:2]) if len(args) >= 2 else ""

    if "pr list" in cmd:
        return summarize_pr_list(data)
    elif "issue list" in cmd:
        return summarize_issue_list(data)
    elif "pr view" in cmd:
        return summarize_pr_view(data)
    elif "repo view" in cmd:
        return summarize_repo_view(data)
    else:
        # Generic JSON summary
        if isinstance(data, list):
            return f"Returned {len(data)} items"
        elif isinstance(data, dict):
            return f"Returned object with keys: {', '.join(list(data.keys())[:10])}"
        else:
            return str(data)[:500]

def main():
    if len(sys.argv) < 2:
        print("Usage: gh_wrapper.py <command> [args...]")
        print("Examples:")
        print("  gh_wrapper.py pr list")
        print("  gh_wrapper.py issue list --state open")
        print("  gh_wrapper.py pr view 123")
        sys.exit(1)

    args = sys.argv[1:]
    result = run_gh(args)
    print(summarize(result, args))

if __name__ == "__main__":
    main()
