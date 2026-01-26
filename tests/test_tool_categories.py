"""Tests for tool_categories module - single source of truth for tool mappings."""

import pytest
from lib.tool_categories import (
    ToolCategory,
    TOOL_CATEGORIES,
    FILE_WRITE_TOOLS,
    WORKFLOW_CONTROL_TOOLS,
    get_tool_category,
    is_file_write_tool,
    is_workflow_control_tool,
)


class TestNativeToolCategories:
    """Test that native Claude Code tools have correct categories."""

    def test_read_is_file_read(self):
        assert TOOL_CATEGORIES["Read"] == ToolCategory.FILE_READ

    def test_edit_is_file_write(self):
        assert TOOL_CATEGORIES["Edit"] == ToolCategory.FILE_WRITE

    def test_write_is_file_write(self):
        assert TOOL_CATEGORIES["Write"] == ToolCategory.FILE_WRITE

    def test_glob_is_file_search(self):
        assert TOOL_CATEGORIES["Glob"] == ToolCategory.FILE_SEARCH

    def test_grep_is_file_search(self):
        assert TOOL_CATEGORIES["Grep"] == ToolCategory.FILE_SEARCH

    def test_bash_is_none_for_special_handling(self):
        # Bash requires special handling via shell_virtualizer
        assert TOOL_CATEGORIES["Bash"] is None

    def test_notebook_edit_is_file_write(self):
        assert TOOL_CATEGORIES["NotebookEdit"] == ToolCategory.FILE_WRITE

    def test_task_is_subagent(self):
        assert TOOL_CATEGORIES["Task"] == ToolCategory.SUBAGENT


class TestMCPRouterNativeVariants:
    """Test that MCP router native variants have correct categories."""

    def test_router_read_file(self):
        assert TOOL_CATEGORIES["mcp__router__native__read_file"] == ToolCategory.FILE_READ

    def test_router_write_file(self):
        assert TOOL_CATEGORIES["mcp__router__native__write_file"] == ToolCategory.FILE_WRITE

    def test_router_edit_file(self):
        assert TOOL_CATEGORIES["mcp__router__native__edit_file"] == ToolCategory.FILE_WRITE

    def test_router_glob(self):
        assert TOOL_CATEGORIES["mcp__router__native__glob"] == ToolCategory.FILE_SEARCH

    def test_router_grep(self):
        assert TOOL_CATEGORIES["mcp__router__native__grep"] == ToolCategory.FILE_SEARCH

    def test_router_bash(self):
        assert TOOL_CATEGORIES["mcp__router__native__bash"] == ToolCategory.SHELL_DANGEROUS


class TestShortNativeVariants:
    """Test that short native__ variants have correct categories."""

    def test_native_read_file(self):
        assert TOOL_CATEGORIES["native__read_file"] == ToolCategory.FILE_READ

    def test_native_write_file(self):
        assert TOOL_CATEGORIES["native__write_file"] == ToolCategory.FILE_WRITE

    def test_native_edit_file(self):
        assert TOOL_CATEGORIES["native__edit_file"] == ToolCategory.FILE_WRITE

    def test_native_glob(self):
        assert TOOL_CATEGORIES["native__glob"] == ToolCategory.FILE_SEARCH

    def test_native_grep(self):
        assert TOOL_CATEGORIES["native__grep"] == ToolCategory.FILE_SEARCH

    def test_native_bash(self):
        assert TOOL_CATEGORIES["native__bash"] == ToolCategory.SHELL_DANGEROUS


class TestSerenaVariants:
    """Test that Serena variants (both plugin and router) have correct categories."""

    def test_plugin_serena_read_file(self):
        assert TOOL_CATEGORIES["mcp__plugin_serena_serena__read_file"] == ToolCategory.FILE_READ

    def test_router_serena_read_file(self):
        assert TOOL_CATEGORIES["mcp__router__serena__read_file"] == ToolCategory.FILE_READ

    def test_plugin_serena_create_text_file(self):
        assert TOOL_CATEGORIES["mcp__plugin_serena_serena__create_text_file"] == ToolCategory.FILE_WRITE

    def test_router_serena_create_text_file(self):
        assert TOOL_CATEGORIES["mcp__router__serena__create_text_file"] == ToolCategory.FILE_WRITE

    def test_plugin_serena_find_symbol(self):
        assert TOOL_CATEGORIES["mcp__plugin_serena_serena__find_symbol"] == ToolCategory.CODE_QUERY

    def test_router_serena_find_symbol(self):
        assert TOOL_CATEGORIES["mcp__router__serena__find_symbol"] == ToolCategory.CODE_QUERY

    def test_plugin_serena_replace_symbol_body(self):
        assert TOOL_CATEGORIES["mcp__plugin_serena_serena__replace_symbol_body"] == ToolCategory.CODE_EDIT

    def test_router_serena_replace_symbol_body(self):
        assert TOOL_CATEGORIES["mcp__router__serena__replace_symbol_body"] == ToolCategory.CODE_EDIT


