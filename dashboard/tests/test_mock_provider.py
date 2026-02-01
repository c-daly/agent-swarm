"""Tests for MockProvider - validates JSON shapes match SqliteProvider."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from dashboard.providers.mock import MockProvider


class TestMockProvider:
    def setup_method(self):
        self.p = MockProvider(seed=42)

    def test_deterministic(self):
        p2 = MockProvider(seed=42)
        assert len(self.p._events) == len(p2._events)

    def test_health(self):
        h = self.p.health()
        assert h["status"] == "ok"
        assert h["total_events"] > 0
        assert h["total_sessions"] == 200

    def test_overview_shape(self):
        o = self.p.overview({})
        for k in ["total_events", "total_sessions", "total_input_tokens",
                   "total_output_tokens", "total_errors", "error_rate"]:
            assert k in o

    def test_tokens_by_day(self):
        r = self.p.tokens({"group_by": "day"})
        assert r["group_by"] == "day"
        assert len(r["data"]) > 0
        assert "period" in r["data"][0]

    def test_tokens_by_tool(self):
        r = self.p.tokens({"group_by": "tool", "limit": "5"})
        assert len(r["data"]) <= 5

    def test_tools_shape(self):
        r = self.p.tools({"sort": "count", "limit": "10"})
        d = r["data"][0]
        for k in ["tool", "call_count", "error_rate"]:
            assert k in d

    def test_sessions_pagination(self):
        r = self.p.sessions({"page": "1", "sort": "tokens"})
        assert r["page"] == 1
        assert len(r["sessions"]) <= 50

    def test_session_detail(self):
        r = self.p.session_detail(self.p._sessions[0])
        assert "events" in r and "summary" in r

    def test_compare(self):
        r = self.p.compare({"from": "2026-01-17"}, {"from": "2026-01-24"})
        assert "deltas" in r

    def test_activity_heatmap(self):
        r = self.p.activity_heatmap({})
        assert "data" in r

    def test_latency_shape(self):
        r = self.p.latency({"limit": "5"})
        if r["data"]:
            assert "histogram" in r["data"][0]

    def test_errors_by_type(self):
        assert self.p.errors({"group_by": "type"})["group_by"] == "type"

    def test_errors_by_tool(self):
        assert self.p.errors({"group_by": "tool"})["group_by"] == "tool"

    def test_filter_by_status(self):
        r = self.p.overview({"status": "error"})
        assert r["error_rate"] == 1.0
