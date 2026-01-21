"""JSONL writer for telemetry events.

Appends events to session-specific JSONL files for DuckDB querying.
"""
import json
from pathlib import Path
from lib.stores.events import ToolCallEvent


class JSONLWriter:
    """Writes ToolCallEvents to session JSONL files."""

    def __init__(self, data_dir: str) -> None:
        """Initialize writer with data directory.

        Args:
            data_dir: Directory to store session JSONL files.
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def get_session_path(self, session_id: str) -> Path:
        """Get path for a session's JSONL file."""
        return self.data_dir / f"session-{session_id}.jsonl"

    def write(self, event: ToolCallEvent) -> None:
        """Append event to session JSONL file.

        Creates file if it doesn't exist. Appends as newline-delimited JSON.
        """
        path = self.get_session_path(event.session_id)
        with open(path, "a") as f:
            f.write(json.dumps(event.to_dict()) + "\n")
