#!/usr/bin/env python3
"""Tests for session-start.py context hierarchy and scope tagging functionality.

Tests:
1. Hierarchy loading finds all levels (user, repo, component)
2. HANDOFF age filtering (< 48 hours only)
3. Scope tags in output format
4. Existing memory pattern tests preserved
"""

import sys
from pathlib import Path
from unittest.mock import patch
import tempfile
import os
import time

# Add hooks to path
hooks_dir = Path(__file__).parent.parent / "hooks"
sys.path.insert(0, str(hooks_dir))


# =============================================================================
# NEW TESTS: Context Hierarchy Loading
# =============================================================================

class TestLoadContextHierarchy:
    """Tests for loading context from all hierarchy levels."""

    def test_finds_all_hierarchy_levels(self):
        """Should walk up from cwd to ~/.claude and find context at each level."""
        from importlib import reload, import_module
        session_start = import_module("session-start")
        reload(session_start)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a hierarchy: user -> repo -> component
            user_dir = Path(tmpdir) / ".claude"
            repo_dir = Path(tmpdir) / "projects" / "myrepo"
            component_dir = repo_dir / "src" / "hooks"
            
            # Create directories and .context folders
            (user_dir / ".context").mkdir(parents=True)
            (repo_dir / ".context").mkdir(parents=True)
            (repo_dir / ".git").mkdir()  # Mark as repo root
            (component_dir / ".context").mkdir(parents=True)
            
            # Create CONTEXT.md at each level
            (user_dir / ".context" / "CONTEXT.md").write_text("## Conventions\nUser conventions")
            (repo_dir / ".context" / "CONTEXT.md").write_text("## Conventions\nRepo conventions")
            (component_dir / ".context" / "CONTEXT.md").write_text("## Conventions\nComponent conventions")
            
            # Test the hierarchy loading
            result = session_start.load_context_hierarchy(component_dir, user_dir)
            
            # Should find all three levels
            assert len(result) == 3
            levels = [ctx["level"] for ctx in result]
            assert "user" in levels
            assert "repo" in levels
            assert "component" in levels

    def test_loads_context_md_from_each_level(self):
        """Should load CONTEXT.md content from each .context/ directory."""
        from importlib import reload, import_module
        session_start = import_module("session-start")
        reload(session_start)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create hierarchy
            user_dir = Path(tmpdir) / ".claude"
            repo_dir = Path(tmpdir) / "repo"
            
            (user_dir / ".context").mkdir(parents=True)
            (repo_dir / ".context").mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            
            (user_dir / ".context" / "CONTEXT.md").write_text("User context content")
            (repo_dir / ".context" / "CONTEXT.md").write_text("Repo context content")
            
            result = session_start.load_context_hierarchy(repo_dir, user_dir)
            
            # Verify content is loaded
            contents = [ctx["content"] for ctx in result if ctx.get("content")]
            assert any("User context" in c for c in contents)
            assert any("Repo context" in c for c in contents)

    def test_loads_memory_md_from_each_level(self):
        """Should also load MEMORY.md from each .context/ directory."""
        from importlib import reload, import_module
        session_start = import_module("session-start")
        reload(session_start)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = Path(tmpdir) / "repo"
            (repo_dir / ".context").mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            
            (repo_dir / ".context" / "MEMORY.md").write_text("""## Patterns Observed
- Repo pattern
  Confidence: high | Last reinforced: 2026-01-10
""")
            
            result = session_start.load_context_hierarchy(repo_dir, Path(tmpdir) / ".claude")
            
            # Should have memory content
            assert any(ctx.get("memory") for ctx in result)


class TestHandoffAgeFiltering:
    """Tests for HANDOFF.md age filtering (< 48 hours)."""

    def test_loads_handoff_under_48_hours(self):
        """Should load HANDOFF.md if modified within 48 hours."""
        from importlib import reload, import_module
        session_start = import_module("session-start")
        reload(session_start)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = Path(tmpdir) / "repo"
            (repo_dir / ".context").mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            
            handoff_file = repo_dir / ".context" / "HANDOFF.md"
            handoff_file.write_text("# Session Handoff\n\nRecent work here")
            # File is fresh (just created)
            
            result = session_start.load_context_hierarchy(repo_dir, Path(tmpdir) / ".claude")
            
            # Should have handoff content
            handoff_content = [ctx.get("handoff") for ctx in result if ctx.get("handoff")]
            assert len(handoff_content) > 0
            assert "Recent work" in handoff_content[0]

    def test_skips_handoff_over_48_hours(self):
        """Should skip HANDOFF.md if modified more than 48 hours ago."""
        from importlib import reload, import_module
        session_start = import_module("session-start")
        reload(session_start)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = Path(tmpdir) / "repo"
            (repo_dir / ".context").mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            
            handoff_file = repo_dir / ".context" / "HANDOFF.md"
            handoff_file.write_text("# Session Handoff\n\nOld work here")
            
            # Set mtime to 49 hours ago
            old_time = time.time() - (49 * 3600)
            os.utime(handoff_file, (old_time, old_time))
            
            result = session_start.load_context_hierarchy(repo_dir, Path(tmpdir) / ".claude")
            
            # Should NOT have handoff content
            handoff_content = [ctx.get("handoff") for ctx in result if ctx.get("handoff")]
            assert len(handoff_content) == 0

    def test_handoff_at_47_hours_is_included(self):
        """HANDOFF.md at 47 hours should be included (well within limit)."""
        from importlib import reload, import_module
        session_start = import_module("session-start")
        reload(session_start)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = Path(tmpdir) / "repo"
            (repo_dir / ".context").mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            
            handoff_file = repo_dir / ".context" / "HANDOFF.md"
            handoff_file.write_text("# Session Handoff\n\nBorderline work")
            
            # Set mtime to 47 hours ago (safely within limit)
            boundary_time = time.time() - (47 * 3600)
            os.utime(handoff_file, (boundary_time, boundary_time))
            
            result = session_start.load_context_hierarchy(repo_dir, Path(tmpdir) / ".claude")
            
            # Should have handoff content
            handoff_content = [ctx.get("handoff") for ctx in result if ctx.get("handoff")]
            assert len(handoff_content) > 0


