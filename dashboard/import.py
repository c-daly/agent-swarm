"""Import pipeline: DuckDB/Claude transcripts -> SQLite.

Usage:
    python dashboard/import.py \
        --db dashboard/data/dashboard.db \
        --duckdb .state/telemetry.duckdb \
        --claude-projects ~/.claude/projects/
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# DuckDB is optional (only needed for --duckdb imports)
try:
    import duckdb

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    session_id TEXT NOT NULL,
    agent_id TEXT DEFAULT '',
    tool TEXT NOT NULL,
    backend TEXT NOT NULL,
    duration_ms INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    agent_type TEXT DEFAULT '',
    workflow_id TEXT DEFAULT '',
    error_type TEXT DEFAULT '',
    was_summarized INTEGER DEFAULT 0,
    original_size INTEGER DEFAULT 0,
    summary_size INTEGER,
    tool_use_id TEXT DEFAULT '',
    import_source TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_tool ON events(tool);
CREATE INDEX IF NOT EXISTS idx_events_backend ON events(backend);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);

CREATE TABLE IF NOT EXISTS content_retrievals (
    content_id TEXT PRIMARY KEY,
    created_at TEXT,
    retrieved_at TEXT,
    was_retrieved INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agent_types (
    agent_id TEXT PRIMARY KEY,
    agent_type TEXT NOT NULL,
    registered_at TEXT
);

CREATE TABLE IF NOT EXISTS import_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_path TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    events_inserted INTEGER DEFAULT 0,
    events_skipped INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS session_files (
    session_id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL
);

CREATE VIEW IF NOT EXISTS v_sessions AS
SELECT
    session_id,
    MIN(timestamp) as start_time,
    MAX(timestamp) as end_time,
    COUNT(*) as event_count,
    SUM(input_tokens) as total_input_tokens,
    SUM(output_tokens) as total_output_tokens,
    SUM(cache_read_tokens) as total_cache_read,
    SUM(cache_creation_tokens) as total_cache_creation,
    SUM(input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens) as total_tokens,
    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count,
    SUM(CASE WHEN was_summarized THEN 1 ELSE 0 END) as summarization_count,
    COUNT(DISTINCT tool) as unique_tools,
    COUNT(DISTINCT agent_id) as agent_count,
    CAST((julianday(MAX(timestamp)) - julianday(MIN(timestamp))) * 86400000 AS INTEGER) as duration_ms
FROM events
GROUP BY session_id;
"""

# Cutoff for DuckDB data confidence
DUCKDB_CUTOFF = "2026-01-21T12:00:00"

# Tools that are Claude-internal (not MCP)
CLAUDE_TOOLS = frozenset({
    "Task", "Skill", "AskUserQuestion", "WebFetch", "WebSearch",
    "TodoWrite", "TodoRead", "EnterPlanMode", "ExitPlanMode",
    "TaskCreate", "TaskUpdate", "TaskGet", "TaskList",
    "NotebookEdit",
})


