#!/usr/bin/env python3
"""PostToolUse telemetry hook - completes tracking for ALL tool calls.

Pairs with telemetry-pretool.py to record duration and status.
Writes to centralized telemetry.json for dashboard consumption.

Now extracts ACTUAL token usage from transcript when available.
"""

import sys
import json
import time
from datetime import datetime, timezone
from pathlib import Path

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
    """Extract actual token usage from the conversation transcript.

    Returns dict with input_tokens, output_tokens, cache_read_input_tokens, etc.
    or None if not available.
    """
    if not transcript_path:
        return None

    path = Path(transcript_path)
    if not path.exists():
        return None

    try:
        # Read the last few lines efficiently (usage is in recent entries)
        content = path.read_text()
        lines = content.strip().split('\n')

        # Search backwards for the most recent usage entry
        for line in reversed(lines[-20:]):  # Check last 20 entries
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

    # Check for MCP tool (extract base name)
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


def update_aggregates(telemetry: dict, event: dict, is_error: bool) -> None:
    """Update aggregate statistics."""
    agg = telemetry.setdefault("aggregates", {})
    # Ensure all required keys exist (handles partial/legacy data)
    agg.setdefault("by_tool", {})
    agg.setdefault("by_backend", {})
    agg.setdefault("subagents", {})
    agg.setdefault("totals", {"calls": 0, "errors": 0, "tokens": 0, "duration_ms": 0})

    tool = event["tool"]
    backend = event["backend"]
    tokens = event["tokens"]
    duration = event["duration_ms"]

    # By tool
    if tool not in agg["by_tool"]:
        agg["by_tool"][tool] = {"count": 0, "tokens": 0, "errors": 0, "duration_ms": 0}
    agg["by_tool"][tool]["count"] += 1
    agg["by_tool"][tool]["tokens"] += tokens
    agg["by_tool"][tool]["duration_ms"] += duration
    if is_error:
        agg["by_tool"][tool]["errors"] += 1

    # By backend
    if backend not in agg["by_backend"]:
        agg["by_backend"][backend] = {"count": 0, "tokens": 0, "errors": 0, "duration_ms": 0}
    agg["by_backend"][backend]["count"] += 1
    agg["by_backend"][backend]["tokens"] += tokens
    agg["by_backend"][backend]["duration_ms"] += duration
    if is_error:
        agg["by_backend"][backend]["errors"] += 1

    # Subagents
    if event.get("subagent_type"):
        sa = event["subagent_type"]
        if sa not in agg["subagents"]:
            agg["subagents"][sa] = {"count": 0, "tokens": 0, "errors": 0}
        agg["subagents"][sa]["count"] += 1
        agg["subagents"][sa]["tokens"] += tokens
        if is_error:
            agg["subagents"][sa]["errors"] += 1

    # Totals
    agg["totals"]["calls"] += 1
    agg["totals"]["tokens"] += tokens
    agg["totals"]["duration_ms"] += duration
    if is_error:
        agg["totals"]["errors"] += 1


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
        # No matching pre-tool entry, skip
        print(json.dumps({}))
        return

    pending = load_json(PENDING_FILE)
    request_data = pending.pop(request_id, None)
    save_json(PENDING_FILE, pending)

    # Clean up latest
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
        tokens_source = "actual"
        tokens_breakdown = {
            "input": actual_tokens["input_tokens"],
            "output": actual_tokens["output_tokens"],
            "cache_read": actual_tokens["cache_read_input_tokens"],
            "cache_create": actual_tokens["cache_creation_input_tokens"]
        }
    else:
        tokens = estimate_tokens(tool_name, subagent_type)
        tokens_source = "estimated"
        tokens_breakdown = None

    # Create event
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": tool_name,
        "backend": request_data.get("backend", "unknown"),
        "duration_ms": duration_ms,
        "status": "error" if is_error else "success",
        "tokens": tokens,
        "tokens_source": tokens_source,
        "subagent_type": subagent_type,
        "error_msg": error_msg
    }
    if tokens_breakdown:
        event["tokens_breakdown"] = tokens_breakdown

    # Load or initialize telemetry
    telemetry = load_json(TELEMETRY_FILE)
    if "events" not in telemetry:
        telemetry = {
            "session_id": datetime.now(timezone.utc).isoformat(),
            "session_start": datetime.now(timezone.utc).isoformat(),
            "events": [],
            "daily_summaries": {},
            "aggregates": {
                "by_tool": {},
                "by_backend": {},
                "subagents": {},
                "totals": {"calls": 0, "errors": 0, "tokens": 0, "duration_ms": 0}
            }
        }

    # Add event (rolling window)
    telemetry["events"].append(event)
    if len(telemetry["events"]) > MAX_EVENTS:
        telemetry["events"] = telemetry["events"][-MAX_EVENTS:]

    # Update daily summaries (persistent historical data)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily = telemetry.setdefault("daily_summaries", {})
    if today not in daily:
        daily[today] = {
            "calls": 0, "tokens": 0, "errors": 0, "duration_ms": 0,
            "cache_read": 0, "cache_create": 0, "input_tokens": 0, "output_tokens": 0
        }
    daily[today]["calls"] += 1
    daily[today]["tokens"] += tokens
    daily[today]["duration_ms"] += duration_ms
    if is_error:
        daily[today]["errors"] += 1

    # Track cache metrics if available
    if tokens_breakdown:
        daily[today]["cache_read"] = daily[today].get("cache_read", 0) + tokens_breakdown["cache_read"]
        daily[today]["cache_create"] = daily[today].get("cache_create", 0) + tokens_breakdown["cache_create"]
        daily[today]["input_tokens"] = daily[today].get("input_tokens", 0) + tokens_breakdown["input"]
        daily[today]["output_tokens"] = daily[today].get("output_tokens", 0) + tokens_breakdown["output"]

    # Update global cache stats
    cache_stats = telemetry.setdefault("cache_stats", {
        "total_cache_read": 0,
        "total_cache_create": 0,
        "calls_with_cache_data": 0
    })
    if tokens_breakdown:
        cache_stats["total_cache_read"] += tokens_breakdown["cache_read"]
        cache_stats["total_cache_create"] += tokens_breakdown["cache_create"]
        cache_stats["calls_with_cache_data"] += 1

    # Update aggregates
    update_aggregates(telemetry, event, is_error)

    # Save
    save_json(TELEMETRY_FILE, telemetry)

    # PostToolUse doesn't need to return anything special
    print(json.dumps({}))


if __name__ == "__main__":
    main()
