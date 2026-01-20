#!/usr/bin/env python3
"""
Context Update CLI

Review and apply proposed context updates from agents.
This is a convenience wrapper around context/updater.py.
"""

import sys
from pathlib import Path

# Add context module to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from context.updater import (
    list_proposals,
    apply_proposal,
    reject_proposal,
    propose_context_update,
    DYNAMIC_SECTIONS,
    STABLE_SECTIONS,
)


def print_help():
    print("Context Update CLI")
    print()
    print("Usage: context-update.py <command> [args]")
    print()
    print("Commands:")
    print("  list [scope]              - List pending proposals")
    print("  show <id> [scope]         - Show full proposal content")
    print("  apply <id> [scope]        - Apply a specific proposal")
    print("  reject <id> [scope]       - Reject a proposal")
    print("  apply-all [scope]         - Apply all pending proposals")
    print()
    print("Scope defaults to current directory if not specified.")
    print()
    print("Dynamic sections (agent-updateable):")
    print(f"  {', '.join(sorted(DYNAMIC_SECTIONS))}")
    print()
    print("Stable sections (manual-only):")
    print(f"  {', '.join(sorted(STABLE_SECTIONS))}")


def main():
    if len(sys.argv) < 2:
        print_help()
        sys.exit(1)

    command = sys.argv[1]

    if command in ["-h", "--help", "help"]:
        print_help()
        sys.exit(0)

    elif command == "list":
        scope = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd()
        proposals = list_proposals(scope)

        if not proposals:
            print("No pending proposals")
            return

        print(f"Pending proposals for {scope}:\n")
        for p in proposals:
            print(f"[{p['id']}] {p['section']} ({p['update_type']})")
            print(f"    Agent: {p['agent_id']}")
            print(f"    Preview: {p['content'][:60]}...")
            print()

    elif command == "show":
        if len(sys.argv) < 3:
            print("Usage: context-update.py show <id> [scope]")
            sys.exit(1)

        proposal_id = sys.argv[2]
        scope = Path(sys.argv[3]) if len(sys.argv) > 3 else Path.cwd()
        proposals = list_proposals(scope)

        for p in proposals:
            if p["id"] == proposal_id:
                print(f"Proposal: {p['id']}")
                print(f"Section: {p['section']}")
                print(f"Type: {p['update_type']}")
                print(f"Agent: {p['agent_id']}")
                print(f"Timestamp: {p['timestamp']}")
                print()
                print("Content:")
                print("-" * 40)
                print(p["content"])
                print("-" * 40)
                return

        print(f"Proposal {proposal_id} not found")
        sys.exit(1)

    elif command == "apply":
        if len(sys.argv) < 3:
            print("Usage: context-update.py apply <id> [scope]")
            sys.exit(1)

        proposal_id = sys.argv[2]
        scope = Path(sys.argv[3]) if len(sys.argv) > 3 else None

        result = apply_proposal(proposal_id, scope)
        if result["success"]:
            print(result["message"])
        else:
            print(f"Error: {result['error']}")
            sys.exit(1)

    elif command == "reject":
        if len(sys.argv) < 3:
            print("Usage: context-update.py reject <id> [scope]")
            sys.exit(1)

        proposal_id = sys.argv[2]
        scope = Path(sys.argv[3]) if len(sys.argv) > 3 else None

        result = reject_proposal(proposal_id, scope)
        if result["success"]:
            print(result["message"])
        else:
            print(f"Error: {result['error']}")
            sys.exit(1)

    elif command == "apply-all":
        scope = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd()
        proposals = list_proposals(scope)

        if not proposals:
            print("No pending proposals")
            return

        print(f"Applying {len(proposals)} proposals...")
        for p in proposals:
            result = apply_proposal(p["id"], scope)
            if result["success"]:
                print(f"  Applied: {p['id']} ({p['section']})")
            else:
                print(f"  Failed: {p['id']} - {result['error']}")

        print("Done")

    else:
        print(f"Unknown command: {command}")
        print("Use --help for usage information")
        sys.exit(1)


if __name__ == "__main__":
    main()
