#!/usr/bin/env python3
"""Migrate historical Claude session JSONL files to v3 telemetry format.

Parses Claude session transcripts and extracts tool call events
for DuckDB querying.

Usage:
    python scripts/migrate_to_v3.py [--source DIR] [--dest DIR] [--dry-run]
"""

import argparse
import gzip
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterator

# Add both lib and project root to path
lib_dir = Path(__file__).parent.parent / "lib"
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(lib_dir))
sys.path.insert(0, str(project_root))
from lib.stores.events import ToolCallEvent  # noqa: E402
from lib.stores.jsonl_writer import JSONLWriter  # noqa: E402


DEFAULT_SOURCE = Path.home() / ".claude" / "projects"
DEFAULT_DEST = Path.home() / ".claude" / "plugins" / "agent-swarm" / ".state" / "telemetry_v3"


def parse_jsonl_file(path: Path) -> Iterator[dict]:
    """Parse JSONL file (handles .gz compression)."""
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        yield json.loads(line)
        else:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        yield json.loads(line)
    except Exception as e:
        print(f"  ⚠️  Error parsing {path}: {e}", file=sys.stderr)


def extract_session_id(path: Path) -> str:
    """Extract session ID from file path."""
    # Path like: .../projects/project-name/session-id.jsonl
    # or .../subagents/agent-xxx.jsonl
    name = path.stem
    if name.startswith("agent-"):
        return name
    return name[:8] if len(name) > 8 else name


def extract_agent_id(record: dict) -> str:
    """Extract agent ID from record."""
    return record.get("agentId", record.get("sessionId", "unknown")[:8])


def classify_backend(tool_name: str) -> str:
    """Classify tool as native, mcp, or claude."""
    if tool_name.startswith("mcp__"):
        return "mcp"
    if tool_name in ("Read", "Write", "Edit", "Glob", "Grep", "Bash", "Task", 
                     "TodoWrite", "AskUserQuestion", "WebFetch", "WebSearch",
                     "NotebookEdit", "NotebookRead"):
        return "native"
    return "claude"


def extract_tool_calls(path: Path) -> Iterator[ToolCallEvent]:
    """Extract tool call events from a session JSONL file.
    
    Looks for tool_use and tool_result message pairs.
    Also extracts token usage from assistant messages.
    """
    session_id = extract_session_id(path)
    
    # Track pending tool uses (waiting for result)
    pending: dict[str, dict] = {}  # tool_use_id -> {name, timestamp, ...}
    
    # Track the most recent usage data (applies to tool calls in same response)
    current_usage: dict = {}
    
    for record in parse_jsonl_file(path):
        # Skip non-message records
        if record.get("type") not in ("assistant", "user"):
            continue
        
        message = record.get("message", {})
        content = message.get("content", [])
        timestamp = record.get("timestamp", "")
        agent_id = extract_agent_id(record)
        
        # Handle assistant messages with tool_use
        if record.get("type") == "assistant":
            # Capture usage data from this response
            usage = message.get("usage", {})
            if usage:
                current_usage = {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
                    "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0),
                }
            
            if isinstance(content, list):
                # Count tool uses in this message for token distribution
                tool_count = sum(1 for item in content if item.get("type") == "tool_use")
                
                for item in content:
                    if item.get("type") == "tool_use":
                        tool_use_id = item.get("id", "")
                        tool_name = item.get("name", "unknown")
                        
                        # Distribute tokens across tool calls in this message
                        tokens_per_tool = {}
                        if current_usage and tool_count > 0:
                            tokens_per_tool = {
                                "input_tokens": current_usage.get("input_tokens", 0) // tool_count,
                                "output_tokens": current_usage.get("output_tokens", 0) // tool_count,
                                "cache_read_tokens": current_usage.get("cache_read_tokens", 0) // tool_count,
                                "cache_creation_tokens": current_usage.get("cache_creation_tokens", 0) // tool_count,
                            }
                        
                        pending[tool_use_id] = {
                            "name": tool_name,
                            "timestamp": timestamp,
                            "agent_id": agent_id,
                            **tokens_per_tool,
                        }
        
        # Handle user messages with tool_result
        if record.get("type") == "user" and isinstance(content, list):
            for item in content:
                if item.get("type") == "tool_result":
                    tool_use_id = item.get("tool_use_id", "")
                    if tool_use_id not in pending:
                        continue
                    
                    start_info = pending.pop(tool_use_id)
                    tool_name = start_info["name"]
                    start_ts = start_info["timestamp"]
                    
                    # Calculate duration
                    duration_ms = 0
                    try:
                        if start_ts and timestamp:
                            start_dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
                            end_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                            duration_ms = int((end_dt - start_dt).total_seconds() * 1000)
                    except Exception:
                        pass
                    
                    # Determine status
                    is_error = item.get("is_error", False)
                    status = "error" if is_error else "success"
                    
                    # Extract error type if present
                    error_type = None
                    if is_error:
                        result_content = item.get("content", "")
                        if isinstance(result_content, str) and "Error:" in result_content:
                            error_type = result_content.split("Error:")[0].strip()[-50:] if "Error:" in result_content else "unknown"
                    
                    yield ToolCallEvent(
                        timestamp=start_ts or timestamp,
                        session_id=session_id,
                        agent_id=start_info["agent_id"],
                        tool=tool_name,
                        backend=classify_backend(tool_name),
                        duration_ms=max(0, duration_ms),
                        status=status,
                        error_type=error_type,
                        input_tokens=start_info.get("input_tokens", 0),
                        output_tokens=start_info.get("output_tokens", 0),
                        cache_read_tokens=start_info.get("cache_read_tokens", 0),
                        cache_creation_tokens=start_info.get("cache_creation_tokens", 0),
                    )


