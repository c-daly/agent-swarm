"""Tests for tool translation layer."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from tool_translator import ToolTranslator, ToolMapping, get_translator, translate_tool


class TestToolMapping:
    """Test ToolMapping dataclass."""

    def test_simple_arg_translation(self):
        """Args are renamed according to arg_map."""
        mapping = ToolMapping(
            native_name="Read",
            mcp_name="mcp__router__native__read_file",
            arg_map={"file_path": "path"},
        )

        result = mapping.translate_args({"file_path": "/tmp/test.py"})

        assert result == {"path": "/tmp/test.py"}

    def test_passthrough_unmapped_args(self):
        """Unmapped args pass through unchanged."""
        mapping = ToolMapping(
            native_name="Test",
            mcp_name="mcp__test",
            arg_map={"a": "b"},
        )

        result = mapping.translate_args({"a": 1, "c": 2})

        assert result == {"b": 1, "c": 2}

    def test_metadata_fields_preserved(self):
        """Fields starting with _ pass through unchanged."""
        mapping = ToolMapping(
            native_name="Read",
            mcp_name="mcp__router__native__read_file",
            arg_map={"file_path": "path"},
        )

        result = mapping.translate_args({
            "file_path": "/tmp/test.py",
            "_agent_type": "implementer",
            "_workflow": "iterate",
        })

        assert result["_agent_type"] == "implementer"
        assert result["_workflow"] == "iterate"
        assert result["path"] == "/tmp/test.py"

    def test_custom_transform(self):
        """Custom transform function is applied."""
        def add_default(args):
            args["timeout"] = args.get("timeout", 30)
            return args

        mapping = ToolMapping(
            native_name="Bash",
            mcp_name="mcp__router__native__bash",
            transform=add_default,
        )

        result = mapping.translate_args({"command": "ls"})

        assert result["command"] == "ls"
        assert result["timeout"] == 30


class TestToolTranslator:
    """Test ToolTranslator class."""

    def test_translate_read(self):
        """Read tool translates correctly."""
        translator = ToolTranslator()

        tool, args = translator.translate("Read", {
            "file_path": "/tmp/test.py",
            "offset": 10,
            "limit": 100,
        })

        assert tool == "mcp__router__native__read_file"
        assert args["file_path"] == "/tmp/test.py"
        assert args["offset"] == 10
        assert args["limit"] == 100

    def test_translate_write(self):
        """Write tool translates correctly."""
        translator = ToolTranslator()

        tool, args = translator.translate("Write", {
            "file_path": "/tmp/test.py",
            "content": "hello world",
        })

        assert tool == "mcp__router__native__write_file"
        assert args["file_path"] == "/tmp/test.py"
        assert args["content"] == "hello world"

    def test_translate_edit(self):
        """Edit tool translates correctly."""
        translator = ToolTranslator()

        tool, args = translator.translate("Edit", {
            "file_path": "/tmp/test.py",
            "old_string": "foo",
            "new_string": "bar",
        })

        assert tool == "mcp__router__native__edit_file"
        assert args["old_string"] == "foo"
        assert args["new_string"] == "bar"

    def test_translate_glob(self):
        """Glob tool translates correctly."""
        translator = ToolTranslator()

        tool, args = translator.translate("Glob", {
            "pattern": "**/*.py",
            "path": "/tmp",
        })

        assert tool == "mcp__router__native__glob"
        assert args["pattern"] == "**/*.py"
        assert args["path"] == "/tmp"

    def test_translate_grep(self):
        """Grep tool translates correctly."""
        translator = ToolTranslator()

        tool, args = translator.translate("Grep", {
            "pattern": "def main",
            "path": "/tmp",
            "-i": True,
        })

        assert tool == "mcp__router__native__grep"
        assert args["pattern"] == "def main"
        assert args["case_insensitive"] is True

    def test_translate_bash(self):
        """Bash tool translates correctly."""
        translator = ToolTranslator()

        tool, args = translator.translate("Bash", {
            "command": "pytest tests/",
            "timeout": 60,
        })

        assert tool == "mcp__router__native__bash"
        assert args["command"] == "pytest tests/"
        assert args["timeout"] == 60

    def test_passthrough_mcp_tools(self):
        """MCP tools pass through unchanged."""
        translator = ToolTranslator()

        tool, args = translator.translate("mcp__router__serena__find_symbol", {
            "name_path_pattern": "MyClass",
        })

        assert tool == "mcp__router__serena__find_symbol"
        assert args["name_path_pattern"] == "MyClass"

    def test_passthrough_unknown_tools(self):
        """Unknown tools pass through unchanged."""
        translator = ToolTranslator()

        tool, args = translator.translate("UnknownTool", {"foo": "bar"})

        assert tool == "UnknownTool"
        assert args == {"foo": "bar"}

    def test_metadata_preserved(self):
        """Agent metadata is preserved through translation."""
        translator = ToolTranslator()

        tool, args = translator.translate("Read", {
            "file_path": "/tmp/test.py",
            "_agent_type": "implementer",
            "_workflow": "iterate",
            "_phase": "implement",
        })

        assert args["_agent_type"] == "implementer"
        assert args["_workflow"] == "iterate"
        assert args["_phase"] == "implement"

    def test_has_mapping(self):
        """has_mapping returns correct values."""
        translator = ToolTranslator()

        assert translator.has_mapping("Read") is True
        assert translator.has_mapping("Write") is True
        assert translator.has_mapping("UnknownTool") is False

    def test_get_mapping(self):
        """get_mapping returns correct mapping."""
        translator = ToolTranslator()

        mapping = translator.get_mapping("Read")

        assert mapping is not None
        assert mapping.mcp_name == "mcp__router__native__read_file"

    def test_register_custom_mapping(self):
        """Can register custom mappings."""
        translator = ToolTranslator()

        translator.register(ToolMapping(
            native_name="CustomTool",
            mcp_name="mcp__custom__tool",
            arg_map={"input": "data"},
        ))

        tool, args = translator.translate("CustomTool", {"input": "test"})

        assert tool == "mcp__custom__tool"
        assert args["data"] == "test"

    def test_unregister_mapping(self):
        """Can unregister mappings."""
        translator = ToolTranslator()

        removed = translator.unregister("Read")

        assert removed is not None
        assert translator.has_mapping("Read") is False

        # Now Read passes through
        tool, args = translator.translate("Read", {"file_path": "/tmp/x"})
        assert tool == "Read"

    def test_reverse_lookup(self):
        """Can find native name from MCP name."""
        translator = ToolTranslator()

        native = translator.reverse_lookup("mcp__router__native__read_file")

        assert native == "Read"

    def test_reverse_lookup_not_found(self):
        """reverse_lookup returns None for unknown MCP tools."""
        translator = ToolTranslator()

        native = translator.reverse_lookup("mcp__unknown__tool")

        assert native is None

    def test_list_mappings(self):
        """list_mappings returns all mappings."""
        translator = ToolTranslator()

        mappings = translator.list_mappings()

        assert "Read" in mappings
        assert "Write" in mappings
        assert "Bash" in mappings
        assert mappings["Read"] == "mcp__router__native__read_file"


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_get_translator_singleton(self):
        """get_translator returns the same instance."""
        t1 = get_translator()
        t2 = get_translator()

        assert t1 is t2

    def test_translate_tool_function(self):
        """translate_tool convenience function works."""
        tool, args = translate_tool("Read", {"file_path": "/tmp/x"})

        assert tool == "mcp__router__native__read_file"
        assert args["file_path"] == "/tmp/x"
