"""Tests for response envelope format.

Tests that responses return summary-only by default, with full content
available via separate request for clean metrics.
"""

import pytest
import json
from unittest.mock import MagicMock, patch


class TestSummaryOnlyResponse:
    """Tests for summary-only default response."""

    def test_envelope_contains_summary(self):
        """Response should contain summary."""
        from lib.mcp_router import format_response_envelope
        
        envelope = format_response_envelope(
            summary='{"count": 5}',
            correlation_id="req-123"
        )
        
        assert "summary" in envelope
        assert envelope["summary"] == '{"count": 5}'

    def test_envelope_contains_correlation_id(self):
        """Response should contain correlation_id for retrieving full."""
        from lib.mcp_router import format_response_envelope
        
        envelope = format_response_envelope(
            summary='{"count": 5}',
            correlation_id="req-123"
        )
        
        assert "correlation_id" in envelope
        assert envelope["correlation_id"] == "req-123"

    def test_envelope_contains_instruction(self):
        """Response should explain how to get full content."""
        from lib.mcp_router import format_response_envelope
        
        envelope = format_response_envelope(
            summary='{}',
            correlation_id="req-123"
        )
        
        assert "instruction" in envelope
        assert "router__get_full" in envelope["instruction"]

    def test_envelope_does_not_contain_full(self):
        """Response should NOT contain full content."""
        from lib.mcp_router import format_response_envelope
        
        envelope = format_response_envelope(
            summary='{"data": "test"}',
            correlation_id="req-123"
        )
        
        assert "full" not in envelope
        assert "data" not in envelope
        assert "content" not in envelope

    def test_envelope_has_full_available_flag(self):
        """Response should indicate full content is available."""
        from lib.mcp_router import format_response_envelope
        
        envelope = format_response_envelope(
            summary='{}',
            correlation_id="req-123"
        )
        
        assert envelope.get("full_available") is True


class TestFullContentStorage:
    """Tests for storing and retrieving full content."""

    def test_store_full_content(self):
        """Should store full content by correlation_id."""
        from lib.mcp_router import ResponseCache
        
        cache = ResponseCache()
        cache.store("req-123", {"content": "full data"})
        
        assert cache.get("req-123") == {"content": "full data"}

    def test_retrieve_full_content(self):
        """Should retrieve stored full content."""
        from lib.mcp_router import ResponseCache
        
        cache = ResponseCache()
        cache.store("req-456", {"text": "complete response"})
        
        result = cache.get("req-456")
        assert result == {"text": "complete response"}

    def test_retrieve_missing_returns_none(self):
        """Should return None for missing correlation_id."""
        from lib.mcp_router import ResponseCache
        
        cache = ResponseCache()
        
        assert cache.get("nonexistent") is None

    def test_cache_tracks_retrievals(self):
        """Should track when full content is retrieved."""
        from lib.mcp_router import ResponseCache
        
        cache = ResponseCache()
        cache.store("req-789", {"data": "test"})
        
        cache.get("req-789")
        
        assert cache.get_retrieval_count("req-789") == 1

    def test_cache_has_ttl(self):
        """Cached content should expire after TTL."""
        from lib.mcp_router import ResponseCache
        import time
        
        cache = ResponseCache(ttl_seconds=0.1)  # 100ms TTL
        cache.store("req-expire", {"data": "temp"})
        
        # Should exist immediately
        assert cache.get("req-expire") is not None
        
        # Wait for expiry
        time.sleep(0.15)
        
        # Should be gone
        assert cache.get("req-expire") is None


class TestGetFullMetrics:
    """Tests for tracking get_full requests in telemetry."""

    def test_get_full_tracked_in_telemetry(self):
        """Calling get_full should be tracked."""
        from lib.mcp_router import TelemetryCollector, ResponseCache
        from pathlib import Path
        import tempfile
        
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            temp_path = Path(f.name)
        
        telemetry = TelemetryCollector(telemetry_file=temp_path)
        cache = ResponseCache()
        
        # Store and retrieve
        cache.store("req-track", {"data": "test"})
        cache.get("req-track")
        
        # Track the retrieval
        telemetry.track_full_retrieval("req-track")
        
        summary = telemetry.get_summary()
        assert summary["aggregates"].get("full_retrievals", 0) >= 1
        
        temp_path.unlink()


class TestEnvelopeEdgeCases:
    """Edge cases for envelope formatting."""

    def test_handles_none_summary(self):
        """Should handle None summary gracefully."""
        from lib.mcp_router import format_response_envelope
        
        envelope = format_response_envelope(
            summary=None,
            correlation_id="req-123"
        )
        
        assert envelope["summary"] == "" or envelope["summary"] is None

    def test_handles_empty_correlation_id(self):
        """Should handle empty correlation_id."""
        from lib.mcp_router import format_response_envelope
        
        envelope = format_response_envelope(
            summary='{"status": "ok"}',
            correlation_id=""
        )
        
        # Should still work, just can't retrieve full
        assert "summary" in envelope

    def test_json_serializable(self):
        """Envelope should be JSON serializable."""
        from lib.mcp_router import format_response_envelope
        
        envelope = format_response_envelope(
            summary='{"test": true}',
            correlation_id="req-json"
        )
        
        # Should not raise
        serialized = json.dumps(envelope)
        assert isinstance(serialized, str)
        
        # Should round-trip
        deserialized = json.loads(serialized)
        assert deserialized["summary"] == '{"test": true}'
