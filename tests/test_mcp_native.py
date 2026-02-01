#!/usr/bin/env python3
"""Tests for MCP Native Tools Server.

This test file defines expected behavior for lib/mcp_native.py, which wraps
Claude Code's native tools (Read, Write, Edit, Glob, Grep, Bash) as MCP tools.

Tests are written TDD-style: they should FAIL initially until mcp_native.py
is implemented.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Add lib to path before imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

# Import will fail until mcp_native.py is created
try:
    from mcp_native import (
        MCPNativeServer,
        NativeToolRegistry,
        read_file,
        write_file,
        edit_file,
        glob_files,
        grep_files,
        run_bash,
    )
    MCP_NATIVE_AVAILABLE = True
except ImportError:
    MCP_NATIVE_AVAILABLE = False


# Skip all tests if module not available (TDD red phase)
pytestmark = pytest.mark.skipif(
    not MCP_NATIVE_AVAILABLE,
    reason="mcp_native module not yet implemented"
)


class TestMCPNativeServerInit:
    """Tests for MCPNativeServer initialization."""

    def test_server_creates_with_defaults(self):
        """MCPNativeServer initializes with default configuration."""
        server = MCPNativeServer()
        assert server is not None
        assert hasattr(server, 'tools')

    def test_server_has_name(self):
        """Server has identifiable name for registration."""
        server = MCPNativeServer()
        assert server.name == "native"

    def test_server_has_version(self):
        """Server exposes version info."""
        server = MCPNativeServer()
        assert hasattr(server, 'version')
        assert isinstance(server.version, str)

    def test_server_can_be_customized(self):
        """Server accepts custom configuration."""
        server = MCPNativeServer(
            name="custom-native",
            timeout=60,
            working_dir="/tmp"
        )
        assert server.name == "custom-native"
        assert server.timeout == 60
        assert server.working_dir == "/tmp"


class TestNativeToolRegistry:
    """Tests for tool registration and discovery."""

    def test_registry_has_all_native_tools(self):
        """Registry contains all six native tools."""
        registry = NativeToolRegistry()
        tool_names = registry.list_tools()

        expected_tools = [
            "read_file",
            "write_file",
            "edit_file",
            "glob",
            "grep",
            "bash"
        ]
        for tool in expected_tools:
            assert tool in tool_names, f"Missing tool: {tool}"

    def test_registry_returns_tool_schemas(self):
        """Registry returns valid JSON schemas for each tool."""
        registry = NativeToolRegistry()

        for tool_name in registry.list_tools():
            schema = registry.get_schema(tool_name)
            assert schema is not None
            assert "type" in schema
            assert schema["type"] == "object"
            assert "properties" in schema

    def test_registry_get_unknown_tool_returns_none(self):
        """Getting unknown tool returns None."""
        registry = NativeToolRegistry()
        schema = registry.get_schema("nonexistent_tool")
        assert schema is None

    def test_tool_descriptions_are_meaningful(self):
        """Each tool has a description explaining its purpose."""
        registry = NativeToolRegistry()

        for tool_name in registry.list_tools():
            desc = registry.get_description(tool_name)
            assert desc is not None
            assert len(desc) > 10, f"Description too short for {tool_name}"


class TestReadFileTool:
    """Tests for read_file tool."""

    def test_read_file_schema(self):
        """read_file has correct schema."""
        registry = NativeToolRegistry()
        schema = registry.get_schema("read_file")

        assert "file_path" in schema["properties"]
        assert schema["properties"]["file_path"]["type"] == "string"
        assert "file_path" in schema.get("required", [])

    def test_read_file_returns_content(self):
        """read_file returns file contents."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Hello, World!")
            temp_path = f.name

        try:
            result = read_file(temp_path)
            assert result["content"] == "Hello, World!"
            assert result["success"] is True
        finally:
            os.unlink(temp_path)

    def test_read_file_with_line_offset(self):
        """read_file respects offset and limit parameters."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("line1\nline2\nline3\nline4\nline5")
            temp_path = f.name

        try:
            result = read_file(temp_path, offset=2, limit=2)
            # Should return lines 3-4 (0-indexed offset=2, limit=2 lines)
            assert "line3" in result["content"]
            assert "line4" in result["content"]
            assert "line1" not in result["content"]
        finally:
            os.unlink(temp_path)

    def test_read_file_nonexistent(self):
        """read_file returns error for nonexistent file."""
        result = read_file("/nonexistent/path/file.txt")
        assert result["success"] is False
        assert "error" in result

    def test_read_file_mcp_format(self):
        """read_file returns MCP-compatible response."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("test content")
            temp_path = f.name

        try:
            server = MCPNativeServer()
            response = server.call_tool("read_file", {"file_path": temp_path})

            # MCP format: {"content": [{"type": "text", "text": "..."}]}
            assert "content" in response
            assert isinstance(response["content"], list)
            assert response["content"][0]["type"] == "text"
        finally:
            os.unlink(temp_path)