class TestScopeTagsInOutput:
    """Tests for scope tags in formatted output."""

    def test_user_scope_tagged_correctly(self):
        """Output should tag user-level context with [user]."""
        from importlib import reload, import_module
        session_start = import_module("session-start")
        reload(session_start)
        
        hierarchy = [
            {"level": "user", "path": "/home/user/.claude", "content": "Prefer ruff over flake8"}
        ]
        
        result = session_start.format_hierarchy_context(hierarchy)
        
        assert "[user]" in result
        assert "ruff" in result

    def test_repo_scope_tagged_with_name(self):
        """Output should tag repo-level context with [repo:name]."""
        from importlib import reload, import_module
        session_start = import_module("session-start")
        reload(session_start)
        
        hierarchy = [
            {"level": "repo", "path": "/projects/agent-swarm", "content": "Use pytest-asyncio for async tests"}
        ]
        
        result = session_start.format_hierarchy_context(hierarchy)
        
        assert "[repo:agent-swarm]" in result
        assert "pytest-asyncio" in result

    def test_component_scope_tagged_with_path(self):
        """Output should tag component-level context with [component:name]."""
        from importlib import reload, import_module
        session_start = import_module("session-start")
        reload(session_start)
        
        hierarchy = [
            {"level": "component", "path": "/projects/agent-swarm/hooks", "content": "JWT refresh in middleware"}
        ]
        
        result = session_start.format_hierarchy_context(hierarchy)
        
        assert "[component:hooks]" in result
        assert "JWT" in result

    def test_multiple_levels_all_tagged(self):
        """Output should show all levels with correct tags."""
        from importlib import reload, import_module
        session_start = import_module("session-start")
        reload(session_start)
        
        hierarchy = [
            {"level": "user", "path": "/home/user/.claude", "content": "User preference"},
            {"level": "repo", "path": "/projects/myrepo", "content": "Repo convention"},
            {"level": "component", "path": "/projects/myrepo/src", "content": "Component rule"},
        ]
        
        result = session_start.format_hierarchy_context(hierarchy)
        
        assert "[user]" in result
        assert "[repo:myrepo]" in result
        assert "[component:src]" in result


# =============================================================================
# EXISTING TESTS: Memory Pattern Loading (preserved from original)
# =============================================================================

class TestLoadMemoryPatterns:
    """Tests for load_memory_patterns function."""

    def test_returns_list_of_pattern_dicts(self):
        """Should return list of dicts with content, category, confidence, last_reinforced keys."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        memory_content = """# Memory: Test

## Patterns Observed
- Test pattern content
  Confidence: high | Last reinforced: 2026-01-10

## Pitfalls Discovered
- Test pitfall content
  Confidence: medium | Last reinforced: 2026-01-08
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scope_path = Path(tmpdir)
            context_dir = scope_path / ".context"
            context_dir.mkdir()
            (context_dir / "MEMORY.md").write_text(memory_content)
            
            result = session_start.load_memory_patterns(scope_path)
            
            assert isinstance(result, list)
            assert len(result) == 2
            
            # Check first pattern has required keys
            pattern = result[0]
            assert "content" in pattern
            assert "category" in pattern
            assert "confidence" in pattern
            assert "last_reinforced" in pattern

    def test_parses_category_from_section_header(self):
        """Should parse category from the markdown section header."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        memory_content = """# Memory: Test

## Patterns Observed
- Pattern content here
  Confidence: high | Last reinforced: 2026-01-10

## Pitfalls Discovered
- Pitfall content here
  Confidence: low | Last reinforced: 2026-01-08

## Effective Approaches
- Approach content here
  Confidence: medium | Last reinforced: 2026-01-09
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scope_path = Path(tmpdir)
            context_dir = scope_path / ".context"
            context_dir.mkdir()
            (context_dir / "MEMORY.md").write_text(memory_content)
            
            result = session_start.load_memory_patterns(scope_path)
            
            categories = [p["category"] for p in result]
            assert "pattern" in categories
            assert "pitfall" in categories
            assert "approach" in categories

    def test_parses_confidence_levels(self):
        """Should correctly parse high/medium/low confidence levels."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        memory_content = """# Memory: Test

