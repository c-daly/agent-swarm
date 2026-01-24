#!/usr/bin/env python3
"""
Context Injection CLI for Subagent Briefing Hook

Called by inject-subagent-briefing.sh to fetch agent-specific context.
This bridge script allows the bash hook to access Python context resolution.
"""

import sys
from pathlib import Path

# Add context module to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from context.resolver import get_agent_context  # noqa: E402


def main():
    if len(sys.argv) < 4:
        print("Usage: context-injection.py inject <agent_type> <working_dir>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    if command != "inject":
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)

    agent_type = sys.argv[2]
    working_dir = Path(sys.argv[3]).resolve()

    try:
        context_md = get_agent_context(agent_type, working_dir)
        if context_md:
            print("# Hierarchical Context")
            print()
            print(context_md)
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