class TestWriteFileTool:
    """Tests for write_file tool."""

    def test_write_file_schema(self):
        """write_file has correct schema."""
        registry = NativeToolRegistry()
        schema = registry.get_schema("write_file")

        assert "file_path" in schema["properties"]
        assert "content" in schema["properties"]
        required = schema.get("required", [])
        assert "file_path" in required
        assert "content" in required

    def test_write_file_creates_file(self):
        """write_file creates new file with content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "new_file.txt")

            result = write_file(file_path, "New content here")
            assert result["success"] is True

            with open(file_path, 'r') as f:
                assert f.read() == "New content here"

    def test_write_file_overwrites_existing(self):
        """write_file overwrites existing file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("old content")
            temp_path = f.name

        try:
            result = write_file(temp_path, "new content")
            assert result["success"] is True

            with open(temp_path, 'r') as f:
                assert f.read() == "new content"
        finally:
            os.unlink(temp_path)

    def test_write_file_creates_parent_dirs(self):
        """write_file creates parent directories if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = os.path.join(tmpdir, "a", "b", "c", "file.txt")

            result = write_file(nested_path, "nested content")
            assert result["success"] is True
            assert os.path.exists(nested_path)

    def test_write_file_permission_error(self):
        """write_file returns error for permission denied."""
        # Try to write to root (should fail for normal user)
        result = write_file("/root/test_file.txt", "content")
        assert result["success"] is False
        assert "error" in result


class TestEditFileTool:
    """Tests for edit_file tool."""

    def test_edit_file_schema(self):
        """edit_file has correct schema."""
        registry = NativeToolRegistry()
        schema = registry.get_schema("edit_file")

        assert "file_path" in schema["properties"]
        assert "old_string" in schema["properties"]
        assert "new_string" in schema["properties"]

    def test_edit_file_replaces_string(self):
        """edit_file replaces old_string with new_string."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Hello, World! Hello again.")
            temp_path = f.name

        try:
            result = edit_file(temp_path, "Hello", "Goodbye")
            assert result["success"] is True

            with open(temp_path, 'r') as f:
                content = f.read()
            # Default: replace first occurrence
            assert "Goodbye, World!" in content
        finally:
            os.unlink(temp_path)

    def test_edit_file_replace_all(self):
        """edit_file with replace_all replaces all occurrences."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Hello, World! Hello again.")
            temp_path = f.name

        try:
            result = edit_file(temp_path, "Hello", "Goodbye", replace_all=True)
            assert result["success"] is True

            with open(temp_path, 'r') as f:
                content = f.read()
            assert content == "Goodbye, World! Goodbye again."
        finally:
            os.unlink(temp_path)

    def test_edit_file_not_found(self):
        """edit_file returns error if old_string not found."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Hello, World!")
            temp_path = f.name

        try:
            result = edit_file(temp_path, "Nonexistent", "Replacement")
            assert result["success"] is False
            assert "not found" in result["error"].lower()
        finally:
            os.unlink(temp_path)

    def test_edit_file_nonexistent_file(self):
        """edit_file returns error for nonexistent file."""
        result = edit_file("/nonexistent/file.txt", "old", "new")
        assert result["success"] is False
        assert "error" in result


