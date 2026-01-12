#!/usr/bin/env python3
"""
Greptile Query API wrapper for freeform codebase queries.

Usage:
    python3 greptile_query.py "Your question about the codebase"
    python3 greptile_query.py "Review architecture" --repo owner/repo --branch main --genius

Environment:
    GREPTILE_API_KEY - Required
    GH_TOKEN - Required (GitHub access token)
"""

import argparse
import json
import os
import subprocess
import sys
from typing import Optional


def get_current_repo() -> tuple[str, str]:
    """Get current repo name and branch from git."""
    try:
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True
        ).stdout.strip()

        if remote.startswith("git@"):
            repo = remote.split(":")[-1].replace(".git", "")
        elif "github.com" in remote:
            repo = "/".join(remote.split("/")[-2:]).replace(".git", "")
        else:
            repo = None

        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=True
        ).stdout.strip()

        return repo, branch
    except subprocess.CalledProcessError:
        return None, None


def query_greptile(
    query: str,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
    genius: bool = False,
    timeout: int = 120
) -> dict:
    """Query Greptile API for freeform codebase analysis."""
    import requests

    api_key = os.environ.get("GREPTILE_API_KEY")
    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

    if not api_key:
        return {"error": "GREPTILE_API_KEY not set"}
    if not gh_token:
        return {"error": "GH_TOKEN or GITHUB_TOKEN not set"}

    if not repo or not branch:
        detected_repo, detected_branch = get_current_repo()
        repo = repo or detected_repo
        branch = branch or detected_branch or "main"

    if not repo:
        return {"error": "Could not detect repository. Use --repo owner/repo"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-GitHub-Token": gh_token,
        "Content-Type": "application/json"
    }

    payload = {
        "messages": [{"id": "1", "content": query, "role": "user"}],
        "repositories": [{"remote": "github", "branch": branch, "repository": repo}],
        "genius": genius
    }

    try:
        resp = requests.post(
            "https://api.greptile.com/v2/query",
            headers=headers,
            json=payload,
            timeout=timeout
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        return {"error": f"Request timed out after {timeout}s"}
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}


def format_output(result: dict, verbose: bool = False) -> str:
    """Format query result for display."""
    if "error" in result:
        return f"ERROR: {result['error']}"

    output = []
    message = result.get("message", "No response")
    output.append(message)

    sources = result.get("sources", [])
    if sources:
        output.append("\n\n--- SOURCES ---")
        for src in sources[:10]:
            filepath = src.get("filepath", "?")
            start = src.get("linestart", "?")
            end = src.get("lineend", "?")
            summary = src.get("summary", "")

            if verbose and summary:
                output.append(f"  {filepath}:{start}-{end}")
                output.append(f"    {summary[:100]}...")
            else:
                output.append(f"  {filepath}:{start}-{end}")

    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(
        description="Query Greptile for codebase analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "How does authentication work?"
  %(prog)s "Review the architecture" --genius
  %(prog)s "Find security issues" --repo owner/repo --branch main
  %(prog)s "Explain the data flow" --json
        """
    )

    parser.add_argument("query", help="Natural language question about the codebase")
    parser.add_argument("--repo", "-r", help="Repository (owner/repo format)")
    parser.add_argument("--branch", "-b", help="Branch name")
    parser.add_argument("--genius", "-g", action="store_true",
                       help="Use genius mode (smarter but slower)")
    parser.add_argument("--json", "-j", action="store_true",
                       help="Output raw JSON")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Include source summaries")
    parser.add_argument("--timeout", "-t", type=int, default=120,
                       help="Request timeout in seconds (default: 120)")

    args = parser.parse_args()

    result = query_greptile(
        query=args.query,
        repo=args.repo,
        branch=args.branch,
        genius=args.genius,
        timeout=args.timeout
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_output(result, verbose=args.verbose))

    sys.exit(1 if "error" in result else 0)


if __name__ == "__main__":
    main()
