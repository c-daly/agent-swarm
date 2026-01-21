#!/usr/bin/env python3
"""
JSONL Extractor - Extract token usage from Claude session logs.

Processes JSONL files from ~/.claude/projects/ to extract actual token usage
data and merge it into the v2 telemetry structure.

Features:
- Chunked processing for large files
- Incremental processing (tracks processed files)
- Background-friendly (can be interrupted and resumed)
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional, Any
import hashlib

# Add lib to path
lib_dir = Path(__file__).parent
sys.path.insert(0, str(lib_dir))

from telemetry_schema_v2 import (
    TelemetryV2,
    DayData,
    TokenData,
    SessionData,
    default_day_data,
    default_token_data,
    default_call_data,
    ensure_day,
    merge_tokens,
    merge_calls,
    add_to_filters,
    load_telemetry_v2,
    save_telemetry_v2,
    recompute_aggregates,
    update_filter_options,
)

# Constants
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
STATE_DIR = Path(__file__).parent.parent / ".state"
TELEMETRY_FILE = STATE_DIR / "telemetry.json"
PROGRESS_FILE = STATE_DIR / "jsonl_processing_progress.json"

# Processing limits
MAX_FILES_PER_BATCH = 50  # Process 50 files at a time
MAX_LINES_PER_FILE = 100000  # Skip files with more lines (likely corrupted)
CHUNK_SIZE = 8192  # Bytes to read at a time


# ─────────────────────────────────────────────────────────────────
# File Discovery
# ─────────────────────────────────────────────────────────────────

def find_jsonl_files() -> list[Path]:
    """Find all JSONL session log files."""
    if not CLAUDE_PROJECTS_DIR.exists():
        return []
    
    jsonl_files = []
    for root, dirs, files in os.walk(CLAUDE_PROJECTS_DIR):
        # Skip hidden directories except .claude itself
        dirs[:] = [d for d in dirs if not d.startswith('.') or d == '.claude']
        
        for f in files:
            if f.endswith('.jsonl'):
                jsonl_files.append(Path(root) / f)
    
    return sorted(jsonl_files)


def get_file_hash(path: Path) -> str:
    """Get a hash of file path + mtime for change detection."""
    stat = path.stat()
    key = f"{path}:{stat.st_mtime}:{stat.st_size}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


# ─────────────────────────────────────────────────────────────────
# Progress Tracking
# ─────────────────────────────────────────────────────────────────

def load_progress() -> dict:
    """Load processing progress state."""
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"processed": {}, "last_run": None}


def save_progress(progress: dict) -> None:
    """Save processing progress state."""
    progress["last_run"] = datetime.now(timezone.utc).isoformat()
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


def is_file_processed(path: Path, progress: dict) -> bool:
    """Check if a file has already been processed (and unchanged)."""
    file_key = str(path)
    if file_key not in progress.get("processed", {}):
        return False
    
    stored_hash = progress["processed"][file_key].get("hash")
    current_hash = get_file_hash(path)
    return stored_hash == current_hash


def mark_file_processed(path: Path, progress: dict, tokens: dict) -> None:
    """Mark a file as processed."""
    file_key = str(path)
    progress.setdefault("processed", {})[file_key] = {
        "hash": get_file_hash(path),
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "tokens": tokens,
    }


# ─────────────────────────────────────────────────────────────────
# JSONL Parsing
# ─────────────────────────────────────────────────────────────────

def extract_session_info(path: Path) -> dict:
    """Extract session metadata from file path and name."""
    # Session ID is typically the filename without extension
    session_id = path.stem
    
    # Try to extract date from path or filename
    # Pattern: might be in directory structure like /projects/project-name/session-id/
    date_str = None
    
    # Check filename for date pattern
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', str(path))
    if date_match:
        date_str = date_match.group(1)
    else:
        # Use file modification time
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        date_str = mtime.strftime("%Y-%m-%d")
    
    return {
        "session_id": session_id,
        "date": date_str,
        "path": str(path),
    }


def parse_jsonl_line(line: str) -> Optional[dict]:
    """Parse a single JSONL line, returning None if invalid."""
    try:
        return json.loads(line.strip())
    except json.JSONDecodeError:
        return None


def extract_tokens_from_message(msg: dict) -> Optional[TokenData]:
    """Extract token usage from a message if present."""
    # Check for usage field (API response format)
    usage = msg.get("usage")
    if usage:
        return {
            "input": usage.get("input_tokens", 0),
            "output": usage.get("output_tokens", 0),
            "cache_read": usage.get("cache_read_input_tokens", 0),
            "cache_creation": usage.get("cache_creation_input_tokens", 0),
            "source": "jsonl",
        }
    
    # Check for nested message.usage
    message = msg.get("message", {})
    if isinstance(message, dict):
        usage = message.get("usage")
        if usage:
            return {
                "input": usage.get("input_tokens", 0),
                "output": usage.get("output_tokens", 0),
                "cache_read": usage.get("cache_read_input_tokens", 0),
                "cache_creation": usage.get("cache_creation_input_tokens", 0),
                "source": "jsonl",
            }
    
    return None


def extract_tool_call(msg: dict) -> Optional[tuple[str, str]]:
    """Extract tool name and backend from a message if it's a tool call."""
    # Check for tool_use content
    content = msg.get("content", [])
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                tool_name = item.get("name", "")
                # Determine backend from tool name
                if tool_name.startswith("mcp__router__"):
                    parts = tool_name.split("__")
                    backend = parts[2] if len(parts) > 2 else "router"
                elif tool_name.startswith("mcp__plugin_"):
                    parts = tool_name.split("__")
                    backend = parts[1].replace("plugin_", "") if len(parts) > 1 else "mcp"
                else:
                    backend = "native"
                return (tool_name, backend)
    
    return None