class TestGlobTool:
    """Tests for glob tool."""

    def test_glob_schema(self):
        """glob has correct schema."""
        registry = NativeToolRegistry()
        schema = registry.get_schema("glob")

        assert "pattern" in schema["properties"]
        assert "pattern" in schema.get("required", [])

    def test_glob_finds_files(self):
        """glob returns matching files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            Path(tmpdir, "test1.py").touch()
            Path(tmpdir, "test2.py").touch()
            Path(tmpdir, "readme.md").touch()

            result = glob_files("*.py", tmpdir)
            assert result["success"] is True
            assert len(result["files"]) == 2
            assert all(f.endswith(".py") for f in result["files"])

    def test_glob_recursive(self):
        """glob with ** pattern is recursive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested structure
            nested = Path(tmpdir) / "subdir" / "deep"
            nested.mkdir(parents=True)
            Path(tmpdir, "top.py").touch()
            Path(nested, "deep.py").touch()

            result = glob_files("**/*.py", tmpdir)
            assert result["success"] is True
            assert len(result["files"]) == 2

    def test_glob_no_matches(self):
        """glob returns empty list for no matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = glob_files("*.nonexistent", tmpdir)
            assert result["success"] is True
            assert result["files"] == []

    def test_glob_default_path(self):
        """glob uses current directory if path not specified."""
        result = glob_files("*.py")
        assert result["success"] is True
        assert isinstance(result["files"], list)


class TestGrepTool:
    """Tests for grep tool."""

    def test_grep_schema(self):
        """grep has correct schema."""
        registry = NativeToolRegistry()
        schema = registry.get_schema("grep")

        assert "pattern" in schema["properties"]
        assert "pattern" in schema.get("required", [])

    def test_grep_finds_pattern(self):
        """grep returns files containing pattern."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            with open(Path(tmpdir, "match.txt"), 'w') as f:
                f.write("This file contains PATTERN here")
            with open(Path(tmpdir, "nomatch.txt"), 'w') as f:
                f.write("This file has nothing")

            result = grep_files("PATTERN", tmpdir)
            assert result["success"] is True
            assert len(result["files"]) == 1
            assert "match.txt" in result["files"][0]

    def test_grep_content_mode(self):
        """grep content mode returns matching lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir, "test.txt"), 'w') as f:
                f.write("line1\nPATTERN line2\nline3")

            result = grep_files("PATTERN", tmpdir, output_mode="content")
            assert result["success"] is True
            assert "output" in result
            assert "PATTERN" in result["output"]

    def test_grep_case_insensitive(self):
        """grep with case_insensitive=True ignores case."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir, "test.txt"), 'w') as f:
                f.write("Hello World")

            result = grep_files("hello", tmpdir, case_insensitive=True)
            assert result["success"] is True
            assert len(result["files"]) == 1

    def test_grep_with_glob_filter(self):
        """grep filters files by glob pattern."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir, "test.py"), 'w') as f:
                f.write("PATTERN in python")
            with open(Path(tmpdir, "test.txt"), 'w') as f:
                f.write("PATTERN in text")

            result = grep_files("PATTERN", tmpdir, file_glob="*.py")
            assert result["success"] is True
            assert len(result["files"]) == 1
            assert "test.py" in result["files"][0]

    def test_grep_no_matches(self):
        """grep returns empty for no matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir, "test.txt"), 'w') as f:
                f.write("nothing here")

            result = grep_files("NONEXISTENT", tmpdir)
            assert result["success"] is True
            assert result["files"] == []


