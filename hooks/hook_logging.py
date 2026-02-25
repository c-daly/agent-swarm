"""
Shared logging module for agent-swarm hooks.

Provides consistent logging across all hook files with:
- File-based logging to .state/hooks.log
- Configurable log levels via LOG_LEVEL env var
- Structured log format with timestamps and context
- Graceful degradation if log file isn't writable
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Log file location (alongside other state files)
LOG_DIR = Path(__file__).resolve().parent.parent / ".state"
LOG_FILE = LOG_DIR / "hooks.log"

# Default log level, overridable via environment
DEFAULT_LOG_LEVEL = "INFO"

# Module-level logger instance
_logger: Optional[logging.Logger] = None


def get_logger(name: str = "agent-swarm.hooks") -> logging.Logger:
    """
    Get or create a configured logger instance.

    Args:
        name: Logger name (typically module name)

    Returns:
        Configured logger instance
    """
    global _logger

    if _logger is not None:
        return _logger

    _logger = logging.getLogger(name)

    # Get log level from environment
    level_name = os.environ.get("AGENT_SWARM_LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)
    _logger.setLevel(level)

    # Avoid duplicate handlers if called multiple times
    if _logger.handlers:
        return _logger

    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Try to add file handler
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        _logger.addHandler(file_handler)
    except (OSError, IOError) as e:
        # Can't write to log file - fall back to stderr only
        sys.stderr.write(f"[hook_logging] Cannot create log file: {e}\n")

    # Always add stderr handler for ERROR and above
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(logging.ERROR)
    _logger.addHandler(stderr_handler)

    return _logger


def log_error(message: str, exc_info: bool = False, **context) -> None:
    """Log an error with optional exception info and context."""
    logger = get_logger()
    if context:
        message = f"{message} | {context}"
    logger.error(message, exc_info=exc_info)


def log_warning(message: str, **context) -> None:
    """Log a warning with optional context."""
    logger = get_logger()
    if context:
        message = f"{message} | {context}"
    logger.warning(message)


def log_info(message: str, **context) -> None:
    """Log info with optional context."""
    logger = get_logger()
    if context:
        message = f"{message} | {context}"
    logger.info(message)


def log_debug(message: str, **context) -> None:
    """Log debug info with optional context."""
    logger = get_logger()
    if context:
        message = f"{message} | {context}"
    logger.debug(message)


class HookError(Exception):
    """Base exception for hook errors."""
    pass


class ConfigError(HookError):
    """Configuration file error (missing, malformed, etc.)."""
    pass


class StateError(HookError):
    """State file error (corrupted, inaccessible, etc.)."""
    pass


class ValidationError(HookError):
    """Input validation error."""
    pass