def init_db(db_path: str) -> sqlite3.Connection:
    """Create/open SQLite DB and ensure schema exists."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA_SQL)
    return conn


def derive_backend(tool_name: str) -> str:
    """Derive backend category from tool name."""
    if tool_name.startswith("mcp__router__"):
        return "router"
    elif tool_name.startswith("mcp__plugin"):
        return "plugin"
    elif tool_name.startswith("mcp__"):
        return "mcp"
    elif tool_name in CLAUDE_TOOLS:
        return "claude"
    else:
        return "native"


def detect_error(content) -> tuple[bool, str]:
    """Detect if tool result content indicates an error.

    Only matches errors that appear in structured positions (first line,
    dict fields), not arbitrary substrings buried in file content.
    """
    if isinstance(content, dict):
        if content.get("isError"):
            return True, str(content.get("content", ""))[:200]
        if "error" in content:
            return True, str(content["error"])[:200]
    if isinstance(content, str):
        # Only check the first line — real errors surface at the top,
        # not buried inside file content or code listings.
        first_line = content.split("\n", 1)[0].strip()
        # Skip line-numbered file output (e.g. "     1\t#!/usr/bin/env python3")
        if re.match(r"^\s*\d+[\t→]", first_line):
            return False, ""
        lower = first_line.lower()
        if any(x in lower for x in ["error:", "error executing", "exception:", "failed:"]):
            return True, content[:200]
    return False, ""


def is_already_imported(conn: sqlite3.Connection, source: str, source_path: str) -> bool:
    """Check if a source file was already imported."""
    row = conn.execute(
        "SELECT COUNT(*) FROM import_log WHERE source = ? AND source_path = ?",
        (source, source_path),
    ).fetchone()
    return row[0] > 0


def dedup_check_duckdb(conn: sqlite3.Connection, ts: str, sid: str, aid: str, tool: str) -> bool:
    """Check if a DuckDB event already exists (4-column key)."""
    row = conn.execute(
        "SELECT COUNT(*) FROM events WHERE timestamp = ? AND session_id = ? AND agent_id = ? AND tool = ?",
        (ts, sid, aid, tool),
    ).fetchone()
    return row[0] > 0


def dedup_check_jsonl(conn: sqlite3.Connection, ts: str, sid: str, aid: str, tool: str, tuid: str) -> bool:
    """Check if a JSONL event already exists (5-column key)."""
    row = conn.execute(
        "SELECT COUNT(*) FROM events WHERE timestamp = ? AND session_id = ? AND agent_id = ? AND tool = ? AND tool_use_id = ?",
        (ts, sid, aid, tool, tuid),
    ).fetchone()
    return row[0] > 0


def extract_agent_id_from_filename(filepath: Path) -> str | None:
    """Extract agent ID from subagent file path, or None for main sessions.

    Main session: <uuid>.jsonl -> returns None (caller should use session_id)
    Subagent (nested): <uuid>/subagents/agent-<id>.jsonl -> returns the <id>
    Subagent (flat): agent-<id>.jsonl -> returns the <id>
    """
    name = filepath.stem  # e.g. "agent-abc123"
    if name.startswith("agent-"):
        return name[6:]  # strip "agent-" prefix
    return None



# ── DuckDB Import
# ── DuckDB Import ──────────────────────────────────────────────────────────

def import_duckdb(conn: sqlite3.Connection, duckdb_path: str, *, force: bool = False, dry_run: bool = False) -> dict:
    """Import events from legacy DuckDB file."""
    if not HAS_DUCKDB:
        print("ERROR: duckdb package not installed. Run: pip install duckdb", file=sys.stderr)
        return {"pre": 0, "post": 0, "skipped": 0}

    source_path = str(Path(duckdb_path).resolve())
    if not force and is_already_imported(conn, "duckdb", source_path):
        print(f"  DuckDB already imported ({source_path}), skipping. Use --force to reimport.")
        return {"pre": 0, "post": 0, "skipped": 0}

    ddb = duckdb.connect(duckdb_path, read_only=True)
    rows = ddb.execute("SELECT * FROM events ORDER BY timestamp").fetchall()
    columns = [desc[0] for desc in ddb.description]

    pre_count = 0
    post_count = 0
    skipped = 0

    for row in rows:
        rec = dict(zip(columns, row))
        ts = rec["timestamp"]
        # Normalize timestamp to ISO 8601 string
        if isinstance(ts, datetime):
            ts = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        ts_str = str(ts)

        sid = str(rec.get("session_id", ""))
        aid = str(rec.get("agent_id", "") or "")
        tool = str(rec.get("tool", ""))

        if dedup_check_duckdb(conn, ts_str, sid, aid, tool):
            skipped += 1
            continue

        is_pre = ts_str < DUCKDB_CUTOFF
        import_source = "duckdb" if is_pre else "duckdb_only"

        if not dry_run:
            conn.execute(
                """INSERT INTO events (
                    timestamp, session_id, agent_id, tool, backend, duration_ms,
                    status, input_tokens, output_tokens, cache_read_tokens,
                    cache_creation_tokens, agent_type, workflow_id, error_type,
                    was_summarized, original_size, summary_size, tool_use_id,
                    import_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ts_str, sid, aid, tool,
                    str(rec.get("backend", "")),
                    int(rec.get("duration_ms", 0)),
                    str(rec.get("status", "success")),
                    int(rec.get("input_tokens", 0) or 0),
                    int(rec.get("output_tokens", 0) or 0),
                    int(rec.get("cache_read_tokens", 0) or 0),
                    int(rec.get("cache_creation_tokens", 0) or 0),
                    str(rec.get("agent_type", "") or ""),
                    str(rec.get("workflow_id", "") or ""),
                    str(rec.get("error_type", "") or ""),
                    int(rec.get("was_summarized", False) or 0),
                    int(rec.get("original_size", 0) or 0),
                    rec.get("summary_size"),
                    "",  # tool_use_id not available in DuckDB
                    import_source,
                ),
            )

        if is_pre:
            pre_count += 1
        else:
            post_count += 1

    # Import content_retrievals
    try:
        cr_rows = ddb.execute("SELECT * FROM content_retrievals").fetchall()
        cr_cols = [desc[0] for desc in ddb.description]
        for row in cr_rows:
            rec = dict(zip(cr_cols, row))
            if not dry_run:
                conn.execute(
                    "INSERT OR IGNORE INTO content_retrievals (content_id, created_at, retrieved_at, was_retrieved) VALUES (?, ?, ?, ?)",
                    (
                        str(rec.get("content_id", "")),
                        str(rec.get("created_at", "") or ""),
                        str(rec.get("retrieved_at", "") or ""),
                        int(rec.get("was_retrieved", 0) or 0),
                    ),
                )
    except Exception:
        pass  # Table may not exist

    # Import agent_types
    try:
        at_rows = ddb.execute("SELECT * FROM agent_types").fetchall()
        at_cols = [desc[0] for desc in ddb.description]
        for row in at_rows:
            rec = dict(zip(at_cols, row))
            if not dry_run:
                conn.execute(
                    "INSERT OR IGNORE INTO agent_types (agent_id, agent_type, registered_at) VALUES (?, ?, ?)",
                    (
                        str(rec.get("agent_id", "")),
                        str(rec.get("agent_type", "")),
                        str(rec.get("registered_at", "") or ""),
                    ),
                )
    except Exception:
        pass  # Table may not exist

    if not dry_run:
        conn.execute(
            "INSERT INTO import_log (source, source_path, imported_at, events_inserted, events_skipped) VALUES (?, ?, ?, ?, ?)",
            ("duckdb", source_path, datetime.now(timezone.utc).isoformat(), pre_count + post_count, skipped),
        )
        conn.commit()

    ddb.close()

    return {"pre": pre_count, "post": post_count, "skipped": skipped}


