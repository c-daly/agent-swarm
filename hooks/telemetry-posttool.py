#!/usr/bin/env python3
"""PostToolUse telemetry hook - completes tracking for ALL tool calls.

Pairs with telemetry-pretool.py to record duration and status.
Writes to centralized telemetry.json using v2.0 unified schema.

Extracts ACTUAL token usage from transcript when available.
"""

import sys
import json
import time
import os
from datetime import datetime, timezone
from pathlib import Path

# Add lib to path for schema imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from stores.events import ToolCallEvent
from stores.jsonl_writer import JSONLWriter

from telemetry_schema_v2 import (
    load_telemetry_v2,
    save_telemetry_v2,
    ensure_day,
    update_timing_stats,
    recompute_aggregates,
    update_filter_options,
    default_token_data,
    default_call_data,
)

# Shared state files
PENDING_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/telemetry_pending.json"
LATEST_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/telemetry_latest.json"
TELEMETRY_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/telemetry.json"

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

MAX_EVENTS = 500


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
        tokens = actual_tokens["total"]
        tokens_source = "jsonl"
        input_tokens = actual_tokens["input_tokens"]
        output_tokens = actual_tokens["output_tokens"]
        cache_read = actual_tokens["cache_read_input_tokens"]
        cache_create = actual_tokens["cache_creation_input_tokens"]
    else:
        tokens = estimate_tokens(tool_name, subagent_type)
        tokens_source = "router"
        input_tokens = 0
        output_tokens = 0
        cache_read = 0
        cache_create = 0

    # Load v2.0 telemetry
    telemetry = load_telemetry_v2(TELEMETRY_FILE)
    
    # Get today's date key
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Ensure day exists
    ensure_day(telemetry, today)
    day_data = telemetry["days"][today]
    
    backend = request_data.get("backend", "unknown")
    
    # Update day-level tokens (no summary wrapper in v2 schema)
    day_data["tokens"]["input"] += input_tokens
    day_data["tokens"]["output"] += output_tokens
    day_data["tokens"]["cache_read"] += cache_read
    day_data["tokens"]["cache_creation"] += cache_create
    if tokens_source == "jsonl":
        day_data["tokens"]["source"] = "jsonl"
    
    # Update day-level calls
    day_data["calls"]["total"] += 1
    
    if tool_name not in day_data["calls"]["by_tool"]:
        day_data["calls"]["by_tool"][tool_name] = {"count": 0, "errors": 0}
    day_data["calls"]["by_tool"][tool_name]["count"] += 1
    if is_error:
        day_data["calls"]["by_tool"][tool_name]["errors"] += 1
    
    if backend not in day_data["calls"]["by_backend"]:
        day_data["calls"]["by_backend"][backend] = {"count": 0, "errors": 0}
    day_data["calls"]["by_backend"][backend]["count"] += 1
    if is_error:
        day_data["calls"]["by_backend"][backend]["errors"] += 1
    
    # Update subagent tracking
    if subagent_type:
        if "by_subagent" not in day_data["calls"]:
            day_data["calls"]["by_subagent"] = {}
        if subagent_type not in day_data["calls"]["by_subagent"]:
            day_data["calls"]["by_subagent"][subagent_type] = {"count": 0, "tokens": 0}
        day_data["calls"]["by_subagent"][subagent_type]["count"] += 1
        day_data["calls"]["by_subagent"][subagent_type]["tokens"] += tokens
    
    # Update timing stats
    update_timing_stats(day_data["timing"], duration_ms)
    
    # Update session tracking
    session_id = get_session_id()
    if session_id not in day_data["sessions"]:
        day_data["sessions"].append(session_id)
    
    if session_id not in day_data["by_session"]:
        day_data["by_session"][session_id] = {
            "tokens": default_token_data(),
            "calls": default_call_data(),
            "start_time": datetime.now(timezone.utc).isoformat(),
            "end_time": None
        }
    
    session = day_data["by_session"][session_id]
    session["tokens"]["input"] += input_tokens
    session["tokens"]["output"] += output_tokens
    session["tokens"]["cache_read"] += cache_read
    session["tokens"]["cache_creation"] += cache_create
    if tokens_source == "jsonl":
        session["tokens"]["source"] = "jsonl"
    
    session["calls"]["total"] += 1
    if tool_name not in session["calls"]["by_tool"]:
        session["calls"]["by_tool"][tool_name] = {"count": 0, "errors": 0}
    session["calls"]["by_tool"][tool_name]["count"] += 1
    if is_error:
        session["calls"]["by_tool"][tool_name]["errors"] += 1
    
    session["end_time"] = datetime.now(timezone.utc).isoformat()
    
    # Recompute rolling aggregates
    recompute_aggregates(telemetry)
    
    # Update filter options
    update_filter_options(telemetry)
    
    # Keep legacy events array for backward compatibility
    if "events" not in telemetry:
        telemetry["events"] = []
    
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "tool": tool_name,
        "backend": backend,
        "duration_ms": duration_ms,
        "status": "error" if is_error else "success",
        "tokens": tokens,
        "tokens_source": tokens_source,
        "subagent_type": subagent_type,
        "error_msg": error_msg
    }
    
    telemetry["events"].append(event)
    if len(telemetry["events"]) > MAX_EVENTS:
        telemetry["events"] = telemetry["events"][-MAX_EVENTS:]
    
    # === Telemetry v3: Write to session JSONL ===
    try:
        jsonl_dir = Path.home() / ".claude/plugins/agent-swarm/.state/sessions"
        writer = JSONLWriter(data_dir=str(jsonl_dir))
        
        v3_event = ToolCallEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
            agent_id=os.environ.get("CLAUDE_AGENT_ID", session_id),
            tool=tool_name,
            backend=backend,
            duration_ms=duration_ms,
            status="error" if is_error else "success",
            error_type=error_msg[:100] if is_error else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_create,
            agent_type=subagent_type if subagent_type else None,
            task_summary=request_data.get("task_summary"),
            workflow_id=os.environ.get("WORKFLOW_ID"),
            workflow_phase=os.environ.get("WORKFLOW_PHASE"),
        )
        writer.write(v3_event)
    except Exception:
        # Don't fail the hook if v3 writing fails
        pass
    
    # Save v2 telemetry
    save_telemetry_v2(telemetry, TELEMETRY_FILE)

    print(json.dumps({}))


if __name__ == "__main__":
    main()
