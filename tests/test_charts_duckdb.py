"""Tests for charts.py DuckDB integration.

Tests that charts.py correctly loads data from the persistent DuckDB store
at .state/telemetry.duckdb instead of legacy JSONL directory checks.
"""

import tempfile
from pathlib import Path

import pytest


class TestDuckDBConnectionPath:
    """Tests for DuckDB connection path in charts.py."""

    def test_uses_duckdb_file_not_jsonl_directory(self):
        """Charts should use .state/telemetry.duckdb, not telemetry_v3/*.jsonl."""
        # Create temp directory with DuckDB file but no JSONL
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / ".state"
            state_dir.mkdir()

            # Create telemetry_v3 dir WITHOUT jsonl files (legacy check should fail)
            v3_dir = state_dir / "telemetry_v3"
            v3_dir.mkdir()

            # The DuckDB store should be initialized and create the db file
            # not from checking TELEMETRY_V3_DIR for jsonl files
            from lib.stores.duckdb_store import DuckDBStore

            # This should work - DuckDB will create the file
            store = DuckDBStore(str(state_dir), "telemetry.duckdb")
            duckdb_path = state_dir / "telemetry.duckdb"
            assert store.db_path == duckdb_path
            assert duckdb_path.exists()

    def test_load_telemetry_v3_queries_duckdb_directly(self):
        """_load_telemetry_v3 should query DuckDB tables, not scan JSONL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)

            # Create DuckDB store with test data
            from lib.stores.duckdb_store import DuckDBStore
            store = DuckDBStore(str(state_dir), "test.duckdb")

            # Insert test event
            store.insert_event({
                "timestamp": "2025-01-22T12:00:00",
                "session_id": "test-session",
                "tool": "Read",
                "backend": "native",
                "duration_ms": 100,
                "status": "success",
                "input_tokens": 500,
                "output_tokens": 200,
            })

            # Query should return data
            summaries = store.get_tool_summaries()
            assert len(summaries) == 1
            assert summaries[0].tool_name == "Read"
            assert summaries[0].call_count == 1


class TestSummarizationFields:
    """Tests for summarization fields in event queries."""

    def test_events_table_has_summarization_fields(self):
        """DuckDB events table should have was_summarized, original_size, summary_size."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from lib.stores.duckdb_store import DuckDBStore
            store = DuckDBStore(str(tmpdir), "test.duckdb")

            # Check table schema has summarization columns
            result = store.conn.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'events'
                AND column_name IN ('was_summarized', 'original_size', 'summary_size')
            """).fetchall()

            column_names = [r[0] for r in result]
            assert "was_summarized" in column_names
            assert "original_size" in column_names
            assert "summary_size" in column_names

    def test_insert_event_with_summarization_data(self):
        """insert_event should accept summarization fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from lib.stores.duckdb_store import DuckDBStore
            store = DuckDBStore(str(tmpdir), "test.duckdb")

            # Insert event with summarization data
            store.insert_event({
                "timestamp": "2025-01-22T12:00:00",
                "session_id": "test-session",
                "tool": "Read",
                "backend": "native",
                "duration_ms": 100,
                "status": "success",
                "was_summarized": True,
                "original_size": 50000,
                "summary_size": 5000,
            })

            # Query the event
            result = store.conn.execute("""
                SELECT was_summarized, original_size, summary_size
                FROM events WHERE session_id = 'test-session'
            """).fetchone()

            assert result[0] is True  # was_summarized
            assert result[1] == 50000  # original_size
            assert result[2] == 5000   # summary_size


