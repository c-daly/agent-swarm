#!/usr/bin/env python3
"""
Simple hook logger for debugging hook execution.

Usage in hook scripts:
    from hook_logger import log_hook
    log_hook("PreToolUse", "combined-enforcement", "allowed Read tool")

View logs:
    tail -f ~/.claude/plugins/agent-swarm/.state/hooks.log
"""

from datetime import datetime
from pathlib import Path

LOG_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/hooks.log"


def log_hook(hook_type: str, hook_name: str, message: str = ""):
    """Log hook execution with timestamp."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] {hook_type:12} | {hook_name:25} | {message}\n"

    with open(LOG_FILE, "a") as f:
        f.write(line)


def clear_log():
    """Clear the hook log file."""
    if LOG_FILE.exists():
        LOG_FILE.unlink()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "clear":
        clear_log()
        print(f"Cleared {LOG_FILE}")
    elif len(sys.argv) > 1 and sys.argv[1] == "tail":
        import subprocess
        subprocess.run(["tail", "-f", str(LOG_FILE)])
    else:
        print(f"Hook log: {LOG_FILE}")
        print("Usage:")
        print("  python3 hook_logger.py clear  - Clear log")
        print("  python3 hook_logger.py tail   - Tail log")
        print("  tail -f ~/.claude/plugins/agent-swarm/.state/hooks.log")
