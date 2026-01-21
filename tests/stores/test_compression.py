"""Tests for session file compression."""
import gzip
import tempfile
from pathlib import Path
from datetime import datetime
from lib.stores.compression import compress_old_sessions


def test_compress_old_sessions_skips_recent():
    """Sessions less than 24h old are not compressed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sessions_dir = Path(tmpdir)
        recent_file = sessions_dir / "session-recent.jsonl"
        recent_file.write_text('{"tool": "Read"}\n')

        compress_old_sessions(sessions_dir, max_age_hours=24)

        assert recent_file.exists()
        assert not (sessions_dir / "session-recent.jsonl.gz").exists()


def test_compress_old_sessions_compresses_old():
    """Sessions older than 24h are compressed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sessions_dir = Path(tmpdir)
        old_file = sessions_dir / "session-old.jsonl"
        old_file.write_text('{"tool": "Read"}\n{"tool": "Write"}\n')

        import os
        old_time = datetime.now().timestamp() - (25 * 3600)
        os.utime(old_file, (old_time, old_time))

        compress_old_sessions(sessions_dir, max_age_hours=24)

        assert not old_file.exists()
        gz_file = sessions_dir / "session-old.jsonl.gz"
        assert gz_file.exists()

        with gzip.open(gz_file, "rt") as f:
            lines = f.read().strip().split("\n")
            assert len(lines) == 2


def test_compress_old_sessions_returns_count():
    """Function returns number of files compressed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sessions_dir = Path(tmpdir)
        
        # Create 2 old files
        import os
        old_time = datetime.now().timestamp() - (25 * 3600)
        
        for i in range(2):
            old_file = sessions_dir / f"session-old{i}.jsonl"
            old_file.write_text('{"tool": "Read"}\n')
            os.utime(old_file, (old_time, old_time))
        
        # Create 1 recent file
        recent_file = sessions_dir / "session-recent.jsonl"
        recent_file.write_text('{"tool": "Read"}\n')
        
        count = compress_old_sessions(sessions_dir, max_age_hours=24)
        assert count == 2


def test_compress_old_sessions_handles_missing_dir():
    """Function handles non-existent directory gracefully."""
    count = compress_old_sessions(Path("/nonexistent/path"), max_age_hours=24)
    assert count == 0


def test_compress_old_sessions_skips_already_compressed():
    """Does not recompress files that already have .gz version."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sessions_dir = Path(tmpdir)
        
        import os
        old_time = datetime.now().timestamp() - (25 * 3600)
        
        # Create old file with existing gz
        old_file = sessions_dir / "session-already.jsonl"
        old_file.write_text('{"tool": "Read"}\n')
        os.utime(old_file, (old_time, old_time))
        
        gz_file = sessions_dir / "session-already.jsonl.gz"
        with gzip.open(gz_file, "wt") as f:
            f.write('{"tool": "Read"}\n')
        
        count = compress_old_sessions(sessions_dir, max_age_hours=24)
        assert count == 0  # Skipped because .gz exists
        assert old_file.exists()  # Original not deleted
