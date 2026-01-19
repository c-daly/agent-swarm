"""Tests for telemetry sequence analysis.

Tests call pattern detection: drill-downs, retries, thrashing, etc.

NOTE: Tests require telemetry infrastructure refactoring for MCP router.
"""

import pytest

pytestmark = pytest.mark.skip(
    reason="Integration test: requires telemetry refactoring for MCP router"
)
from unittest.mock import patch
from pathlib import Path
import tempfile
import json


class TestSequenceAnalysis:
    """Tests for sequence pattern detection in telemetry."""

    @pytest.fixture
    def telemetry(self):
        """Create TelemetryCollector with temp file."""
        from lib.mcp_router import TelemetryCollector
        
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            temp_path = Path(f.name)
        
        collector = TelemetryCollector(telemetry_file=temp_path)
        yield collector
        
        # Cleanup
        if temp_path.exists():
            temp_path.unlink()

    def _add_event(self, telemetry, tool: str, backend: str = "test", 
                   status: str = "success", args_hash: str = ""):
        """Helper to add a synthetic event."""
        event = {
            "ts": "2024-01-01T00:00:00Z",
            "tool": tool,
            "backend": backend,
            "duration_ms": 100,
            "status": status,
            "tokens_est": 500,
            "args_hash": args_hash,  # For duplicate detection
            "error_msg": "" if status == "success" else "test error"
        }
        telemetry._data["events"].append(event)

    # === Drill-down Detection ===
    
    def test_detects_grep_to_read_drilldown(self, telemetry):
        """grep followed by read_file on result = drill-down."""
        self._add_event(telemetry, "grep", args_hash="pattern:foo")
        self._add_event(telemetry, "read_file", args_hash="file:src/foo.py")
        
        analysis = telemetry.analyze_sequences()
        
        assert analysis["drill_downs"]["count"] >= 1
        assert "grep→read_file" in analysis["drill_downs"]["patterns"]

    def test_detects_glob_to_read_drilldown(self, telemetry):
        """glob followed by read_file = drill-down."""
        self._add_event(telemetry, "glob")
        self._add_event(telemetry, "read_file")
        
        analysis = telemetry.analyze_sequences()
        
        assert analysis["drill_downs"]["count"] >= 1

    def test_no_drilldown_when_different_flow(self, telemetry):
        """grep followed by unrelated tool is not a drill-down."""
        self._add_event(telemetry, "grep")
        self._add_event(telemetry, "write_file")  # Different flow
        
        analysis = telemetry.analyze_sequences()
        
        assert analysis["drill_downs"]["count"] == 0

    # === Repeat/Retry Detection ===

    def test_detects_identical_repeat(self, telemetry):
        """Same tool with same args = repeat."""
        self._add_event(telemetry, "read_file", args_hash="file:foo.py")
        self._add_event(telemetry, "read_file", args_hash="file:foo.py")
        
        analysis = telemetry.analyze_sequences()
        
        assert analysis["repeats"]["count"] >= 1

    def test_detects_error_retry_pattern(self, telemetry):
        """Error followed by same call = retry."""
        self._add_event(telemetry, "bash", status="error", args_hash="cmd:test")
        self._add_event(telemetry, "bash", status="success", args_hash="cmd:test")
        
        analysis = telemetry.analyze_sequences()
        
        assert analysis["retries"]["count"] >= 1

    def test_no_repeat_for_different_args(self, telemetry):
        """Same tool with different args is not a repeat."""
        self._add_event(telemetry, "read_file", args_hash="file:foo.py")
        self._add_event(telemetry, "read_file", args_hash="file:bar.py")
        
        analysis = telemetry.analyze_sequences()
        
        assert analysis["repeats"]["count"] == 0

    # === Thrashing Detection ===

    def test_detects_thrashing_pattern(self, telemetry):
        """Alternating between same tools = thrashing."""
        for _ in range(3):
            self._add_event(telemetry, "grep", args_hash="pattern:x")
            self._add_event(telemetry, "read_file", args_hash="file:a.py")
        
        analysis = telemetry.analyze_sequences()
        
        assert analysis["thrashing"]["detected"] is True

    def test_no_thrashing_for_normal_flow(self, telemetry):
        """Normal varied sequence is not thrashing."""
        self._add_event(telemetry, "glob")
        self._add_event(telemetry, "read_file")
        self._add_event(telemetry, "edit_file")
        self._add_event(telemetry, "bash")
        
        analysis = telemetry.analyze_sequences()
        
        assert analysis["thrashing"]["detected"] is False

    # === Burst Detection ===

    def test_detects_backend_burst(self, telemetry):
        """Many calls to same backend in short window = burst."""
        for i in range(10):
            self._add_event(telemetry, f"tool_{i}", backend="serena")
        
        analysis = telemetry.analyze_sequences()
        
        assert analysis["bursts"]["count"] >= 1
        assert "serena" in analysis["bursts"]["backends"]

    # === Summary Effectiveness ===

    def test_calculates_drilldown_rate(self, telemetry):
        """Drill-down rate = drill-downs / discovery calls."""
        # 2 discovery calls (grep, glob)
        self._add_event(telemetry, "grep")
        self._add_event(telemetry, "read_file")  # drill-down
        self._add_event(telemetry, "glob")
        self._add_event(telemetry, "write_file")  # no drill-down
        
        analysis = telemetry.analyze_sequences()
        
        # 1 drill-down out of 2 discovery calls = 50%
        assert analysis["summary_effectiveness"]["drill_down_rate"] == 0.5

    # === Error Cascade Detection ===

    def test_detects_error_cascade(self, telemetry):
        """Multiple consecutive errors = cascade."""
        for _ in range(4):
            self._add_event(telemetry, "bash", status="error")
        
        analysis = telemetry.analyze_sequences()
        
        assert analysis["error_cascades"]["count"] >= 1

    def test_no_cascade_for_isolated_errors(self, telemetry):
        """Isolated errors are not a cascade."""
        self._add_event(telemetry, "bash", status="error")
        self._add_event(telemetry, "read_file", status="success")
        self._add_event(telemetry, "grep", status="error")
        
        analysis = telemetry.analyze_sequences()
        
        assert analysis["error_cascades"]["count"] == 0

    # === Integration with get_summary ===

    def test_sequence_analysis_in_summary(self, telemetry):
        """Sequence analysis should be included in telemetry summary."""
        self._add_event(telemetry, "grep")
        self._add_event(telemetry, "read_file")
        
        summary = telemetry.get_summary()
        
        assert "sequences" in summary
        assert "drill_downs" in summary["sequences"]


