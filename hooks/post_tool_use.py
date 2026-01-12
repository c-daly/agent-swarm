#!/usr/bin/env python3
"""
PostToolUse hook for agent-swarm plugin.

Tracks Bash command completions to update verification state
(lint runs, test runs, format runs).
"""

import sys
import json
from pathlib import Path

# Import verification gates and review gate
sys.path.insert(0, str(Path.home() / ".claude/plugins/agent-swarm/hooks"))
sys.path.insert(0, str(Path.home() / ".claude/plugins/agent-swarm/lib"))
from verification_gates import on_bash_complete
try:
    from review_gate import on_push
    REVIEW_GATE_AVAILABLE = True
except ImportError:
    REVIEW_GATE_AVAILABLE = False


def main():
    """Handle PostToolUse events."""
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    tool_result = input_data.get("tool_result", {})

    # Only track Bash commands
    if tool_name != "Bash":
        return

    # Extract command and exit code
    command = tool_input.get("command", "")

    # Try to extract exit code from tool result
    # The result format varies, but often includes exit code info
    exit_code = 0  # Default to success
    result_content = tool_result.get("content", "")
    if isinstance(result_content, str):
        if "exit code: " in result_content.lower():
            # Parse exit code from result
            import re
            match = re.search(r'exit code:\s*(\d+)', result_content, re.IGNORECASE)
            if match:
                exit_code = int(match.group(1))
        elif "error" in result_content.lower() or "failed" in result_content.lower():
            # Heuristic: likely failure
            exit_code = 1

    # Update verification state
    on_bash_complete(command, exit_code)

    # Clean up git_approval.flag after successful git commit/push (one-time use)
    if exit_code == 0:
        import re
        import subprocess
        if re.search(r'\bgit\s+(commit|push)\b', command):
            approval_flag = Path.home() / ".claude/plugins/agent-swarm/.state/git_approval.flag"
            if approval_flag.exists():
                approval_flag.unlink()

        # Track successful pushes with review_gate (moved from PreToolUse per Greptile P1)
        if REVIEW_GATE_AVAILABLE and re.search(r'\bgit\s+push\b', command):
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    sha = result.stdout.strip()
                    on_push(sha)
            except Exception:
                pass


if __name__ == "__main__":  # pragma: no cover
    main()
