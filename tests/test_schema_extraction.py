#!/usr/bin/env python3
"""Tests for schema-based summary extraction in MCP router.

Tests the _extract_summary method and its tool-specific schemas.
"""

import json
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from mcp_router import MCPRouter  # noqa: E402


@pytest.fixture
def router():
    """Create router with mocked LLM."""
    r = MCPRouter(summarizer="none")  # No real LLM
    return r


@pytest.fixture
def router_with_llm():
    """Create router with mocked LLM that returns valid JSON."""
    r = MCPRouter(summarizer="none")
    return r


class TestSchemaDefinitions:
    """Test that schemas are properly defined."""

    def test_tool_schemas_exist(self, router):
        """All native tools have schemas."""
        expected_tools = ["grep", "glob", "bash", "read_file", "write_file", "edit_file"]
        for tool in expected_tools:
            assert tool in router.TOOL_SCHEMAS, f"Missing schema for {tool}"

    def test_schemas_have_required_fields(self, router):
        """Each schema has description and schema fields."""
        for tool, config in router.TOOL_SCHEMAS.items():
            assert "description" in config, f"{tool} missing description"
            assert "schema" in config, f"{tool} missing schema"
            assert isinstance(config["schema"], dict), f"{tool} schema not a dict"

    def test_generic_schema_exists(self, router):
        """Generic fallback schema exists."""
        assert hasattr(router, "GENERIC_SCHEMA")
        assert "schema" in router.GENERIC_SCHEMA


class TestExtractContent:
    """Test content extraction from MCP responses."""

    def test_extract_from_mcp_format(self, router):
        """Extract text from standard MCP response."""
        response = {
            "result": {
                "content": [{"type": "text", "text": "hello world"}]
            }
        }
        content = router._extract_content(response)
        assert content == "hello world"

    def test_extract_from_string_result(self, router):
        """Extract from simple string result."""
        response = {"result": "simple string"}
        content = router._extract_content(response)
        assert content == "simple string"

    def test_extract_fallback_to_json(self, router):
        """Fall back to JSON dump for unknown format."""
        response = {"something": "else"}
        content = router._extract_content(response)
        assert "something" in content


class TestFallbackExtract:
    """Test fallback extraction when LLM unavailable."""

    def test_fallback_write_file_success(self, router):
        """Fallback detects write_file success."""
        result = router._fallback_extract("write_file", "File written successfully")
        data = json.loads(result)
        assert data["success"] is True

    def test_fallback_write_file_error(self, router):
        """Fallback detects write_file error."""
        result = router._fallback_extract("write_file", "Error: permission denied")
        data = json.loads(result)
        assert data["success"] is False

    def test_fallback_bash(self, router):
        """Fallback extracts bash output."""
        output = "line1\nline2\nline3\nline4\nline5\nline6"
        result = router._fallback_extract("bash", output)
        data = json.loads(result)
        assert data["line_count"] == 6
        assert "line1" in data["preview"]

    def test_fallback_generic(self, router):
        """Fallback generic extraction."""
        content = "x" * 1000
        result = router._fallback_extract("unknown_tool", content)
        data = json.loads(result)
        assert data["char_count"] == 1000
        assert data["truncated"] is True
        assert len(data["preview"]) == 500