## Patterns Observed
- High confidence pattern
  Confidence: high | Last reinforced: 2026-01-10
- Medium confidence pattern
  Confidence: medium | Last reinforced: 2026-01-09
- Low confidence pattern
  Confidence: low | Last reinforced: 2026-01-08
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scope_path = Path(tmpdir)
            context_dir = scope_path / ".context"
            context_dir.mkdir()
            (context_dir / "MEMORY.md").write_text(memory_content)
            
            result = session_start.load_memory_patterns(scope_path)
            
            confidences = {p["content"]: p["confidence"] for p in result}
            assert confidences["High confidence pattern"] == "high"
            assert confidences["Medium confidence pattern"] == "medium"
            assert confidences["Low confidence pattern"] == "low"

    def test_handles_missing_memory_file(self):
        """Should return empty list when MEMORY.md doesn't exist."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            scope_path = Path(tmpdir)
            # No .context/MEMORY.md created
            
            result = session_start.load_memory_patterns(scope_path)
            
            assert result == []

    def test_parses_last_reinforced_date(self):
        """Should extract the last reinforced date."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        memory_content = """# Memory: Test

## Patterns Observed
- Test pattern
  Confidence: high | Last reinforced: 2026-01-15
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scope_path = Path(tmpdir)
            context_dir = scope_path / ".context"
            context_dir.mkdir()
            (context_dir / "MEMORY.md").write_text(memory_content)
            
            result = session_start.load_memory_patterns(scope_path)
            
            assert result[0]["last_reinforced"] == "2026-01-15"

    def test_handles_malformed_content_gracefully(self):
        """Should skip malformed entries without crashing."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        memory_content = """# Memory: Test

## Patterns Observed
- Valid pattern
  Confidence: high | Last reinforced: 2026-01-10
- Malformed entry without confidence line
Some random text
- Another valid pattern
  Confidence: medium | Last reinforced: 2026-01-09
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scope_path = Path(tmpdir)
            context_dir = scope_path / ".context"
            context_dir.mkdir()
            (context_dir / "MEMORY.md").write_text(memory_content)
            
            result = session_start.load_memory_patterns(scope_path)
            
            # Should get at least the valid patterns
            assert len(result) >= 2


class TestFormatMemoryPatterns:
    """Tests for format_memory_patterns function."""

    def test_formats_patterns_for_display(self):
        """Should format patterns as readable text."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        patterns = [
            {"content": "Test pattern", "category": "pattern", "confidence": "high", "last_reinforced": "2026-01-10"},
            {"content": "Test pitfall", "category": "pitfall", "confidence": "medium", "last_reinforced": "2026-01-08"},
        ]
        
        result = session_start.format_memory_patterns(patterns)
        
        assert isinstance(result, str)
        assert "Test pattern" in result
        assert "Test pitfall" in result

    def test_limits_pattern_count(self):
        """Should respect max_patterns parameter."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        patterns = [
            {"content": f"Pattern {i}", "category": "pattern", "confidence": "high", "last_reinforced": "2026-01-10"}
            for i in range(10)
        ]
        
        result = session_start.format_memory_patterns(patterns, max_patterns=3)
        
        # Should only include 3 patterns
        count = sum(1 for i in range(10) if f"Pattern {i}" in result)
        assert count == 3

    def test_returns_empty_string_for_empty_list(self):
        """Should return empty string when no patterns provided."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        result = session_start.format_memory_patterns([])
        
        assert result == ""

    def test_includes_confidence_indicator(self):
        """Should show confidence level in output."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        patterns = [
            {"content": "High confidence item", "category": "pattern", "confidence": "high", "last_reinforced": "2026-01-10"},
        ]
        
        result = session_start.format_memory_patterns(patterns)
        
        # Should indicate confidence somehow (uses ! for high)
        assert "!" in result or "high" in result.lower()

    def test_groups_by_category(self):
        """Should group patterns by category in output."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        patterns = [
            {"content": "Pattern 1", "category": "pattern", "confidence": "high", "last_reinforced": "2026-01-10"},
            {"content": "Pitfall 1", "category": "pitfall", "confidence": "medium", "last_reinforced": "2026-01-09"},
            {"content": "Pattern 2", "category": "pattern", "confidence": "medium", "last_reinforced": "2026-01-08"},
        ]
        
        result = session_start.format_memory_patterns(patterns, max_patterns=10)
        
        # Should have category indicators
        assert "pattern" in result.lower() or "Pattern" in result
        assert "pitfall" in result.lower() or "Pitfall" in result


class TestSearchEpisodicMemoryFastFail:
    """Tests for search_episodic_memory early return when plugin missing."""

    def test_returns_empty_immediately_if_plugin_missing(self):
        """Should return empty list immediately if episodic-memory plugin doesn't exist."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        # Mock the episodic root to not exist
        with patch.object(Path, 'exists', return_value=False):
            result = session_start.search_episodic_memory("test query")
            
            assert result == []
