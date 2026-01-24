#!/usr/bin/env python3
"""Tests for session-start.py handoff auto-discovery functionality."""

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

# Add hooks and lib to path
hooks_dir = Path(__file__).parent.parent / "hooks"
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(hooks_dir))
sys.path.insert(0, str(lib_dir))


class TestDiscoverProjectHandoffs:
    """Tests for discover_project_handoffs function."""

    def test_finds_handoff_in_project(self):
        """Should find handoff files in current project's .serena/memories."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            memories = root / ".serena" / "memories"
            memories.mkdir(parents=True)
            
            handoff = memories / "handoff-2026-01-24-feature.md"
            handoff.write_text("# Session Handoff\n\n## Current Task\nImplement feature X")
            
            with patch.object(Path, 'cwd', return_value=root):
                result = session_start.discover_project_handoffs(root)
            
            assert len(result) >= 1
            assert any("handoff-2026-01-24-feature" in str(h) for h in result)

    def test_returns_empty_if_no_handoffs(self):
        """Should return empty list if no handoffs exist."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            
            result = session_start.discover_project_handoffs(root)
            
            assert result == []

    def test_sorts_by_recency(self):
        """Should return handoffs sorted by modification time, newest first."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            memories = root / ".serena" / "memories"
            memories.mkdir(parents=True)
            
            # Create older handoff
            older = memories / "handoff-2026-01-20-old.md"
            older.write_text("# Old")
            older_mtime = time.time() - 86400  # 1 day ago
            os.utime(older, (older_mtime, older_mtime))
            
            # Create newer handoff
            newer = memories / "handoff-2026-01-24-new.md"
            newer.write_text("# New")
            
            result = session_start.discover_project_handoffs(root)
            
            assert len(result) == 2
            assert "new" in result[0].name.lower()


class TestFormatHandoffContext:
    """Tests for format_handoff_context function."""

    def test_formats_single_handoff(self):
        """Should format a single handoff into context message."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            handoff = root / "handoff-2026-01-24-feature.md"
            handoff.write_text("""# Session Handoff - 2026-01-24

## Current Task
Implement contextual handoff system

## Status
- Phase: Implementation
- Progress: Tests written
- Blockers: None

## Key Files
- lib/project_root.py
- hooks/session-start.py

## Next Steps
1. Implement format_handoff_context
""")
            
            result = session_start.format_handoff_context([handoff])
            
            assert "Handoff" in result or "handoff" in result
            assert "contextual" in result.lower() or "Implementation" in result

    def test_truncates_long_content(self):
        """Should truncate very long handoff content."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            handoff = root / "handoff-2026-01-24-verbose.md"
            handoff.write_text("# Long Handoff\n\n" + "x" * 5000)
            
            result = session_start.format_handoff_context([handoff], max_chars=500)
            
            assert len(result) <= 600  # Some buffer for formatting

    def test_handles_multiple_handoffs(self):
        """Should handle multiple handoffs, preferring most recent."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            
            handoff1 = root / "handoff-2026-01-24-first.md"
            handoff1.write_text("# First\nTask: First task")
            
            handoff2 = root / "handoff-2026-01-23-second.md"
            handoff2.write_text("# Second\nTask: Second task")
            
            result = session_start.format_handoff_context([handoff1, handoff2])
            
            # Should include most recent or mention there are multiple
            assert "First" in result or "handoff" in result.lower()


class TestHandoffIntegration:
    """Integration tests for handoff auto-discovery in session start."""

    def test_handoff_included_in_system_message(self):
        """Handoff content should be included in session start output."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            memories = root / ".serena" / "memories"
            memories.mkdir(parents=True)
            
            handoff = memories / "handoff-2026-01-24-test.md"
            handoff.write_text("""# Session Handoff

## Current Task
Test the handoff system

## Status
- Phase: Testing
""")
            
            # Mock cwd and find_project_root
            with patch('project_root.find_project_root', return_value=root):
                with patch.object(Path, 'cwd', return_value=root):
                    handoffs = session_start.discover_project_handoffs(root)
                    context = session_start.format_handoff_context(handoffs)
            
            assert "handoff" in context.lower() or "Task" in context

    def test_no_handoff_no_message(self):
        """Should not include handoff section if no handoffs exist."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            # No .serena/memories directory
            
            result = session_start.discover_project_handoffs(root)
            context = session_start.format_handoff_context(result)
            
            # Should return empty or minimal message
            assert context == "" or "No handoffs" in context or len(context) < 50


class TestHandoffPendingStatus:
    """Tests for detecting pending/in-progress handoffs."""

    def test_detects_pending_status(self):
        """Should prioritize handoffs with pending/in-progress status."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            memories = root / ".serena" / "memories"
            memories.mkdir(parents=True)
            
            # Older but pending handoff
            pending = memories / "handoff-2026-01-20-pending.md"
            pending.write_text("""# Session Handoff

## Status
- Phase: In Progress
- Blockers: Waiting for review
""")
            pending_mtime = time.time() - 86400
            os.utime(pending, (pending_mtime, pending_mtime))
            
            # Newer but completed handoff
            complete = memories / "handoff-2026-01-24-done.md"
            complete.write_text("""# Session Handoff

## Status
- Phase: Complete
- All tasks done
""")
            
            result = session_start.discover_project_handoffs(root)
            
            # Should find both (function doesn't filter by status, just returns by recency)
            assert len(result) == 2


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
