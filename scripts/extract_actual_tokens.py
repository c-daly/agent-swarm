#!/usr/bin/env python3
"""Extract actual token usage from all Claude Code transcripts.

Parses .jsonl transcript files to build accurate historical token data.
Computes DELTAS between consecutive messages (not cumulative sums).
Backfills daily_summaries in telemetry.json with real API usage.

Usage:
    python3 extract_actual_tokens.py           # Extract and show summary
    python3 extract_actual_tokens.py --update  # Update telemetry.json
    python3 extract_actual_tokens.py --export  # Export to CSV
"""

import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import sys

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
TELEMETRY_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/telemetry.json"
STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"


def parse_timestamp(ts: str) -> datetime | None:
    """Parse ISO timestamp to datetime."""
    if not ts:
        return None
    try:
        # Handle various ISO formats
        ts = ts.replace("Z", "+00:00")
        if "." in ts:
            # Truncate microseconds if too long
            parts = ts.split(".")
            if "+" in parts[1]:
                micro, tz = parts[1].split("+")
                ts = f"{parts[0]}.{micro[:6]}+{tz}"
            elif "-" in parts[1] and parts[1].count("-") == 1:
                micro, tz = parts[1].split("-")
                ts = f"{parts[0]}.{micro[:6]}-{tz}"
        return datetime.fromisoformat(ts)
    except:
        return None


def parse_transcript(filepath: Path) -> dict:
    """Parse a single transcript file and extract usage data with deltas.

    Returns dict with:
        - entries: list of usage entries with delta values
        - session_id: the session ID
        - final_cumulative: final cumulative values (absolutes)
        - start_time, end_time: session time bounds
    """
    raw_entries = []
    session_id = None

    try:
        content = filepath.read_text(errors='replace')
        for line in content.strip().split('\n'):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                msg = data.get("message", {})

                # Capture session_id from any entry
                if not session_id and data.get("sessionId"):
                    session_id = data.get("sessionId")

                # Only care about assistant messages with usage data
                if msg.get("role") == "assistant" and "usage" in msg:
                    usage = msg["usage"]
                    ts = data.get("timestamp", "")

                    raw_entries.append({
                        "timestamp": ts,
                        "parsed_ts": parse_timestamp(ts),
                        "model": msg.get("model", "unknown"),
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "cache_read": usage.get("cache_read_input_tokens", 0),
                        "cache_create": usage.get("cache_creation_input_tokens", 0),
                        "agent_id": data.get("agentId", "main"),
                        "session_id": data.get("sessionId", session_id or "unknown"),
                        "git_branch": data.get("gitBranch", ""),
                    })
            except json.JSONDecodeError:
                continue
    except Exception as e:
        print(f"  Warning: Could not parse {filepath.name}: {e}", file=sys.stderr)
        return {"entries": [], "session_id": None}

    if not raw_entries:
        return {"entries": [], "session_id": session_id}

    # Sort by timestamp within this transcript
    raw_entries.sort(key=lambda x: x["timestamp"])

    # Compute deltas between consecutive entries
    delta_entries = []
    prev = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_create": 0}

    for entry in raw_entries:
        # Calculate delta from previous entry
        delta = {
            "timestamp": entry["timestamp"],
            "parsed_ts": entry["parsed_ts"],
            "model": entry["model"],
            "agent_id": entry["agent_id"],
            "session_id": entry["session_id"],
            "git_branch": entry["git_branch"],
            # Delta values (incremental)
            "input_tokens": max(0, entry["input_tokens"] - prev["input_tokens"]),
            "output_tokens": max(0, entry["output_tokens"] - prev["output_tokens"]),
            "cache_read": max(0, entry["cache_read"] - prev["cache_read"]),
            "cache_create": max(0, entry["cache_create"] - prev["cache_create"]),
            # Also store cumulative for reference
            "cumulative_input": entry["input_tokens"],
            "cumulative_output": entry["output_tokens"],
            "cumulative_cache_read": entry["cache_read"],
            "cumulative_cache_create": entry["cache_create"],
        }

        # Total delta
        delta["total_tokens"] = (
            delta["input_tokens"] +
            delta["output_tokens"] +
            delta["cache_read"] +
            delta["cache_create"]
        )

        delta_entries.append(delta)
        prev = {
            "input_tokens": entry["input_tokens"],
            "output_tokens": entry["output_tokens"],
            "cache_read": entry["cache_read"],
            "cache_create": entry["cache_create"],
        }

    # Get final cumulative values (absolutes)
    final = raw_entries[-1] if raw_entries else {}
    final_cumulative = {
        "input_tokens": final.get("input_tokens", 0),
        "output_tokens": final.get("output_tokens", 0),
        "cache_read": final.get("cache_read", 0),
        "cache_create": final.get("cache_create", 0),
        "total_tokens": (
            final.get("input_tokens", 0) +
            final.get("output_tokens", 0) +
            final.get("cache_read", 0) +
            final.get("cache_create", 0)
        ),
    }

    # Get time bounds
    start_time = raw_entries[0]["parsed_ts"] if raw_entries else None
    end_time = raw_entries[-1]["parsed_ts"] if raw_entries else None

    return {
        "entries": delta_entries,
        "session_id": session_id,
        "final_cumulative": final_cumulative,
        "start_time": start_time,
        "end_time": end_time,
        "call_count": len(delta_entries),
    }


