#!/usr/bin/env python3
"""Import old activity.log and subagent_metrics.json into new telemetry format."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"
ACTIVITY_LOG = STATE_DIR / "activity.log"
SUBAGENT_METRICS = STATE_DIR / "subagent_metrics.json"
TELEMETRY_FILE = STATE_DIR / "telemetry.json"

# Token estimates
TOKEN_ESTIMATES = {
    "Read": 2000, "Write": 500, "Edit": 800, "Bash": 1000,
    "Glob": 500, "Grep": 1000, "Task": 5000, "WebFetch": 3000,
    "AskUserQuestion": 200, "TodoWrite": 100,
}

SUBAGENT_TOKEN_ESTIMATES = {
    "Explore": 25000, "Plan": 30000, "Implement": 100000,
    "general-purpose": 50000, "Bash": 10000,
    "feature-dev:code-explorer": 40000,
    "feature-dev:code-reviewer": 30000,
}


def parse_activity_log():
    """Parse activity.log and extract tool events."""
    if not ACTIVITY_LOG.exists():
        print("No activity.log found")
        return []

    events = []
    today = datetime.now().strftime("%Y-%m-%d")

    with open(ACTIVITY_LOG) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Try JSON format first
            if line.startswith("{"):
                try:
                    entry = json.loads(line)
                    ts = entry.get("timestamp", "00:00:00")
                    event_type = entry.get("event_type", "")
                    details = entry.get("details", "")

                    # Extract tool name from details
                    tool = "unknown"
                    if isinstance(details, str):
                        # "Bash: some command" or just "Read"
                        if ":" in details:
                            tool = details.split(":")[0].strip()
                        else:
                            tool = details.split()[0] if details else "unknown"

                    if event_type in ["ALLOWED", "BLOCKED", "WARNING"]:
                        events.append({
                            "ts": f"{today}T{ts}",
                            "tool": tool,
                            "backend": "claude-native",
                            "duration_ms": 0,  # Unknown
                            "status": "error" if event_type == "BLOCKED" else "success",
                            "tokens_est": TOKEN_ESTIMATES.get(tool, 500),
                            "subagent_type": "",
                            "error_msg": "" if event_type != "BLOCKED" else "Blocked by enforcement"
                        })
                except json.JSONDecodeError:
                    pass

            # Try old plain format: [HH:MM:SS] EVENT: Tool
            else:
                match = re.match(r'\[(\d{2}:\d{2}:\d{2})\]\s+(\w+):\s+(\w+)', line)
                if match:
                    ts, event_type, tool = match.groups()
                    if event_type in ["ALLOWED", "BLOCKED"]:
                        events.append({
                            "ts": f"{today}T{ts}",
                            "tool": tool,
                            "backend": "claude-native",
                            "duration_ms": 0,
                            "status": "error" if event_type == "BLOCKED" else "success",
                            "tokens_est": TOKEN_ESTIMATES.get(tool, 500),
                            "subagent_type": "",
                            "error_msg": ""
                        })

    return events


def parse_subagent_metrics():
    """Parse subagent_metrics.json and create telemetry events."""
    if not SUBAGENT_METRICS.exists():
        print("No subagent_metrics.json found")
        return []

    events = []
    metrics = json.loads(SUBAGENT_METRICS.read_text())

    for agent_id, data in metrics.items():
        agent_type = data.get("agent_type", "unknown")
        spawned_at = data.get("spawned_at", "")

        # Estimate tokens based on agent type
        tokens = 50000  # Default
        for key, val in SUBAGENT_TOKEN_ESTIMATES.items():
            if key in agent_type.lower():
                tokens = val
                break

        events.append({
            "ts": spawned_at,
            "tool": "Task",
            "backend": "claude-native",
            "duration_ms": 0,  # Unknown
            "status": "success" if data.get("status") == "completed" else "success",
            "tokens_est": tokens,
            "subagent_type": agent_type,
            "error_msg": ""
        })

    return events


def update_aggregates(telemetry: dict, events: list) -> None:
    """Update aggregate statistics from events."""
    agg = telemetry.setdefault("aggregates", {
        "by_tool": {},
        "by_backend": {},
        "subagents": {},
        "totals": {"calls": 0, "errors": 0, "tokens_est": 0, "duration_ms": 0}
    })

    for event in events:
        tool = event["tool"]
        backend = event["backend"]
        tokens = event["tokens_est"]
        duration = event["duration_ms"]
        is_error = event["status"] == "error"

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
        agg["totals"]["tokens_est"] += tokens
        agg["totals"]["duration_ms"] += duration
        if is_error:
            agg["totals"]["errors"] += 1


def import_data():
    """Import old data into telemetry.json."""
    print("Importing old telemetry data...")

    # Parse old sources
    activity_events = parse_activity_log()
    print(f"  Parsed {len(activity_events)} events from activity.log")

    subagent_events = parse_subagent_metrics()
    print(f"  Parsed {len(subagent_events)} events from subagent_metrics.json")

    # Combine and sort by timestamp
    all_events = activity_events + subagent_events
    all_events.sort(key=lambda x: x.get("ts", ""))

    if not all_events:
        print("No old data to import")
        return

    # Load existing telemetry or create new
    if TELEMETRY_FILE.exists():
        telemetry = json.loads(TELEMETRY_FILE.read_text())
        existing_count = len(telemetry.get("events", []))
        print(f"  Existing telemetry has {existing_count} events")
    else:
        telemetry = {
            "session_id": datetime.now(timezone.utc).isoformat(),
            "session_start": datetime.now(timezone.utc).isoformat(),
            "events": [],
            "aggregates": {
                "by_tool": {},
                "by_backend": {},
                "subagents": {},
                "totals": {"calls": 0, "errors": 0, "tokens_est": 0, "duration_ms": 0}
            }
        }

    # Add imported events (prepend so new events come after)
    all_combined = all_events + telemetry.get("events", [])

    # Recalculate aggregates from ALL events (before truncating)
    telemetry["aggregates"] = {
        "by_tool": {},
        "by_backend": {},
        "subagents": {},
        "totals": {"calls": 0, "errors": 0, "tokens_est": 0, "duration_ms": 0}
    }
    update_aggregates(telemetry, all_combined)

    # Build daily_summaries from all events (for historical trending)
    daily_summaries = {}
    for event in all_combined:
        ts = event.get("ts", "")
        if ts:
            # Extract date from timestamp (YYYY-MM-DD)
            date_str = ts[:10] if len(ts) >= 10 else ""
            if date_str and date_str[0].isdigit():
                if date_str not in daily_summaries:
                    daily_summaries[date_str] = {"calls": 0, "tokens": 0, "errors": 0, "duration_ms": 0}
                daily_summaries[date_str]["calls"] += 1
                daily_summaries[date_str]["tokens"] += event.get("tokens_est", 0)
                daily_summaries[date_str]["duration_ms"] += event.get("duration_ms", 0)
                if event.get("status") == "error":
                    daily_summaries[date_str]["errors"] += 1
    telemetry["daily_summaries"] = daily_summaries

    # Keep last 500 events for display (but aggregates include all)
    if len(all_combined) > 500:
        telemetry["events"] = all_combined[-500:]
    else:
        telemetry["events"] = all_combined

    # Save
    TELEMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    TELEMETRY_FILE.write_text(json.dumps(telemetry, indent=2))

    print(f"\n✅ Imported {len(all_events)} historical events")
    print(f"   Total events now: {len(telemetry['events'])}")
    print(f"   Days with data: {len(daily_summaries)}")
    print(f"   Total calls: {telemetry['aggregates']['totals']['calls']}")
    print(f"   Est. tokens: {telemetry['aggregates']['totals']['tokens_est']:,}")


if __name__ == "__main__":
    import_data()
