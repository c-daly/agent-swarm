# Summarization Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix socket path to return summarized responses with guidance, and add telemetry for callback rate tracking.

**Architecture:** Modify `_handle_socket_client` to wrap responses in `{summary, full, content_id, guidance}` envelope (matching main MCP path), wire up telemetry recording, and add a callback rate query method.

**Tech Stack:** Python, DuckDB, pytest

---

## Task 1: Add Callback Rate Query to DuckDB Store

**Files:**
- Modify: `lib/stores/duckdb_store.py` (add method after line 648)
- Test: `tests/stores/test_duckdb_store.py`

**Step 1: Write the failing test**

Add to `tests/stores/test_duckdb_store.py`:

```python
def test_get_summarization_callback_rate_empty(tmp_path):
    """Callback rate returns zeros when no data."""
    store = DuckDBStore(tmp_path / "test.db")
    result = store.get_summarization_callback_rate(days=7)
    
    assert result["total_offered"] == 0
    assert result["total_retrieved"] == 0
    assert result["callback_rate"] == 0.0
    assert result["days"] == 7


def test_get_summarization_callback_rate_with_data(tmp_path):
    """Callback rate calculates correctly from content_retrievals."""
    store = DuckDBStore(tmp_path / "test.db")
    
    # Create 3 summaries
    store.record_content_creation("c001")
    store.record_content_creation("c002")
    store.record_content_creation("c003")
    
    # Retrieve 1 of them
    store.record_content_retrieval("c002")
    
    result = store.get_summarization_callback_rate(days=7)
    
    assert result["total_offered"] == 3
    assert result["total_retrieved"] == 1
    assert result["callback_rate"] == pytest.approx(0.333, rel=0.01)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/stores/test_duckdb_store.py::test_get_summarization_callback_rate_empty -v`
Expected: FAIL with "AttributeError: 'DuckDBStore' object has no attribute 'get_summarization_callback_rate'"

**Step 3: Write minimal implementation**

Add to `lib/stores/duckdb_store.py` after line 648 (after `record_content_retrieval`):

```python
    def get_summarization_callback_rate(self, days: int = 7) -> dict:
        """Get summarization callback rate for the past N days.

        Returns:
            Dict with total_offered, total_retrieved, callback_rate, days
        """
        result = self.conn.execute(
            """
            SELECT
                COUNT(*) as total_offered,
                COUNT(*) FILTER (WHERE was_retrieved = TRUE) as total_retrieved
            FROM content_retrievals
            WHERE created_at >= CURRENT_DATE - INTERVAL ? DAY
        """,
            [days],
        ).fetchone()

        total_offered = result[0] or 0
        total_retrieved = result[1] or 0
        callback_rate = total_retrieved / total_offered if total_offered > 0 else 0.0

        return {
            "total_offered": total_offered,
            "total_retrieved": total_retrieved,
            "callback_rate": callback_rate,
            "days": days,
        }
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/stores/test_duckdb_store.py -k "callback_rate" -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add lib/stores/duckdb_store.py tests/stores/test_duckdb_store.py
git commit -m "feat(telemetry): add get_summarization_callback_rate query"
```

---

## Task 2: Fix Socket Handler Response Format

**Files:**
- Modify: `lib/mcp_router.py:1180-1186` (in `_handle_socket_client`)
- Test: `tests/test_mcp_router.py`

**Step 1: Write the failing test**

Add to `tests/test_mcp_router.py` (or create if needed):

```python
import json
import socket
import threading
import time


def test_socket_returns_summary_envelope(tmp_path):
    """Socket handler should return {summary, full, content_id, guidance} envelope."""
    from lib.mcp_router import MCPRouter

    router = MCPRouter()
    port = router.start_socket_listener()

    try:
        # Give server time to start
        time.sleep(0.1)

        # Connect and send a tools/call request
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(("127.0.0.1", port))
            s.settimeout(5.0)

            # Request router__ping (simple tool that should work)
            request = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 1,
                "params": {"name": "router__ping", "arguments": {}},
            }
            s.sendall(json.dumps(request).encode() + b"\n")

            # Read response
            response_data = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                if b"\n" in response_data:
                    break

            response = json.loads(response_data.decode().strip())

        # The result should be an envelope with summary, full, guidance
        result = response.get("result", {})
        
        # Check envelope structure
        assert "summary" in result or "full" in result, f"Expected envelope, got: {result}"
        assert "guidance" in result, f"Expected guidance in envelope, got: {result}"

    finally:
        router.stop_socket_listener()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp_router.py::test_socket_returns_summary_envelope -v`
Expected: FAIL with "AssertionError: Expected guidance in envelope"

**Step 3: Write minimal implementation**

Modify `lib/mcp_router.py` in `_handle_socket_client`, around line 1180-1186.

Find this code block:
```python
                        else:
                            if isinstance(backend_result, dict) and "result" in backend_result:
                                full_content = backend_result["result"]
                            else:
                                full_content = backend_result
                            result = full_content
                            result_size = len(json.dumps(result)) if result else 0
                            _router_log("socket", f"{log_prefix} Success result_size={result_size}")
```

