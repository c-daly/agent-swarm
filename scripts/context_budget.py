#!/usr/bin/env python3
"""
Context budget tracker - enforces token limits per phase.
Ruthless context management.

Usage:
    python3 context_budget.py check
    python3 context_budget.py add <tokens>
    python3 context_budget.py reset
"""

import json
import sys
from pathlib import Path

STATE_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/session.json"

# Token budgets per phase (approximate)
PHASE_BUDGETS = {
    "intake": 2000,  # Should be quick
    "research": 5000,  # More room for findings
    "explore": 3000,  # References only
    "design": 4000,  # Plan should be concise
    "implement": 10000,  # Most work here, but via subagents
    "review": 3000,  # Focused review
    "debug": 5000,  # May need investigation
    "git": 1000,  # Simple operations
}


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def check_budget(state: dict) -> str:
    phase = state.get("phase", "")
    used = state.get("context_used", 0)
    budget = PHASE_BUDGETS.get(phase, 5000)
    remaining = budget - used
    pct = (used / budget) * 100 if budget > 0 else 0

    status = "OK" if remaining > 0 else "EXCEEDED"

    return f"""[CONTEXT BUDGET] Phase: {phase}
  Used: {used:,} / {budget:,} tokens ({pct:.0f}%)
  Remaining: {remaining:,}
  Status: {status}"""


def add_tokens(state: dict, tokens: int) -> str:
    used = state.get("context_used", 0) + tokens
    state["context_used"] = used
    save_state(state)

    phase = state.get("phase", "")
    budget = PHASE_BUDGETS.get(phase, 5000)

    if used > budget:
        return f"[BUDGET WARNING] Exceeded by {used - budget:,} tokens. Consider:\n  - Using batch scripts\n  - Spawning subagent\n  - Moving to next phase"

    return f"[BUDGET] Added {tokens:,}. Now at {used:,}/{budget:,}"


def reset_budget(state: dict) -> str:
    state["context_used"] = 0
    save_state(state)
    return "[BUDGET] Reset to 0"


def main():
    if len(sys.argv) < 2:
        print("Usage: context_budget.py check|add <tokens>|reset")
        sys.exit(1)

    state = load_state()
    cmd = sys.argv[1]

    if cmd == "check":
        print(check_budget(state))
    elif cmd == "add" and len(sys.argv) >= 3:
        try:
            tokens = int(sys.argv[2])
            print(add_tokens(state, tokens))
        except ValueError:
            print("Error: tokens must be a number")
    elif cmd == "reset":
        print(reset_budget(state))
    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
