"""Parallel JSONL import — parses files with multiprocessing, batch-inserts into SQLite.

Usage:
    python dashboard/import_parallel.py --db dashboard/data/dashboard.db --claude-projects ~/.claude/projects/ --workers 4
"""

import argparse
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# Import the core functions from import.py
sys.path.insert(0, str(Path(__file__).parent.parent))
import importlib
imp = importlib.import_module("dashboard.import")

parse_jsonl_file = imp.parse_jsonl_file
find_jsonl_files = imp.find_jsonl_files
init_db = imp.init_db
SCHEMA_SQL = imp.SCHEMA_SQL


def get_already_imported(db_path: str) -> set[str]:
    """Get set of source_paths already in import_log."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT source_path FROM import_log WHERE source = 'claude_transcript'"
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


def parse_one_file(filepath_str: str) -> tuple[str, list[dict]]:
    """Parse a single JSONL file — runs in worker process."""
    filepath = Path(filepath_str)
    events = parse_jsonl_file(filepath)
    return filepath_str, events


def main():
    parser = argparse.ArgumentParser(description="Parallel JSONL import")
    parser.add_argument("--db", required=True)
    parser.add_argument("--claude-projects", default="~/.claude/projects/")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    db_path = str(Path(args.db).resolve())
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)

    # Ensure schema exists
    conn = init_db(db_path)
    conn.close()

    # Find files to import
    projects_dir = Path(args.claude_projects).expanduser()
    all_files = find_jsonl_files(str(projects_dir))
    already = get_already_imported(db_path)
    pending = [f for f in all_files if str(f.resolve()) not in already]

    print(f"Total JSONL files: {len(all_files)}")
    print(f"Already imported:  {len(already)}")
    print(f"Pending:           {len(pending)}")

    if not pending:
        print("Nothing to import.")
        return

    # Phase 1: Parse files in parallel
    print(f"\nParsing {len(pending)} files with {args.workers} workers...")
    t0 = time.time()
    parsed = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(parse_one_file, str(f)): f for f in pending}
        done = 0
        for future in as_completed(futures):
            filepath_str, events = future.result()
            parsed[filepath_str] = events
            done += 1
            if done % 200 == 0:
                print(f"  Parsed {done}/{len(pending)} files...")

    parse_time = time.time() - t0
    total_events = sum(len(evts) for evts in parsed.values())
    print(f"  Parsed {len(parsed)} files in {parse_time:.1f}s -> {total_events} events")

    # Phase 2: Batch insert into SQLite (single writer)
    print(f"\nInserting into SQLite...")
    t1 = time.time()
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA synchronous=NORMAL")

    inserted_total = 0
    skipped_total = 0
    files_done = 0

    for filepath_str, events in parsed.items():
        inserted = 0
        skipped = 0
        source_path = str(Path(filepath_str).resolve())

        for evt in events:
            # Dedup check
            row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE timestamp=? AND session_id=? AND agent_id=? AND tool=? AND tool_use_id=?",
                (evt["timestamp"], evt["session_id"], evt["agent_id"], evt["tool"], evt["tool_use_id"]),
            ).fetchone()
            if row[0] > 0:
                skipped += 1
                continue

            conn.execute(
                """INSERT INTO events (
                    timestamp, session_id, agent_id, tool, backend, duration_ms,
                    status, input_tokens, output_tokens, cache_read_tokens,
                    cache_creation_tokens, agent_type, workflow_id, error_type,
                    was_summarized, original_size, summary_size, tool_use_id, import_source
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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

        # Record session file mapping
        if events:
            session_id = events[0].get("session_id", "")
            if session_id:
                conn.execute(
                    "INSERT OR IGNORE INTO session_files (session_id, file_path) VALUES (?,?)",
                    (session_id, source_path),
                )

        # Log import
        conn.execute(
            "INSERT INTO import_log (source, source_path, imported_at, events_inserted, events_skipped) VALUES (?,?,?,?,?)",
            ("claude_transcript", source_path, datetime.now(timezone.utc).isoformat(), inserted, skipped),
        )

        inserted_total += inserted
        skipped_total += skipped
        files_done += 1

        # Commit every 50 files
        if files_done % 50 == 0:
            conn.commit()
            print(f"  {files_done}/{len(parsed)} files, {inserted_total} inserted...")

    conn.commit()
    insert_time = time.time() - t1

    total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    sessions = conn.execute("SELECT COUNT(DISTINCT session_id) FROM events").fetchone()[0]
    conn.close()

    print(f"  Inserted {inserted_total} events, skipped {skipped_total} dupes in {insert_time:.1f}s")
    print(f"\nTotal events in DB: {total}")
    print(f"Total sessions:     {sessions}")
    print(f"Total time:         {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
