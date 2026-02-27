#!/usr/bin/env python3
"""Rebuild daily_summaries from existing telemetry.json events.

Run this once to populate historical daily data for the token trend chart.
"""

import json
from pathlib import Path

TELEMETRY_FILE = Path(__file__).resolve().parent.parent / ".state" / "telemetry.json"


def rebuild():
    if not TELEMETRY_FILE.exists():
        print("No telemetry.json found")
        return

    telemetry = json.loads(TELEMETRY_FILE.read_text())
    events = telemetry.get("events", [])

    print(f"Processing {len(events)} events...")

    # Build daily_summaries from events
    daily_summaries = telemetry.get("daily_summaries", {})

    for event in events:
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
    TELEMETRY_FILE.write_text(json.dumps(telemetry, indent=2))

    print("\n✅ Rebuilt daily_summaries")
    print(f"   Days with data: {len(daily_summaries)}")
    for date_str in sorted(daily_summaries.keys()):
        summary = daily_summaries[date_str]
        print(f"   {date_str}: {summary['calls']} calls, {summary['tokens']:,} tokens")


if __name__ == "__main__":
    rebuild()