# ── Claude JSONL Import ────────────────────────────────────────────────────

def find_jsonl_files(projects_dir: str) -> list[Path]:
    """Find all .jsonl files under the Claude projects directory."""
    root = Path(projects_dir).expanduser()
    if not root.exists():
        return []
    results = []
    for p in root.rglob("*.jsonl"):
        if not any(part.startswith(".") for part in p.relative_to(root).parts):
            results.append(p)
    return sorted(results)


def parse_jsonl_file(filepath: Path, agent_type_map: dict[str, str] | None = None) -> list[dict]:
    """Parse a JSONL file and extract per-tool-call events.

    If agent_type_map is provided (mutable dict), also extracts Task tool_use
    -> agentId -> subagent_type mappings in-place during parsing. This avoids
    needing a separate pass over the file.
    """
    lines = filepath.read_text(errors="replace").splitlines()
    entries = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not entries:
        return []

    # Extract agent_type mappings from Task tool_use blocks (main sessions only)
    if agent_type_map is not None:
        task_types: dict[str, str] = {}  # tool_use_id -> subagent_type
        for entry in entries:
            if entry.get("type") == "assistant":
                for block in entry.get("message", {}).get("content", []):
                    if (isinstance(block, dict)
                            and block.get("type") == "tool_use"
                            and block.get("name") == "Task"):
                        inp = block.get("input", {})
                        st = inp.get("subagent_type", "")
                        if st:
                            task_types[block.get("id", "")] = st
            elif entry.get("type") == "user" and task_types:
                for block in entry.get("message", {}).get("content", []):
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    tuid = block.get("tool_use_id", "")
                    if tuid not in task_types:
                        continue
                    content = str(block.get("content", ""))
                    for pattern in [r"agentId:\s*(\w+)", r"task_id>(\w+)<"]:
                        m = re.search(pattern, content)
                        if m:
                            agent_type_map[m.group(1)] = task_types[tuid]
                            break

    # Build tool_result map: tool_use_id -> (content, timestamp)
    tool_results: dict[str, tuple] = {}
    for entry in entries:
        if entry.get("type") != "user":
            continue
        msg = entry.get("message", {})
        content_blocks = msg.get("content", [])
        if isinstance(content_blocks, str):
            continue
        ts = entry.get("timestamp", "")
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tuid = block.get("tool_use_id", "")
                if tuid:
                    tool_results[tuid] = (block.get("content", ""), ts)

    # Determine agent_id from filename
    agent_id_override = extract_agent_id_from_filename(filepath)

    # Extract events from assistant entries
    events = []
    for entry in entries:
        if entry.get("type") != "assistant":
            continue

        msg = entry.get("message", {})
        if not isinstance(msg, dict):
            continue

        content_blocks = msg.get("content", [])
        if isinstance(content_blocks, str):
            continue

        usage = msg.get("usage", {})
        timestamp = entry.get("timestamp", "")
        session_id = entry.get("sessionId", "")

        # Count tool_use blocks in this message for token attribution
        tool_use_blocks = [b for b in content_blocks if isinstance(b, dict) and b.get("type") == "tool_use"]
        n_tools = max(len(tool_use_blocks), 1)

        # Divide tokens evenly across tool calls
        input_tokens = int(usage.get("input_tokens", 0)) // n_tools
        output_tokens = int(usage.get("output_tokens", 0)) // n_tools
        cache_read = int(usage.get("cache_read_input_tokens", 0)) // n_tools
        cache_creation = int(usage.get("cache_creation_input_tokens", 0)) // n_tools

        for block in tool_use_blocks:
            tool_name = block.get("name", "")
            tool_use_id = block.get("id", "")
            backend = derive_backend(tool_name)

            agent_id = agent_id_override if agent_id_override else session_id

            # Find matching result
            result_content, result_ts = tool_results.get(tool_use_id, ("", ""))
            is_error, error_type = detect_error(result_content)
            original_size = len(str(result_content))
            was_summarized = 1 if (original_size > 2000 and tool_name != "router__get_full") else 0
            summary_size = min(original_size, 2000) if was_summarized else None

            # Duration
            duration_ms = 0
            if timestamp and result_ts:
                try:
                    t_use = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    t_result = datetime.fromisoformat(result_ts.replace("Z", "+00:00"))
                    duration_ms = max(0, int((t_result - t_use).total_seconds() * 1000))
                except (ValueError, TypeError):
                    pass

            events.append({
                "timestamp": timestamp,
                "session_id": session_id,
                "agent_id": agent_id,
                "tool": tool_name,
                "backend": backend,
                "duration_ms": duration_ms,
                "status": "error" if is_error else "success",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": cache_read,
                "cache_creation_tokens": cache_creation,
                "agent_type": (agent_type_map or {}).get(agent_id_override, "") if agent_id_override else "",
                "workflow_id": "",
                "error_type": error_type,
                "was_summarized": was_summarized,
                "original_size": original_size,
                "summary_size": summary_size,
                "tool_use_id": tool_use_id,
                "import_source": "claude_transcript",
            })

    return events


