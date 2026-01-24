#!/usr/bin/env python3
"""
Tests for context/resolver.py

Tests the hierarchical context resolution system.
"""

import pytest
from pathlib import Path
import sys

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from context.resolver import (  # noqa: E402
    resolve_context,
    get_agent_context,
    show_context_tree,
    find_context_file,
    detect_level,
    ContextLayer,
)


class TestContextLayer:
    """Test ContextLayer parsing."""

    def test_parse_sections(self):
        content = """# Context: Test

## Purpose
This is the purpose section.

## Conventions
- Use tabs
- No trailing whitespace
"""
        layer = ContextLayer(path=Path("/test"), level="repo", content=content)

        assert "purpose" in layer.sections
        assert "conventions" in layer.sections
        assert "This is the purpose section." in layer.sections["purpose"]

    def test_parse_metadata_inherit(self):
        content = """# Context: Test
@inherit: false
@override: conventions
@priority: high

## Purpose
Test
"""
        layer = ContextLayer(path=Path("/test"), level="repo", content=content)

        assert layer.metadata["inherit"] is False
        assert "conventions" in layer.metadata["override"]
        assert layer.metadata["priority"] == "high"

    def test_parse_metadata_defaults(self):
        content = "## Purpose\nTest"
        layer = ContextLayer(path=Path("/test"), level="repo", content=content)

        assert layer.metadata["inherit"] is True
        assert layer.metadata["override"] == []
        assert layer.metadata["priority"] == "normal"


