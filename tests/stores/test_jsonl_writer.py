"""Tests for JSONL event writer."""
import json
import tempfile
from pathlib import Path
from lib.stores.jsonl_writer import JSONLWriter
from lib.stores.events import ToolCallEvent


def test_writer_creates_file():
    """Writer creates session file if it doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = JSONLWriter(data_dir=tmpdir)
        event = ToolCallEvent(
            timestamp="2026-01-21T10:00:00Z",
            session_id="test-session",
            agent_id="agent-1",
            tool="Read",
            backend="native",
            duration_ms=100,
            status="success",
        )
        writer.write(event)

        session_file = Path(tmpdir) / "session-test-session.jsonl"
        assert session_file.exists()


def test_writer_appends_events():
    """Writer appends multiple events to same file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = JSONLWriter(data_dir=tmpdir)

        for i in range(3):
            event = ToolCallEvent(
                timestamp=f"2026-01-21T10:0{i}:00Z",
                session_id="test-session",
                agent_id="agent-1",
                tool=f"Tool{i}",
                backend="native",
                duration_ms=100 + i,
                status="success",
            )
            writer.write(event)

        session_file = Path(tmpdir) / "session-test-session.jsonl"
        lines = session_file.read_text().strip().split("\n")
        assert len(lines) == 3

        # Verify JSONL format
        for line in lines:
            data = json.loads(line)
            assert "tool" in data


def test_writer_session_path():
    """Writer returns correct session file path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = JSONLWriter(data_dir=tmpdir)
        path = writer.get_session_path("my-session")
        assert path == Path(tmpdir) / "session-my-session.jsonl"