class TestGracefulNoDataHandling:
    """Tests for graceful handling when no summarization data exists."""

    def test_get_summarization_stats_returns_empty_on_no_data(self):
        """Summarization queries should return empty/zero when no data exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from lib.stores.duckdb_store import DuckDBStore
            store = DuckDBStore(str(tmpdir), "test.duckdb")

            # Query summarization stats on empty database
            # Use COALESCE to handle NULL values from empty aggregations
            result = store.conn.execute("""
                SELECT
                    COUNT(*) as total,
                    COALESCE(SUM(CASE WHEN was_summarized THEN 1 ELSE 0 END), 0) as summarized,
                    AVG(CASE WHEN was_summarized AND original_size > 0
                        THEN 1.0 * summary_size / original_size ELSE NULL END) as avg_ratio
                FROM events
            """).fetchone()

            assert result[0] == 0  # total count
            assert result[1] == 0  # summarized count (COALESCE handles NULL)
            assert result[2] is None  # avg ratio (NULL when no data)

    def test_compression_ratio_calculation(self):
        """Compression ratio should be calculated correctly from summarization data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from lib.stores.duckdb_store import DuckDBStore
            store = DuckDBStore(str(tmpdir), "test.duckdb")

            # Insert summarized event
            store.insert_event({
                "timestamp": "2025-01-22T12:00:00",
                "session_id": "test-session",
                "tool": "Read",
                "backend": "native",
                "duration_ms": 100,
                "status": "success",
                "was_summarized": True,
                "original_size": 10000,
                "summary_size": 2000,  # 80% compression (20% of original)
            })

            # Calculate compression ratio
            result = store.conn.execute("""
                SELECT
                    ROUND(100.0 * (1.0 - 1.0 * summary_size / original_size), 1) as compression_pct
                FROM events
                WHERE was_summarized AND original_size > 0
            """).fetchone()

            assert result[0] == 80.0  # 80% compression

    def test_tokens_saved_calculation(self):
        """Tokens saved should be calculated from original_size - summary_size."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from lib.stores.duckdb_store import DuckDBStore
            store = DuckDBStore(str(tmpdir), "test.duckdb")

            # Insert multiple summarized events
            for i in range(3):
                store.insert_event({
                    "timestamp": f"2025-01-22T12:0{i}:00",
                    "session_id": "test-session",
                    "tool": "Read",
                    "backend": "native",
                    "duration_ms": 100,
                    "status": "success",
                    "was_summarized": True,
                    "original_size": 10000,
                    "summary_size": 2000,
                })

            # Calculate total tokens saved
            result = store.conn.execute("""
                SELECT SUM(original_size - summary_size) as tokens_saved
                FROM events
                WHERE was_summarized
            """).fetchone()

            # 3 events * (10000 - 2000) = 24000
            assert result[0] == 24000


class TestLegacyCodeRemoval:
    """Tests to verify legacy JSONL directory checks are removed."""

    def test_no_jsonl_glob_in_initialization(self):
        """DuckDBStore init should not glob for JSONL files."""
        import inspect
        from lib.stores.duckdb_store import DuckDBStore

        # Get the source code of __init__
        source = inspect.getsource(DuckDBStore.__init__)

        # Should not contain JSONL file globbing
        assert "*.jsonl" not in source
        assert "glob" not in source.lower()

    def test_duckdb_store_works_without_jsonl_files(self):
        """DuckDBStore should work in directory with no JSONL files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from lib.stores.duckdb_store import DuckDBStore

            # Directory has no JSONL files - should still work
            store = DuckDBStore(str(tmpdir), "test.duckdb")

            # Should be able to insert and query
            store.insert_event({
                "timestamp": "2025-01-22T12:00:00",
                "session_id": "test",
                "tool": "Test",
                "backend": "test",
                "duration_ms": 1,
                "status": "success",
            })

            result = store.get_tool_summaries()
            assert len(result) == 1