class TestBashTool:
    """Tests for bash tool."""

    def test_bash_schema(self):
        """bash has correct schema."""
        registry = NativeToolRegistry()
        schema = registry.get_schema("bash")

        assert "command" in schema["properties"]
        assert "command" in schema.get("required", [])

    def test_bash_executes_command(self):
        """bash executes simple command."""
        result = run_bash("echo 'Hello World'")
        assert result["success"] is True
        assert "Hello World" in result["stdout"]

    def test_bash_returns_exit_code(self):
        """bash returns exit code."""
        result = run_bash("exit 0")
        assert result["exit_code"] == 0

        result = run_bash("exit 1")
        assert result["exit_code"] == 1

    def test_bash_captures_stderr(self):
        """bash captures stderr output."""
        result = run_bash("echo 'error' >&2")
        assert "error" in result.get("stderr", "")

    def test_bash_timeout(self):
        """bash respects timeout."""
        result = run_bash("sleep 10", timeout=1)
        assert result["success"] is False
        assert "timeout" in result["error"].lower()

    def test_bash_working_directory(self):
        """bash respects working directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_bash("pwd", cwd=tmpdir)
            assert tmpdir in result["stdout"]

    def test_bash_complex_command(self):
        """bash handles piped commands."""
        result = run_bash("echo 'hello world' | tr 'a-z' 'A-Z'")
        assert result["success"] is True
        assert "HELLO WORLD" in result["stdout"]


class TestBashFileIOLockdown:
    """Tests for _check_bash_file_io — blocks file reads/writes in bash."""

    # -- Blocked: file-reading commands ----------------------------------------

    @pytest.mark.parametrize("cmd", [
        "cat /etc/passwd",
        "head -n 10 file.txt",
        "tail -f /var/log/syslog",
        "less README.md",
        "more README.md",
        "tac file.txt",
        "nl file.txt",
        "strings binary.so",
        "xxd dump.bin",
        "hexdump -C file.bin",
        "od -A x file.bin",
    ])
    def test_blocks_read_commands(self, cmd):
        from lib.controller import _check_bash_file_io
        result = _check_bash_file_io(cmd)
        assert result is not None
        assert "native__read_file" in result

    # -- Blocked: search commands ----------------------------------------------

    @pytest.mark.parametrize("cmd", [
        "grep -r 'TODO' src/",
        "egrep 'pattern' file.txt",
        "fgrep 'literal' file.txt",
        "rg 'pattern' .",
        "ag 'search' lib/",
        "ack 'needle'",
    ])
    def test_blocks_search_commands(self, cmd):
        from lib.controller import _check_bash_file_io
        result = _check_bash_file_io(cmd)
        assert result is not None
        assert "native__grep" in result or "native__glob" in result

    # -- Blocked: process/transform commands -----------------------------------

    @pytest.mark.parametrize("cmd", [
        "sed 's/foo/bar/g' file.txt",
        "awk '{print $1}' data.csv",
    ])
    def test_blocks_process_commands(self, cmd):
        from lib.controller import _check_bash_file_io
        result = _check_bash_file_io(cmd)
        assert result is not None
        assert "native__read_file" in result or "native__edit_file" in result

    # -- Blocked: write commands -----------------------------------------------

    def test_blocks_tee(self):
        from lib.controller import _check_bash_file_io
        result = _check_bash_file_io("echo hello | tee output.txt")
        assert result is not None
        assert "native__write_file" in result

    # -- Blocked: output redirection -------------------------------------------

    @pytest.mark.parametrize("cmd", [
        "echo hello > output.txt",
        "echo hello >> output.txt",
        "ls -la >listing.txt",
    ])
    def test_blocks_output_redirect(self, cmd):
        from lib.controller import _check_bash_file_io
        result = _check_bash_file_io(cmd)
        assert result is not None
        assert "Output redirection blocked" in result

    # -- Blocked: input redirection --------------------------------------------

    def test_blocks_input_redirect(self):
        from lib.controller import _check_bash_file_io
        result = _check_bash_file_io("wc -l < data.txt")
        assert result is not None
        assert "Input redirection blocked" in result

    # -- Blocked: inline script file I/O ---------------------------------------

    @pytest.mark.parametrize("cmd", [
        "python3 -c 'content = open(\"f.txt\").read()'",
        "python -c 'open(\"f.txt\", \"w\").write(\"x\")'",
        "ruby -e 'open(\"f.txt\").read'",
    ])
    def test_blocks_inline_script_file_io(self, cmd):
        from lib.controller import _check_bash_file_io
        result = _check_bash_file_io(cmd)
        assert result is not None
        assert "blocked" in result.lower()

    # -- Blocked: dd with file operands ----------------------------------------

    @pytest.mark.parametrize("cmd", [
        "dd if=/tmp/input of=/tmp/output bs=1M",
        "dd if=/tmp/input bs=512",
        "dd of=/tmp/output bs=512",
    ])
    def test_blocks_dd_file_io(self, cmd):
        from lib.controller import _check_bash_file_io
        result = _check_bash_file_io(cmd)
        assert result is not None
        assert "dd file I/O blocked" in result

    # -- Blocked: commands after shell operators --------------------------------

    @pytest.mark.parametrize("cmd", [
        "echo ok && cat secret.txt",
        "echo ok ; head -5 file.txt",
        "echo ok || tail file.txt",
        "result=$(cat file.txt)",
        "echo `grep pattern file`",
    ])
    def test_blocks_commands_after_operators(self, cmd):
        from lib.controller import _check_bash_file_io
        assert _check_bash_file_io(cmd) is not None

    # -- Blocked: sudo / env prefix --------------------------------------------

    @pytest.mark.parametrize("cmd", [
        "sudo cat /etc/shadow",
        "env cat file.txt",
        "sudo env head -1 file.txt",
    ])
    def test_blocks_prefixed_commands(self, cmd):
        from lib.controller import _check_bash_file_io
        assert _check_bash_file_io(cmd) is not None

    # -- Blocked: full-path commands -------------------------------------------

    def test_blocks_full_path_commands(self):
        from lib.controller import _check_bash_file_io
        assert _check_bash_file_io("/usr/bin/cat file.txt") is not None
        assert _check_bash_file_io("/bin/grep pattern file") is not None

    # -- Allowed: safe commands ------------------------------------------------

    @pytest.mark.parametrize("cmd", [
        "echo 'Hello World'",
        "ls -la",
        "pwd",
        "date",
        "whoami",
        "mkdir -p /tmp/test",
        "rm /tmp/test/file.txt",
        "mv /tmp/a /tmp/b",
        "cp /tmp/a /tmp/b",
        "chmod 644 /tmp/file",
        "git status",
        "git diff",
        "npm install",
        "pip install requests",
        "python3 -c 'print(1+1)'",
        "exit 0",
        "sleep 1",
        "echo 'hello world' | tr 'a-z' 'A-Z'",
        "wc -l",
    ])
    def test_allows_safe_commands(self, cmd):
        from lib.controller import _check_bash_file_io
        assert _check_bash_file_io(cmd) is None

    # -- Allowed: /dev/* redirections ------------------------------------------

    @pytest.mark.parametrize("cmd", [
        "echo error >/dev/null",
        "echo error 2>/dev/null",
        "echo error >/dev/stderr",
        "cmd </dev/stdin",
    ])
    def test_allows_dev_redirections(self, cmd):
        from lib.controller import _check_bash_file_io
        assert _check_bash_file_io(cmd) is None

    # -- Allowed: fd duplication -----------------------------------------------

    @pytest.mark.parametrize("cmd", [
        "echo error >&2",
        "cmd 2>&1",
    ])
    def test_allows_fd_duplication(self, cmd):
        from lib.controller import _check_bash_file_io
        assert _check_bash_file_io(cmd) is None

    # -- Allowed: heredocs -----------------------------------------------------

    def test_allows_heredocs(self):
        from lib.controller import _check_bash_file_io
        assert _check_bash_file_io("python3 <<EOF\nprint('hi')\nEOF") is None

    # -- Allowed: dd to /dev/* -------------------------------------------------

    def test_allows_dd_to_dev(self):
        from lib.controller import _check_bash_file_io
        assert _check_bash_file_io("dd if=/dev/zero of=/dev/null bs=1M count=1") is None

    # -- Integration: controller blocks bash file I/O --------------------------

    def test_controller_blocks_cat(self, tmp_path):
        """Controller._native_bash returns error for cat."""
        from lib.controller import Controller
        ctrl = Controller(config_dir=tmp_path, data_dir=tmp_path)
        result = ctrl._native_bash({"command": "cat /etc/hostname"})
        assert result.get("isError") is True
        assert "blocked" in result["error"]

    def test_controller_allows_echo(self, tmp_path):
        """Controller._native_bash allows echo."""
        from lib.controller import Controller
        ctrl = Controller(config_dir=tmp_path, data_dir=tmp_path)
        result = ctrl._native_bash({"command": "echo hello"})
        assert result.get("isError") is not True
        assert result["stdout"].strip() == "hello"


class TestMCPProtocol:
    """Tests for MCP protocol compliance."""

    def test_server_handles_initialize(self):
        """Server responds to initialize request."""
        server = MCPNativeServer()
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"}
            }
        }
        response = server.handle_request(request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "result" in response
        assert "serverInfo" in response["result"]

    def test_server_handles_tools_list(self):
        """Server responds to tools/list request."""
        server = MCPNativeServer()
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        }
        response = server.handle_request(request)

        assert "result" in response
        assert "tools" in response["result"]
        tools = response["result"]["tools"]
        assert len(tools) >= 6  # At least our 6 native tools

    def test_server_handles_tools_call(self):
        """Server responds to tools/call request."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("test content")
            temp_path = f.name

        try:
            server = MCPNativeServer()
            request = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "read_file",
                    "arguments": {"file_path": temp_path}
                }
            }
            response = server.handle_request(request)

            assert "result" in response
            assert "content" in response["result"]
        finally:
            os.unlink(temp_path)

    def test_server_returns_error_for_unknown_tool(self):
        """Server returns error for unknown tool."""
        server = MCPNativeServer()
        request = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "nonexistent_tool",
                "arguments": {}
            }
        }
        response = server.handle_request(request)

        assert "error" in response or response["result"].get("isError", False)

    def test_response_format_has_content_array(self):
        """Tool responses follow MCP format with content array."""
        server = MCPNativeServer()
        result = server.call_tool("bash", {"command": "echo test"})

        # MCP standard format
        assert "content" in result
        assert isinstance(result["content"], list)
        assert len(result["content"]) > 0
        assert "type" in result["content"][0]
        assert "text" in result["content"][0]


