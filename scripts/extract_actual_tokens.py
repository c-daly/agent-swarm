#!/usr/bin/env python3
"""Extract actual token usage from all Claude Code transcripts.

Parses .jsonl transcript files to build accurate historical token data.
Backfills daily_summaries in telemetry.json with real API usage.

Usage:
    python3 extract_actual_tokens.py           # Extract and show summary
    python3 extract_actual_tokens.py --update  # Update telemetry.json
    python3 extract_actual_tokens.py --export  # Export to CSV
"""

import json
import argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import sys

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
TELEMETRY_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/telemetry.json"
STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"


def parse_transcript(filepath: Path) -> list[dict]:
    """Parse a single transcript file and extract usage data."""
    entries = []

    try:
        content = filepath.read_text(errors='replace')
        for line in content.strip().split('\n'):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                msg = data.get("message", {})

                # Only care about assistant messages with usage data
                if msg.get("role") == "assistant" and "usage" in msg:
                    usage = msg["usage"]

                    entry = {
                        "timestamp": data.get("timestamp", ""),
                        "model": msg.get("model", "unknown"),
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "cache_read": usage.get("cache_read_input_tokens", 0),
                        "cache_create": usage.get("cache_creation_input_tokens", 0),
                        "agent_id": data.get("agentId", "main"),
                        "session_id": data.get("sessionId", ""),
                        "git_branch": data.get("gitBranch", ""),
                    }

                    # Calculate total tokens
                    entry["total_tokens"] = (
                        entry["input_tokens"] +
                        entry["output_tokens"] +
                        entry["cache_read"] +
                        entry["cache_create"]
                    )

                    entries.append(entry)
            except json.JSONDecodeError:
                continue
    except Exception as e:
        print(f"  Warning: Could not parse {filepath.name}: {e}", file=sys.stderr)

    return entries


def extract_all_usage() -> dict:
    """Extract usage from all transcript files."""
    all_entries = []
    files_processed = 0
    files_with_data = 0

    # Find all jsonl files
    transcript_files = list(CLAUDE_PROJECTS.glob("**/*.jsonl"))
    print(f"Found {len(transcript_files)} transcript files")

    for i, filepath in enumerate(transcript_files):
        if (i + 1) % 200 == 0:
            print(f"  Processing {i + 1}/{len(transcript_files)}...")

        entries = parse_transcript(filepath)
        if entries:
            all_entries.extend(entries)
            files_with_data += 1
        files_processed += 1

    print(f"Processed {files_processed} files, {files_with_data} had usage data")
    print(f"Extracted {len(all_entries)} API call records")

    return {"entries": all_entries, "files_processed": files_processed}


def aggregate_by_day(entries: list[dict]) -> dict:
    """Aggregate entries by date."""
    daily = defaultdict(lambda: {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read": 0,
        "cache_create": 0,
        "total_tokens": 0,
        "by_model": defaultdict(lambda: {"calls": 0, "tokens": 0}),
        "by_agent": defaultdict(lambda: {"calls": 0, "tokens": 0}),
        "by_session": defaultdict(lambda: {"calls": 0, "tokens": 0, "start": None, "end": None}),
    })

    for entry in entries:
        ts = entry.get("timestamp", "")
        if not ts:
            continue

        # Parse date from ISO timestamp
        try:
            if "T" in ts:
                date = ts.split("T")[0]
            else:
                date = ts[:10]
        except:
            continue

        day = daily[date]
        day["calls"] += 1
        day["input_tokens"] += entry["input_tokens"]
        day["output_tokens"] += entry["output_tokens"]
        day["cache_read"] += entry["cache_read"]
        day["cache_create"] += entry["cache_create"]
        day["total_tokens"] += entry["total_tokens"]

        # By model
        model = entry.get("model", "unknown")
        day["by_model"][model]["calls"] += 1
        day["by_model"][model]["tokens"] += entry["total_tokens"]

        # By agent
        agent = entry.get("agent_id", "main") or "main"
        day["by_agent"][agent]["calls"] += 1
        day["by_agent"][agent]["tokens"] += entry["total_tokens"]

        # By session
        session = entry.get("session_id", "unknown") or "unknown"
        day["by_session"][session]["calls"] += 1
        day["by_session"][session]["tokens"] += entry["total_tokens"]
        # Track session time range
        if day["by_session"][session]["start"] is None or ts < day["by_session"][session]["start"]:
            day["by_session"][session]["start"] = ts
        if day["by_session"][session]["end"] is None or ts > day["by_session"][session]["end"]:
            day["by_session"][session]["end"] = ts

    # Convert defaultdicts to regular dicts for JSON serialization
    result = {}
    for date, data in daily.items():
        result[date] = {
            "calls": data["calls"],
            "input_tokens": data["input_tokens"],
            "output_tokens": data["output_tokens"],
            "cache_read": data["cache_read"],
            "cache_create": data["cache_create"],
            "total_tokens": data["total_tokens"],
            "by_model": dict(data["by_model"]),
            "by_agent": dict(data["by_agent"]),
            "by_session": dict(data["by_session"]),
        }

    return result


