"""Tests for dashboard HTTP server routing and API dispatch."""

import json
import threading
import time
import urllib.request
import urllib.error
from http.server import HTTPServer
from pathlib import Path

import pytest

# Add dashboard to path so imports work
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dashboard.server import DashboardHandler
from dashboard.providers.mock import MockProvider


@pytest.fixture(scope="module")
def server():
    """Start a test server on a random port with MockProvider."""
    provider = MockProvider()
    DashboardHandler.provider = provider
    DashboardHandler.jsonl_dir = "/tmp/nonexistent"
    DashboardHandler.static_dir = str(Path(__file__).parent.parent / "static")

    httpd = HTTPServer(("127.0.0.1", 0), DashboardHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


def get_json(base_url, path):
    """Helper to GET a JSON endpoint."""
    url = f"{base_url}{path}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def get_status(base_url, path):
    """Helper to GET and return status code."""
    url = f"{base_url}{path}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


# --- Health ---

class TestHealth:
    def test_health_returns_ok(self, server):
        data = get_json(server, "/api/health")
        assert data["status"] == "ok"
        assert "total_events" in data

    def test_health_has_event_count(self, server):
        data = get_json(server, "/api/health")
        assert data["total_events"] > 0


# --- Overview ---

class TestOverview:
    def test_overview_shape(self, server):
        data = get_json(server, "/api/overview")
        for key in ["total_events", "total_sessions", "total_input_tokens",
                     "total_output_tokens", "error_rate"]:
            assert key in data, f"Missing key: {key}"

    def test_overview_with_filters(self, server):
        data = get_json(server, "/api/overview?from=2026-01-20&to=2026-01-25")
        assert data["total_events"] > 0


# --- Tokens ---

class TestTokens:
    def test_tokens_by_day(self, server):
        data = get_json(server, "/api/tokens?group_by=day")
        assert data["group_by"] == "day"
        assert len(data["data"]) > 0
        assert "input" in data["data"][0]

    def test_tokens_by_tool(self, server):
        data = get_json(server, "/api/tokens?group_by=tool")
        assert data["group_by"] == "tool"
        assert len(data["data"]) > 0

    def test_tokens_by_agent(self, server):
        data = get_json(server, "/api/tokens?group_by=agent")
        assert data["group_by"] == "agent"


# --- Tools ---

class TestTools:
    def test_tools_default_sort(self, server):
        data = get_json(server, "/api/tools")
        assert "data" in data
        assert len(data["data"]) > 0
        assert "tool" in data["data"][0]
        assert "call_count" in data["data"][0]

    def test_tools_sort_by_errors(self, server):
        data = get_json(server, "/api/tools?sort=errors")
        assert data["sort"] == "errors"


# --- Concurrency ---

class TestConcurrency:
    def test_concurrency_needs_session(self, server):
        data = get_json(server, "/api/concurrency")
        # MockProvider handles empty session gracefully
        assert "events" in data or "error" in data

    def test_concurrency_with_session(self, server):
        # Get a valid session ID first
        sessions = get_json(server, "/api/sessions")
        sid = sessions["sessions"][0]["session_id"]
        data = get_json(server, f"/api/concurrency?session={sid}")
        assert "events" in data


# --- Summarization ---

class TestSummarization:
    def test_summarization_shape(self, server):
        data = get_json(server, "/api/summarization")
        for key in ["total_events", "summarized_count", "summarization_rate"]:
            assert key in data


# --- Sessions ---

class TestSessions:
    def test_sessions_paginated(self, server):
        data = get_json(server, "/api/sessions")
        assert "sessions" in data
        assert "page" in data
        assert "total_sessions" in data
        assert len(data["sessions"]) > 0

    def test_sessions_page_2(self, server):
        data = get_json(server, "/api/sessions?page=2")
        assert data["page"] == 2

    def test_sessions_sort_by_errors(self, server):
        data = get_json(server, "/api/sessions?sort=errors")
        assert data["sort"] == "errors"


# --- Session Detail ---

class TestSessionDetail:
    def test_session_detail(self, server):
        sessions = get_json(server, "/api/sessions")
        sid = sessions["sessions"][0]["session_id"]
        data = get_json(server, f"/api/session/{sid}")
        assert data["session_id"] == sid
        assert "events" in data
        assert "summary" in data

    def test_session_detail_unknown(self, server):
        data = get_json(server, "/api/session/nonexistent-id")
        assert data["session_id"] == "nonexistent-id"
        assert len(data["events"]) == 0


# --- Session Replay ---

class TestSessionReplay:
    def test_replay_no_file(self, server):
        data = get_json(server, "/api/session/nonexistent/replay")
        assert "messages" in data
        # No transcript file exists so messages will be empty or error
        assert len(data["messages"]) == 0 or "error" in data


# --- Compare ---

class TestCompare:
    def test_compare_ranges(self, server):
        data = get_json(server, "/api/compare?from_a=2026-01-15&to_a=2026-01-20&from_b=2026-01-21&to_b=2026-01-25")
        assert "range_a" in data
        assert "range_b" in data
        assert "deltas" in data


# --- Activity Heatmap ---

class TestActivityHeatmap:
    def test_heatmap_shape(self, server):
        data = get_json(server, "/api/activity_heatmap")
        assert "data" in data
        assert len(data["data"]) > 0
        entry = data["data"][0]
        assert "day" in entry
        assert "hour" in entry
        assert "count" in entry


# --- Latency ---

class TestLatency:
    def test_latency_shape(self, server):
        data = get_json(server, "/api/latency")
        assert "data" in data
        assert len(data["data"]) > 0
        entry = data["data"][0]
        assert "tool" in entry
        assert "histogram" in entry


# --- Errors ---

class TestErrors:
    def test_errors_by_type(self, server):
        data = get_json(server, "/api/errors?group_by=type")
        assert data["group_by"] == "type"
        assert "data" in data

    def test_errors_by_tool(self, server):
        data = get_json(server, "/api/errors?group_by=tool")
        assert data["group_by"] == "tool"


# --- Static Files ---

class TestStaticFiles:
    def test_unknown_api_returns_404(self, server):
        status = get_status(server, "/api/nonexistent")
        assert status == 404

    def test_missing_static_returns_404(self, server):
        status = get_status(server, "/nonexistent.html")
        assert status == 404


# --- Routing Edge Cases ---

class TestRouting:
    def test_session_replay_before_detail(self, server):
        """Replay route must match before detail route."""
        sessions = get_json(server, "/api/sessions")
        sid = sessions["sessions"][0]["session_id"]
        data = get_json(server, f"/api/session/{sid}/replay")
        assert "messages" in data

    def test_query_params_forwarded(self, server):
        """Filters from query string reach the provider."""
        data = get_json(server, "/api/overview?tool=Bash")
        assert data["total_events"] > 0
