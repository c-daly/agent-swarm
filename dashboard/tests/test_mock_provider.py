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
        assert self.p._events[0]["timestamp"] == p2._events[0]["timestamp"]

    def test_health(self):
        h = self.p.health()
        assert h["status"] == "ok"
        assert h["total_events"] > 0
        assert h["total_sessions"] == 200

    def test_overview_shape(self):
        o = self.p.overview({})
        for key in ["total_events", "total_sessions", "total_input_tokens",
                     "total_output_tokens", "total_errors", "error_rate",
                     "avg_duration_ms", "unique_tools", "subagent_count"]:
            assert key in o, f"Missing key: {key}"

    def test_tokens_by_day(self):
        r = self.p.tokens({"group_by": "day"})
        assert r["group_by"] == "day"
        assert len(r["data"]) > 0
        assert "period" in r["data"][0]
        assert "input" in r["data"][0]

    def test_tokens_by_tool(self):
        r = self.p.tokens({"group_by": "tool", "limit": "5"})
        assert r["group_by"] == "tool"
        assert len(r["data"]) <= 5
        assert "tool" in r["data"][0]

    def test_tokens_by_agent(self):
        r = self.p.tokens({"group_by": "agent"})
        assert r["group_by"] == "agent"
        roles = {d["agent_role"] for d in r["data"]}
        assert "main" in roles

    def test_tools_shape(self):
        r = self.p.tools({"sort": "count", "limit": "10"})
        assert "data" in r
        d = r["data"][0]
        for k in ["tool", "call_count", "error_count", "error_rate", "total_tokens"]:
            assert k in d

    def test_concurrency(self):
        sid = self.p._sessions[0]
        r = self.p.concurrency({"session": sid})
        assert r["session_id"] == sid
        assert "max_concurrency" in r
        assert "events" in r

    def test_summarization_shape(self):
        r = self.p.summarization({})
        for k in ["total_events", "summarized_count", "summarization_rate",
                   "full_content_requests", "effective_summarized", "by_agent_role",
                   "get_full_rate", "get_full_since", "summaries_since_get_full"]:
            assert k in r

    def test_sessions_pagination(self):
        r = self.p.sessions({"page": "1", "sort": "tokens"})
        assert r["page"] == 1
        assert r["total_sessions"] > 0
        assert len(r["sessions"]) <= 50

    def test_session_detail(self):
        sid = self.p._sessions[0]
        r = self.p.session_detail(sid)
        assert r["session_id"] == sid
        assert "events" in r
        assert "summary" in r
        assert "total_events" in r["summary"]

    def test_session_replay_mock(self):
        r = self.p.session_replay("sess-0000", "/tmp")
        assert "error" in r

    def test_compare(self):
        r = self.p.compare(
            {"from": "2026-01-17", "to": "2026-01-20"},
            {"from": "2026-01-24", "to": "2026-01-27"},
        )
        assert "range_a" in r
        assert "range_b" in r
        assert "deltas" in r

    def test_activity_heatmap(self):
        r = self.p.activity_heatmap({})
        assert "data" in r
        if r["data"]:
            assert "day" in r["data"][0]
            assert "hour" in r["data"][0]

    def test_latency_shape(self):
        r = self.p.latency({"limit": "5"})
        assert "data" in r
        if r["data"]:
            d = r["data"][0]
            assert "histogram" in d
            assert "<100ms" in d["histogram"]

    def test_errors_by_type(self):
        r = self.p.errors({"group_by": "type"})
        assert r["group_by"] == "type"

    def test_errors_by_tool(self):
        r = self.p.errors({"group_by": "tool"})
        assert r["group_by"] == "tool"

    def test_filter_by_tool(self):
        r = self.p.overview({"tool": "Bash"})
        assert r["total_events"] > 0
        assert r["total_events"] < self.p.overview({})["total_events"]

    def test_filter_by_status(self):
        r = self.p.overview({"status": "error"})
        assert r["total_events"] > 0
        assert r["error_rate"] == 1.0
