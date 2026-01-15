"""Log file rotation to prevent unbounded growth.

Implements size-based rotation with optional date suffixes
to keep log files manageable.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO


class RotatingLog:
    """A log file that rotates when size threshold is reached.

    Args:
        path: Path to the log file.
        max_size_kb: Maximum size in KB before rotation (default: 1000 = 1MB).
        max_files: Maximum number of rotated files to keep (default: 5).
        date_suffix: If True, use date suffix instead of numeric (default: False).
    """

    def __init__(
        self,
        path: Path,
        max_size_kb: int = 1000,
        max_files: int = 5,
        date_suffix: bool = False,
    ):
        self.path = Path(path)
        self.max_size_bytes = max_size_kb * 1024
        self.max_files = max_files
        self.date_suffix = date_suffix
        self._file: Optional[TextIO] = None
        self._current_size = 0

        # Initialize current size if file exists
        if self.path.exists():
            self._current_size = self.path.stat().st_size

    def _open(self):
        """Open the log file for appending."""
        if self._file is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self.path, "a", encoding="utf-8")

    def write(self, message: str) -> None:
        """Write a message to the log, rotating if necessary.

        Args:
            message: The message to write.
        """
        self._open()

        # Check if we need to rotate before writing
        message_bytes = len(message.encode("utf-8"))
        if self._current_size + message_bytes > self.max_size_bytes:
            self._rotate()

        self._file.write(message)
        self._file.flush()
        self._current_size += message_bytes

    def _rotate(self) -> None:
        """Rotate the current log file."""
        if self._file:
            self._file.close()
            self._file = None

        if not self.path.exists():
            return

        # Generate rotated filename
        if self.date_suffix:
            suffix = datetime.now().strftime(".%Y%m%d_%H%M%S")
        else:
            suffix = ".1"

        rotated_path = self.path.with_suffix(self.path.suffix + suffix)

        # Rename current log to rotated name
        self.path.rename(rotated_path)

        # Clean up old rotated files
        self._cleanup_old_files()

        # Reset size counter
        self._current_size = 0

        # Reopen for fresh writes
        self._open()

    def _cleanup_old_files(self) -> None:
        """Remove old rotated files beyond max_files limit."""
        # Find all rotated files
        pattern = f"{self.path.name}.*"
        rotated_files = list(self.path.parent.glob(pattern))

        # Sort by modification time (oldest first)
        rotated_files.sort(key=lambda p: p.stat().st_mtime)

        # Remove oldest files if we have too many
        while len(rotated_files) >= self.max_files:
            oldest = rotated_files.pop(0)
            try:
                oldest.unlink()
            except OSError:
                pass

    def close(self) -> None:
        """Close the log file."""
        if self._file:
            self._file.close()
            self._file = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def rotate_existing_logs(state_dir: Path, max_size_kb: int = 500, max_files: int = 3) -> int:
    """Rotate any existing large log files in the state directory.

    Args:
        state_dir: Directory containing log files.
        max_size_kb: Threshold for rotation.
        max_files: Maximum files to keep per log.

    Returns:
        Number of files rotated.
    """
    rotated = 0

    for log_file in state_dir.glob("*.log"):
        if log_file.stat().st_size > max_size_kb * 1024:
            log = RotatingLog(log_file, max_size_kb=max_size_kb, max_files=max_files)
            log._rotate()
            log.close()
            rotated += 1

    return rotated
