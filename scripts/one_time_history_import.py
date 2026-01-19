#!/usr/bin/env python3
"""One-time migration: Import historical data from metrics_history.json into telemetry.json.

This script extracts daily summaries from the old metrics_history.json format
and adds them as historical_timeline to the new telemetry.json format.

Run once after the telemetry system is set up to preserve historical data.

Usage:
    python3 scripts/one_time_history_import.py
"""

import json
from pathlib import Path
from collections import defaultdict

STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"
METRICS_HIST = STATE_DIR / "metrics_history.json"
TELEMETRY = STATE_DIR / "telemetry.json"


def main():
    if not METRICS_HIST.exists():
        print(f"ERROR: {METRICS_HIST} not found")
        return 1

    if not TELEMETRY.exists():
        print(f"ERROR: {TELEMETRY} not found - run some tools first to initialize")
        return 1

    # Load metrics history
    with open(METRICS_HIST) as f:
        hist = json.load(f)

    snapshots = hist.get("snapshots", [])
    print(f"Loaded {len(snapshots)} snapshots from metrics_history.json")

    # Extract daily maximums (snapshots accumulate throughout the day)
    daily_data = defaultdict(lambda: {"tokens": 0, "events": 0, "tools": {}})

    for snap in snapshots:
        date = snap.get("timestamp", "")[:10]  # YYYY-MM-DD
        if not date:
            continue

        metrics = snap.get("metrics", {})
        events = metrics.get("total_events", 0)
        total_tokens = sum(metrics.get("token_by_tool", {}).values())

        # Keep max per day (snapshots accumulate)
        if events > daily_data[date]["events"]:
            daily_data[date]["events"] = events
            daily_data[date]["tokens"] = total_tokens
            daily_data[date]["tools"] = metrics.get("tools_by_type", {})

    # Build timeline array
    timeline = []
    for date in sorted(daily_data.keys()):
        d = daily_data[date]
        timeline.append({
            "date": date,
            "tokens": d["tokens"],
            "events": d["events"],
            "tools": d["tools"]
        })

    print(f"Built timeline with {len(timeline)} days:")
    for t in timeline:
        print(f"  {t['date']}: {t['tokens']:,} tokens, {t['events']} events")

    # Load current telemetry
    with open(TELEMETRY) as f:
        telemetry = json.load(f)

    # Check if already imported
    if telemetry.get("historical_timeline"):
        print(f"\nWARNING: historical_timeline already exists with {len(telemetry['historical_timeline'])} entries")
        response = input("Overwrite? [y/N]: ").strip().lower()
        if response != 'y':
            print("Aborted")
            return 0

    # Add historical_timeline
    telemetry["historical_timeline"] = timeline

    # Save
    with open(TELEMETRY, "w") as f:
        json.dump(telemetry, f, indent=2)

    print(f"\nSaved telemetry with historical_timeline ({len(timeline)} entries)")
    return 0


if __name__ == "__main__":
    exit(main())