def extract_all_usage() -> dict:
    """Extract usage from all transcript files."""
    all_entries = []
    sessions = {}  # session_id -> session metadata
    files_processed = 0
    files_with_data = 0

    # Find all jsonl files
    transcript_files = list(CLAUDE_PROJECTS.glob("**/*.jsonl"))
    print(f"Found {len(transcript_files)} transcript files")

    for i, filepath in enumerate(transcript_files):
        if (i + 1) % 200 == 0:
            print(f"  Processing {i + 1}/{len(transcript_files)}...")

        result = parse_transcript(filepath)
        entries = result["entries"]

        if entries:
            all_entries.extend(entries)
            files_with_data += 1

            # Track session metadata
            sid = result["session_id"] or filepath.stem
            if sid not in sessions or (result["end_time"] and
                (sessions[sid].get("end_time") is None or
                 result["end_time"] > sessions[sid]["end_time"])):
                sessions[sid] = {
                    "start_time": result["start_time"],
                    "end_time": result["end_time"],
                    "final_cumulative": result["final_cumulative"],
                    "call_count": result["call_count"],
                }
        files_processed += 1

    print(f"Processed {files_processed} files, {files_with_data} had usage data")
    print(f"Extracted {len(all_entries)} API call records (delta-based)")
    print(f"Found {len(sessions)} unique sessions")

    return {
        "entries": all_entries,
        "sessions": sessions,
        "files_processed": files_processed,
    }


def aggregate_by_day(entries: list[dict], sessions: dict) -> dict:
    """Aggregate entries by date with both incremental and absolute values."""
    daily = defaultdict(lambda: {
        # Incremental (delta-based) - actual work done
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read": 0,
        "cache_create": 0,
        "total_tokens": 0,
        # Session tracking for work hours
        "session_times": [],  # list of (start, end) tuples
        "work_hours": 0,
        # Breakdowns
        "by_model": defaultdict(lambda: {"calls": 0, "tokens": 0}),
        "by_agent": defaultdict(lambda: {"calls": 0, "tokens": 0}),
        "by_session": defaultdict(lambda: {
            "calls": 0, "tokens": 0, "start": None, "end": None
        }),
    })

    for entry in entries:
        ts = entry.get("timestamp", "")
        if not ts:
            continue

        # Parse date from ISO timestamp
        try:
            date = ts.split("T")[0] if "T" in ts else ts[:10]
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

        # By session - track time bounds
        session = entry.get("session_id", "unknown") or "unknown"
        day["by_session"][session]["calls"] += 1
        day["by_session"][session]["tokens"] += entry["total_tokens"]

        parsed_ts = entry.get("parsed_ts")
        if parsed_ts:
            if day["by_session"][session]["start"] is None or ts < day["by_session"][session]["start"]:
                day["by_session"][session]["start"] = ts
            if day["by_session"][session]["end"] is None or ts > day["by_session"][session]["end"]:
                day["by_session"][session]["end"] = ts

    # Calculate work hours per day from session time spans
    for date, data in daily.items():
        total_hours = 0
        for sid, sdata in data["by_session"].items():
            if sdata["start"] and sdata["end"]:
                start = parse_timestamp(sdata["start"])
                end = parse_timestamp(sdata["end"])
                if start and end and end > start:
                    hours = (end - start).total_seconds() / 3600
                    total_hours += hours
        data["work_hours"] = round(total_hours, 2)

    # Convert defaultdicts and add normalized metrics
    result = {}
    for date, data in daily.items():
        work_hours = data["work_hours"] or 1  # Avoid division by zero
        calls = data["calls"] or 1

        result[date] = {
            # Incremental (actual work)
            "calls": data["calls"],
            "input_tokens": data["input_tokens"],
            "output_tokens": data["output_tokens"],
            "cache_read": data["cache_read"],
            "cache_create": data["cache_create"],
            "total_tokens": data["total_tokens"],
            # Time tracking
            "work_hours": data["work_hours"],
            "sessions": len(data["by_session"]),
            # Normalized metrics (for comparison)
            "tokens_per_hour": round(data["total_tokens"] / work_hours),
            "tokens_per_call": round(data["total_tokens"] / calls),
            "calls_per_hour": round(calls / work_hours, 1),
            # Breakdowns
            "by_model": dict(data["by_model"]),
            "by_agent": dict(data["by_agent"]),
            "by_session": {k: dict(v) for k, v in data["by_session"].items()},
        }

    return result