class TestConsistencyWithPhaseModel:
    """Test that phase_model uses the same TOOL_CATEGORIES."""

    def test_phase_model_imports_from_tool_categories(self):
        from lib.phase_model import TOOL_CATEGORIES as phase_model_categories
        # Should be the exact same object
        assert phase_model_categories == TOOL_CATEGORIES

    def test_phase_model_uses_same_tool_category_enum(self):
        from lib.phase_model import ToolCategory as PhaseToolCategory
        # Should be the exact same enum
        assert PhaseToolCategory == ToolCategory


class TestConsistencyWithPermissionStore:
    """Test that permission_store uses the same TOOL_CATEGORIES."""

    def test_permission_store_imports_from_tool_categories(self):
        from lib.permission_store import TOOL_CATEGORIES as perm_store_categories
        # Should be the exact same object
        assert perm_store_categories == TOOL_CATEGORIES

    def test_permission_store_uses_same_tool_category_enum(self):
        from lib.permission_store import ToolCategory as PermToolCategory
        # Should be the exact same enum
        assert PermToolCategory == ToolCategory

    def test_permission_store_uses_file_write_tools(self):
        from lib.permission_store import FILE_WRITE_TOOLS as perm_file_write
        assert perm_file_write == FILE_WRITE_TOOLS

    def test_permission_store_uses_workflow_control_tools(self):
        from lib.permission_store import WORKFLOW_CONTROL_TOOLS as perm_workflow
        assert perm_workflow == WORKFLOW_CONTROL_TOOLS


class TestHelperFunctions:
    """Test the helper functions."""

    def test_get_tool_category_known_tool(self):
        assert get_tool_category("Read") == ToolCategory.FILE_READ

    def test_get_tool_category_unknown_tool(self):
        assert get_tool_category("NonexistentTool") is None

    def test_is_file_write_tool_true(self):
        assert is_file_write_tool("Edit") is True
        assert is_file_write_tool("Write") is True
        assert is_file_write_tool("NotebookEdit") is True

    def test_is_file_write_tool_false(self):
        assert is_file_write_tool("Read") is False
        assert is_file_write_tool("Bash") is False

    def test_is_workflow_control_tool_true(self):
        assert is_workflow_control_tool("mcp__router__workflow__workflow_start") is True
        assert is_workflow_control_tool("workflow_set_state") is True

    def test_is_workflow_control_tool_false(self):
        assert is_workflow_control_tool("Read") is False


class TestToolCategoryCoverage:
    """Test that all tool categories have at least one tool."""

    def test_all_categories_have_tools(self):
        """Each ToolCategory should have at least one tool mapped to it."""
        categories_with_tools = set()
        for category in TOOL_CATEGORIES.values():
            if category is not None:
                categories_with_tools.add(category)

        # These categories should all have tools
        expected = {
            ToolCategory.FILE_READ,
            ToolCategory.FILE_WRITE,
            ToolCategory.CODE_QUERY,
            ToolCategory.CODE_EDIT,
            ToolCategory.FILE_SEARCH,
            ToolCategory.SHELL_DANGEROUS,
            ToolCategory.WEB_RESEARCH,
            ToolCategory.SUBAGENT,
            ToolCategory.MEMORY,
            ToolCategory.USER_INTERACTION,
            ToolCategory.WORKFLOW_CONTROL,
        }

        missing = expected - categories_with_tools
        assert not missing, f"Categories without tools: {missing}"

    def test_file_read_has_multiple_variants(self):
        """FILE_READ should include native and MCP variants."""
        file_read_tools = [
            name for name, cat in TOOL_CATEGORIES.items()
            if cat == ToolCategory.FILE_READ
        ]
        # Should have at least: Read, mcp__router__native__read_file, native__read_file
        assert len(file_read_tools) >= 3, f"Expected more FILE_READ tools: {file_read_tools}"
        assert "Read" in file_read_tools
        assert "mcp__router__native__read_file" in file_read_tools

    def test_file_write_has_multiple_variants(self):
        """FILE_WRITE should include native and MCP variants."""
        file_write_tools = [
            name for name, cat in TOOL_CATEGORIES.items()
            if cat == ToolCategory.FILE_WRITE
        ]
        # Should have at least: Edit, Write, mcp__router__native__edit_file
        assert len(file_write_tools) >= 3, f"Expected more FILE_WRITE tools: {file_write_tools}"
        assert "Edit" in file_write_tools
        assert "Write" in file_write_tools
        assert "mcp__router__native__edit_file" in file_write_tools

    def test_file_search_has_multiple_variants(self):
        """FILE_SEARCH should include native and MCP variants."""
        file_search_tools = [
            name for name, cat in TOOL_CATEGORIES.items()
            if cat == ToolCategory.FILE_SEARCH
        ]
        # Should have at least: Glob, Grep, mcp__router__native__glob
        assert len(file_search_tools) >= 3, f"Expected more FILE_SEARCH tools: {file_search_tools}"
        assert "Glob" in file_search_tools
        assert "Grep" in file_search_tools
        assert "mcp__router__native__glob" in file_search_tools