class TestExtractSummaryWithMockedLLM:
    """Test _extract_summary with mocked LLM responses."""

    def test_grep_schema_extraction(self, router):
        """Test grep extraction with mocked LLM."""
        # Mock LLM to return valid grep schema
        mock_response = json.dumps({
            "files": ["lib/foo.py", "lib/bar.py"],
            "by_file": {"lib/foo.py": [10, 20], "lib/bar.py": [5]},
            "match_count": 3
        })
        router._llm_call = MagicMock(return_value=mock_response)

        response = {
            "result": {
                "content": [{"type": "text", "text": "lib/foo.py:10:def foo():\nlib/foo.py:20:def bar():\nlib/bar.py:5:class Baz:"}]
            }
        }
        result = router._extract_summary("grep", response)
        data = json.loads(result)

        assert data["files"] == ["lib/foo.py", "lib/bar.py"]
        assert data["match_count"] == 3

    def test_glob_schema_extraction(self, router):
        """Test glob extraction with mocked LLM."""
        mock_response = json.dumps({
            "by_directory": {"lib": ["foo.py", "bar.py"], "tests": ["test_foo.py"]},
            "total": 3
        })
        router._llm_call = MagicMock(return_value=mock_response)

        response = {
            "result": {
                "content": [{"type": "text", "text": '{"files": ["lib/foo.py", "lib/bar.py", "tests/test_foo.py"]}'}]
            }
        }
        result = router._extract_summary("glob", response)
        data = json.loads(result)

        assert "by_directory" in data
        assert data["total"] == 3

    def test_bash_schema_extraction(self, router):
        """Test bash extraction with mocked LLM."""
        mock_response = json.dumps({
            "exit_code": 0,
            "line_count": 5,
            "preview": "line1\nline2\nline3\nline4\nline5",
            "error": None
        })
        router._llm_call = MagicMock(return_value=mock_response)

        response = {
            "result": {
                "content": [{"type": "text", "text": "line1\nline2\nline3\nline4\nline5"}]
            }
        }
        result = router._extract_summary("bash", response)
        data = json.loads(result)

        assert data["exit_code"] == 0
        assert data["line_count"] == 5

    def test_fallback_on_invalid_llm_response(self, router):
        """Falls back when LLM returns invalid JSON."""
        router._llm_call = MagicMock(return_value="not valid json {{{")

        response = {
            "result": {
                "content": [{"type": "text", "text": "some output"}]
            }
        }
        result = router._extract_summary("bash", response)
        # Should fall back but still return valid JSON
        data = json.loads(result)
        assert "line_count" in data or "preview" in data

    def test_fallback_on_empty_llm_response(self, router):
        """Falls back when LLM returns empty."""
        router._llm_call = MagicMock(return_value="")

        response = {
            "result": {
                "content": [{"type": "text", "text": "some output"}]
            }
        }
        result = router._extract_summary("bash", response)
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_error_response_handling(self, router):
        """Error responses return error JSON."""
        response = {"error": "Something went wrong"}
        result = router._extract_summary("any_tool", response)
        data = json.loads(result)
        assert "error" in data


class TestPromptConstruction:
    """Test that prompts are constructed correctly."""

    def test_prompt_includes_schema(self, router):
        """Prompt includes the tool's schema."""
        calls = []
        def capture_call(prompt):
            calls.append(prompt)
            return "{}"
        router._llm_call = capture_call

        response = {"result": {"content": [{"type": "text", "text": "test"}]}}
        router._extract_summary("grep", response)

        assert len(calls) == 1
        prompt = calls[0]
        assert "files" in prompt  # grep schema includes files
        assert "match_count" in prompt
        assert "JSON" in prompt

    def test_prompt_truncates_long_content(self, router):
        """Prompt truncates content to 2000 chars."""
        calls = []
        def capture_call(prompt):
            calls.append(prompt)
            return "{}"
        router._llm_call = capture_call

        # Use 'Q' to avoid conflicts with template text containing 'x' (exit, text, etc.)
        long_content = "Q" * 5000
        response = {"result": {"content": [{"type": "text", "text": long_content}]}}
        router._extract_summary("bash", response)

        prompt = calls[0]
        # Content in prompt should be truncated - allow small margin for edge cases
        assert prompt.count("Q") <= 2000


class TestIntegrationWithNativeTools:
    """Integration tests with actual native tools module."""

    def test_native_tools_use_router(self):
        """native_tools functions route through router."""
        from native_tools import _get_router  # noqa: E402

        router = _get_router()
        assert router is not None
        assert "native" in [s["name"] for s in router.list_servers()]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
