#!/usr/bin/env python3
"""Project root detection for contextual handoffs.

Detects project root by walking up from working directory looking for markers:
- .git/
- pyproject.toml
- package.json
- .project-root (explicit marker)
"""

import re
import time
from datetime import date
from pathlib import Path
from typing import Optional

# Project root markers in priority order (first match wins)
PROJECT_MARKERS = [
    ".git",          # Git repository
    ".project-root", # Explicit marker
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
]


def find_project_root(path: Optional[str | Path] = None) -> Path:
    """Find project root by walking up from path looking for markers.
    
    Args:
        path: Starting path. Defaults to current working directory.
        
    Returns:
        Path to project root, or the starting path if no markers found.
    """
    if path is None:
        path = Path.cwd()
    else:
        path = Path(path).resolve()
    
    # Walk up directory tree
    current = path if path.is_dir() else path.parent
    
    while current != current.parent:  # Stop at filesystem root
        for marker in PROJECT_MARKERS:
            marker_path = current / marker
            if marker_path.exists():
                return current
        current = current.parent
    
    # Check root directory too
    for marker in PROJECT_MARKERS:
        if (current / marker).exists():
            return current
    
    # No markers found, return original path
    return path if path.is_dir() else path.parent


def get_handoff_dir(project_root: Path, create: bool = False) -> Path:
    """Get the handoff directory for a project.
    
    Args:
        project_root: Project root path
        create: If True, create the directory if it doesn't exist
        
    Returns:
        Path to handoff directory (.serena/memories under project root)
    """
    handoff_dir = project_root / ".serena" / "memories"
    
    if create and not handoff_dir.exists():
        handoff_dir.mkdir(parents=True, exist_ok=True)
    
    return handoff_dir


def find_recent_handoffs(
    project_root: Path,
    max_count: int = 5,
    max_age_hours: Optional[int] = None
) -> list[Path]:
    """Find recent handoff files in the project.
    
    Args:
        project_root: Project root path
        max_count: Maximum number of handoffs to return
        max_age_hours: If set, only return handoffs modified within this many hours
        
    Returns:
        List of handoff file paths, sorted by modification time (newest first)
    """
    handoff_dir = get_handoff_dir(project_root)
    
    if not handoff_dir.exists():
        return []
    
    handoffs = list(handoff_dir.glob("handoff-*.md"))
    
    if not handoffs:
        return []
    
    # Filter by age if specified
    if max_age_hours is not None:
        cutoff_time = time.time() - (max_age_hours * 3600)
        handoffs = [h for h in handoffs if h.stat().st_mtime >= cutoff_time]
    
    # Sort by modification time, newest first
    handoffs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    
    return handoffs[:max_count]


def build_handoff_filename(topic: str) -> str:
    """Build a handoff filename with date and topic.
    
    Args:
        topic: Topic/description for the handoff
        
    Returns:
        Filename like 'handoff-2026-01-24-topic-name.md'
    """
    today = date.today().isoformat()
    
    # Sanitize topic for filesystem
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '-', topic.lower())
    sanitized = re.sub(r'-+', '-', sanitized)  # Collapse multiple dashes
    sanitized = sanitized.strip('-')[:50]  # Limit length
    
    return f"handoff-{today}-{sanitized}.md"


def get_handoff_path(topic: str, path: Optional[str | Path] = None) -> Path:
    """Get full path for a new handoff file.
    
    Args:
        topic: Topic/description for the handoff
        path: Starting path for project detection. Defaults to cwd.
        
    Returns:
        Full path where handoff should be saved
    """
    project_root = find_project_root(path)
    handoff_dir = get_handoff_dir(project_root, create=True)
    filename = build_handoff_filename(topic)
    
    return handoff_dir / filename