def find_jsonl_files(source_dir: Path) -> Iterator[Path]:
    """Find all JSONL files in source directory."""
    patterns = ["**/*.jsonl", "**/*.jsonl.gz"]
    for pattern in patterns:
        yield from source_dir.glob(pattern)


def migrate(source_dir: Path, dest_dir: Path, dry_run: bool = False) -> dict:
    """Migrate all JSONL files from source to v3 format in dest.
    
    Returns stats dict with counts.
    """
    stats = {
        "files_processed": 0,
        "files_skipped": 0,
        "events_written": 0,
        "errors": 0,
    }
    
    dest_dir.mkdir(parents=True, exist_ok=True)
    writer = JSONLWriter(str(dest_dir)) if not dry_run else None
    
    files = list(find_jsonl_files(source_dir))
    print(f"Found {len(files)} JSONL files to process")
    
    for path in files:
        try:
            event_count = 0
            for event in extract_tool_calls(path):
                if writer:
                    writer.write(event)
                event_count += 1
            
            if event_count > 0:
                stats["files_processed"] += 1
                stats["events_written"] += event_count
                print(f"  ✓ {path.name}: {event_count} events")
            else:
                stats["files_skipped"] += 1
                
        except Exception as e:
            stats["errors"] += 1
            print(f"  ✗ {path.name}: {e}", file=sys.stderr)
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Migrate Claude session JSONL files to v3 telemetry format"
    )
    parser.add_argument(
        "--source", "-s",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"Source directory with JSONL files (default: {DEFAULT_SOURCE})"
    )
    parser.add_argument(
        "--dest", "-d",
        type=Path,
        default=DEFAULT_DEST,
        help=f"Destination directory for v3 JSONL files (default: {DEFAULT_DEST})"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Parse files but don't write output"
    )
    
    args = parser.parse_args()
    
    print("📊 Migrating telemetry to v3 format")
    print(f"   Source: {args.source}")
    print(f"   Dest:   {args.dest}")
    if args.dry_run:
        print("   (DRY RUN - no files will be written)")
    print()
    
    if not args.source.exists():
        print(f"❌ Source directory not found: {args.source}", file=sys.stderr)
        sys.exit(1)
    
    stats = migrate(args.source, args.dest, args.dry_run)
    
    print()
    print("✅ Migration complete:")
    print(f"   Files processed: {stats['files_processed']}")
    print(f"   Files skipped:   {stats['files_skipped']}")
    print(f"   Events written:  {stats['events_written']}")
    if stats['errors']:
        print(f"   Errors:          {stats['errors']}")


if __name__ == "__main__":
    main()
