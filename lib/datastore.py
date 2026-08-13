#!/usr/bin/env python3
"""SQLite event store for the daemon.

Append-only event log. Tracks tool calls, workflow events, and session
metadata. Feeds dashboards and analytics. Uses SQLite with WAL mode
for concurrent read access.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class EventRecord:
    timestamp: datetime
    tool: str
    backend: str
    status: str  # "success" | "error"
    duration_ms: float = 0.0
    session_id: str = ""
    agent_id: str = ""
    agent_type: str = ""
    workflow_id: str = ""
    error_type: str = ""
    was_summarized: bool = False
    original_size: int = 0
    summary_size: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    phase: str = ""
    target: str = ""


@dataclass
class DaySummary:
    date: date
    total_calls: int
    total_tokens: int
    unique_sessions: int
    unique_tools: int
    error_count: int
    summarization_count: int
    avg_duration_ms: float


@dataclass
class ToolSummary:
    tool_name: str
    call_count: int
    avg_duration_ms: float
    error_rate: float


_CREATE_SCHEMA = """\
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    tool TEXT NOT NULL,
    backend TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_ms REAL DEFAULT 0,
    session_id TEXT DEFAULT '',
    agent_id TEXT DEFAULT '',
    agent_type TEXT DEFAULT '',
    workflow_id TEXT DEFAULT '',
    error_type TEXT DEFAULT '',
    was_summarized INTEGER DEFAULT 0,
    original_size INTEGER DEFAULT 0,
    summary_size INTEGER,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    phase TEXT DEFAULT '',
    target TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_tool ON events(tool);
"""

_INSERT_EVENT = """\
INSERT INTO events (
    timestamp, tool, backend, status, duration_ms,
    session_id, agent_id, agent_type, workflow_id,
    error_type, was_summarized, original_size, summary_size,
    input_tokens, output_tokens, cache_read_tokens,
    cache_creation_tokens, phase, target
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_COLUMNS = """\
timestamp, tool, backend, status, duration_ms,
    session_id, agent_id, agent_type, workflow_id,
    error_type, was_summarized, original_size, summary_size,
    input_tokens, output_tokens, cache_read_tokens,
    cache_creation_tokens, phase, target"""


class DataStore:
    """Event persistence and reporting backed by SQLite.

    Thread-safe via RLock serialization of writes. WAL mode allows
    concurrent reads without blocking writes.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._lock = threading.RLock()
        self._conn.executescript(_CREATE_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Add columns introduced after a DB was first created (idempotent)."""
        with self._lock:
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(events)")}
            if "phase" not in cols:
                self._conn.execute(
                    "ALTER TABLE events ADD COLUMN phase TEXT DEFAULT ''"
                )
            if "target" not in cols:
                self._conn.execute(
                    "ALTER TABLE events ADD COLUMN target TEXT DEFAULT ''"
                )

    def record_event(self, event: dict) -> None:
        """Insert a single event.

        Args:
            event: Dict with keys matching EventRecord fields.
                   Missing keys get defaults.
                   "timestamp" defaults to utcnow if not provided.
        """
        ts = event.get("timestamp", datetime.now(tz=timezone.utc).isoformat())
        if isinstance(ts, datetime):
            ts = ts.isoformat()
        with self._lock:
            self._conn.execute(
                _INSERT_EVENT,
                (
                    ts,
                    event.get("tool", ""),
                    event.get("backend", ""),
                    event.get("status", "success"),
                    event.get("duration_ms", 0),
                    event.get("session_id", ""),
                    event.get("agent_id", ""),
                    event.get("agent_type", ""),
                    event.get("workflow_id", ""),
                    event.get("error_type", ""),
                    1 if event.get("was_summarized", False) else 0,
                    event.get("original_size", 0),
                    event.get("summary_size"),
                    event.get("input_tokens", 0),
                    event.get("output_tokens", 0),
                    event.get("cache_read_tokens", 0),
                    event.get("cache_creation_tokens", 0),
                    event.get("phase", ""),
                    event.get("target", ""),
                ),
            )
            self._conn.commit()

    def get_daily_summary(self, day: date) -> DaySummary | None:
        """Get aggregated metrics for a single day."""
        day_str = day.isoformat()
        with self._lock:
            row = self._conn.execute(
                """SELECT
                    COUNT(*) as total_calls,
                    COALESCE(SUM(input_tokens + output_tokens), 0) as total_tokens,
                    COUNT(DISTINCT session_id) as unique_sessions,
                    COUNT(DISTINCT tool) as unique_tools,
                    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count,
                    SUM(CASE WHEN was_summarized THEN 1 ELSE 0 END) as summarization_count,
                    COALESCE(AVG(duration_ms), 0) as avg_duration_ms
                FROM events
                WHERE DATE(timestamp) = ?""",
                (day_str,),
            ).fetchone()
        if row is None or row[0] == 0:
            return None
        return DaySummary(
            date=day,
            total_calls=row[0],
            total_tokens=row[1],
            unique_sessions=row[2],
            unique_tools=row[3],
            error_count=row[4],
            summarization_count=row[5],
            avg_duration_ms=row[6],
        )

    def get_tool_summaries(self, limit: int = 20) -> list[ToolSummary]:
        """Get tool-level aggregated stats, sorted by call count descending."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT
                    tool as tool_name,
                    COUNT(*) as call_count,
                    COALESCE(AVG(duration_ms), 0) as avg_duration_ms,
                    COALESCE(
                        CAST(SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS FLOAT) /
                        NULLIF(COUNT(*), 0), 0
                    ) as error_rate
                FROM events
                GROUP BY tool
                ORDER BY call_count DESC
                LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            ToolSummary(
                tool_name=r[0],
                call_count=r[1],
                avg_duration_ms=r[2],
                error_rate=r[3],
            )
            for r in rows
        ]

    def get_session_events(self, session_id: str) -> list[EventRecord]:
        """Get all events for a specific session, ordered by timestamp."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM events "
                "WHERE session_id = ? ORDER BY timestamp",
                (session_id,),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def query_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        tool: str | None = None,
        backend: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 1000,
    ) -> list[EventRecord]:
        """Flexible event query with optional filters. All AND-combined."""
        clauses: list[str] = []
        params: list[Any] = []
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(start.isoformat())
        if end is not None:
            clauses.append("timestamp <= ?")
            params.append(end.isoformat())
        if tool is not None:
            clauses.append("tool = ?")
            params.append(tool)
        if backend is not None:
            clauses.append("backend = ?")
            params.append(backend)
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM events "
                f"{where} ORDER BY timestamp LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def close(self) -> None:
        """Close SQLite connection."""
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row_to_record(row: tuple) -> EventRecord:
        ts = row[0]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        return EventRecord(
            timestamp=ts,
            tool=row[1],
            backend=row[2],
            status=row[3],
            duration_ms=row[4],
            session_id=row[5],
            agent_id=row[6],
            agent_type=row[7],
            workflow_id=row[8],
            error_type=row[9],
            was_summarized=bool(row[10]),
            original_size=row[11],
            summary_size=row[12],
            input_tokens=row[13],
            output_tokens=row[14],
            cache_read_tokens=row[15],
            cache_creation_tokens=row[16],
            phase=row[17],
            target=row[18],
        )
