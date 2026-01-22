"""Tests for TelemetryCollector integration with TelemetryService.

Tests that TelemetryCollector can delegate persistence to TelemetryService
while maintaining backward compatibility with file-based telemetry.
"""

from datetime import datetime, timezone
from unittest.mock import Mock

from lib.mcp_router import TelemetryCollector
from lib.telemetry_service import TelemetryService


class TestTelemetryCollectorIntegration:
    """Test TelemetryCollector integration with TelemetryService."""

    def test_accepts_telemetry_service_in_constructor(self, tmp_path):
        """TelemetryCollector should accept optional TelemetryService instance."""
        mock_service = Mock(spec=TelemetryService)
        telemetry_file = tmp_path / "telemetry.json"
        
        collector = TelemetryCollector(
            telemetry_file=telemetry_file,
            telemetry_service=mock_service
        )
        
        # Should store the service
        assert collector._telemetry_service is mock_service

    def test_works_without_telemetry_service(self, tmp_path):
        """TelemetryCollector should work without TelemetryService (backward compat)."""
        telemetry_file = tmp_path / "telemetry.json"
        
        collector = TelemetryCollector(telemetry_file=telemetry_file)
        
        # Should not have telemetry service
        assert collector._telemetry_service is None
        
        # Should still be able to track requests/responses
        corr_id = collector.track_request("serena", "read_file", {"path": "/test"})
        assert corr_id.startswith("req-")
        
        # Should not crash when tracking response without service
        collector.track_response(corr_id, error=False)

    def test_calls_insert_event_when_service_available(self, tmp_path):
        """track_response should call TelemetryService.insert_event when available."""
        mock_service = Mock(spec=TelemetryService)
        telemetry_file = tmp_path / "telemetry.json"
        
        collector = TelemetryCollector(
            telemetry_file=telemetry_file,
            telemetry_service=mock_service
        )
        
        # Track a request and response
        corr_id = collector.track_request("serena", "read_file", {"path": "/test.py"})
        collector.track_response(corr_id, error=False, full_size=1000, summary_size=500)
        
        # Should have called insert_event once
        assert mock_service.insert_event.call_count == 1

    def test_does_not_call_insert_event_without_service(self, tmp_path):
        """track_response should NOT call insert_event when service not available."""
        telemetry_file = tmp_path / "telemetry.json"
        
        collector = TelemetryCollector(telemetry_file=telemetry_file)
        
        # Track a request and response
        corr_id = collector.track_request("serena", "read_file", {"path": "/test.py"})
        collector.track_response(corr_id, error=False)
        
        # Should not crash (no service to call)
        # Test passes if no exception raised

    def test_event_field_mapping(self, tmp_path):
        """Test that TelemetryCollector maps fields correctly to TelemetryService format."""
        mock_service = Mock(spec=TelemetryService)
        telemetry_file = tmp_path / "telemetry.json"
        
        collector = TelemetryCollector(
            telemetry_file=telemetry_file,
            telemetry_service=mock_service
        )
        
        # Track a successful request
        corr_id = collector.track_request(
            "serena", 
            "read_file", 
            {"relative_path": "/test.py"}
        )
        collector.track_response(
            corr_id, 
            error=False, 
            full_size=1000, 
            summary_size=500
        )
        
        # Get the event that was passed to insert_event
        call_args = mock_service.insert_event.call_args
        assert call_args is not None
        event = call_args[0][0]  # First positional argument
        
        # Verify required fields are present and mapped correctly
        assert "timestamp" in event  # TelemetryCollector "ts" → "timestamp"
        assert "session_id" in event  # Should include session_id
        assert event["tool"] == "read_file"  # tool mapping
        assert event["backend"] == "serena"  # backend mapping
        assert "duration_ms" in event  # duration_ms mapping
        assert event["status"] == "success"  # status mapping
        
        # Verify timestamp is ISO format
        datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        
        # Verify session_id matches collector's session
        assert event["session_id"] == collector._session_id

    def test_event_field_mapping_with_error(self, tmp_path):
        """Test field mapping for error events."""
        mock_service = Mock(spec=TelemetryService)
        telemetry_file = tmp_path / "telemetry.json"
        
        collector = TelemetryCollector(
            telemetry_file=telemetry_file,
            telemetry_service=mock_service
        )
        
        # Track a failed request
        corr_id = collector.track_request("native", "bash", {"command": "false"})
        collector.track_response(
            corr_id,
            error=True,
            error_msg="Command failed with exit code 1"
        )
        
        # Get the event
        event = mock_service.insert_event.call_args[0][0]
        
        # Verify error fields
        assert event["status"] == "error"
        assert event["backend"] == "native"
        assert event["tool"] == "bash"
        # Error type should be extracted or set
        assert "error_type" in event

    def test_event_field_mapping_with_subagent(self, tmp_path):
        """Test field mapping for subagent (Task tool) events."""
        mock_service = Mock(spec=TelemetryService)
        telemetry_file = tmp_path / "telemetry.json"
        
        collector = TelemetryCollector(
            telemetry_file=telemetry_file,
            telemetry_service=mock_service
        )
        
        # Track a Task tool request (subagent)
        corr_id = collector.track_request(
            "task",
            "Task",
            {"subagent_type": "Explore", "task": "Find error handlers"}
        )
        collector.track_response(corr_id, error=False)
        
        # Get the event
        event = mock_service.insert_event.call_args[0][0]
        
        # Verify subagent-specific fields
        assert event["tool"] == "Task"
        assert event["agent_type"] == "Explore"  # subagent_type → agent_type

    def test_event_field_mapping_with_summarization(self, tmp_path):
        """Test field mapping for events with summarization data."""
        mock_service = Mock(spec=TelemetryService)
        telemetry_file = tmp_path / "telemetry.json"
        
        collector = TelemetryCollector(
            telemetry_file=telemetry_file,
            telemetry_service=mock_service
        )
        
        # Track request with summarization
        corr_id = collector.track_request("serena", "find_symbol", {"name": "test"})
        collector.track_response(
            corr_id,
            error=False,
            full_size=5000,
            summary_size=1200
        )
        
        # Get the event
        event = mock_service.insert_event.call_args[0][0]
        
        # Verify summarization fields
        assert event.get("was_summarized") is True
        assert event.get("original_size") == 5000
        assert event.get("summary_size") == 1200

    def test_dual_write_both_file_and_service(self, tmp_path):
        """Test that both file and service receive data (dual-write during migration)."""
        mock_service = Mock(spec=TelemetryService)
        telemetry_file = tmp_path / "telemetry.json"
        
        collector = TelemetryCollector(
            telemetry_file=telemetry_file,
            telemetry_service=mock_service
        )
        
        # Track request/response
        corr_id = collector.track_request("serena", "read_file", {"path": "/test.py"})
        collector.track_response(corr_id, error=False)
        
        # Verify service was called
        assert mock_service.insert_event.call_count == 1
        
        # Verify file was written (should exist and contain data)
        assert telemetry_file.exists()
        import json
        with open(telemetry_file) as f:
            file_data = json.load(f)
        
        # Should have today's data
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert today in file_data.get("days", {})
