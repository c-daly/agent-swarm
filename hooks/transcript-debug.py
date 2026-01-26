#!/usr/bin/env python3
"""Debug: log ALL PreToolUse input fields."""
import json
import sys
from pathlib import Path
from datetime import datetime

log = Path.home() / ".claude/plugins/agent-swarm/.state/transcript_debug.log"
log.parent.mkdir(parents=True, exist_ok=True)

data = json.loads(sys.stdin.read())

with open(log, "a") as f:
    f.write(f"\n{datetime.now().isoformat()} | ALL_KEYS: {sorted(data.keys())}\n")
    f.write(f"  agentId: {data.get('agentId', 'NOT_PRESENT')}\n")
    f.write(f"  tool_name: {data.get('tool_name', 'NOT_PRESENT')}\n")
    f.write(f"  sessionId: {data.get('sessionId', 'NOT_PRESENT')}\n")
    f.write(f"  transcript_path: {data.get('transcript_path', 'NOT_PRESENT')}\n")

print(json.dumps({"hookSpecificOutput": {"permissionDecision": "allow"}}))