def process_jsonl_file(path: Path) -> dict:
    """Process a single JSONL file and return extracted data."""
    tokens = default_token_data("jsonl")
    calls = default_call_data()
    session_info = extract_session_info(path)
    
    start_time = None
    end_time = None
    line_count = 0
    
    try:
        with open(path, 'r', errors='replace') as f:
            for line in f:
                line_count += 1
                if line_count > MAX_LINES_PER_FILE:
                    # File is too large, skip rest
                    break
                
                msg = parse_jsonl_line(line)
                if not msg:
                    continue
                
                # Extract timestamp
                ts = msg.get("timestamp") or msg.get("ts")
                if ts:
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if start_time is None or dt < start_time:
                            start_time = dt
                        if end_time is None or dt > end_time:
                            end_time = dt
                    except (ValueError, TypeError):
                        pass
                
                # Extract tokens
                msg_tokens = extract_tokens_from_message(msg)
                if msg_tokens:
                    merge_tokens(tokens, msg_tokens)
                
                # Extract tool calls
                tool_info = extract_tool_call(msg)
                if tool_info:
                    tool_name, backend = tool_info
                    calls["total"] = calls.get("total", 0) + 1
                    calls.setdefault("by_tool", {})[tool_name] = \
                        calls.get("by_tool", {}).get(tool_name, 0) + 1
                    calls.setdefault("by_backend", {})[backend] = \
                        calls.get("by_backend", {}).get(backend, 0) + 1
    
    except (IOError, OSError) as e:
        print(f"Error reading {path}: {e}", file=sys.stderr)
        return None
    
    return {
        "session_id": session_info["session_id"],
        "date": session_info["date"],
        "path": str(path),
        "tokens": tokens,
        "calls": calls,
        "start": start_time.isoformat() if start_time else None,
        "end": end_time.isoformat() if end_time else None,
        "line_count": line_count,
    }


# ─────────────────────────────────────────────────────────────────
# Telemetry Integration
# ─────────────────────────────────────────────────────────────────

def merge_session_into_telemetry(telemetry: TelemetryV2, session_data: dict) -> None:
    """Merge extracted session data into telemetry structure."""
    date_key = session_data["date"]
    session_id = session_data["session_id"]
    
    # Ensure day exists
    day = ensure_day(telemetry, date_key)
    
    # Merge tokens into day (preferring jsonl source)
    merge_tokens(day["tokens"], session_data["tokens"])
    
    # Merge calls
    merge_calls(day["calls"], session_data["calls"])
    
    # Add session to day
    if session_id not in day["sessions"]:
        day["sessions"].append(session_id)
    
    # Add/update session data
    day["by_session"][session_id] = {
        "start": session_data.get("start") or "",
        "end": session_data.get("end") or "",
        "tokens": session_data["tokens"],
        "calls": session_data["calls"],
        "summarization": {"offered": 0, "accepted": 0, "rejected": 0},
    }
    
    # Update filters
    for tool in session_data["calls"].get("by_tool", {}).keys():
        add_to_filters(telemetry["filters"], tool=tool)
    for backend in session_data["calls"].get("by_backend", {}).keys():
        add_to_filters(telemetry["filters"], backend=backend)
    add_to_filters(telemetry["filters"], session=session_id)
    
    # Track processed file
    telemetry.setdefault("processed_files", {}).setdefault("session_logs", [])
    if session_data["path"] not in telemetry["processed_files"]["session_logs"]:
        telemetry["processed_files"]["session_logs"].append(session_data["path"])