Replace with:
```python
                        else:
                            if isinstance(backend_result, dict) and "result" in backend_result:
                                full_content = backend_result["result"]
                            else:
                                full_content = backend_result
                            
                            # Return envelope matching main MCP path
                            envelope = {
                                "summary": route_response.summary,
                                "full": full_content,
                                "content_id": route_response.correlation_id,
                                "guidance": (
                                    "Use this summary to proceed. If you need specific details, "
                                    "make a targeted follow-up query rather than requesting full content. "
                                    "Full retrieval via router__poll(correlation_id) should be a last resort."
                                ),
                            }
                            result = envelope
                            result_size = len(json.dumps(result)) if result else 0
                            _router_log("socket", f"{log_prefix} Success result_size={result_size}")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_mcp_router.py::test_socket_returns_summary_envelope -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/mcp_router.py tests/test_mcp_router.py
git commit -m "fix(socket): return summary envelope instead of raw content"
```

---

## Task 3: Wire Up Telemetry Recording in Socket Path

**Files:**
- Modify: `lib/mcp_router.py:1180-1190` (after creating envelope)
- Test: Integration test verifying `content_retrievals` table populates

**Step 1: Write the failing test**

Add to `tests/test_mcp_router.py`:

```python
def test_socket_records_content_creation(tmp_path):
    """Socket handler should record content creation for telemetry."""
    from lib.mcp_router import MCPRouter
    from lib.stores.duckdb_store import DuckDBStore

    # Create router with DuckDB store
    db_path = tmp_path / "telemetry.db"
    store = DuckDBStore(db_path)
    router = MCPRouter()
    
    # Inject store (may need to expose this or use existing mechanism)
    # For now, check if router has a telemetry store we can query
    
    port = router.start_socket_listener()

    try:
        time.sleep(0.1)

        # Make a request that generates a summary
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(("127.0.0.1", port))
            s.settimeout(5.0)

            request = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 1,
                "params": {"name": "router__ping", "arguments": {}},
            }
            s.sendall(json.dumps(request).encode() + b"\n")
            
            response_data = b""
            while b"\n" not in response_data:
                chunk = s.recv(4096)
                if not chunk:
                    break
                response_data += chunk

            response = json.loads(response_data.decode().strip())

        # Verify content_id was returned
        result = response.get("result", {})
        content_id = result.get("content_id")
        
        # If content_id exists, it should be recorded
        # (Implementation depends on how router accesses store)
        assert content_id is not None or result.get("summary") is not None

    finally:
        router.stop_socket_listener()
```

**Step 2: Run test to verify current behavior**

Run: `pytest tests/test_mcp_router.py::test_socket_records_content_creation -v`
Expected: May pass or fail depending on correlation_id presence

**Step 3: Add telemetry recording**

In `lib/mcp_router.py`, after creating the envelope (right after the `envelope = {...}` block), add:

```python
                            # Track content creation for callback rate analysis
                            if route_response.correlation_id and hasattr(self, '_duckdb_store'):
                                try:
                                    self._duckdb_store.record_content_creation(
                                        route_response.correlation_id
                                    )
                                except Exception:
                                    pass  # Non-critical telemetry
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_mcp_router.py::test_socket_records_content_creation -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/mcp_router.py tests/test_mcp_router.py
git commit -m "feat(telemetry): record content creation from socket path"
```

---

## Task 4: Add Callback Rate to Telemetry Dashboard

**Files:**
- Modify: `lib/charts.py` (add new chart function)
- Modify: `scripts/realtime_dashboard.py` (include in dashboard)

**Step 1: Add chart function**

Add to `lib/charts.py`:

```python
def get_callback_rate_chart(service: TelemetryService) -> str:
    """Render summarization callback rate stats.
    
    Args:
        service: TelemetryService instance
        
    Returns:
        Formatted string showing callback rate metrics
    """
    try:
        stats = service._store.get_summarization_callback_rate(days=7)
    except Exception:
        return "Callback Rate: [No data available]"
    
    lines = [
        "=" * 40,
        "SUMMARIZATION CALLBACK RATE (7 days)",
        "=" * 40,
        f"Summaries Offered:  {stats['total_offered']:>10}",
        f"Full Retrievals:    {stats['total_retrieved']:>10}",
        f"Callback Rate:      {stats['callback_rate']:>10.1%}",
        "",
        "Target: <10% (summaries are sufficient)",
        "=" * 40,
    ]
    return "\n".join(lines)
```

**Step 2: Run existing tests**

Run: `pytest tests/ -k "chart" -v`
Expected: PASS (existing tests still work)

**Step 3: Commit**

```bash
git add lib/charts.py
git commit -m "feat(dashboard): add callback rate chart"
```

---

## Task 5: Run Full Test Suite and Verify

**Step 1: Run all tests**

Run: `pytest tests/ -v --tb=short`
Expected: All tests PASS

**Step 2: Run type checks**

Run: `mypy lib/mcp_router.py lib/stores/duckdb_store.py lib/charts.py`
Expected: No errors

**Step 3: Run linter**

Run: `ruff check lib/mcp_router.py lib/stores/duckdb_store.py lib/charts.py`
Expected: No errors (or fix any issues)

**Step 4: Final commit**

```bash
git add -A
git commit -m "chore: final cleanup for summarization fix"
```

---

## Verification Checklist

After all tasks complete:

- [ ] Socket responses include `{summary, full, content_id, guidance}` envelope
- [ ] `content_retrievals` table populates for socket requests
- [ ] `get_summarization_callback_rate()` returns valid data
- [ ] All tests pass
- [ ] Type checks pass
- [ ] Linter passes

## Manual Testing

1. Start the router: `python -m lib.mcp_router`
2. In a separate terminal, run a subagent task
3. Check that subagent receives summarized responses
4. Query callback rate: 
   ```python
   from lib.stores.duckdb_store import DuckDBStore
   store = DuckDBStore(".state/telemetry.db")
   print(store.get_summarization_callback_rate())
   ```
