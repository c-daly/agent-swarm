#!/usr/bin/env python3
"""Tests for the TCP server + MCP protocol."""

import json
import socket
import threading
import time

import pytest
import yaml

from lib.controller import Controller
from lib.router import Router


# --- Fixtures ---


_PERM_CONFIG = {
    "global": {
        "allowed": ["native__*", "router__*", "workflow__*"],
        "blocked": [],
        "superblocked": [],
    },
}


@pytest.fixture
def ctrl(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "permissions.yaml").write_text(yaml.dump(_PERM_CONFIG))
    (config_dir / "backends.json").write_text("{}")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return Controller(config_dir=config_dir, data_dir=data_dir)


@pytest.fixture
def router_port(ctrl):
    """Start a Router on a random port, yield the port, then shut down."""
    # Use port 0 to let OS assign a free port
    r = Router(port=0, controller=ctrl)
    r._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    r._server.bind(("127.0.0.1", 0))
    port = r._server.getsockname()[1]
    r._server.listen(32)
    r._server.settimeout(1.0)
    r._running = True

    t = threading.Thread(target=_serve_loop, args=(r,), daemon=True)
    t.start()

    yield port, r

    r.shutdown()
    t.join(timeout=3)


def _serve_loop(router: Router):
    """Serve loop that uses the already-bound socket."""
    while router._running:
        try:
            client, addr = router._server.accept()
        except socket.timeout:
            continue
        except OSError:
            break

        with router._connections_lock:
            if router._active_connections >= 64:
                client.close()
                continue
            router._active_connections += 1

        threading.Thread(
            target=router._handle_connection,
            args=(client,),
            daemon=True,
        ).start()


def _send_recv(port, request):
    """Send a JSON-RPC request and receive response."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect(("127.0.0.1", port))
    sock.sendall((json.dumps(request) + "\n").encode())
    data = b""
    while b"\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    sock.close()
    return json.loads(data.split(b"\n")[0]) if data else None


def _mcp_connect(port):
    """Full MCP handshake, return connected socket."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect(("127.0.0.1", port))

    # Initialize
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"},
        },
    }
    sock.sendall((json.dumps(init) + "\n").encode())
    resp_data = b""
    while b"\n" not in resp_data:
        resp_data += sock.recv(4096)

    # Notification
    notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    sock.sendall((json.dumps(notif) + "\n").encode())

    return sock


# --- Tests ---


class TestMCPHandshake:
    def test_initialize(self, router_port):
        port, _ = router_port
        resp = _send_recv(port, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        })
        assert resp["id"] == 1
        assert resp["result"]["protocolVersion"] == "2024-11-05"
        assert resp["result"]["serverInfo"]["name"] == "agent-swarm"


class TestToolsList:
    def test_lists_tools(self, router_port):
        port, _ = router_port
        sock = _mcp_connect(port)

        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        sock.sendall((json.dumps(req) + "\n").encode())
        data = b""
        while b"\n" not in data:
            data += sock.recv(4096)
        sock.close()

        resp = json.loads(data.split(b"\n")[0])
        tools = resp["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "native__read_file" in names
        assert "native__bash" in names
        assert "router__ping" in names
        assert "workflow__workflow_start" in names


class TestToolsCall:
    def test_ping(self, router_port):
        port, _ = router_port
        sock = _mcp_connect(port)

        req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "router__ping", "arguments": {}},
        }
        sock.sendall((json.dumps(req) + "\n").encode())
        data = b""
        while b"\n" not in data:
            data += sock.recv(4096)
        sock.close()

        resp = json.loads(data.split(b"\n")[0])
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["status"] == "ok"

    def test_read_file(self, router_port, tmp_path):
        port, _ = router_port
        f = tmp_path / "hello.txt"
        f.write_text("hello from router test")

        sock = _mcp_connect(port)
        req = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "native__read_file",
                "arguments": {"file_path": str(f)},
            },
        }
        sock.sendall((json.dumps(req) + "\n").encode())
        data = b""
        while b"\n" not in data:
            data += sock.recv(4096)
        sock.close()

        resp = json.loads(data.split(b"\n")[0])
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "hello from router test" in content["content"]


class TestErrorHandling:
    def test_parse_error(self, router_port):
        port, _ = router_port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(("127.0.0.1", port))
        sock.sendall(b"not json at all\n")
        data = b""
        while b"\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        sock.close()
        resp = json.loads(data.split(b"\n")[0])
        assert resp["error"]["code"] == -32700

    def test_method_not_found(self, router_port):
        port, _ = router_port
        resp = _send_recv(port, {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "nonexistent",
            "params": {},
        })
        assert resp["error"]["code"] == -32601

    def test_invalid_request(self, router_port):
        port, _ = router_port
        resp = _send_recv(port, {"jsonrpc": "1.0", "id": 6, "method": "ping"})
        assert resp["error"]["code"] == -32600