def calculate_session_absolutes(sessions: dict) -> dict:
    """Calculate absolute totals from session final values."""
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read": 0,
        "cache_create": 0,
        "total_tokens": 0,
        "sessions": len(sessions),
    }

    for sid, sdata in sessions.items():
        final = sdata.get("final_cumulative", {})
        totals["input_tokens"] += final.get("input_tokens", 0)
        totals["output_tokens"] += final.get("output_tokens", 0)
        totals["cache_read"] += final.get("cache_read", 0)
        totals["cache_create"] += final.get("cache_create", 0)
        totals["total_tokens"] += final.get("total_tokens", 0)

    return totals


def print_summary(daily_data: dict, session_absolutes: dict):
    """Print a summary of the extracted data."""
    print("\n" + "=" * 100)
    print("DAILY TOKEN USAGE SUMMARY (Delta-based Incremental)")
    print("=" * 100)

    total_tokens = 0
    total_calls = 0
    total_hours = 0

    header = f"{'Date':<12} {'Tokens':>14} {'Calls':>7} {'Hours':>6} {'Tok/Hr':>10} {'Tok/Call':>10} {'Sessions':>8}"
    print(header)
    print("-" * 100)

    for date in sorted(daily_data.keys()):
        data = daily_data[date]
        total_tokens += data["total_tokens"]
        total_calls += data["calls"]
        total_hours += data["work_hours"]

        print(f"{date:<12} {data['total_tokens']:>14,} {data['calls']:>7,} "
              f"{data['work_hours']:>6.1f} {data['tokens_per_hour']:>10,} "
              f"{data['tokens_per_call']:>10,} {data['sessions']:>8}")

    print("-" * 100)
    avg_tok_hr = round(total_tokens / total_hours) if total_hours > 0 else 0
    avg_tok_call = round(total_tokens / total_calls) if total_calls > 0 else 0
    print(f"{'TOTAL':<12} {total_tokens:>14,} {total_calls:>7,} "
          f"{total_hours:>6.1f} {avg_tok_hr:>10,} {avg_tok_call:>10,}")
    print("=" * 100)

    # Token breakdown
    total_input = sum(d["input_tokens"] for d in daily_data.values())
    total_output = sum(d["output_tokens"] for d in daily_data.values())
    total_cache_read = sum(d["cache_read"] for d in daily_data.values())
    total_cache_create = sum(d["cache_create"] for d in daily_data.values())

    print(f"\nIncremental Token Breakdown (Delta-based):")
    print(f"  Input tokens:        {total_input:>15,}")
    print(f"  Output tokens:       {total_output:>15,}")
    print(f"  Cache read (hits):   {total_cache_read:>15,}")
    print(f"  Cache create (miss): {total_cache_create:>15,}")

    if total_cache_read + total_cache_create > 0:
        cache_hit_rate = total_cache_read / (total_cache_read + total_cache_create) * 100
        print(f"  Cache hit rate:      {cache_hit_rate:>14.1f}%")

    # Session absolutes (cumulative final values)
    print(f"\nSession Absolutes (Final cumulative per session):")
    print(f"  Sessions:            {session_absolutes['sessions']:>15,}")
    print(f"  Total tokens:        {session_absolutes['total_tokens']:>15,}")
    print(f"  Input tokens:        {session_absolutes['input_tokens']:>15,}")
    print(f"  Output tokens:       {session_absolutes['output_tokens']:>15,}")
    print(f"  Cache read:          {session_absolutes['cache_read']:>15,}")
    print(f"  Cache create:        {session_absolutes['cache_create']:>15,}")


