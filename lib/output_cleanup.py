"""Output cleanup utilities for agent task files.

This module provides functions to find and clean up stale agent output files
to prevent disk space issues. Output files are stored in /tmp/claude/*/tasks/
as JSONL files that can grow large over time.

IMPORTANT: Only operates on files in /tmp/claude/*/tasks/ - never touches .state/ files.
"""
from pathlib import Path
import glob
import time
from typing import List


def find_stale_outputs(max_age_hours: int = 24, base_path: str = "/tmp") -> List[Path]:
    """Find output files older than threshold.
    
    Args:
        max_age_hours: Files older than this many hours are considered stale.
        base_path: Base directory to search in (default: /tmp, overridable for testing).
    
    Returns:
        List of Path objects for stale output files.
    """
    stale_files = []
    current_time = time.time()
    max_age_seconds = max_age_hours * 3600
    
    # Search pattern: /tmp/claude/*/tasks/*.output
    search_pattern = str(Path(base_path) / "claude" / "*" / "tasks" / "*.output")
    
    try:
        for file_path_str in glob.glob(search_pattern):
            file_path = Path(file_path_str)
            
            # Skip if this is in a .state directory (safety check)
            if ".state" in file_path.parts:
                continue
            
            try:
                # Check file age
                mtime = file_path.stat().st_mtime
                age_seconds = current_time - mtime
                
                if age_seconds > max_age_seconds:
                    stale_files.append(file_path)
            except (OSError, IOError):
                # Skip files we can't stat
                continue
                
    except Exception:
        # Handle missing directories or other errors gracefully
        pass
    
    return stale_files


def cleanup_stale_outputs(max_age_hours: int = 24, dry_run: bool = False, base_path: str = "/tmp") -> dict:
    """Clean up old output files.
    
    Args:
        max_age_hours: Delete files older than this many hours.
        dry_run: If True, report what would be deleted without actually deleting.
        base_path: Base directory to search in (default: /tmp, overridable for testing).
    
    Returns:
        Dictionary with:
            - files_deleted: Number of files deleted (or would be deleted in dry_run)
            - space_reclaimed: Bytes freed (or would be freed in dry_run)
    """
    stale_files = find_stale_outputs(max_age_hours=max_age_hours, base_path=base_path)
    
    files_deleted = 0
    space_reclaimed = 0
    
    for file_path in stale_files:
        try:
            # Get file size before deletion
            file_size = file_path.stat().st_size
            
            if not dry_run:
                # Actually delete the file
                file_path.unlink()
            
            # Count as deleted (even in dry_run mode for reporting)
            files_deleted += 1
            space_reclaimed += file_size
            
        except (OSError, IOError):
            # Handle deletion errors gracefully - continue with other files
            continue
    
    return {
        "files_deleted": files_deleted,
        "space_reclaimed": space_reclaimed
    }


def get_output_size_stats(base_path: str = "/tmp") -> dict:
    """Get statistics on output file storage.
    
    Args:
        base_path: Base directory to search in (default: /tmp, overridable for testing).
    
    Returns:
        Dictionary with:
            - total_files: Number of output files found
            - total_size_bytes: Total size in bytes
            - total_size_mb: Total size in megabytes
    """
    total_files = 0
    total_size_bytes = 0
    
    # Search pattern: /tmp/claude/*/tasks/*.output
    search_pattern = str(Path(base_path) / "claude" / "*" / "tasks" / "*.output")
    
    try:
        for file_path_str in glob.glob(search_pattern):
            file_path = Path(file_path_str)
            
            # Skip if this is in a .state directory (safety check)
            if ".state" in file_path.parts:
                continue
            
            try:
                file_size = file_path.stat().st_size
                total_files += 1
                total_size_bytes += file_size
            except (OSError, IOError):
                # Skip files we can't stat
                continue
                
    except Exception:
        # Handle missing directories or other errors gracefully
        pass
    
    total_size_mb = total_size_bytes / (1024 * 1024) if total_size_bytes > 0 else 0.0
    
    return {
        "total_files": total_files,
        "total_size_bytes": total_size_bytes,
        "total_size_mb": total_size_mb
    }