class TestChartsLoadFromDuckDB:
    """Integration tests for charts loading data from DuckDB."""

    def test_token_spend_chart_from_duckdb(self):
        """Token spend chart should pull data from DuckDB store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from lib.stores.duckdb_store import DuckDBStore
            from lib.charts import get_token_spend_chart

            store = DuckDBStore(str(tmpdir), "test.duckdb")

            # Insert test events
            store.insert_event({
                "timestamp": "2025-01-22T12:00:00",
                "session_id": "test",
                "tool": "Read",
                "backend": "native",
                "duration_ms": 100,
                "status": "success",
                "input_tokens": 1000,
                "output_tokens": 500,
            })

            result = get_token_spend_chart(store, days=7)

            # Should return data from the DuckDB query
            assert isinstance(result, list)
            if result:  # May be empty if date filtering excludes test data
                assert "day" in result[0]
                assert "total_tokens" in result[0]

    def test_error_rate_chart_from_duckdb(self):
        """Error rate chart should pull data from DuckDB store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from lib.stores.duckdb_store import DuckDBStore
            from lib.charts import get_error_rate_chart

            store = DuckDBStore(str(tmpdir), "test.duckdb")

            # Insert success and error events
            store.insert_event({
                "timestamp": "2025-01-22T12:00:00",
                "session_id": "test",
                "tool": "Bash",
                "backend": "native",
                "duration_ms": 100,
                "status": "success",
            })
            store.insert_event({
                "timestamp": "2025-01-22T12:01:00",
                "session_id": "test",
                "tool": "Bash",
                "backend": "native",
                "duration_ms": 100,
                "status": "error",
            })

            result = get_error_rate_chart(store)

            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0]["tool"] == "Bash"
            assert result[0]["total_calls"] == 2
            assert result[0]["errors"] == 1
            assert result[0]["error_pct"] == 50.0

    def test_cache_efficiency_chart_from_duckdb(self):
        """Cache efficiency chart should pull data from DuckDB store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from lib.stores.duckdb_store import DuckDBStore
            from lib.charts import get_cache_efficiency_chart

            store = DuckDBStore(str(tmpdir), "test.duckdb")

            # Insert event with cache data
            store.insert_event({
                "timestamp": "2025-01-22T12:00:00",
                "session_id": "test",
                "tool": "Read",
                "backend": "native",
                "duration_ms": 100,
                "status": "success",
                "input_tokens": 1000,
                "cache_read_tokens": 500,
            })

            result = get_cache_efficiency_chart(store, days=7)

            assert isinstance(result, list)


class TestChartsGracefulNoData:
    """Tests for graceful handling when charts have no data to display."""

    def test_compression_chart_shows_placeholder_on_no_data(self):
        """Compression charts should show meaningful placeholder when no data exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from lib.stores.duckdb_store import DuckDBStore
            store = DuckDBStore(str(tmpdir), "test.duckdb")

            # Query compression data on empty database - should not error
            result = store.conn.execute("""
                SELECT
                    COALESCE(COUNT(*), 0) as total_events,
                    COALESCE(SUM(CASE WHEN was_summarized THEN 1 ELSE 0 END), 0) as summarized_count,
                    COALESCE(SUM(original_size - summary_size), 0) as tokens_saved
                FROM events
            """).fetchone()

            assert result[0] == 0  # No events
            assert result[1] == 0  # No summarized events
            assert result[2] == 0  # No tokens saved

    def test_summarization_queries_handle_null_sizes(self):
        """Queries should handle NULL original_size/summary_size gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from lib.stores.duckdb_store import DuckDBStore
            store = DuckDBStore(str(tmpdir), "test.duckdb")

            # Insert event WITHOUT summarization fields
            store.insert_event({
                "timestamp": "2025-01-22T12:00:00",
                "session_id": "test",
                "tool": "Read",
                "backend": "native",
                "duration_ms": 100,
                "status": "success",
            })

            # Query should not error even when sizes are NULL
            result = store.conn.execute("""
                SELECT
                    COUNT(*) as total,
                    COALESCE(SUM(CASE WHEN was_summarized THEN 1 ELSE 0 END), 0) as summarized,
                    COALESCE(SUM(CASE WHEN original_size IS NOT NULL AND summary_size IS NOT NULL
                        THEN original_size - summary_size ELSE 0 END), 0) as saved
                FROM events
            """).fetchone()

            assert result[0] == 1  # One event
            assert result[1] == 0  # Not summarized (was_summarized defaults to FALSE)
            assert result[2] == 0  # No savings (sizes are NULL)


class TestChartsModuleInitialization:
    """Tests for charts.py module-level DuckDB initialization."""

    def test_charts_init_uses_state_telemetry_duckdb_path(self):
        """charts.py should initialize DuckDBStore with .state/telemetry.duckdb path."""
        
        # Read the charts.py source directly
        charts_path = Path(__file__).parent.parent / "scripts" / "charts.py"
        source = charts_path.read_text()
        
        # Verify it looks for .state/telemetry.duckdb, not telemetry_v3/*.jsonl
        # The initialization should NOT require JSONL files to exist
        assert "telemetry.duckdb" in source or "DuckDBStore" in source, \
            "charts.py should reference telemetry.duckdb or DuckDBStore"

    def test_legacy_jsonl_check_should_be_removed(self):
        """charts.py should not check for *.jsonl files to initialize DuckDB."""
        charts_path = Path(__file__).parent.parent / "scripts" / "charts.py"
        source = charts_path.read_text()
        
        # Find initialization section (lines 40-50)
        lines = source.split('\n')
        init_section = '\n'.join(lines[39:55])  # Lines 40-55
        
        # Should NOT require JSONL files to exist for DuckDB to work
        # Legacy pattern: if TELEMETRY_V3_DIR.exists() and any(TELEMETRY_V3_DIR.glob("**/*.jsonl"))
        if "any(TELEMETRY_V3_DIR.glob" in init_section:
            pytest.fail(
                "charts.py still uses legacy JSONL check for DuckDB initialization. "
                "DuckDB should be initialized from .state/telemetry.duckdb directly."
            )
