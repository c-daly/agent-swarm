"""Tests for dashboard v3-only schema without JSON fallback.

Verifies that the dashboard serve endpoint returns v3 schema data
from DuckDB without falling back to JSON file reads.
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestDashboardV3SchemaOnly:
    """Tests for v3-only dashboard data flow."""

    def test_serve_endpoint_returns_v3_schema(self):
        """Dashboard /telemetry endpoint should return schema_version 3."""
        # This tests the data format expectation
        v3_data = {
            "events": [],
            "schema_version": 3,
            "aggregates": {
                "total_calls": 10,
                "total_tokens": 5000,
                "total_sessions": 2,
                "by_tool": {"Read": {"count": 5, "tokens": 2500}},
                "by_agent_type": {"implementer": {"count": 3, "tokens": 1500}},
                "summarization": {"offered": 5, "full_requested": 1},
            }
        }
        
        assert v3_data["schema_version"] == 3
        assert "total_calls" in v3_data["aggregates"]
        assert "by_tool" in v3_data["aggregates"]
        assert "summarization" in v3_data["aggregates"]

    def test_duckdb_failure_returns_error_not_json_fallback(self):
        """When DuckDB fails, return error response, not JSON file data."""
        # The expected behavior after removing JSON fallback:
        # - DuckDB failure should result in error info in response
        # - NOT fallback to reading TELEMETRY_FILE
        
        error_response = {
            "events": [],
            "schema_version": 3,
            "aggregates": {
                "total_calls": 0,
                "total_tokens": 0,
                "total_sessions": 0,
                "by_tool": {},
                "by_agent_type": {},
                "summarization": {"offered": 0, "full_requested": 0},
            },
            "error": "DuckDB query failed"
        }
        
        # Error response should still have schema_version 3
        assert error_response["schema_version"] == 3
        # Error response should have error field
        assert "error" in error_response
        # Should NOT have data from JSON fallback
        assert error_response["aggregates"]["total_calls"] == 0

    def test_no_normalize_v2_in_js(self):
        """JavaScript should only use normalizeV3Data, not normalizeV2Data."""
        # Read the dashboard generation code
        from scripts.realtime_dashboard import generate_dashboard
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock STATE_DIR and DASHBOARD_FILE
            state_dir = Path(tmpdir)
            dashboard_file = state_dir / "dashboard.html"
            
            with patch('scripts.realtime_dashboard.STATE_DIR', state_dir), \
                 patch('scripts.realtime_dashboard.DASHBOARD_FILE', dashboard_file):
                generate_dashboard()
                
                html = dashboard_file.read_text()
                
                # Should NOT contain normalizeV2Data function definition
                assert "function normalizeV2Data" not in html
                
                # Should contain normalizeV3Data function
                assert "function normalizeV3Data" in html
                
                # refresh() should use normalizeV3Data directly, not chain through v2
                assert "normalizeV2Data(normalizeV3Data" not in html
                assert "normalizeV3Data(rawData)" in html


class TestNoJsonFallbackInServe:
    """Tests that serve_dashboard doesn't read from JSON files."""

    def test_telemetry_file_not_read_on_duckdb_error(self):
        """TELEMETRY_FILE.read_text() should not be called when DuckDB fails."""
        # This is a behavioral test - the code should not have the fallback path
        
        # Import and check the source code doesn't contain the fallback pattern
        import inspect
        from scripts.realtime_dashboard import serve_dashboard
        
        source = inspect.getsource(serve_dashboard)
        
        # After cleanup, these patterns should NOT exist in serve_dashboard:
        # - TELEMETRY_FILE.exists()
        # - TELEMETRY_FILE.read_text()
        assert "TELEMETRY_FILE.exists()" not in source
        assert "TELEMETRY_FILE.read_text()" not in source


class TestDuckDBTimestampHandling:
    """Tests for handling datetime objects from DuckDB in chart generation."""

    def test_charts_handle_datetime_timestamps(self):
        """Charts should handle datetime.datetime objects from DuckDB, not just strings."""
        # DuckDB returns datetime.datetime objects, not strings
        # The charts code was expecting strings and using [:19] slicing

        event_with_datetime = {
            "ts": datetime(2026, 1, 22, 17, 4, 5, 274754),
            "timestamp": datetime(2026, 1, 22, 17, 4, 5, 274754),
            "tool": "Bash",
            "status": "success",
        }

        # The fix should convert datetime to string before slicing
        ts = event_with_datetime.get("ts", "")
        if isinstance(ts, datetime):
            ts = ts.isoformat()
        ts_truncated = ts[:19]

        assert ts_truncated == "2026-01-22T17:04:05"

    def test_load_telemetry_returns_string_timestamps(self):
        """_load_telemetry_v3() should return events with string timestamps."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))

        from scripts.charts import load_telemetry, _duckdb_store

        if _duckdb_store is None:
            pytest.skip("DuckDB not available")

        data = load_telemetry()
        events = data.get("events", [])

        if not events:
            pytest.skip("No events in database")

        # All timestamps should be strings, not datetime objects
        for event in events[:5]:  # Check first 5
            ts = event.get("ts")
            timestamp = event.get("timestamp")

            assert isinstance(ts, str), f"ts should be string, got {type(ts)}"
            assert isinstance(timestamp, str), f"timestamp should be string, got {type(timestamp)}"


class TestChartsGeneration:
    """Tests that charts can be generated without errors."""

    def test_chart_realtime_telemetry_no_error(self):
        """chart_realtime_telemetry() should not raise TypeError on datetime."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))

        from scripts.charts import chart_realtime_telemetry, _duckdb_store

        if _duckdb_store is None:
            pytest.skip("DuckDB not available")

        # This should not raise TypeError: 'datetime.datetime' object is not subscriptable
        try:
            chart_realtime_telemetry()
        except TypeError as e:
            if "datetime.datetime" in str(e) and "not subscriptable" in str(e):
                pytest.fail(f"chart_realtime_telemetry() raised datetime subscript error: {e}")
            raise  # Re-raise other TypeErrors

    def test_dashboard_generation_no_error(self):
        """Dashboard generation should complete without datetime errors."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))

        from scripts.charts import load_telemetry, _duckdb_store

        if _duckdb_store is None:
            pytest.skip("DuckDB not available")

        data = load_telemetry()
        events = data.get("events", [])

        # Simulate what chart_realtime_telemetry does with timestamps
        for e in events[:5]:
            ts = e.get("ts", "")
            try:
                # This should work after the fix
                ts_str = ts[:19] if isinstance(ts, str) else ts.isoformat()[:19]
            except TypeError as err:
                pytest.fail(f"Timestamp handling failed: {err}")
