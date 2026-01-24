"""Tests for content retrieval tracking.

Tests tracking of whether agents retrieve full content after receiving summaries.
"""

import tempfile

import pytest

from lib.stores.duckdb_store import DuckDBStore


@pytest.fixture
def duckdb_store():
    """Create a temporary DuckDB store for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = DuckDBStore(data_dir=tmpdir, db_name="test.duckdb")
        yield store
        store.conn.close()


class TestContentRetrievalTracking:
    """Test suite for content retrieval tracking."""

    def test_record_content_creation(self, duckdb_store):
        """Test that content creation is recorded with correct defaults."""
        content_id = "c123abc456def"
        
        # Record content creation
        duckdb_store.record_content_creation(content_id)
        
        # Query the record
        result = duckdb_store.conn.execute(
            "SELECT content_id, created_at, retrieved_at, was_retrieved FROM content_retrievals WHERE content_id = ?",
            [content_id]
        ).fetchone()
        
        assert result is not None, "Content creation record should exist"
        assert result[0] == content_id, "Content ID should match"
        assert result[1] is not None, "Created timestamp should be set"
        assert result[2] is None, "Retrieved timestamp should be null initially"
        assert result[3] is False, "was_retrieved should be False initially"

    def test_record_content_retrieval(self, duckdb_store):
        """Test that content retrieval updates the record correctly."""
        content_id = "c789def012ghi"
        
        # First create the content record
        duckdb_store.record_content_creation(content_id)
        
        # Then record retrieval
        duckdb_store.record_content_retrieval(content_id)
        
        # Query the updated record
        result = duckdb_store.conn.execute(
            "SELECT content_id, retrieved_at, was_retrieved FROM content_retrievals WHERE content_id = ?",
            [content_id]
        ).fetchone()
        
        assert result is not None, "Content record should exist"
        assert result[0] == content_id, "Content ID should match"
        assert result[1] is not None, "Retrieved timestamp should be set"
        assert result[2] is True, "was_retrieved should be True after retrieval"

    def test_record_retrieval_without_creation(self, duckdb_store):
        """Test recording retrieval for non-existent content_id (should handle gracefully)."""
        content_id = "c_nonexistent"
        
        # Try to record retrieval without creation - should not raise error
        # but should not create a record either (or handle as appropriate)
        duckdb_store.record_content_retrieval(content_id)
        
        # Query to verify behavior
        result = duckdb_store.conn.execute(
            "SELECT COUNT(*) FROM content_retrievals WHERE content_id = ?",
            [content_id]
        ).fetchone()
        
        # Should not create a record for non-existent content
        assert result[0] == 0, "Should not create record for non-existent content_id"

    def test_duplicate_content_creation(self, duckdb_store):
        """Test that duplicate content creation is handled (primary key constraint)."""
        content_id = "c_duplicate"
        
        # First creation should succeed
        duckdb_store.record_content_creation(content_id)
        
        # Second creation should be handled gracefully (e.g., ignore or update)
        # This tests the PRIMARY KEY constraint behavior
        try:
            duckdb_store.record_content_creation(content_id)
            # If no exception, verify only one record exists
            result = duckdb_store.conn.execute(
                "SELECT COUNT(*) FROM content_retrievals WHERE content_id = ?",
                [content_id]
            ).fetchone()
            assert result[0] == 1, "Should have exactly one record for duplicate content_id"
        except Exception:
            # If exception is expected, verify original record still exists
            result = duckdb_store.conn.execute(
                "SELECT COUNT(*) FROM content_retrievals WHERE content_id = ?",
                [content_id]
            ).fetchone()
            assert result[0] == 1, "Original record should still exist after duplicate attempt"

    def test_multiple_retrievals(self, duckdb_store):
        """Test that multiple retrievals of same content_id are idempotent."""
        content_id = "c_multi_retrieve"
        
        # Create content
        duckdb_store.record_content_creation(content_id)
        
        # Retrieve multiple times
        duckdb_store.record_content_retrieval(content_id)
        duckdb_store.record_content_retrieval(content_id)
        duckdb_store.record_content_retrieval(content_id)
        
        # Should still have one record with was_retrieved=True
        result = duckdb_store.conn.execute(
            "SELECT COUNT(*), MAX(was_retrieved) FROM content_retrievals WHERE content_id = ?",
            [content_id]
        ).fetchone()
        
        assert result[0] == 1, "Should have exactly one record"
        assert result[1] is True, "was_retrieved should be True"

    def test_retrieval_stats_query(self, duckdb_store):
        """Test querying retrieval statistics across multiple content items."""
        # Create multiple content items with different retrieval patterns
        duckdb_store.record_content_creation("c_retrieved_1")
        duckdb_store.record_content_retrieval("c_retrieved_1")
        
        duckdb_store.record_content_creation("c_retrieved_2")
        duckdb_store.record_content_retrieval("c_retrieved_2")
        
        duckdb_store.record_content_creation("c_not_retrieved_1")
        duckdb_store.record_content_creation("c_not_retrieved_2")
        duckdb_store.record_content_creation("c_not_retrieved_3")
        
        # Query statistics
        stats = duckdb_store.conn.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN was_retrieved THEN 1 ELSE 0 END) as retrieved_count,
                SUM(CASE WHEN NOT was_retrieved THEN 1 ELSE 0 END) as not_retrieved_count
            FROM content_retrievals
        """).fetchone()
        
        assert stats[0] == 5, "Total should be 5"
        assert stats[1] == 2, "Retrieved count should be 2"
        assert stats[2] == 3, "Not retrieved count should be 3"