class TestSequenceAnalysisEdgeCases:
    """Edge cases for sequence analysis."""

    @pytest.fixture
    def telemetry(self):
        """Create TelemetryCollector with temp file."""
        from lib.mcp_router import TelemetryCollector
        
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            temp_path = Path(f.name)
        
        collector = TelemetryCollector(telemetry_file=temp_path)
        yield collector
        
        if temp_path.exists():
            temp_path.unlink()

    def test_empty_events_returns_zeros(self, telemetry):
        """Empty event list should return zero counts."""
        analysis = telemetry.analyze_sequences()
        
        assert analysis["drill_downs"]["count"] == 0
        assert analysis["repeats"]["count"] == 0
        assert analysis["thrashing"]["detected"] is False

    def test_single_event_no_patterns(self, telemetry):
        """Single event cannot form patterns."""
        telemetry._data["events"].append({
            "ts": "2024-01-01T00:00:00Z",
            "tool": "grep",
            "backend": "test",
            "status": "success"
        })
        
        analysis = telemetry.analyze_sequences()
        
        assert analysis["drill_downs"]["count"] == 0

    def test_handles_missing_args_hash(self, telemetry):
        """Events without args_hash should still be analyzed."""
        telemetry._data["events"].append({
            "ts": "2024-01-01T00:00:00Z",
            "tool": "grep",
            "backend": "test",
            "status": "success"
            # No args_hash
        })
        telemetry._data["events"].append({
            "ts": "2024-01-01T00:00:00Z",
            "tool": "read_file",
            "backend": "test",
            "status": "success"
        })
        
        # Should not raise
        analysis = telemetry.analyze_sequences()
        assert "drill_downs" in analysis