def print_summary(daily_data: dict):
    """Print a summary of the extracted data."""
    print("\n" + "=" * 80)
    print("DAILY TOKEN USAGE SUMMARY (Actual API Data)")
    print("=" * 80)

    total_tokens = 0
    total_calls = 0
    total_sessions = 0

    for date in sorted(daily_data.keys()):
        data = daily_data[date]
        total_tokens += data["total_tokens"]
        total_calls += data["calls"]
        sessions = len(data.get("by_session", {}))
        total_sessions += sessions

        # Format numbers with commas
        tokens_fmt = f"{data['total_tokens']:,}"
        calls_fmt = f"{data['calls']:,}"

        # Model breakdown
        models = ", ".join(f"{m}: {d['calls']}" for m, d in sorted(data["by_model"].items()))

        print(f"{date}: {tokens_fmt:>15} tokens | {calls_fmt:>6} calls | {sessions:>3} sessions | {models}")

    print("-" * 80)
    print(f"TOTAL:     {total_tokens:>15,} tokens | {total_calls:>6,} calls | {total_sessions:>3} sessions")
    print("=" * 80)

    # Cache efficiency
    total_cache_read = sum(d["cache_read"] for d in daily_data.values())
    total_cache_create = sum(d["cache_create"] for d in daily_data.values())
    total_input = sum(d["input_tokens"] for d in daily_data.values())
    total_output = sum(d["output_tokens"] for d in daily_data.values())

    print(f"\nToken Breakdown:")
    print(f"  Input tokens:        {total_input:>15,}")
    print(f"  Output tokens:       {total_output:>15,}")
    print(f"  Cache read (hits):   {total_cache_read:>15,}")
    print(f"  Cache create (miss): {total_cache_create:>15,}")

    if total_cache_read + total_cache_create > 0:
        cache_hit_rate = total_cache_read / (total_cache_read + total_cache_create) * 100
        print(f"\n  Cache hit rate: {cache_hit_rate:.1f}%")


def update_telemetry(daily_data: dict):
    """Update telemetry.json with actual historical data."""
    if TELEMETRY_FILE.exists():
        telemetry = json.loads(TELEMETRY_FILE.read_text())
    else:
        telemetry = {"events": [], "daily_summaries": {}, "aggregates": {}}

    # Create new daily_summaries_actual section
    telemetry["daily_summaries_actual"] = {}

    for date, data in daily_data.items():
        telemetry["daily_summaries_actual"][date] = {
            "calls": data["calls"],
            "tokens": data["total_tokens"],
            "input_tokens": data["input_tokens"],
            "output_tokens": data["output_tokens"],
            "cache_read": data["cache_read"],
            "cache_create": data["cache_create"],
            "by_model": data["by_model"],
            "by_agent": data["by_agent"],
            "by_session": data["by_session"],
        }

    # Also update the regular daily_summaries with total_tokens
    for date, data in daily_data.items():
        if date not in telemetry.get("daily_summaries", {}):
            telemetry.setdefault("daily_summaries", {})[date] = {
                "calls": data["calls"],
                "tokens": data["total_tokens"],
                "errors": 0,
                "duration_ms": 0
            }
        else:
            # Update tokens with actual value
            telemetry["daily_summaries"][date]["tokens"] = data["total_tokens"]
            telemetry["daily_summaries"][date]["calls"] = data["calls"]

    # Save
    TELEMETRY_FILE.write_text(json.dumps(telemetry, indent=2))
    print(f"\n✅ Updated {TELEMETRY_FILE}")


def export_csv(daily_data: dict):
    """Export to CSV file."""
    csv_file = STATE_DIR / "token_usage_history.csv"

    lines = ["date,calls,total_tokens,input_tokens,output_tokens,cache_read,cache_create"]

    for date in sorted(daily_data.keys()):
        data = daily_data[date]
        lines.append(f"{date},{data['calls']},{data['total_tokens']},{data['input_tokens']},{data['output_tokens']},{data['cache_read']},{data['cache_create']}")

    csv_file.write_text("\n".join(lines))
    print(f"\n✅ Exported to {csv_file}")


def main():
    parser = argparse.ArgumentParser(description="Extract actual token usage from transcripts")
    parser.add_argument("--update", action="store_true", help="Update telemetry.json")
    parser.add_argument("--export", action="store_true", help="Export to CSV")
    args = parser.parse_args()

    print("Extracting token usage from Claude Code transcripts...")
    print()

    # Extract all usage data
    result = extract_all_usage()
    entries = result["entries"]

    if not entries:
        print("No usage data found!")
        return

    # Aggregate by day
    daily_data = aggregate_by_day(entries)

    # Print summary
    print_summary(daily_data)

    # Update telemetry if requested
    if args.update:
        update_telemetry(daily_data)

    # Export CSV if requested
    if args.export:
        export_csv(daily_data)

    if not args.update and not args.export:
        print("\nRun with --update to save to telemetry.json")
        print("Run with --export to save to CSV")


if __name__ == "__main__":
    main()
