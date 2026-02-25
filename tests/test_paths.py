"""Tests for lib/paths.py - centralized path resolution.

Verifies that all paths are derived from two anchors:
  1. PLUGIN_ROOT (from __file__ or AGENT_SWARM_ROOT env var)
  2. CLAUDE_HOME (from Path.home()/.claude or CLAUDE_HOME env var)

No path in the codebase should contain a hard-coded username or
assume a specific install location.
"""

import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Project root for this worktree
PROJECT_ROOT = Path(__file__).parent.parent


class TestPluginRoot:
    """PLUGIN_ROOT resolves to the actual plugin directory."""

    def test_plugin_root_default(self):
        """PLUGIN_ROOT defaults to the directory containing lib/paths.py's grandparent."""
        from lib.paths import PLUGIN_ROOT
        assert PLUGIN_ROOT == Path(__file__).parent.parent.resolve()

    def test_plugin_root_is_directory(self):
        from lib.paths import PLUGIN_ROOT
        assert PLUGIN_ROOT.is_dir()

    def test_plugin_root_contains_expected_structure(self):
        """Sanity check: PLUGIN_ROOT should contain key directories."""
        from lib.paths import PLUGIN_ROOT
        assert (PLUGIN_ROOT / "lib").is_dir()
        assert (PLUGIN_ROOT / "hooks").is_dir()
        assert (PLUGIN_ROOT / "config").is_dir()

    def test_plugin_root_env_override(self):
        """AGENT_SWARM_ROOT env var overrides PLUGIN_ROOT."""
        import importlib
        import lib.paths as paths_mod

        with patch.dict(os.environ, {"AGENT_SWARM_ROOT": "/tmp/fake-plugin"}):
            importlib.reload(paths_mod)
            assert paths_mod.PLUGIN_ROOT == Path("/tmp/fake-plugin")

        # Restore
        os.environ.pop("AGENT_SWARM_ROOT", None)
        importlib.reload(paths_mod)


class TestClaudeHome:
    """CLAUDE_HOME resolves to the user's .claude directory."""

    def test_claude_home_default(self):
        from lib.paths import CLAUDE_HOME
        assert CLAUDE_HOME == Path.home() / ".claude"

    def test_claude_home_env_override(self):
        """CLAUDE_HOME env var overrides the default."""
        import importlib
        import lib.paths as paths_mod

        with patch.dict(os.environ, {"CLAUDE_HOME": "/tmp/fake-claude"}):
            importlib.reload(paths_mod)
            assert paths_mod.CLAUDE_HOME == Path("/tmp/fake-claude")

        os.environ.pop("CLAUDE_HOME", None)
        importlib.reload(paths_mod)


class TestDerivedPaths:
    """All derived paths should be built from PLUGIN_ROOT or CLAUDE_HOME."""

    def test_state_dir(self):
        from lib.paths import PLUGIN_ROOT, STATE_DIR
        assert STATE_DIR == PLUGIN_ROOT / ".state"

    def test_claude_projects(self):
        from lib.paths import CLAUDE_HOME, CLAUDE_PROJECTS
        assert CLAUDE_PROJECTS == CLAUDE_HOME / "projects"

    def test_config_dir(self):
        from lib.paths import PLUGIN_ROOT, CONFIG_DIR
        assert CONFIG_DIR == PLUGIN_ROOT / "config"

    def test_lib_dir(self):
        from lib.paths import PLUGIN_ROOT, LIB_DIR
        assert LIB_DIR == PLUGIN_ROOT / "lib"

    def test_hooks_dir(self):
        from lib.paths import PLUGIN_ROOT, HOOKS_DIR
        assert HOOKS_DIR == PLUGIN_ROOT / "hooks"

    def test_scripts_dir(self):
        from lib.paths import PLUGIN_ROOT, SCRIPTS_DIR
        assert SCRIPTS_DIR == PLUGIN_ROOT / "scripts"