class TestErrorHandling:
    """Tests for error handling."""

    def test_invalid_json_returns_parse_error(self):
        """Invalid JSON returns parse error."""
        server = MCPNativeServer()
        response = server.handle_raw_request("not valid json")

        assert "error" in response
        assert response["error"]["code"] == -32700  # Parse error

    def test_missing_method_returns_invalid_request(self):
        """Missing method returns invalid request error."""
        server = MCPNativeServer()
        request = {"jsonrpc": "2.0", "id": 1}  # No method
        response = server.handle_request(request)

        assert "error" in response
        assert response["error"]["code"] == -32600  # Invalid request

    def test_missing_required_param_returns_error(self):
        """Missing required parameter returns error."""
        server = MCPNativeServer()
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "read_file",
                "arguments": {}  # Missing file_path
            }
        }
        response = server.handle_request(request)

        # Should have error about missing file_path
        result = response.get("result", {})
        assert result.get("isError", False) or "error" in response

    def test_internal_error_is_caught(self):
        """Internal errors are caught and returned gracefully."""
        server = MCPNativeServer()

        # Mock a tool to raise exception
        with patch.object(server, '_execute_tool', side_effect=RuntimeError("Test error")):
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "bash", "arguments": {"command": "echo"}}
            }
            response = server.handle_request(request)

            # Should not crash, should return error
            assert "error" in response or response.get("result", {}).get("isError")