class TestFindContextFile:
    """Test context file discovery."""

    def test_find_context_in_hidden_dir(self, tmp_path):
        context_dir = tmp_path / ".context"
        context_dir.mkdir()
        context_file = context_dir / "CONTEXT.md"
        context_file.write_text("## Purpose\nTest")

        found = find_context_file(tmp_path)
        assert found == context_file

    def test_find_context_in_claude_dir(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        context_file = claude_dir / "CONTEXT.md"
        context_file.write_text("## Purpose\nTest")

        found = find_context_file(tmp_path)
        assert found == context_file

    def test_find_visible_context(self, tmp_path):
        context_file = tmp_path / "CONTEXT.md"
        context_file.write_text("## Purpose\nTest")

        found = find_context_file(tmp_path)
        assert found == context_file

    def test_no_context_file(self, tmp_path):
        found = find_context_file(tmp_path)
        assert found is None

    def test_priority_order(self, tmp_path):
        """Hidden .context dir should take priority over visible file."""
        # Create both
        context_dir = tmp_path / ".context"
        context_dir.mkdir()
        hidden_file = context_dir / "CONTEXT.md"
        hidden_file.write_text("## Purpose\nHidden")

        visible_file = tmp_path / "CONTEXT.md"
        visible_file.write_text("## Purpose\nVisible")

        found = find_context_file(tmp_path)
        assert found == hidden_file


class TestDetectLevel:
    """Test directory level detection."""

    def test_detect_user_level(self, tmp_path):
        user_dir = tmp_path / ".claude"
        user_dir.mkdir()

        level = detect_level(user_dir, tmp_path / "work", user_dir)
        assert level == "user"

    def test_detect_repo_level(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()

        level = detect_level(repo_dir, repo_dir / "src", tmp_path / ".claude")
        assert level == "repo"

    def test_detect_feature_level(self, tmp_path):
        repo_dir = tmp_path / "repo"
        feature_dir = repo_dir / "features" / "auth"
        feature_dir.mkdir(parents=True)
        (repo_dir / ".git").mkdir()

        level = detect_level(feature_dir, feature_dir, tmp_path / ".claude")
        assert level == "feature"


class TestResolveContext:
    """Test full context resolution."""

    def test_resolve_single_layer(self, tmp_path):
        context_file = tmp_path / "CONTEXT.md"
        context_file.write_text(
            """## Purpose
Test project

## Conventions
- Use Python 3.10+
"""
        )

        ctx = resolve_context(tmp_path, user_dir=tmp_path / ".claude")

        assert len(ctx.layers) == 1
        assert "purpose" in ctx.merged_sections
        assert "Test project" in ctx.merged_sections["purpose"]

    def test_resolve_hierarchy(self, tmp_path):
        # User level - separate from project tree
        user_dir = tmp_path / "home" / ".claude"
        user_dir.mkdir(parents=True)
        (user_dir / "CONTEXT.md").write_text(
            """## Preferences
- Be concise
"""
        )

        # Repo level
        repo_dir = tmp_path / "projects" / "repo"
        repo_dir.mkdir(parents=True)
        (repo_dir / ".git").mkdir()
        (repo_dir / "CONTEXT.md").write_text(
            """## Conventions
- Use TypeScript
"""
        )

        # Feature level
        feature_dir = repo_dir / "features" / "auth"
        feature_dir.mkdir(parents=True)
        (feature_dir / "CONTEXT.md").write_text(
            """## Purpose
Authentication feature
"""
        )

        ctx = resolve_context(feature_dir, user_dir=user_dir)

        # Should find: user, repo, feature (3 layers)
        assert len(ctx.layers) == 3
        # All sections should be merged
        assert "preferences" in ctx.merged_sections
        assert "conventions" in ctx.merged_sections
        assert "purpose" in ctx.merged_sections

    def test_override_section(self, tmp_path):
        # Parent
        parent_dir = tmp_path / "parent"
        parent_dir.mkdir()
        (parent_dir / "CONTEXT.md").write_text(
            """## Conventions
Parent conventions
"""
        )

        # Child with override
        child_dir = parent_dir / "child"
        child_dir.mkdir()
        (child_dir / "CONTEXT.md").write_text(
            """@override: conventions

## Conventions
Child conventions only
"""
        )

        ctx = resolve_context(child_dir, user_dir=tmp_path / ".claude")

        # Should only have child conventions, not appended
        assert "Child conventions only" in ctx.merged_sections["conventions"]
        assert "Parent conventions" not in ctx.merged_sections["conventions"]

    def test_no_inherit(self, tmp_path):
        # Parent
        parent_dir = tmp_path / "parent"
        parent_dir.mkdir()
        (parent_dir / "CONTEXT.md").write_text(
            """## Purpose
Parent purpose

## Conventions
Parent conventions
"""
        )

        # Child that doesn't inherit
        child_dir = parent_dir / "child"
        child_dir.mkdir()
        (child_dir / "CONTEXT.md").write_text(
            """@inherit: false

## Purpose
Child purpose only
"""
        )

        ctx = resolve_context(child_dir, user_dir=tmp_path / ".claude")

        # Should only have child content
        assert "Child purpose only" in ctx.merged_sections["purpose"]
        assert "conventions" not in ctx.merged_sections


class TestAggregatedContext:
    """Test context merging and output."""

    def test_to_markdown(self, tmp_path):
        context_file = tmp_path / "CONTEXT.md"
        context_file.write_text(
            """## Purpose
Test

## Conventions
- Rule 1
"""
        )

        ctx = resolve_context(tmp_path, user_dir=tmp_path / ".claude")
        md = ctx.to_markdown()

        assert "## Purpose" in md
        assert "## Conventions" in md

    def test_to_dict(self, tmp_path):
        context_file = tmp_path / "CONTEXT.md"
        context_file.write_text("## Purpose\nTest")

        ctx = resolve_context(tmp_path, user_dir=tmp_path / ".claude")
        d = ctx.to_dict()

        assert "layers" in d
        assert "merged" in d
        assert len(d["layers"]) == 1

    def test_get_sections(self, tmp_path):
        context_file = tmp_path / "CONTEXT.md"
        context_file.write_text(
            """## Purpose
Test

## Conventions
Rules

## Pitfalls
Watch out
"""
        )

        ctx = resolve_context(tmp_path, user_dir=tmp_path / ".claude")
        sections = ctx.get_sections(["purpose", "conventions"])

        assert "purpose" in sections
        assert "conventions" in sections
        assert "pitfalls" not in sections


class TestAgentContext:
    """Test agent-specific context filtering."""

    def test_explorer_context(self, tmp_path):
        context_file = tmp_path / "CONTEXT.md"
        context_file.write_text(
            """## Purpose
Project purpose

## Boundaries
Feature boundaries

## Conventions
Code conventions

## Pitfalls
Known issues
"""
        )

        ctx = get_agent_context("explorer", tmp_path)

        # Explorer should get boundaries and conventions
        assert "boundaries" in ctx.lower() or "Boundaries" in ctx
        assert "conventions" in ctx.lower() or "Conventions" in ctx

    def test_implementer_context(self, tmp_path):
        context_file = tmp_path / "CONTEXT.md"
        context_file.write_text(
            """## Purpose
Project purpose

## Conventions
Code conventions

## Patterns
Design patterns

## Pitfalls
Known issues
"""
        )

        ctx = get_agent_context("implementer", tmp_path)

        # Implementer should get conventions, patterns, pitfalls
        assert "conventions" in ctx.lower() or "Conventions" in ctx
        assert "patterns" in ctx.lower() or "Patterns" in ctx
        assert "pitfalls" in ctx.lower() or "Pitfalls" in ctx


class TestShowContextTree:
    """Test context tree visualization."""

    def test_tree_output(self, tmp_path):
        context_file = tmp_path / "CONTEXT.md"
        context_file.write_text(
            """## Purpose
Test

## Conventions
Rules
"""
        )

        tree = show_context_tree(tmp_path)

        assert "Context Hierarchy" in tree
        assert "purpose" in tree.lower()
        assert "conventions" in tree.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
