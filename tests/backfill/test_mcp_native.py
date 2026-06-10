"""
Characterization tests for lib/mcp_native.py.

These tests pin the CURRENT behavior of the module.  They were written
after the module existed and are expected to PASS on first run.  If a
behavior looks surprising, a "# NOTE: possible bug" comment is left but
the test still pins what the code actually does today.
"""

from pathlib import Path


from lib.mcp_native import (
    read_file,
    write_file,
    edit_file,
    glob_files,
    grep_files,
    run_bash,
    NativeToolRegistry,
    MCPNativeServer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tree(tmp_path: Path) -> dict:
    """Create a small file tree used by glob/grep tests.

    Returns a dict mapping logical names to absolute Path objects.
    """
    (tmp_path / "sub").mkdir()
    a = tmp_path / "alpha.py"
    b = tmp_path / "beta.txt"
    c = tmp_path / "sub" / "gamma.py"

    a.write_text("# alpha module\nHELLO = 'world'\n", encoding="utf-8")
    b.write_text("just some text\nno code here\n", encoding="utf-8")
    c.write_text("# gamma module\nHELLO = 'universe'\n", encoding="utf-8")

    return {"alpha": a, "beta": b, "gamma": c}


# ===========================================================================
# read_file
# ===========================================================================

class TestReadFile:

    def test_full_read(self, tmp_path):
        f = tmp_path / "sample.txt"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")

        result = read_file(str(f))

        assert result["success"] is True
        assert result["content"] == "line1\nline2\nline3\n"

    def test_offset_and_limit_window(self, tmp_path):
        f = tmp_path / "multiline.txt"
        f.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")

        # offset=1, limit=2 → lines b and c
        result = read_file(str(f), offset=1, limit=2)

        assert result["success"] is True
        assert result["content"] == "b\nc\n"

    def test_offset_only(self, tmp_path):
        f = tmp_path / "multiline.txt"
        f.write_text("a\nb\nc\n", encoding="utf-8")

        result = read_file(str(f), offset=1)

        assert result["success"] is True
        assert result["content"] == "b\nc\n"

    def test_limit_only(self, tmp_path):
        f = tmp_path / "multiline.txt"
        f.write_text("a\nb\nc\n", encoding="utf-8")

        result = read_file(str(f), limit=2)

        assert result["success"] is True
        assert result["content"] == "a\nb\n"

    def test_missing_file_returns_error(self, tmp_path):
        missing = str(tmp_path / "does_not_exist.txt")
        result = read_file(missing)

        # Current behavior: success=False with an error string
        assert result["success"] is False
        assert "error" in result
        assert missing in result["error"] or "not found" in result["error"].lower()


# ===========================================================================
# write_file
# ===========================================================================

class TestWriteFile:

    def test_creates_file(self, tmp_path):
        f = tmp_path / "new.txt"
        result = write_file(str(f), "hello\n")

        assert result["success"] is True
        assert f.read_text(encoding="utf-8") == "hello\n"

    def test_creates_parent_dirs(self, tmp_path):
        f = tmp_path / "deep" / "nested" / "file.txt"
        result = write_file(str(f), "deep content")

        assert result["success"] is True
        assert f.exists()
        assert f.read_text(encoding="utf-8") == "deep content"

    def test_overwrites_existing_file(self, tmp_path):
        f = tmp_path / "existing.txt"
        f.write_text("old content", encoding="utf-8")

        result = write_file(str(f), "new content")

        assert result["success"] is True
        assert f.read_text(encoding="utf-8") == "new content"


# ===========================================================================
# edit_file
# ===========================================================================

class TestEditFile:

    def test_single_occurrence_replaced(self, tmp_path):
        f = tmp_path / "edit_me.txt"
        f.write_text("foo bar foo", encoding="utf-8")

        result = edit_file(str(f), "foo", "baz")

        assert result["success"] is True
        # replace_all defaults to False → only first occurrence
        assert f.read_text(encoding="utf-8") == "baz bar foo"

    def test_replace_all(self, tmp_path):
        f = tmp_path / "edit_me.txt"
        f.write_text("foo bar foo baz foo", encoding="utf-8")

        result = edit_file(str(f), "foo", "qux", replace_all=True)

        assert result["success"] is True
        assert f.read_text(encoding="utf-8") == "qux bar qux baz qux"

    def test_old_string_not_found_returns_error(self, tmp_path):
        f = tmp_path / "no_match.txt"
        f.write_text("nothing to see here", encoding="utf-8")

        result = edit_file(str(f), "NONEXISTENT", "replacement")

        # Current behavior: success=False with error message
        assert result["success"] is False
        assert "error" in result

    def test_missing_file_returns_error(self, tmp_path):
        missing = str(tmp_path / "ghost.txt")
        result = edit_file(missing, "x", "y")

        assert result["success"] is False
        assert "error" in result


# ===========================================================================
# glob_files
# ===========================================================================

class TestGlobFiles:

    def test_simple_pattern(self, tmp_path):
        _make_tree(tmp_path)

        result = glob_files("*.py", path=str(tmp_path))

        assert result["success"] is True
        names = {Path(p).name for p in result["files"]}
        assert "alpha.py" in names
        # beta.txt is not a .py file
        assert "beta.txt" not in names

    def test_recursive_pattern(self, tmp_path):
        _make_tree(tmp_path)

        result = glob_files("**/*.py", path=str(tmp_path))

        assert result["success"] is True
        names = {Path(p).name for p in result["files"]}
        assert "alpha.py" in names
        assert "gamma.py" in names

    def test_no_matches_returns_empty_list(self, tmp_path):
        _make_tree(tmp_path)

        result = glob_files("*.rb", path=str(tmp_path))

        assert result["success"] is True
        assert result["files"] == []


# ===========================================================================
# grep_files
# ===========================================================================

class TestGrepFiles:

    def test_files_mode(self, tmp_path):
        _make_tree(tmp_path)

        result = grep_files("HELLO", path=str(tmp_path), output_mode="files")

        assert result["success"] is True
        names = {Path(p).name for p in result["files"]}
        assert "alpha.py" in names
        assert "gamma.py" in names
        # beta.txt does not contain HELLO
        assert "beta.txt" not in names

    def test_content_mode(self, tmp_path):
        _make_tree(tmp_path)

        result = grep_files("HELLO", path=str(tmp_path), output_mode="content")

        assert result["success"] is True
        assert "output" in result
        assert "HELLO" in result["output"]

    def test_case_insensitive(self, tmp_path):
        _make_tree(tmp_path)

        # Pattern in lowercase, actual content is uppercase HELLO
        result = grep_files("hello", path=str(tmp_path), case_insensitive=True)

        assert result["success"] is True
        assert len(result["files"]) >= 1

    def test_case_sensitive_misses(self, tmp_path):
        _make_tree(tmp_path)

        # With case sensitivity on, lowercase "hello" should not match "HELLO"
        result = grep_files("hello", path=str(tmp_path), case_insensitive=False)

        assert result["success"] is True
        # alpha.py and gamma.py contain HELLO (uppercase), not hello
        names = {Path(p).name for p in result["files"]}
        assert "alpha.py" not in names

    def test_file_glob_filter(self, tmp_path):
        _make_tree(tmp_path)

        # Only search .py files; beta.txt would match "text" but we filter it out
        result = grep_files(
            "text",
            path=str(tmp_path),
            file_glob="*.txt",
            output_mode="files",
        )

        assert result["success"] is True
        names = {Path(p).name for p in result["files"]}
        assert "beta.txt" in names
        assert "alpha.py" not in names

    def test_no_match_returns_empty_files(self, tmp_path):
        _make_tree(tmp_path)

        result = grep_files("ZZZNOMATCH", path=str(tmp_path))

        assert result["success"] is True
        assert result["files"] == []


# ===========================================================================
# run_bash
# ===========================================================================

class TestRunBash:

    def test_simple_echo(self):
        result = run_bash("echo ok")

        assert result["success"] is True
        assert result["stdout"].strip() == "ok"
        assert result["exit_code"] == 0

    def test_nonzero_exit(self):
        result = run_bash("exit 42")

        assert result["success"] is False
        assert result["exit_code"] == 42

    def test_cwd_respected(self, tmp_path):
        result = run_bash("pwd", cwd=str(tmp_path))

        assert result["success"] is True
        # Resolve both to handle symlinks (e.g. /tmp on macOS)
        assert Path(result["stdout"].strip()).resolve() == tmp_path.resolve()

    def test_stderr_captured(self):
        result = run_bash("echo err >&2; exit 1")

        assert result["exit_code"] != 0
        assert "err" in result["stderr"]

    def test_stdout_and_stderr_keys_present(self):
        result = run_bash("echo hello")

        assert "stdout" in result
        assert "stderr" in result
        assert "exit_code" in result


# ===========================================================================
# NativeToolRegistry
# ===========================================================================

class TestNativeToolRegistry:

    EXPECTED_TOOLS = {"read_file", "write_file", "edit_file", "glob", "grep", "bash"}

    def test_list_tools_returns_expected_names(self):
        registry = NativeToolRegistry()
        tools = registry.list_tools()

        assert isinstance(tools, list)
        assert set(tools) == self.EXPECTED_TOOLS

    def test_list_tools_returns_copy(self):
        registry = NativeToolRegistry()
        tools = registry.list_tools()
        tools.append("INJECTED")

        # Internal list must be unaffected
        assert "INJECTED" not in registry.list_tools()

    def test_get_schema_known_tool(self):
        registry = NativeToolRegistry()
        schema = registry.get_schema("read_file")

        assert isinstance(schema, dict)
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "file_path" in schema["properties"]
        assert "required" in schema
        assert "file_path" in schema["required"]

    def test_get_schema_has_correct_shape_for_bash(self):
        registry = NativeToolRegistry()
        schema = registry.get_schema("bash")

        assert schema["type"] == "object"
        assert "command" in schema["properties"]
        assert "command" in schema["required"]

    def test_get_schema_unknown_tool_returns_none(self):
        registry = NativeToolRegistry()
        result = registry.get_schema("nonexistent_tool")

        assert result is None

    def test_get_description_known_tool(self):
        registry = NativeToolRegistry()
        desc = registry.get_description("write_file")

        assert isinstance(desc, str)
        assert len(desc) > 0

    def test_get_description_unknown_tool_returns_none(self):
        registry = NativeToolRegistry()
        result = registry.get_description("nonexistent_tool")

        assert result is None


# ===========================================================================
# MCPNativeServer — properties
# ===========================================================================

class TestMCPNativeServerProperties:

    def test_default_name(self):
        server = MCPNativeServer()
        assert server.name == "native"

    def test_custom_name(self):
        server = MCPNativeServer(name="my-server")
        assert server.name == "my-server"

    def test_version_is_string(self):
        server = MCPNativeServer()
        assert isinstance(server.version, str)
        assert len(server.version) > 0

    def test_default_timeout(self):
        server = MCPNativeServer()
        assert server.timeout == 120

    def test_custom_timeout(self):
        server = MCPNativeServer(timeout=30)
        assert server.timeout == 30

    def test_working_dir_default_none(self):
        server = MCPNativeServer()
        assert server.working_dir is None

    def test_tools_property_structure(self):
        server = MCPNativeServer()
        tools = server.tools

        assert isinstance(tools, list)
        assert len(tools) == 6  # read_file, write_file, edit_file, glob, grep, bash

        for t in tools:
            assert "name" in t
            assert "description" in t
            assert "inputSchema" in t


# ===========================================================================
# MCPNativeServer.handle_raw_request / handle_request
# ===========================================================================

class TestMCPNativeServerRequests:

    def test_invalid_json_returns_parse_error(self):
        server = MCPNativeServer()
        response = server.handle_raw_request("{not valid json")

        assert response["jsonrpc"] == "2.0"
        assert response["id"] is None
        assert "error" in response
        assert response["error"]["code"] == -32700

    def test_handle_initialize_request(self):
        server = MCPNativeServer()
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {}
        }
        response = server.handle_request(request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "result" in response
        result = response["result"]
        assert "protocolVersion" in result
        assert result["serverInfo"]["name"] == "native"

    def test_handle_tools_list_request(self):
        server = MCPNativeServer()
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        }
        response = server.handle_request(request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 2
        assert "result" in response
        assert "tools" in response["result"]
        tool_names = {t["name"] for t in response["result"]["tools"]}
        assert "read_file" in tool_names
        assert "bash" in tool_names

    def test_handle_unknown_method_returns_method_not_found(self):
        server = MCPNativeServer()
        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "nonexistent/method",
            "params": {}
        }
        response = server.handle_request(request)

        assert "error" in response
        assert response["error"]["code"] == -32601

    def test_handle_missing_method_returns_invalid_request(self):
        server = MCPNativeServer()
        request = {"jsonrpc": "2.0", "id": 4}  # no "method" key
        response = server.handle_request(request)

        assert "error" in response
        assert response["error"]["code"] == -32600

    def test_handle_tools_call_read_file(self, tmp_path):
        server = MCPNativeServer()
        f = tmp_path / "hello.txt"
        f.write_text("characterization test content\n", encoding="utf-8")

        request = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "read_file",
                "arguments": {"file_path": str(f)}
            }
        }
        response = server.handle_request(request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 5
        assert "result" in response
        result = response["result"]
        assert "content" in result
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == "text"
        assert "characterization test content" in result["content"][0]["text"]


# ===========================================================================
# MCPNativeServer.call_tool
# ===========================================================================

class TestMCPNativeServerCallTool:

    def test_call_tool_read_file_dispatches(self, tmp_path):
        server = MCPNativeServer()
        f = tmp_path / "dispatch.txt"
        f.write_text("dispatch test\n", encoding="utf-8")

        result = server.call_tool("read_file", {"file_path": str(f)})

        assert "content" in result
        assert result["content"][0]["type"] == "text"
        assert "dispatch test" in result["content"][0]["text"]
        assert "isError" not in result or result.get("isError") is False

    def test_call_tool_unknown_name_returns_error(self):
        server = MCPNativeServer()
        result = server.call_tool("totally_unknown", {})

        assert result.get("isError") is True
        assert "Unknown tool" in result["content"][0]["text"]

    def test_call_tool_write_then_read(self, tmp_path):
        server = MCPNativeServer()
        f = tmp_path / "roundtrip.txt"

        write_result = server.call_tool("write_file", {
            "file_path": str(f),
            "content": "round-trip content\n"
        })
        assert write_result.get("isError") is not True

        read_result = server.call_tool("read_file", {"file_path": str(f)})
        assert "round-trip content" in read_result["content"][0]["text"]