# ─────────────────────────────────────────────────────────────────
# Main Processing
# ─────────────────────────────────────────────────────────────────

def process_batch(max_files: int = MAX_FILES_PER_BATCH, verbose: bool = True) -> dict:
    """Process a batch of JSONL files and update telemetry.
    
    Returns:
        dict with processing statistics
    """
    progress = load_progress()
    telemetry = load_telemetry_v2(TELEMETRY_FILE)
    
    all_files = find_jsonl_files()
    unprocessed = [f for f in all_files if not is_file_processed(f, progress)]
    
    stats = {
        "total_files": len(all_files),
        "unprocessed": len(unprocessed),
        "processed_this_batch": 0,
        "tokens_extracted": 0,
        "errors": 0,
    }
    
    if verbose:
        print(f"Found {len(all_files)} JSONL files, {len(unprocessed)} unprocessed")
    
    batch = unprocessed[:max_files]
    
    for i, path in enumerate(batch):
        if verbose:
            print(f"[{i+1}/{len(batch)}] Processing {path.name}...")
        
        result = process_jsonl_file(path)
        
        if result is None:
            stats["errors"] += 1
            continue
        
        # Merge into telemetry
        merge_session_into_telemetry(telemetry, result)
        
        # Mark as processed
        mark_file_processed(path, progress, result["tokens"])
        
        stats["processed_this_batch"] += 1
        total_tokens = (result["tokens"].get("input", 0) + 
                       result["tokens"].get("output", 0))
        stats["tokens_extracted"] += total_tokens
    
    if stats["processed_this_batch"] > 0:
        # Recompute aggregates
        if verbose:
            print("Recomputing aggregates...")
        recompute_aggregates(telemetry)
        update_filter_options(telemetry)
        
        # Save
        if verbose:
            print("Saving telemetry...")
        save_telemetry_v2(telemetry, TELEMETRY_FILE)
        save_progress(progress)
    
    stats["remaining"] = len(unprocessed) - stats["processed_this_batch"]
    
    return stats


def process_all(verbose: bool = True) -> dict:
    """Process all unprocessed JSONL files in batches."""
    total_stats = {
        "batches": 0,
        "total_processed": 0,
        "total_tokens": 0,
        "total_errors": 0,
    }
    
    while True:
        stats = process_batch(verbose=verbose)
        total_stats["batches"] += 1
        total_stats["total_processed"] += stats["processed_this_batch"]
        total_stats["total_tokens"] += stats["tokens_extracted"]
        total_stats["total_errors"] += stats["errors"]
        
        if stats["remaining"] == 0:
            break
        
        if verbose:
            print(f"\nBatch complete. {stats['remaining']} files remaining.\n")
    
    return total_stats


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Extract tokens from JSONL session logs")
    parser.add_argument("--batch", type=int, default=MAX_FILES_PER_BATCH,
                       help="Max files per batch")
    parser.add_argument("--all", action="store_true",
                       help="Process all files (may take a while)")
    parser.add_argument("--quiet", action="store_true",
                       help="Suppress progress output")
    parser.add_argument("--stats", action="store_true",
                       help="Just show stats, don't process")
    args = parser.parse_args()
    
    if args.stats:
        progress = load_progress()
        all_files = find_jsonl_files()
        unprocessed = [f for f in all_files if not is_file_processed(f, progress)]
        print(f"Total JSONL files: {len(all_files)}")
        print(f"Already processed: {len(all_files) - len(unprocessed)}")
        print(f"Remaining: {len(unprocessed)}")
        if progress.get("last_run"):
            print(f"Last run: {progress['last_run']}")
        return
    
    verbose = not args.quiet
    
    if args.all:
        stats = process_all(verbose=verbose)
        print(f"\nAll processing complete:")
        print(f"  Batches: {stats['batches']}")
        print(f"  Files processed: {stats['total_processed']}")
        print(f"  Tokens extracted: {stats['total_tokens']:,}")
        print(f"  Errors: {stats['total_errors']}")
    else:
        stats = process_batch(max_files=args.batch, verbose=verbose)
        print(f"\nBatch complete:")
        print(f"  Processed: {stats['processed_this_batch']}")
        print(f"  Tokens extracted: {stats['tokens_extracted']:,}")
        print(f"  Remaining: {stats['remaining']}")


if __name__ == "__main__":
    main()