def update_telemetry(daily_data: dict, session_absolutes: dict):
    """Update telemetry.json with actual historical data."""
    if TELEMETRY_FILE.exists():
        telemetry = json.loads(TELEMETRY_FILE.read_text())
    else:
        telemetry = {"events": [], "daily_summaries": {}, "aggregates": {}}

    # Store both incremental and absolute data
    telemetry["daily_summaries_incremental"] = {}
    telemetry["session_absolutes"] = session_absolutes

    for date, data in daily_data.items():
        telemetry["daily_summaries_incremental"][date] = {
            "calls": data["calls"],
            "tokens": data["total_tokens"],
            "input_tokens": data["input_tokens"],
            "output_tokens": data["output_tokens"],
            "cache_read": data["cache_read"],
            "cache_create": data["cache_create"],
            "work_hours": data["work_hours"],
            "sessions": data["sessions"],
            "tokens_per_hour": data["tokens_per_hour"],
            "tokens_per_call": data["tokens_per_call"],
            "calls_per_hour": data["calls_per_hour"],
            "by_model": data["by_model"],
            "by_agent": data["by_agent"],
        }

    # Update the regular daily_summaries with incremental values
    for date, data in daily_data.items():
        telemetry.setdefault("daily_summaries", {})[date] = {
            "calls": data["calls"],
            "tokens": data["total_tokens"],
            "input_tokens": data.get("input_tokens", 0),
            "output_tokens": data.get("output_tokens", 0),
            "cache_read": data.get("cache_read", 0),
            "cache_create": data.get("cache_create", 0),
            "work_hours": data["work_hours"],
            "tokens_per_hour": data["tokens_per_hour"],
            "errors": telemetry.get("daily_summaries", {}).get(date, {}).get("errors", 0),
            "duration_ms": telemetry.get("daily_summaries", {}).get(date, {}).get("duration_ms", 0),
        }

    # Save
    TELEMETRY_FILE.write_text(json.dumps(telemetry, indent=2))
    print(f"\n✅ Updated {TELEMETRY_FILE}")


def export_csv(daily_data: dict):
    """Export to CSV file with normalized metrics."""
    csv_file = STATE_DIR / "token_usage_history.csv"

    lines = ["date,calls,total_tokens,input_tokens,output_tokens,cache_read,cache_create,work_hours,tokens_per_hour,tokens_per_call,calls_per_hour,sessions"]

    for date in sorted(daily_data.keys()):
        d = daily_data[date]
        lines.append(
            f"{date},{d['calls']},{d['total_tokens']},{d['input_tokens']},"
            f"{d['output_tokens']},{d['cache_read']},{d['cache_create']},"
            f"{d['work_hours']},{d['tokens_per_hour']},{d['tokens_per_call']},"
            f"{d['calls_per_hour']},{d['sessions']}"
        )

    csv_file.write_text("\n".join(lines))
    print(f"\n✅ Exported to {csv_file}")


def main():
    parser = argparse.ArgumentParser(description="Extract actual token usage from transcripts")
    parser.add_argument("--update", action="store_true", help="Update telemetry.json")
    parser.add_argument("--export", action="store_true", help="Export to CSV")
    args = parser.parse_args()

    print("Extracting token usage from Claude Code transcripts...")
    print("(Computing deltas between consecutive messages per session)")
    print()

    # Extract all usage data
    result = extract_all_usage()
    entries = result["entries"]
    sessions = result["sessions"]

    if not entries:
        print("No usage data found!")
        return

    # Aggregate by day (incremental/delta-based)
    daily_data = aggregate_by_day(entries, sessions)

    # Calculate session absolutes
    session_absolutes = calculate_session_absolutes(sessions)

    # Print summary
    print_summary(daily_data, session_absolutes)

    # Update telemetry if requested
    if args.update:
        update_telemetry(daily_data, session_absolutes)

    # Export CSV if requested
    if args.export:
        export_csv(daily_data)

    if not args.update and not args.export:
        print("\nRun with --update to save to telemetry.json")
        print("Run with --export to save to CSV")


if __name__ == "__main__":
    main()