class TestKeepAlive:
    def test_multiple_requests_same_connection(self, router_port):
        port, _ = router_port
        sock = _mcp_connect(port)

        for i in range(3):
            req = {
                "jsonrpc": "2.0",
                "id": 10 + i,
                "method": "tools/call",
                "params": {"name": "router__ping", "arguments": {}},
            }
            sock.sendall((json.dumps(req) + "\n").encode())
            data = b""
            while b"\n" not in data:
                data += sock.recv(4096)
            resp = json.loads(data.split(b"\n")[0])
            assert resp["id"] == 10 + i

        sock.close()


class TestSummarizeAndRetrieve:
    """Tests for the summarization → get_full pipeline."""

    def test_summarization_pipeline(self, router_port, tmp_path):
        """Deterministic: large file triggers summarization, get_full returns full content."""
        port, router = router_port
        ctrl = router._controller
        ctrl._summarization_threshold = 200

        # Build a file with @ characters spread throughout
        lines = []
        for i in range(80):
            if i % 7 == 0:
                lines.append(f"config_{i}: value@domain.com  # entry {i}")
            else:
                lines.append(f"config_{i}: plain_value  # entry {i}")
        content = "\n".join(lines)
        expected_count = content.count("@")

        f = tmp_path / "large_config.txt"
        f.write_text(content)
        assert len(content) > 200

        # Read through the controller — should get summarized
        result = ctrl.handle_call("native__read_file", {"file_path": str(f)})

        assert isinstance(result, dict)
        assert result.get("full_available") is True
        assert "content_id" in result
        assert "summary" in result
        assert "instruction" in result

        content_id = result["content_id"]

        # The summary (truncation fallback) should lose some @ characters
        summary_at_count = str(result["summary"]).count("@")
        assert summary_at_count < expected_count, (
            f"Summary has {summary_at_count} @ but expected fewer than {expected_count}"
        )

        # get_full should return the complete original content
        full_result = ctrl.handle_call("router__get_full", {"content_id": content_id})

        full_text = str(full_result)
        assert full_text.count("@") >= expected_count, (
            f"Expected >= {expected_count} @ in full content, got {full_text.count('@')}"
        )

        # Telemetry should record both calls
        events = ctrl.data._conn.execute(
            "SELECT tool, was_summarized FROM events ORDER BY id"
        ).fetchall()
        tool_names = [e[0] for e in events]
        assert "native__read_file" in tool_names
        assert "router__get_full" in tool_names

    @pytest.mark.integration
    def test_agent_calls_get_full(self, router_port, tmp_path):
        """LLM agent autonomously calls get_full when summary can't answer the question.

        Routes every tool call through ctrl.handle_call() — the real pipeline.
        Requires OPENAI_API_KEY.
        """
        import os

        openai = pytest.importorskip("openai")

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            pytest.skip("OPENAI_API_KEY not set")

        port, router = router_port
        ctrl = router._controller
        ctrl._summarization_threshold = 200

        # File with @ characters spread throughout — impossible to count from truncation
        lines = []
        for i in range(80):
            if i % 7 == 0:
                lines.append(f"config_{i}: value@domain.com  # entry {i}")
            else:
                lines.append(f"config_{i}: plain_value  # entry {i}")
        content = "\n".join(lines)
        expected_count = content.count("@")

        f = tmp_path / "large_config.txt"
        f.write_text(content)

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "native__read_file",
                    "description": "Read the contents of a file at the given path.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Absolute path to the file",
                            }
                        },
                        "required": ["file_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "router__get_full",
                    "description": (
                        "Retrieve the full, unsummarized content of a previously "
                        "returned result using its content_id. Use this when a tool "
                        "response was summarized and you need the complete content."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content_id": {
                                "type": "string",
                                "description": "The content_id from a summarized response",
                            }
                        },
                        "required": ["content_id"],
                    },
                },
            },
        ]

        client = openai.OpenAI(api_key=api_key)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a precise assistant. Use the provided tools to answer "
                    "questions. When a tool response indicates content was summarized "
                    "(full_available=true), use router__get_full with the content_id "
                    "to retrieve the complete content before making calculations."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"How many '@' characters appear in the file {f}? "
                    "Return ONLY the integer count, nothing else."
                ),
            },
        ]

        get_full_called = False
        final_answer = None

        for _turn in range(6):
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
            msg = response.choices[0].message

            if msg.tool_calls:
                messages.append(msg)
                for tc in msg.tool_calls:
                    if tc.function.name == "router__get_full":
                        get_full_called = True

                    args = json.loads(tc.function.arguments)
                    result = ctrl.handle_call(tc.function.name, args)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, default=str),
                    })
            else:
                final_answer = msg.content
                break

        assert get_full_called, (
            "Agent did not call router__get_full — "
            "it should have recognized the summary was insufficient"
        )
        assert final_answer is not None, "Agent did not produce a final answer"