class TestResolveConfigPaths:
    """resolve_plugin_path() replaces {{PLUGIN_ROOT}} in strings."""

    def test_resolve_simple_string(self):
        from lib.paths import resolve_plugin_path, PLUGIN_ROOT
        result = resolve_plugin_path("{{PLUGIN_ROOT}}/bin/mcp-native")
        assert result == f"{PLUGIN_ROOT}/bin/mcp-native"

    def test_resolve_no_placeholder(self):
        from lib.paths import resolve_plugin_path
        result = resolve_plugin_path("python3 somefile.py")
        assert result == "python3 somefile.py"

    def test_resolve_multiple_placeholders(self):
        from lib.paths import resolve_plugin_path, PLUGIN_ROOT
        result = resolve_plugin_path("{{PLUGIN_ROOT}}/a {{PLUGIN_ROOT}}/b")
        assert result == f"{PLUGIN_ROOT}/a {PLUGIN_ROOT}/b"

    def test_resolve_claude_home_placeholder(self):
        from lib.paths import resolve_plugin_path, CLAUDE_HOME
        result = resolve_plugin_path("{{CLAUDE_HOME}}/projects")
        assert result == f"{CLAUDE_HOME}/projects"

    def test_resolve_in_list(self):
        """resolve_config_paths handles lists (e.g., command arrays in backends.json)."""
        from lib.paths import resolve_config_paths, PLUGIN_ROOT
        input_list = ["python3", "{{PLUGIN_ROOT}}/bin/mcp-native"]
        result = resolve_config_paths(input_list)
        assert result == ["python3", f"{PLUGIN_ROOT}/bin/mcp-native"]

    def test_resolve_in_dict(self):
        """resolve_config_paths handles dicts recursively."""
        from lib.paths import resolve_config_paths, PLUGIN_ROOT
        input_dict = {
            "command": ["python3", "{{PLUGIN_ROOT}}/bin/mcp-native"],
            "name": "native",
        }
        result = resolve_config_paths(input_dict)
        assert result["command"] == ["python3", f"{PLUGIN_ROOT}/bin/mcp-native"]
        assert result["name"] == "native"

    def test_resolve_nested(self):
        """resolve_config_paths handles nested structures."""
        from lib.paths import resolve_config_paths, PLUGIN_ROOT
        input_data = {
            "native": {
                "command": ["python3", "{{PLUGIN_ROOT}}/bin/mcp-native"],
            }
        }
        result = resolve_config_paths(input_data)
        assert result["native"]["command"][1] == f"{PLUGIN_ROOT}/bin/mcp-native"


class TestBackendsJsonPortable:
    """backends.json should use {{PLUGIN_ROOT}} placeholders, not absolute paths."""

    def test_no_hardcoded_home_paths(self):
        """backends.json must not contain any hard-coded home directory paths."""
        backends_path = PROJECT_ROOT / "config" / "backends.json"
        content = backends_path.read_text()
        assert not re.search(r"/(?:home|Users)/\w+/", content), (
            f"backends.json contains hard-coded user paths: {content}"
        )

    def test_uses_plugin_root_placeholder(self):
        """backends.json should use {{PLUGIN_ROOT}} for plugin-relative paths."""
        backends_path = PROJECT_ROOT / "config" / "backends.json"
        data = json.loads(backends_path.read_text())
        for name, cfg in data.items():
            for arg in cfg.get("command", []):
                if "agent-swarm" in str(arg):
                    assert "{{PLUGIN_ROOT}}" in str(arg), (
                        f"Backend '{name}' has hard-coded plugin path: {arg}"
                    )

    def test_resolved_paths_are_valid(self):
        """After resolution, backend command paths should exist."""
        from lib.paths import resolve_config_paths
        backends_path = PROJECT_ROOT / "config" / "backends.json"
        data = json.loads(backends_path.read_text())
        resolved = resolve_config_paths(data)

        for name, cfg in resolved.items():
            cmd = cfg.get("command", [])
            for arg in cmd:
                if arg.endswith(".py") and "/" in arg:
                    assert Path(arg).exists(), (
                        f"Backend '{name}': resolved path does not exist: {arg}"
                    )


