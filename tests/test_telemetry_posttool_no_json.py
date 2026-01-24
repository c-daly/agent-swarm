#!/usr/bin/env python3
"""Test that telemetry-posttool.py does NOT write to telemetry.json (v2 JSON file).

The telemetry system has migrated to v3 (DuckDB) and should only write to DuckDB,
not the legacy v2 JSON file.
"""

import json
import sys
import time
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestPosttoolNoJsonWrites:
    """Verify telemetry-posttool.py does not write to v2 JSON file."""

    @pytest.fixture
    def temp_state_dir(self, tmp_path):
        """Create a temporary state directory structure."""
        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        return state_dir

    @pytest.fixture
    def mock_pending_request(self, temp_state_dir):
        """Create a pending request file that the posttool expects."""
        pending_file = temp_state_dir / "telemetry_pending.json"
        latest_file = temp_state_dir / "telemetry_latest.json"
        
        request_id = "test-request-123"
        pending_data = {
            request_id: {
                "start_time": time.time() - 0.1,  # Started 100ms ago
                "tool_name": "test_tool",
                "backend": "native",
                "subagent_type": "",
            }
        }
        latest_data = {"test_tool": request_id}
        
        pending_file.write_text(json.dumps(pending_data))
        latest_file.write_text(json.dumps(latest_data))
        
        return request_id

    def test_posttool_does_not_import_save_telemetry_v2(self):
        """Verify the posttool module does not import save_telemetry_v2."""
        hook_path = Path(__file__).parent.parent / "hooks" / "telemetry-posttool.py"
        content = hook_path.read_text()
        
        # Should NOT have save_telemetry_v2 import
        assert "save_telemetry_v2" not in content, (
            "telemetry-posttool.py should not import save_telemetry_v2 - "
            "v2 JSON writes should be removed"
        )
        
        # Should NOT have load_telemetry_v2 import
        assert "load_telemetry_v2" not in content, (
            "telemetry-posttool.py should not import load_telemetry_v2 - "
            "v2 JSON reads should be removed"
        )

    def test_posttool_does_not_call_save_telemetry_v2(self):
        """Verify posttool does not call save_telemetry_v2."""
        hook_path = Path(__file__).parent.parent / "hooks" / "telemetry-posttool.py"
        content = hook_path.read_text()
        
        # Should NOT have any call to save_telemetry_v2
        assert "save_telemetry_v2(" not in content, (
            "telemetry-posttool.py should not call save_telemetry_v2()"
        )

    def test_posttool_does_not_reference_telemetry_json_for_v2(self):
        """Verify posttool does not use TELEMETRY_FILE for v2 operations."""
        hook_path = Path(__file__).parent.parent / "hooks" / "telemetry-posttool.py"
        content = hook_path.read_text()
        
        # Should NOT have load_telemetry_v2(TELEMETRY_FILE)
        assert "load_telemetry_v2(TELEMETRY_FILE)" not in content, (
            "telemetry-posttool.py should not load v2 telemetry from TELEMETRY_FILE"
        )
        
        # Should NOT have save_telemetry_v2(..., TELEMETRY_FILE)
        assert "save_telemetry_v2(telemetry, TELEMETRY_FILE)" not in content, (
            "telemetry-posttool.py should not save v2 telemetry to TELEMETRY_FILE"
        )

    def test_posttool_still_has_duckdb_insert(self):
        """Verify posttool still writes to DuckDB via TelemetryService."""
        hook_path = Path(__file__).parent.parent / "hooks" / "telemetry-posttool.py"
        content = hook_path.read_text()
        
        # Should still have TelemetryService import
        assert "from lib.telemetry_service import TelemetryService" in content, (
            "telemetry-posttool.py must still import TelemetryService"
        )
        
        # Should still have insert_event call
        assert "service.insert_event(" in content, (
            "telemetry-posttool.py must still call service.insert_event()"
        )

    def test_posttool_does_not_build_v2_telemetry_structure(self):
        """Verify posttool does not build v2 telemetry data structures."""
        hook_path = Path(__file__).parent.parent / "hooks" / "telemetry-posttool.py"
        content = hook_path.read_text()
        
        # Should NOT have ensure_day call (v2 schema function)
        assert "ensure_day(" not in content, (
            "telemetry-posttool.py should not call ensure_day() - this is v2 schema code"
        )
        
        # Should NOT have update_timing_stats call (v2 schema function)
        assert "update_timing_stats(" not in content, (
            "telemetry-posttool.py should not call update_timing_stats() - this is v2 schema code"
        )
        
        # Should NOT have recompute_aggregates call (v2 schema function)
        assert "recompute_aggregates(" not in content, (
            "telemetry-posttool.py should not call recompute_aggregates() - this is v2 schema code"
        )
        
        # Should NOT have update_filter_options call (v2 schema function)
        assert "update_filter_options(" not in content, (
            "telemetry-posttool.py should not call update_filter_options() - this is v2 schema code"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
