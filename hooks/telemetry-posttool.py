#!/usr/bin/env python3
"""PostToolUse telemetry hook - completes tracking for tool calls.

Pairs with telemetry-pretool.py to record duration and status.
Writes to DuckDB via TelemetryService.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.telemetry_service import TelemetryService  # noqa: E402

STATE_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/telemetry_pending.json"


def load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def detect_error(tool_response) -> tuple[bool, str]:
    """Detect if tool output indicates an error."""
    if isinstance(tool_response, dict):
        if tool_response.get("isError"):
            return True, str(tool_response.get("content", ""))[:200]
        if "error" in tool_response:
            return True, str(tool_response["error"])[:200]
    if isinstance(tool_response, str):
        lower = tool_response.lower()
        if "error:" in lower or "exception:" in lower or "failed:" in lower:
            return True, tool_response[:200]
    return False, ""


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps({}))
        return

    tool_name = input_data.get("tool_name", "")
    tool_response = input_data.get("tool_response", {})

    # Read pending entry from pretool
    pending = load_json(STATE_FILE)
    entry = pending.pop(tool_name, None)
    save_json(STATE_FILE, pending)

    if not entry:
        print(json.dumps({}))
        return

    # Calculate duration
    start_time = entry.get("t", time.time())
    duration_ms = int((time.time() - start_time) * 1000)

    # Detect errors
    is_error, error_msg = detect_error(tool_response)

    backend = entry.get("b", "unknown")
    subagent_type = entry.get("s", "")
    session_id = os.environ.get("CLAUDE_SESSION_ID", datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))

    # Write to DuckDB
    try:
        state_dir = Path.home() / ".claude/plugins/agent-swarm/.state"
        service = TelemetryService(data_dir=str(state_dir))

        # Measure output size for summarization tracking
        if isinstance(tool_response, dict):
            output_str = json.dumps(tool_response)
        else:
            output_str = str(tool_response) if tool_response else ""
        original_size = len(output_str)
        was_summarized = original_size > 2000

        service.insert_event({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "agent_id": os.environ.get("CLAUDE_AGENT_ID", session_id),
            "tool": tool_name,
            "backend": backend,
            "duration_ms": duration_ms,
            "status": "error" if is_error else "success",
            "error_type": error_msg[:100] if is_error else None,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "agent_type": subagent_type if subagent_type else None,
            "workflow_id": os.environ.get("WORKFLOW_ID"),
            "was_summarized": was_summarized,
            "original_size": original_size,
            "summary_size": min(original_size, 2000) if was_summarized else None,
        })
    except Exception:
        pass  # Don't fail the hook if telemetry writing fails

    print(json.dumps({}))


if __name__ == "__main__":
    main()