class TestHooksJsonPortable:
    """hooks.json should use {{PLUGIN_ROOT}} placeholders, not absolute paths."""

    def test_no_hardcoded_home_paths(self):
        hooks_path = PROJECT_ROOT / "hooks" / "hooks.json"
        content = hooks_path.read_text()
        assert not re.search(r"/(?:home|Users)/\w+/", content), (
            f"hooks.json contains hard-coded user paths: {content}"
        )

    def test_uses_plugin_root_placeholder(self):
        hooks_path = PROJECT_ROOT / "hooks" / "hooks.json"
        content = hooks_path.read_text()
        if "agent-swarm" in content:
            assert "{{PLUGIN_ROOT}}" in content


class TestBatchScriptsPortable:
    """batch_search.py and batch_glob.py should not have hard-coded paths."""

    def test_batch_search_no_hardcoded_paths(self):
        path = PROJECT_ROOT / "lib" / "scripts" / "batch_search.py"
        content = path.read_text()
        assert not re.search(r"/(?:home|Users)/\w+/", content), (
            "batch_search.py contains hard-coded user paths"
        )

    def test_batch_glob_no_hardcoded_paths(self):
        path = PROJECT_ROOT / "lib" / "scripts" / "batch_glob.py"
        content = path.read_text()
        assert not re.search(r"/(?:home|Users)/\w+/", content), (
            "batch_glob.py contains hard-coded user paths"
        )


class TestShellScriptsPortable:
    """Shell scripts should use dirname-based resolution, not absolute paths."""

    def test_mcp_router_wrapper_no_hardcoded_paths(self):
        path = PROJECT_ROOT / "bin" / "mcp-router-wrapper"
        content = path.read_text()
        assert not re.search(r"/(?:home|Users)/\w+/", content), (
            "mcp-router-wrapper contains hard-coded user paths"
        )


class TestPythonFilesNoHardcodedPluginPaths:
    """No Python source file should contain hard-coded paths to the plugin directory.

    Files should use lib.paths constants or Path(__file__) relative resolution.
    Path.home() / ".claude" is acceptable for CLAUDE_HOME (user config dir).
    Path.home() / ".claude/plugins/agent-swarm" is NOT acceptable (should use PLUGIN_ROOT).
    """

    @pytest.fixture
    def python_source_files(self):
        """All .py files in the project, excluding tests, docs, and __pycache__."""
        files = []
        for py_file in PROJECT_ROOT.rglob("*.py"):
            rel = py_file.relative_to(PROJECT_ROOT)
            skip_dirs = {"__pycache__", ".worktrees", "docs"}
            if any(part in skip_dirs for part in rel.parts):
                continue
            files.append(py_file)
        return files

    def test_no_hardcoded_absolute_user_paths(self, python_source_files):
        """No .py file should contain /home/username or /Users/username paths.

        Excludes generic examples like /home/user/ used in docstrings.
        """
        violations = []
        for py_file in python_source_files:
            # Skip this test file itself
            if py_file.name == "test_paths.py":
                continue
            content = py_file.read_text()
            matches = re.findall(r"/(?:home|Users)/\w+/[^\s\"']+", content)
            # Filter out generic docstring examples (/home/user/)
            matches = [m for m in matches if "/home/user/" not in m]
            if matches:
                rel = py_file.relative_to(PROJECT_ROOT)
                violations.append(f"  {rel}: {matches}")
        assert not violations, (
            "Files with hard-coded absolute user paths:\n" + "\n".join(violations)
        )

    def test_no_hardcoded_plugin_path_via_home(self, python_source_files):
        """No .py file should construct the plugin path via Path.home() / '.claude/plugins/agent-swarm'.

        Use PLUGIN_ROOT from lib.paths or Path(__file__).parent instead.
        """
        pattern = re.compile(
            r'Path\.home\(\)\s*/\s*["\']\.claude/plugins/agent-swarm'
        )
        violations = []
        for py_file in python_source_files:
            # Skip this test file itself (it references the pattern)
            if py_file.name == "test_paths.py":
                continue
            content = py_file.read_text()
            if pattern.search(content):
                rel = py_file.relative_to(PROJECT_ROOT)
                violations.append(f"  {rel}")
        assert not violations, (
            "Files constructing plugin path via Path.home():\n"
            + "\n".join(violations)
            + "\n\nUse PLUGIN_ROOT from lib.paths or Path(__file__).parent instead."
        )
