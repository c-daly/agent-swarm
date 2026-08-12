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


# ============================================================================
# Tests for enhanced resolver functionality: workspace detection, scope
# inference, and save_at_scope
# ============================================================================


class TestWorkspaceDetection:
    """Test workspace-level detection (directory containing multiple .git children)."""

    def test_detect_workspace_with_multiple_git_children(self, tmp_path):
        """A directory with multiple .git subdirectories is a workspace."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Create two repos within workspace
        repo1 = workspace / "repo1"
        repo1.mkdir()
        (repo1 / ".git").mkdir()

        repo2 = workspace / "repo2"
        repo2.mkdir()
        (repo2 / ".git").mkdir()

        level = detect_level(workspace, repo1 / "src", tmp_path / ".claude")
        assert level == "workspace"

    def test_detect_not_workspace_with_single_git(self, tmp_path):
        """A directory with only one .git child is NOT a workspace."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        repo = workspace / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        level = detect_level(workspace, repo / "src", tmp_path / ".claude")
        # Should NOT be workspace since only one .git child
        assert level != "workspace"

    def test_workspace_detection_ignores_nested_git(self, tmp_path):
        """Only direct children .git dirs count, not deeply nested ones."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Single repo with nested submodule
        repo = workspace / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        submodule = repo / "vendor" / "lib"
        submodule.mkdir(parents=True)
        (submodule / ".git").mkdir()

        level = detect_level(workspace, repo / "src", tmp_path / ".claude")
        # workspace itself only has one direct .git child (repo/.git)
        assert level != "workspace"


class TestScopeInference:
    """Test infer_scope function for determining where context should be saved."""

    def test_infer_user_scope_with_always(self, tmp_path):
        """Content with 'always' indicates user-level preference."""
        from context.resolver import infer_scope

        content = "I always prefer tabs over spaces."
        scope, path = infer_scope(content, tmp_path)

        assert scope == "user"
        assert path == Path.home() / ".claude"

    def test_infer_user_scope_with_never(self, tmp_path):
        """Content with 'never' indicates user-level preference."""
        from context.resolver import infer_scope

        content = "Never use semicolons in JavaScript."
        scope, path = infer_scope(content, tmp_path)

        assert scope == "user"
        assert path == Path.home() / ".claude"

    def test_infer_user_scope_with_i_prefer(self, tmp_path):
        """Content with 'I prefer' indicates user-level preference."""
        from context.resolver import infer_scope

        content = "I prefer functional programming style."
        scope, path = infer_scope(content, tmp_path)

        assert scope == "user"
        assert path == Path.home() / ".claude"

    def test_infer_component_scope_with_file_paths(self, tmp_path):
        """Content mentioning specific file paths is component-level."""
        from context.resolver import infer_scope

        # Create a file structure
        component = tmp_path / "src" / "auth"
        component.mkdir(parents=True)
        (component / "login.py").touch()

        content = "The login.py file handles authentication."
        scope, path = infer_scope(content, component)

        assert scope == "component"
        assert path == component

    def test_infer_repo_scope_default(self, tmp_path):
        """Content without global indicators or paths defaults to repo."""
        from context.resolver import infer_scope

        repo = tmp_path / "myrepo"
        repo.mkdir()
        (repo / ".git").mkdir()

        content = "This project uses pytest for testing."
        scope, path = infer_scope(content, repo)

        assert scope == "repo"
        assert path == repo

    def test_infer_scope_finds_repo_root(self, tmp_path):
        """When in a subdirectory, repo scope should find the repo root."""
        from context.resolver import infer_scope

        repo = tmp_path / "myrepo"
        repo.mkdir()
        (repo / ".git").mkdir()

        subdir = repo / "src" / "lib"
        subdir.mkdir(parents=True)

        content = "This module handles data processing."
        scope, path = infer_scope(content, subdir)

        assert scope == "repo"
        assert path == repo


class TestSaveAtScope:
    """Test save_at_scope function for persisting context content."""

    @pytest.fixture(autouse=True)
    def _anchor_repo_root(self, tmp_path):
        """Make tmp_path the repo root so scope inference is deterministic.

        save_at_scope() infers "repo" scope by walking upward for a `.git`
        directory. With no `.git` inside tmp_path the walk escapes into
        shared ancestors (e.g. /tmp); a stray marker left there by an
        unrelated process then redirects the save out of tmp_path. Anchoring
        tmp_path as the repo root isolates these tests from that state.
        """
        (tmp_path / ".git").mkdir()

    def test_save_creates_context_directory(self, tmp_path):
        """save_at_scope creates .context directory if needed."""
        from context.resolver import save_at_scope

        content = "This project uses pytest for testing."
        saved_path = save_at_scope(content, "MEMORY.md", tmp_path)

        assert (tmp_path / ".context").exists()
        assert (tmp_path / ".context").is_dir()

    def test_save_appends_to_file(self, tmp_path):
        """save_at_scope appends content to existing file."""
        from context.resolver import save_at_scope

        # Create existing memory file
        context_dir = tmp_path / ".context"
        context_dir.mkdir()
        memory_file = context_dir / "MEMORY.md"
        memory_file.write_text("# Existing memory\n\nFirst entry.\n")

        content = "Second entry about testing."
        saved_path = save_at_scope(content, "MEMORY.md", tmp_path)

        result = saved_path.read_text()
        assert "First entry" in result
        assert "Second entry" in result

    def test_save_returns_correct_path(self, tmp_path):
        """save_at_scope returns the path where content was saved."""
        from context.resolver import save_at_scope

        content = "Test content."
        saved_path = save_at_scope(content, "MEMORY.md", tmp_path)

        assert saved_path == tmp_path / ".context" / "MEMORY.md"
        assert saved_path.exists()

    def test_save_at_user_scope(self, tmp_path, monkeypatch):
        """Content with global indicators saves to user directory."""
        from context.resolver import save_at_scope

        # Mock home directory
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        content = "I always want verbose output."
        saved_path = save_at_scope(content, "MEMORY.md", tmp_path / "some" / "project")

        assert saved_path.parent.parent == fake_home / ".claude"

    def test_save_handles_different_file_types(self, tmp_path):
        """save_at_scope works with different file types."""
        from context.resolver import save_at_scope

        content = "Decision: Use PostgreSQL for persistence."
        saved_path = save_at_scope(content, "DECISIONS.md", tmp_path)

        assert saved_path.name == "DECISIONS.md"
        assert saved_path.exists()
        assert content in saved_path.read_text()