class TestTelemetryServiceIntegration:
    """Test TelemetryService exposes content retrieval tracking methods."""

    def test_telemetry_service_has_tracking_methods(self):
        """Test that TelemetryService exposes record_content_creation and record_content_retrieval."""
        from lib.telemetry_service import TelemetryService
        
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TelemetryService(data_dir=tmpdir)
            
            # Check methods exist
            assert hasattr(service, 'record_content_creation'), \
                "TelemetryService should have record_content_creation method"
            assert hasattr(service, 'record_content_retrieval'), \
                "TelemetryService should have record_content_retrieval method"
            
            # Test basic functionality
            service.record_content_creation("test_content_id")
            service.record_content_retrieval("test_content_id")


class TestMCPControllerIntegration:
    """Test MCPController calls tracking methods appropriately."""

    def test_handle_call_tracks_summarized_content(self):
        """Test that handle_call records content creation when summarization occurs."""
        from lib.mcp_controller import MCPController
        from lib.summarization_service import SummarizationService
        from lib.telemetry_service import TelemetryService
        from lib.workflow_state_service import WorkflowStateService
        from unittest.mock import Mock, patch
        
        with tempfile.TemporaryDirectory() as tmpdir:
            workflow_state = WorkflowStateService()
            summarization = SummarizationService(workflow_state, threshold=10)
            telemetry = TelemetryService(data_dir=tmpdir)
            
            # Mock routing service to return large content
            mock_routing = Mock()
            mock_routing.route.return_value = "x" * 100  # Large content to trigger summarization
            
            controller = MCPController(
                routing_service=mock_routing,
                summarization_service=summarization,
                telemetry_service=telemetry,
                workflow_state_service=workflow_state
            )
            
            # Call handle_call which should trigger summarization
            # Patch insert_event to avoid timestamp conversion issues
            with patch.object(controller._telemetry._store, 'insert_event'):
                result = controller.handle_call("test_tool", {})
            
            # Result should be a summary dict with content_id
            assert isinstance(result, dict), "Result should be dict for summarized content"
            assert "content_id" in result, "Result should contain content_id"
            
            content_id = result["content_id"]
            
            # Verify content creation was recorded
            record = telemetry._store.conn.execute(
                "SELECT content_id, was_retrieved FROM content_retrievals WHERE content_id = ?",
                [content_id]
            ).fetchone()
            
            assert record is not None, "Content creation should be recorded"
            assert record[0] == content_id, "Content ID should match"
            assert record[1] is False, "Should not be retrieved yet"

    def test_get_full_content_tracks_retrieval(self):
        """Test that get_full_content records content retrieval."""
        from lib.mcp_controller import MCPController
        from lib.telemetry_service import TelemetryService
        from lib.workflow_state_service import WorkflowStateService
        
        with tempfile.TemporaryDirectory() as tmpdir:
            workflow_state = WorkflowStateService()
            telemetry = TelemetryService(data_dir=tmpdir)
            
            controller = MCPController(
                telemetry_service=telemetry,
                workflow_state_service=workflow_state
            )
            
            # Store some content
            content_id = "c_test_retrieval"
            test_content = {"data": "test content"}
            workflow_state.store_content(content_id, test_content)
            
            # Record creation first
            telemetry.record_content_creation(content_id)
            
            # Retrieve full content
            retrieved = controller.get_full_content(content_id)
            
            assert retrieved == test_content, "Should retrieve correct content"
            
            # Verify retrieval was recorded
            record = telemetry._store.conn.execute(
                "SELECT content_id, was_retrieved FROM content_retrievals WHERE content_id = ?",
                [content_id]
            ).fetchone()
            
            assert record is not None, "Record should exist"
            assert record[1] is True, "Should be marked as retrieved"

    def test_get_full_content_nonexistent_does_not_track(self):
        """Test that get_full_content for non-existent content doesn't create tracking record."""
        from lib.mcp_controller import MCPController
        from lib.telemetry_service import TelemetryService
        from lib.workflow_state_service import WorkflowStateService
        
        with tempfile.TemporaryDirectory() as tmpdir:
            workflow_state = WorkflowStateService()
            telemetry = TelemetryService(data_dir=tmpdir)
            
            controller = MCPController(
                telemetry_service=telemetry,
                workflow_state_service=workflow_state
            )
            
            # Try to retrieve non-existent content
            result = controller.get_full_content("c_nonexistent")
            
            assert "error" in result, "Should return error for non-existent content"
            
            # Verify no tracking record was created
            count = telemetry._store.conn.execute(
                "SELECT COUNT(*) FROM content_retrievals WHERE content_id = ?",
                ["c_nonexistent"]
            ).fetchone()[0]
            
            assert count == 0, "Should not create tracking record for failed retrieval"
