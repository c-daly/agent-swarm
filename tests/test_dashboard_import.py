#!/usr/bin/env python3
"""Tests for dashboard/import.py transcript-import change detection (C5 import-freeze).

The bug: `is_already_imported` matched only on (source, source_path), so a Claude
transcript that grew after its first import was skipped forever -- the dashboard
DB froze at the first import (e.g. 14 of 1,090+ calls recorded). The fix adds
mtime/size change detection so a grown transcript is re-processed (per-event
dedup then inserts only the new events).
"""

import importlib.util
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

_IMPORT_PY = Path(__file__).parent.parent / "dashboard" / "import.py"
_spec = importlib.util.spec_from_file_location("dashboard_import", _IMPORT_PY)
dashboard_import = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dashboard_import)


@pytest.fixture
def conn(tmp_path):
    c = dashboard_import.init_db(str(tmp_path / "dash.db"))
    yield c
    c.close()


def _log_import(conn, path, mtime, size):
    conn.execute(
        "INSERT INTO import_log (source, source_path, imported_at, events_inserted, "
        "events_skipped, source_mtime, source_size) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("claude_transcript", path, datetime.now(timezone.utc).isoformat(), 1, 0, mtime, size),
    )
    conn.commit()


def _entry(tuid, ts="2026-08-13T10:00:00Z"):
    return json.dumps({
        "type": "assistant",
        "timestamp": ts,
        "sessionId": "sess-1",
        "message": {"content": [{"type": "tool_use", "id": tuid, "name": "Bash"}], "usage": {}},
    })


class TestImportLogMigration:
    def test_import_log_has_change_detection_columns(self, conn):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(import_log)")}
        assert "source_mtime" in cols
        assert "source_size" in cols

    def test_migration_adds_columns_to_legacy_import_log(self, tmp_path):
        # A DB created before change detection existed must gain the columns
        # idempotently when reopened via init_db.
        db = str(tmp_path / "legacy.db")
        c0 = sqlite3.connect(db)
        c0.execute(
            "CREATE TABLE import_log (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "source TEXT NOT NULL, source_path TEXT NOT NULL, imported_at TEXT NOT NULL, "
            "events_inserted INTEGER DEFAULT 0, events_skipped INTEGER DEFAULT 0)"
        )
        c0.commit()
        c0.close()
        conn = dashboard_import.init_db(db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(import_log)")}
        assert "source_mtime" in cols and "source_size" in cols
        conn.close()


class TestIsAlreadyImported:
    def test_unchanged_file_is_already_imported(self, conn):
        _log_import(conn, "/p/s.jsonl", 100.0, 500)
        assert dashboard_import.is_already_imported(
            conn, "claude_transcript", "/p/s.jsonl", 100.0, 500) is True

    def test_grown_file_is_not_already_imported(self, conn):
        # The freeze: a transcript whose size changed must count as not-imported.
        _log_import(conn, "/p/s.jsonl", 100.0, 500)
        assert dashboard_import.is_already_imported(
            conn, "claude_transcript", "/p/s.jsonl", 100.0, 900) is False

    def test_changed_mtime_is_not_already_imported(self, conn):
        _log_import(conn, "/p/s.jsonl", 100.0, 500)
        assert dashboard_import.is_already_imported(
            conn, "claude_transcript", "/p/s.jsonl", 200.0, 500) is False

    def test_path_only_check_is_backward_compatible(self, conn):
        # Called without mtime/size (e.g. the duckdb path) -> path-only match.
        _log_import(conn, "/p/s.jsonl", 100.0, 500)
        assert dashboard_import.is_already_imported(
            conn, "claude_transcript", "/p/s.jsonl") is True


class TestReimportOnGrowth:
    def test_grown_transcript_reimports_new_events(self, conn, tmp_path):
        projects = tmp_path / "projects"
        proj = projects / "myproj"
        proj.mkdir(parents=True)
        f = proj / "session.jsonl"
        f.write_text(_entry("tu-1") + "\n")

        r1 = dashboard_import.import_claude_transcripts(conn, str(projects))
        assert r1["inserted"] == 1

        # Transcript grows: a new tool call is appended (size changes).
        f.write_text(_entry("tu-1") + "\n" + _entry("tu-2") + "\n")

        r2 = dashboard_import.import_claude_transcripts(conn, str(projects))
        assert r2["inserted"] == 1  # only the new event; tu-1 is deduped

        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert total == 2