def import_claude_transcripts(
    conn: sqlite3.Connection, projects_dir: str, *, force: bool = False, dry_run: bool = False
) -> dict:
    """Import Claude JSONL transcripts.

    Processes main sessions first to build agentId -> subagent_type map,
    then processes subagent files with type info available.
    """
    files = find_jsonl_files(projects_dir)
    total_inserted = 0
    total_skipped = 0
    files_processed = 0

    # Separate main sessions from subagent files so we process mains first
    main_files = [f for f in files if not f.stem.startswith("agent-")]
    sub_files = [f for f in files if f.stem.startswith("agent-")]

    # Load existing agent_type mappings from DB
    agent_type_map: dict[str, str] = {}
    for row in conn.execute("SELECT agent_id, agent_type FROM agent_types").fetchall():
        agent_type_map[row[0]] = row[1]

    def _import_file(filepath: Path) -> tuple[int, int]:
        source_path = str(filepath.resolve())
        if not force and is_already_imported(conn, "claude_transcript", source_path):
            return 0, 0

        events = parse_jsonl_file(filepath, agent_type_map=agent_type_map)
        inserted = skipped = 0

        for evt in events:
            if dedup_check_jsonl(
                conn, evt["timestamp"], evt["session_id"], evt["agent_id"],
                evt["tool"], evt["tool_use_id"]
            ):
                skipped += 1
                continue

            if not dry_run:
                conn.execute(
                    """INSERT INTO events (
                        timestamp, session_id, agent_id, tool, backend, duration_ms,
                        status, input_tokens, output_tokens, cache_read_tokens,
                        cache_creation_tokens, agent_type, workflow_id, error_type,
                        was_summarized, original_size, summary_size, tool_use_id,
                        import_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        evt["timestamp"], evt["session_id"], evt["agent_id"],
                        evt["tool"], evt["backend"], evt["duration_ms"],
                        evt["status"], evt["input_tokens"], evt["output_tokens"],
                        evt["cache_read_tokens"], evt["cache_creation_tokens"],
                        evt["agent_type"], evt["workflow_id"], evt["error_type"],
                        evt["was_summarized"], evt["original_size"], evt["summary_size"],
                        evt["tool_use_id"], evt["import_source"],
                    ),
                )
                inserted += 1

        if events and not dry_run:
            session_id = events[0].get("session_id", "")
            if session_id:
                conn.execute(
                    "INSERT OR IGNORE INTO session_files (session_id, file_path) VALUES (?, ?)",
                    (session_id, source_path),
                )

        if not dry_run and (inserted > 0 or skipped > 0):
            conn.execute(
                "INSERT INTO import_log (source, source_path, imported_at, events_inserted, events_skipped) VALUES (?, ?, ?, ?, ?)",
                ("claude_transcript", source_path, datetime.now(timezone.utc).isoformat(), inserted, skipped),
            )
            conn.commit()

        return inserted, skipped

    # Pass 1: main sessions — parse extracts agent_type mappings into agent_type_map
    for filepath in main_files:
        ins, skip = _import_file(filepath)
        total_inserted += ins
        total_skipped += skip
        files_processed += 1

    # Persist any new agent_type mappings discovered during pass 1
    if not dry_run and agent_type_map:
        for aid, atype in agent_type_map.items():
            conn.execute(
                "INSERT OR REPLACE INTO agent_types (agent_id, agent_type, registered_at) VALUES (?, ?, ?)",
                (aid, atype, datetime.now(timezone.utc).isoformat()),
            )
        conn.commit()

    # Pass 2: subagent files — agent_type_map now populated for lookups
    for filepath in sub_files:
        ins, skip = _import_file(filepath)
        total_inserted += ins
        total_skipped += skip
        files_processed += 1

    return {"files": files_processed, "inserted": total_inserted, "skipped": total_skipped}


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Import telemetry data into dashboard SQLite DB")
    parser.add_argument("--db", required=True, help="Path to output SQLite database")
    parser.add_argument("--claude-projects", default="~/.claude/projects/", help="Path to Claude projects directory")
    parser.add_argument("--duckdb", default=None, help="Path to legacy DuckDB file")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be imported without writing")
    parser.add_argument("--force", action="store_true", help="Re-import files already in import_log")
    args = parser.parse_args()

    # Ensure parent directory exists
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = init_db(str(db_path))

    print("Dashboard Import Pipeline")
    print("=" * 40)

    # DuckDB import
    if args.duckdb:
        duckdb_path = Path(args.duckdb).expanduser()
        if not duckdb_path.exists():
            print(f"  WARNING: DuckDB file not found: {duckdb_path}")
        else:
            print(f"\nImporting DuckDB: {duckdb_path}")
            result = import_duckdb(conn, str(duckdb_path), force=args.force, dry_run=args.dry_run)
            print(f"  Pre-Jan 21 (duckdb): {result['pre']} inserted")
            print(f"  Post-Jan 21 (duckdb_only): {result['post']} inserted")
            print(f"  Skipped (duplicates): {result['skipped']}")

    # Claude transcripts
    projects_dir = Path(args.claude_projects).expanduser()
    if projects_dir.exists():
        print(f"\nImporting Claude transcripts: {projects_dir}")
        result = import_claude_transcripts(conn, str(projects_dir), force=args.force, dry_run=args.dry_run)
        print(f"  Files processed: {result['files']}")
        print(f"  Events inserted: {result['inserted']}")
        print(f"  Events skipped (duplicates): {result['skipped']}")
    else:
        print(f"\n  WARNING: Claude projects dir not found: {projects_dir}")

    # Summary
    total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    sessions = conn.execute("SELECT COUNT(DISTINCT session_id) FROM events").fetchone()[0]
    print(f"\nTotal events in database: {total}")
    print(f"Total sessions: {sessions}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
