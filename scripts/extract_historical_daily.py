#!/usr/bin/env python3
"""Extract historical daily summaries from metrics_history.json.

Run once to populate daily_summaries with historical data for trending.
"""

import json
from pathlib import Path
from collections import defaultdict

METRICS_HISTORY = Path(__file__).resolve().parent.parent / ".state" / "metrics_history.json"
TELEMETRY_FILE = Path(__file__).resolve().parent.parent / ".state" / "telemetry.json"

# Token estimates by tool type
TOKEN_ESTIMATES = {
    "Read": 2000, "Write": 500, "Edit": 800, "Bash": 1000,
    "Glob": 500, "Grep": 1000, "Task": 5000, "WebFetch": 3000,
    "AskUserQuestion": 200, "TodoWrite": 100, "TaskOutput": 500,
    "Skill": 200, "EnterPlanMode": 100,
    # MCP tools (base names)
    "read_file": 2000, "find_symbol": 1500, "search_for_pattern": 1500,
    "get_symbols_overview": 1000, "list_dir": 500, "replace_content": 800,
    "write_file": 500, "list_directory": 500, "create_text_file": 500,
}


def estimate_tokens(tool_name):
    """Estimate tokens for a tool call."""
    if "mcp__" in tool_name or "__" in tool_name:
        parts = tool_name.split("__")
        base_name = parts[-1] if parts else tool_name
        return TOKEN_ESTIMATES.get(base_name, 500)
    return TOKEN_ESTIMATES.get(tool_name, 500)


def extract():
    if not METRICS_HISTORY.exists():
        print("No metrics_history.json found")
        return

    metrics = json.loads(METRICS_HISTORY.read_text())
    snapshots = metrics.get("snapshots", [])
    print(f"Found {len(snapshots)} snapshots in metrics_history.json")

    # Track daily totals using delta between snapshots
    daily_data = defaultdict(lambda: {"calls": 0, "tokens": 0, "errors": 0, "duration_ms": 0})

    prev_tools = {}
    for snap in snapshots:
        ts = snap.get("timestamp", "")
        date_str = ts[:10] if ts else ""
        if not date_str:
            continue

        tools = snap.get("metrics", {}).get("tools_by_type", {})

        # Calculate delta from previous snapshot
        for tool, count in tools.items():
            prev_count = prev_tools.get(tool, 0)
            delta = max(0, count - prev_count)
            if delta > 0:
                daily_data[date_str]["calls"] += delta
                daily_data[date_str]["tokens"] += delta * estimate_tokens(tool)

        prev_tools = tools.copy()

    print("\nHistorical daily data extracted:")
    for date in sorted(daily_data.keys()):
        d = daily_data[date]
        print(f"  {date}: {d['calls']:,} calls, {d['tokens']:,} tokens")

    # Load existing telemetry and merge
    if TELEMETRY_FILE.exists():
        telemetry = json.loads(TELEMETRY_FILE.read_text())
    else:
        telemetry = {"events": [], "aggregates": {}, "daily_summaries": {}}

    existing_daily = telemetry.get("daily_summaries", {})

    # Merge - newer telemetry data takes precedence over historical estimates
    merged = {}
    all_dates = set(daily_data.keys()) | set(existing_daily.keys())
    for date in all_dates:
        if date in existing_daily:
            merged[date] = existing_daily[date]  # Prefer new accurate data
        else:
            merged[date] = daily_data[date]  # Use historical estimate

    telemetry["daily_summaries"] = merged
    TELEMETRY_FILE.write_text(json.dumps(telemetry, indent=2))

    print(f"\n✅ Merged {len(daily_data)} historical days with {len(existing_daily)} recent days")
    print(f"   Total days with data: {len(merged)}")


if __name__ == "__main__":
    extract()
