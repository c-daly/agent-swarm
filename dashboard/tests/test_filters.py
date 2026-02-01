"""Tests for dashboard/providers/filters.py."""

import sys
from pathlib import Path

# Ensure dashboard package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dashboard.providers.filters import build_where, period_group_expr


class TestBuildWhere:
    """Tests for the build_where SQL builder."""

    def test_empty_filters(self):
        clause, params = build_where({})
        assert clause == ""
        assert params == []

    def test_from_filter(self):
        clause, params = build_where({"from": "2026-01-15T00:00:00Z"})
        assert clause == "WHERE timestamp >= ?"
        assert params == ["2026-01-15T00:00:00Z"]

    def test_to_filter(self):
        clause, params = build_where({"to": "2026-01-20T23:59:59Z"})
        assert clause == "WHERE timestamp <= ?"
        assert params == ["2026-01-20T23:59:59Z"]

    def test_from_and_to(self):
        clause, params = build_where({
            "from": "2026-01-15T00:00:00Z",
            "to": "2026-01-20T23:59:59Z",
        })
        assert "timestamp >= ?" in clause
        assert "timestamp <= ?" in clause
        assert "AND" in clause
        assert len(params) == 2

    def test_tool_single(self):
        clause, params = build_where({"tool": "Bash"})
        assert "tool IN (?)" in clause
        assert params == ["Bash"]

    def test_tool_multiple(self):
        clause, params = build_where({"tool": "Bash,Read,Write"})
        assert "tool IN (?,?,?)" in clause
        assert params == ["Bash", "Read", "Write"]

    def test_tool_strips_whitespace(self):
        clause, params = build_where({"tool": "Bash , Read"})
        assert params == ["Bash", "Read"]

    def test_backend_single(self):
        clause, params = build_where({"backend": "native"})
        assert "backend IN (?)" in clause
        assert params == ["native"]

    def test_backend_multiple(self):
        clause, params = build_where({"backend": "native,router"})
        assert "backend IN (?,?)" in clause
        assert params == ["native", "router"]

    def test_status_filter(self):
        clause, params = build_where({"status": "error"})
        assert clause == "WHERE status = ?"
        assert params == ["error"]

    def test_session_filter(self):
        clause, params = build_where({"session": "abc123"})
        assert clause == "WHERE session_id = ?"
        assert params == ["abc123"]

    def test_agent_type_main(self):
        clause, params = build_where({"agent_type": "main"})
        assert "agent_id = session_id" in clause
        assert params == []

    def test_agent_type_subagent(self):
        clause, params = build_where({"agent_type": "subagent"})
        assert "agent_id != session_id" in clause
        assert params == []

    def test_agent_type_specific(self):
        clause, params = build_where({"agent_type": "Explore"})
        assert "agent_type = ?" in clause
        assert params == ["Explore"]

    def test_import_source_filter(self):
        clause, params = build_where({"import_source": "duckdb"})
        assert clause == "WHERE import_source = ?"
        assert params == ["duckdb"]

    def test_combined_filters(self):
        clause, params = build_where({
            "from": "2026-01-15T00:00:00Z",
            "tool": "Bash",
            "status": "success",
        })
        assert clause.startswith("WHERE ")
        parts = clause.replace("WHERE ", "").split(" AND ")
        assert len(parts) == 3
        assert len(params) == 3


class TestPeriodGroupExpr:
    """Tests for the period_group_expr SQL expression builder."""

    def test_hour(self):
        expr = period_group_expr("hour")
        assert "%H:00" in expr
        assert "strftime" in expr

    def test_day(self):
        expr = period_group_expr("day")
        assert expr == "strftime('%Y-%m-%d', timestamp)"

    def test_week(self):
        expr = period_group_expr("week")
        assert "%W" in expr

    def test_month(self):
        expr = period_group_expr("month")
        assert expr == "strftime('%Y-%m', timestamp)"

    def test_unknown_defaults_to_day(self):
        expr = period_group_expr("unknown")
        assert expr == "strftime('%Y-%m-%d', timestamp)"