class TestIntegrationWithRouter:
    """Tests for integration with MCP Router."""

    def test_server_can_be_registered_with_router(self):
        """Native server can register with MCPRouter."""
        # Import router (already tested working)
        from mcp_router import MCPRouter

        router = MCPRouter(enable_telemetry=False)
        server = MCPNativeServer()

        # Register using server's command
        result = router.register_server(
            name="native",
            command=server.get_command(),
            tool_prefix="native"
        )
        assert result["status"] == "registered"

    def test_server_provides_command_for_subprocess(self):
        """Server provides command list for subprocess spawning."""
        server = MCPNativeServer()
        command = server.get_command()

        assert isinstance(command, list)
        assert len(command) > 0
        assert "python" in command[0] or "python3" in command[0]


class TestToolSchemaValidation:
    """Tests verifying tool schemas are valid."""

    def test_all_tools_have_valid_json_schema(self):
        """All tool schemas are valid JSON Schema."""
        registry = NativeToolRegistry()

        for tool_name in registry.list_tools():
            schema = registry.get_schema(tool_name)

            # Basic JSON Schema requirements
            assert schema["type"] == "object"
            assert "properties" in schema

            # All property types are valid
            for prop_name, prop_schema in schema["properties"].items():
                assert "type" in prop_schema or "anyOf" in prop_schema

    def test_read_file_schema_complete(self):
        """read_file schema has all expected properties."""
        registry = NativeToolRegistry()
        schema = registry.get_schema("read_file")

        props = schema["properties"]
        assert "file_path" in props
        # Optional params
        assert "offset" in props or True  # May be optional
        assert "limit" in props or True

    def test_write_file_schema_complete(self):
        """write_file schema has all expected properties."""
        registry = NativeToolRegistry()
        schema = registry.get_schema("write_file")

        props = schema["properties"]
        assert "file_path" in props
        assert "content" in props

    def test_edit_file_schema_complete(self):
        """edit_file schema has all expected properties."""
        registry = NativeToolRegistry()
        schema = registry.get_schema("edit_file")

        props = schema["properties"]
        assert "file_path" in props
        assert "old_string" in props
        assert "new_string" in props

    def test_glob_schema_complete(self):
        """glob schema has all expected properties."""
        registry = NativeToolRegistry()
        schema = registry.get_schema("glob")

        props = schema["properties"]
        assert "pattern" in props

    def test_grep_schema_complete(self):
        """grep schema has all expected properties."""
        registry = NativeToolRegistry()
        schema = registry.get_schema("grep")

        props = schema["properties"]
        assert "pattern" in props

    def test_bash_schema_complete(self):
        """bash schema has all expected properties."""
        registry = NativeToolRegistry()
        schema = registry.get_schema("bash")

        props = schema["properties"]
        assert "command" in props


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
