#!/usr/bin/env python3
"""Import old activity.log and subagent_metrics.json into v2 telemetry format.

Merges historical data with existing v2 telemetry.json, preserving all data.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from lib.telemetry_schema_v2 import (
    load_telemetry_v2,
    save_telemetry_v2,
    ensure_day,
    recompute_aggregates,
    update_filter_options,
)

STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"
ACTIVITY_LOG = STATE_DIR / "activity.log"
SUBAGENT_METRICS = STATE_DIR / "subagent_metrics.json"

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
                        if ":" in details:
                            tool = details.split(":")[0].strip()
                        else:
                            tool = details.split()[0] if details else "unknown"

                    if event_type in ["ALLOWED", "BLOCKED", "WARNING"]:
                        events.append({
                            "ts": f"{today}T{ts}",
                            "tool": tool,
                            "backend": "native",
                            "duration_ms": 0,
                            "status": "error" if event_type == "BLOCKED" else "success",
                            "tokens_est": TOKEN_ESTIMATES.get(tool, 500),
                            "subagent_type": "",
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
                            "backend": "native",
                            "duration_ms": 0,
                            "status": "error" if event_type == "BLOCKED" else "success",
                            "tokens_est": TOKEN_ESTIMATES.get(tool, 500),
                            "subagent_type": "",
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
            "backend": "native",
            "duration_ms": 0,
            "status": "success",
            "tokens_est": tokens,
            "subagent_type": agent_type,
        })

    return events


def merge_events_into_v2(telemetry: dict, events: list) -> None:
    """Merge parsed events into v2 telemetry structure."""
    for event in events:
        ts = event.get("ts", "")
        if not ts or len(ts) < 10:
            continue
        
        date_str = ts[:10]
        if not date_str[0].isdigit():
            continue

        tool = event.get("tool", "unknown")
        backend = event.get("backend", "native")
        tokens_est = event.get("tokens_est", 0)
        
        # Ensure day exists in v2 structure
        ensure_day(telemetry, date_str)
        day = telemetry["days"][date_str]
        
        # Update day tokens (estimated, so use input field)
        day["tokens"]["input"] = day["tokens"].get("input", 0) + tokens_est
        day["tokens"]["source"] = "estimated"
        
        # Update day calls
        day["calls"]["total"] = day["calls"].get("total", 0) + 1
        if "by_tool" not in day["calls"]:
            day["calls"]["by_tool"] = {}
        day["calls"]["by_tool"][tool] = day["calls"]["by_tool"].get(tool, 0) + 1
        if "by_backend" not in day["calls"]:
            day["calls"]["by_backend"] = {}
        day["calls"]["by_backend"][backend] = day["calls"]["by_backend"].get(backend, 0) + 1


def import_data():
    """Import old data into v2 telemetry.json."""
    print("Importing old telemetry data into v2 format...")

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

    # Load existing v2 telemetry or create new
    telemetry = load_telemetry_v2()
    print(f"  Loaded v2 telemetry (version: {telemetry.get('version', 'unknown')})")

    # Merge events into v2 structure
    merge_events_into_v2(telemetry, all_events)

    # Recompute aggregates from days data
    recompute_aggregates(telemetry)
    
    # Update filter options
    update_filter_options(telemetry)

    # Save
    save_telemetry_v2(telemetry)

    # Summary
    agg = telemetry.get("aggregates", {}).get("all_time", {})
    calls = agg.get("calls", {})
    tokens = agg.get("tokens", {})
    
    print(f"\n✅ Imported {len(all_events)} historical events into v2 format")
    print(f"   Days with data: {len(telemetry.get('days', {}))}")
    print(f"   Total calls: {calls.get('total', 0)}")
    print(f"   Est. tokens: {tokens.get('input', 0) + tokens.get('output', 0):,}")


if __name__ == "__main__":
    import_data()
