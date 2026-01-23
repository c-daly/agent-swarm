#!/usr/bin/env python3
"""PostToolUse telemetry hook - completes tracking for ALL tool calls.

Pairs with telemetry-pretool.py to record duration and status.
Writes to DuckDB via TelemetryService (v3 telemetry).

Extracts ACTUAL token usage from transcript when available.
"""

import sys
import json
import time
import os
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.stores.events import ToolCallEvent  # noqa: F401 - referenced by other hooks
from lib.telemetry_service import TelemetryService

# Shared state files
PENDING_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/telemetry_pending.json"
LATEST_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/telemetry_latest.json"

# Token estimates by tool type (conservative estimates)
TOKEN_ESTIMATES = {
    # Native Claude tools
    "Read": 2000,
    "Write": 500,
    "Edit": 800,
    "Bash": 1000,
    "Glob": 500,
    "Grep": 1000,
    "Task": 5000,  # Base, subagent adds more
    "WebFetch": 3000,
    "WebSearch": 2000,
    "AskUserQuestion": 200,
    "TodoWrite": 100,
    # MCP tools (rough estimates)
    "read_file": 2000,
    "find_symbol": 1500,
    "search_for_pattern": 1500,
    "get_symbols_overview": 1000,
    "list_dir": 500,
    "replace_content": 800,
    "execute_shell_command": 1000,
}

# Subagent token estimates (much larger)
SUBAGENT_TOKEN_ESTIMATES = {
    "Explore": 25000,
    "Plan": 30000,
    "Implement": 100000,
    "general-purpose": 50000,
    "Bash": 10000,
    "feature-dev:code-explorer": 40000,
    "feature-dev:code-reviewer": 30000,
    "feature-dev:code-architect": 50000,
}


def extract_tokens_from_transcript(transcript_path: str) -> dict | None:
    """Extract actual token usage from the conversation transcript."""
    if not transcript_path:
        return None

    path = Path(transcript_path)
    if not path.exists():
        return None

    try:
        content = path.read_text()
        lines = content.strip().split('\n')

        for line in reversed(lines[-20:]):
            try:
                entry = json.loads(line)
                if "message" in entry and "usage" in entry.get("message", {}):
                    usage = entry["message"]["usage"]
                    return {
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
                        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
                        "total": (
                            usage.get("input_tokens", 0) +
                            usage.get("output_tokens", 0) +
                            usage.get("cache_read_input_tokens", 0) +
                            usage.get("cache_creation_input_tokens", 0)
                        )
                    }
            except json.JSONDecodeError:
                continue
        return None
    except Exception:
        return None


def load_json(path: Path) -> dict:
    """Load JSON file safely."""
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_json(path: Path, data: dict) -> None:
    """Save JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def estimate_tokens(tool_name: str, subagent_type: str = "") -> int:
    """Estimate tokens for a tool call."""
    if subagent_type:
        return SUBAGENT_TOKEN_ESTIMATES.get(subagent_type, 50000)

    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__")
        base_name = parts[-1] if parts else tool_name
        return TOKEN_ESTIMATES.get(base_name, 500)

    return TOKEN_ESTIMATES.get(tool_name, 500)


def detect_error(tool_output) -> tuple[bool, str]:
    """Detect if tool output indicates an error."""
    if isinstance(tool_output, dict):
        if tool_output.get("isError"):
            return True, str(tool_output.get("content", ""))[:200]
        if "error" in tool_output:
            return True, str(tool_output["error"])[:200]
    if isinstance(tool_output, str):
        lower = tool_output.lower()
        if "error:" in lower or "exception:" in lower or "failed:" in lower:
            return True, tool_output[:200]
    return False, ""


def get_session_id() -> str:
    """Get current session ID from environment or generate one."""
    return os.environ.get("CLAUDE_SESSION_ID", datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps({}))
        return

    tool_name = input_data.get("tool_name", "")
    tool_output = input_data.get("tool_output", {})

    # Find the pending request
    latest = load_json(LATEST_FILE)
    request_id = latest.get(tool_name)

    if not request_id:
        print(json.dumps({}))
        return

    pending = load_json(PENDING_FILE)
    request_data = pending.pop(request_id, None)
    save_json(PENDING_FILE, pending)

    if tool_name in latest:
        del latest[tool_name]
        save_json(LATEST_FILE, latest)

    if not request_data:
        print(json.dumps({}))
        return

    # Calculate duration
    start_time = request_data.get("start_time", time.time())
    duration_ms = int((time.time() - start_time) * 1000)

    # Detect errors
    is_error, error_msg = detect_error(tool_output)

    # Try to get actual tokens from transcript, fall back to estimate
    subagent_type = request_data.get("subagent_type", "")
    transcript_path = input_data.get("transcript_path", "")
    actual_tokens = extract_tokens_from_transcript(transcript_path)

    if actual_tokens:
        input_tokens = actual_tokens["input_tokens"]
        output_tokens = actual_tokens["output_tokens"]
        cache_read = actual_tokens["cache_read_input_tokens"]
        cache_create = actual_tokens["cache_creation_input_tokens"]
    else:
        input_tokens = 0
        output_tokens = 0
        cache_read = 0
        cache_create = 0

    backend = request_data.get("backend", "unknown")
    session_id = get_session_id()

    # === Telemetry v3: Write to DuckDB via TelemetryService ===
    try:
        state_dir = Path.home() / ".claude/plugins/agent-swarm/.state"
        service = TelemetryService(data_dir=str(state_dir))
        
        # Summary tracking (mcp-summarizer hook removed in router refactor)
        was_summarized = False
        original_size = None
        summary_size = None
        
        event_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "agent_id": os.environ.get("CLAUDE_AGENT_ID", session_id),
            "tool": tool_name,
            "backend": backend,
            "duration_ms": duration_ms,
            "status": "error" if is_error else "success",
            "error_type": error_msg[:100] if is_error else None,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read,
            "cache_creation_tokens": cache_create,
            "agent_type": subagent_type if subagent_type else None,
            "workflow_id": os.environ.get("WORKFLOW_ID"),
            "was_summarized": was_summarized,
            "original_size": original_size,
            "summary_size": summary_size,
        }
        service.insert_event(event_data)
    except Exception:
        # Don't fail the hook if telemetry writing fails
        pass

    print(json.dumps({}))


if __name__ == "__main__":
    main()
