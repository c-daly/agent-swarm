"""Session file compression utilities.

Compresses old session JSONL files to save disk space.
DuckDB can query both .jsonl and .jsonl.gz transparently.
"""
import gzip
import shutil
from pathlib import Path
from datetime import datetime


def compress_old_sessions(sessions_dir: Path, max_age_hours: int = 24) -> int:
    """Compress session JSONL files older than max_age_hours.

    Args:
        sessions_dir: Directory containing session-*.jsonl files.
        max_age_hours: Files older than this are compressed.

    Returns:
        Number of files compressed.
    """
    sessions_dir = Path(sessions_dir)
    if not sessions_dir.exists():
        return 0

    compressed_count = 0
    now = datetime.now().timestamp()
    max_age_seconds = max_age_hours * 3600

    for jsonl_file in sessions_dir.glob("*.jsonl"):
        # Skip if already has .gz version
        gz_path = jsonl_file.with_suffix(".jsonl.gz")
        if gz_path.exists():
            continue

        # Skip if too recent
        file_age = now - jsonl_file.stat().st_mtime
        if file_age < max_age_seconds:
            continue

        # Compress the file
        with open(jsonl_file, "rb") as f_in:
            with gzip.open(gz_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Remove original after successful compression
        jsonl_file.unlink()
        compressed_count += 1

    return compressed_count
