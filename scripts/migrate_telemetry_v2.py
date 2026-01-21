#!/usr/bin/env python3
"""
Migrate telemetry.json from v1 to v2.0 schema.

This script converts the existing fragmented telemetry structure to the
unified v2.0 schema while preserving all historical data.

Usage:
    python migrate_telemetry_v2.py [--dry-run]
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

from telemetry_schema_v2 import (
    default_telemetry_v2,
    default_day_data,
    default_token_data,
    default_call_data,
)

STATE_DIR = Path(__file__).parent.parent / ".state"
TELEMETRY_FILE = STATE_DIR / "telemetry.json"
BACKUP_FILE = STATE_DIR / "telemetry.v1.backup.json"
OUTPUT_FILE = STATE_DIR / "telemetry.json"


def load_v1_telemetry() -> dict:
    """Load existing v1 telemetry data."""
    # Prefer backup file if exists (contains original v1 data)
    if BACKUP_FILE.exists():
        with open(BACKUP_FILE) as f:
            data = json.load(f)
            # Ensure it's v1 format
            if "daily_summaries" in data:
                print(f"Loading from backup {BACKUP_FILE}")
                return data
    
    if not TELEMETRY_FILE.exists():
        print(f"No telemetry file found at {TELEMETRY_FILE}")
        return {}
    
    with open(TELEMETRY_FILE) as f:
        return json.load(f)


def migrate_v1_to_v2(v1_data: dict) -> dict:
    """Convert v1 telemetry to v2 schema."""
    # Check if already v2
    if v1_data.get("version") == "2.0":
        print("Already v2.0, no migration needed")
        return v1_data
    
    v2_data = default_telemetry_v2()
    
    # Migrate daily_summaries to days
    print("Migrating daily_summaries...")
    daily = v1_data.get("daily_summaries", {})
    for date_key, summary in daily.items():
        if date_key not in v2_data["days"]:
            v2_data["days"][date_key] = default_day_data()
        
        day = v2_data["days"][date_key]
        day["tokens"]["input"] = summary.get("input_tokens", 0)
        day["tokens"]["output"] = summary.get("output_tokens", 0)
        day["tokens"]["cache_read"] = summary.get("cache_read", 0)
        day["tokens"]["cache_creation"] = summary.get("cache_create", 0)
        day["tokens"]["source"] = "router"
        day["calls"]["total"] = summary.get("calls", 0)
        
        duration_ms = summary.get("duration_ms", 0)
        calls = summary.get("calls", 1) or 1
        day["timing"]["avg_response_ms"] = duration_ms / calls if calls > 0 else 0
    
    # Migrate aggregates
    print("Migrating aggregates...")
    agg = v1_data.get("aggregates", {})
    
    # by_tool - v2 schema stores direct integers (tool name → count)
    v2_data["aggregates"]["all_time"]["calls"]["by_tool"] = {
        tool: stats.get("count", 0) for tool, stats in agg.get("by_tool", {}).items()
    }

    # by_backend - v2 schema stores direct integers (backend name → count)
    v2_data["aggregates"]["all_time"]["calls"]["by_backend"] = {
        backend: stats.get("count", 0) for backend, stats in agg.get("by_backend", {}).items()
    }
    
    # totals
    totals = agg.get("totals", {})
    v2_data["aggregates"]["all_time"]["calls"]["total"] = totals.get("calls", 0)
    v2_data["aggregates"]["all_time"]["tokens"]["total"] = totals.get("tokens", 0)
    
    # cache_stats
    print("Migrating cache_stats...")
    cache = v1_data.get("cache_stats", {})
    v2_data["aggregates"]["all_time"]["tokens"]["cache_read"] = cache.get("total_cache_read", 0)
    v2_data["aggregates"]["all_time"]["tokens"]["cache_creation"] = cache.get("total_cache_create", 0)
    
    # Copy events for backward compatibility
    print("Copying events...")
    v2_data["events"] = v1_data.get("events", [])
    
    # Update filter options from aggregates
    print("Building filter options...")
    tools = set(v2_data["aggregates"]["all_time"]["calls"]["by_tool"].keys())
    backends = set(v2_data["aggregates"]["all_time"]["calls"]["by_backend"].keys())
    v2_data["filters"] = {
        "available_tools": sorted(tools),
        "available_backends": sorted(backends),
        "available_sessions": []
    }
    
    v2_data["last_updated"] = datetime.now(timezone.utc).isoformat()
    
    return v2_data


def main():
    dry_run = "--dry-run" in sys.argv
    
    print(f"Loading v1 telemetry...")
    v1_data = load_v1_telemetry()
    
    if not v1_data:
        print("No data to migrate")
        return
    
    print(f"\nV1 Structure:")
    print(f"  - events: {len(v1_data.get('events', []))} items")
    print(f"  - daily_summaries: {len(v1_data.get('daily_summaries', {}))} days")
    print(f"  - aggregates.by_tool: {len(v1_data.get('aggregates', {}).get('by_tool', {}))} tools")
    
    print("\nMigrating to v2.0...")
    v2_data = migrate_v1_to_v2(v1_data)
    
    print(f"\nV2 Structure:")
    print(f"  - days: {len(v2_data.get('days', {}))} days")
    print(f"  - events: {len(v2_data.get('events', []))} items")
    print(f"  - aggregates.all_time.calls.by_tool: {len(v2_data['aggregates']['all_time']['calls']['by_tool'])} tools")
    print(f"  - filters.available_tools: {len(v2_data['filters']['available_tools'])} tools")
    print(f"  - filters.available_backends: {len(v2_data['filters']['available_backends'])} backends")
    
    if dry_run:
        print("\n[DRY RUN] Would save to:", OUTPUT_FILE)
    else:
        print(f"\nSaving v2 telemetry to {OUTPUT_FILE}...")
        with open(OUTPUT_FILE, "w") as f:
            json.dump(v2_data, f, indent=2)
        
        print("Migration complete!")


if __name__ == "__main__":
    main()
