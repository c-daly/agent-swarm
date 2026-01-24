#!/usr/bin/env python3
"""Migrate telemetry.json to v2 format.

Transforms:
- Adds version: "2.0"
- Copies daily_summaries data into days{} structure
- Builds filter_options from aggregates.by_tool and aggregates.by_backend
- Preserves all existing data
"""

import json
from pathlib import Path

TELEMETRY_FILE = Path.home() / ".claude" / "plugins" / "agent-swarm" / ".state" / "telemetry.json"

def migrate_to_v2():
    """Migrate telemetry.json to v2 format."""
    if not TELEMETRY_FILE.exists():
        print(f"ERROR: {TELEMETRY_FILE} not found")
        return False
    
    # Load current data
    with open(TELEMETRY_FILE) as f:
        data = json.load(f)
    
    # Check if already v2
    if data.get("version") == "2.0":
        print("Already at version 2.0, nothing to do")
        return True
    
    print(f"Migrating from version {data.get('version', '1.0 (implicit)')} to 2.0")
    
    # Set version
    data["version"] = "2.0"
    
    # Build days{} from daily_summaries{}
    daily_summaries = data.get("daily_summaries", {})
    days = data.get("days", {})
    
    for date_str, summary in daily_summaries.items():
        if date_str not in days:
            # Create v2 day structure
            days[date_str] = {
                "sessions": {},  # Will be populated by future events
                "aggregates": {
                    "calls": summary.get("calls", 0),
                    "tokens": summary.get("tokens", 0),
                    "errors": summary.get("errors", 0),
                    "duration_ms": summary.get("duration_ms", 0),
                    "cache_read": summary.get("cache_read", 0),
                    "cache_create": summary.get("cache_create", 0),
                    "input_tokens": summary.get("input_tokens", 0),
                    "output_tokens": summary.get("output_tokens", 0),
                    "by_tool": {},  # Would need event-level data to reconstruct
                    "by_backend": {}  # Would need event-level data to reconstruct
                }
            }
    
    data["days"] = days
    
    # Build filter_options from aggregates
    aggregates = data.get("aggregates", {})
    by_tool = aggregates.get("by_tool", {})
    by_backend = aggregates.get("by_backend", {})
    
    filter_options = {
        "tools": sorted(by_tool.keys()),
        "backends": sorted(by_backend.keys()),
        "sessions": [],  # Would need to extract from events
        "date_range": {
            "earliest": min(daily_summaries.keys()) if daily_summaries else None,
            "latest": max(daily_summaries.keys()) if daily_summaries else None
        }
    }
    
    # Extract unique session_ids from events if available
    events = data.get("events", [])
    session_ids = set()
    for event in events:
        sid = event.get("session_id")
        if sid:
            session_ids.add(sid)
    filter_options["sessions"] = sorted(session_ids)
    
    data["filter_options"] = filter_options
    
    # Backup original
    backup_file = TELEMETRY_FILE.with_suffix(".json.bak")
    with open(backup_file, "w") as f:
        json.dump(data, f)  # Save current state as backup before writing
    print(f"Backup saved to {backup_file}")
    
    # Actually, backup the ORIGINAL file first
    import shutil
    original_backup = TELEMETRY_FILE.with_suffix(".json.v1.bak")
    shutil.copy(TELEMETRY_FILE, original_backup)
    print(f"Original backup saved to {original_backup}")
    
    # Save migrated data
    with open(TELEMETRY_FILE, "w") as f:
        json.dump(data, f, indent=2)
    
    print("Migration complete!")
    print(f"  - Version: {data['version']}")
    print(f"  - Days populated: {len(days)}")
    print("  - Filter options:")
    print(f"    - Tools: {len(filter_options['tools'])}")
    print(f"    - Backends: {len(filter_options['backends'])}")
    print(f"    - Sessions: {len(filter_options['sessions'])}")
    print(f"    - Date range: {filter_options['date_range']['earliest']} to {filter_options['date_range']['latest']}")
    
    return True


if __name__ == "__main__":
    success = migrate_to_v2()
    exit(0 if success else 1)
