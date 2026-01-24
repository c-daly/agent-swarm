#!/usr/bin/env python3
"""Migrate JSONL telemetry files to DuckDB.

Reads all session JSONL files and inserts events into the persistent
DuckDB database via TelemetryService.

Usage:
    python3 scripts/migrate_jsonl_to_duckdb.py
    python3 scripts/migrate_jsonl_to_duckdb.py --dry-run
"""

import json
import sys
from pathlib import Path
from glob import glob

# Add project root and lib to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "lib"))

from lib.telemetry_service import TelemetryService  # noqa: E402


def migrate_jsonl_to_duckdb(dry_run: bool = False) -> dict:
    """Migrate all JSONL files to DuckDB.
    
    Args:
        dry_run: If True, only count events without inserting.
        
    Returns:
        Dict with migration stats.
    """
    state_dir = Path.home() / ".claude/plugins/agent-swarm/.state"
    jsonl_dir = state_dir / "telemetry_v3"
    
    if not jsonl_dir.exists():
        print(f"No JSONL directory found at {jsonl_dir}")
        return {"files": 0, "events": 0, "errors": 0}
    
    # Find all JSONL files (including gzipped)
    patterns = [
        str(jsonl_dir / "*.jsonl"),
        str(jsonl_dir / "*.jsonl.gz"),
    ]
    
    files = []
    for pattern in patterns:
        files.extend(glob(pattern))
    
    if not files:
        print(f"No JSONL files found in {jsonl_dir}")
        return {"files": 0, "events": 0, "errors": 0}
    
    print(f"Found {len(files)} JSONL files to migrate")
    
    if not dry_run:
        service = TelemetryService(data_dir=str(state_dir))
    
    stats = {"files": 0, "events": 0, "errors": 0, "skipped": 0}
    
    for filepath in sorted(files):
        filepath = Path(filepath)
        stats["files"] += 1
        
        print(f"  Processing {filepath.name}...", end=" ")
        
        try:
            # Handle gzipped files
            if filepath.suffix == ".gz":
                import gzip
                opener = gzip.open
            else:
                opener = open
            
            file_events = 0
            file_errors = 0
            
            with opener(filepath, "rt") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        event = json.loads(line)
                        
                        if not dry_run:
                            service.insert_event(event)
                        
                        file_events += 1
                        stats["events"] += 1
                        
                    except json.JSONDecodeError:
                        stats["errors"] += 1
                        file_errors += 1
                    except Exception:
                        stats["errors"] += 1
                        file_errors += 1
            
            print(f"{file_events} events" + (f", {file_errors} errors" if file_errors else ""))
            
        except Exception as e:
            print(f"ERROR: {e}")
            stats["errors"] += 1
    
    return stats


def main():
    dry_run = "--dry-run" in sys.argv
    
    if dry_run:
        print("=== DRY RUN - No data will be written ===\n")
    else:
        print("=== Migrating JSONL to DuckDB ===\n")
    
    stats = migrate_jsonl_to_duckdb(dry_run=dry_run)
    
    print(f"\n=== Migration {'Preview' if dry_run else 'Complete'} ===")
    print(f"  Files processed: {stats['files']}")
    print(f"  Events {'found' if dry_run else 'migrated'}: {stats['events']}")
    print(f"  Errors: {stats['errors']}")
    
    if dry_run:
        print("\nRun without --dry-run to perform migration.")
    else:
        print("\nData now in: ~/.claude/plugins/agent-swarm/.state/telemetry.duckdb")


if __name__ == "__main__":
    main()
