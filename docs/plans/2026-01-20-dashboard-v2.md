# Dashboard v2 Implementation Plan

**Goal:** Create a trustworthy telemetry dashboard with proper data abstraction layer, validation, and support for future graph queries.

**Architecture:** Repository pattern with abstract store interfaces (AnalyticsStore, TraceStore, GraphStore) backed by DuckDB initially. Validation layer catches data inconsistencies. Dashboard code never touches database directly.

**Tech Stack:** DuckDB (analytics), Python dataclasses (models), existing charts.py (visualization)

---

## Phase 1: Data Layer Foundation

### Task 1: Create Store Interfaces

**Files:**
- Create: `lib/stores/__init__.py`
- Create: `lib/stores/interfaces.py`
- Test: `tests/test_stores.py`

**Step 1: Write the failing test**

```python
# tests/test_stores.py
"""Tests for telemetry store interfaces and implementations."""
import pytest
from datetime import date
from lib.stores.interfaces import (
    AnalyticsStore,
    TraceStore,
    GraphStore,
    DaySummary,
    ToolCallRecord,
)


def test_analytics_store_is_abstract():
    """AnalyticsStore cannot be instantiated directly."""
    with pytest.raises(TypeError):
        AnalyticsStore()


def test_trace_store_is_abstract():
    """TraceStore cannot be instantiated directly."""
    with pytest.raises(TypeError):
        TraceStore()


def test_graph_store_is_abstract():
    """GraphStore cannot be instantiated directly."""
    with pytest.raises(TypeError):
        GraphStore()


def test_day_summary_dataclass():
    """DaySummary holds daily aggregated metrics."""
    summary = DaySummary(
        date=date(2026, 1, 20),
        sessions=5,
        total_tokens=10000,
        tool_calls=50,
        cache_hits=30,
        cache_ratio=0.6,
        summarizations_offered=20,
        summarizations_accepted=15,
        avg_compression_ratio=0.1,
        tokens_saved=5000,
    )
    assert summary.sessions == 5
    assert summary.cache_ratio == 0.6


def test_tool_call_record_dataclass():
    """ToolCallRecord holds individual tool call data."""
    record = ToolCallRecord(
        session_id="abc123",
        turn_id="turn1",
        timestamp="2026-01-20T10:00:00Z",
        tool="mcp__router__serena__find_symbol",
        duration_ms=250,
        response_size=5000,
        is_cache_hit=False,
        summary_size=500,
        full_requested=True,
        parent_uuid=None,
        is_sidechain=False,
        git_branch="main",
    )
    assert record.tool == "mcp__router__serena__find_symbol"
    assert record.full_requested is True
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_stores.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'lib.stores'"

**Step 3: Create init file**

```python
# lib/stores/__init__.py
"""Telemetry data stores with pluggable backends."""
from .interfaces import (
    AnalyticsStore,
    TraceStore,
    GraphStore,
    DaySummary,
    ToolCallRecord,
    SessionRecord,
    ToolSummary,
    ValidatedMetrics,
)

__all__ = [
    "AnalyticsStore",
    "TraceStore",
    "GraphStore",
    "DaySummary",
    "ToolCallRecord",
    "SessionRecord",
    "ToolSummary",
    "ValidatedMetrics",
]
```

**Step 4: Write interfaces module**

```python
# lib/stores/interfaces.py
"""Abstract interfaces for telemetry data stores.

Separates query types so different backends can handle different needs:
- AnalyticsStore: Aggregations, time series, summaries (DuckDB)
- TraceStore: Individual records, filtering, drill-down (DuckDB)
- GraphStore: Relationships, paths, patterns (Future: Neo4j)
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Any


@dataclass
class DaySummary:
    """Aggregated metrics for a single day."""
    date: date
    sessions: int
    total_tokens: int
    tool_calls: int
    cache_hits: int
    cache_ratio: float
    summarizations_offered: int
    summarizations_accepted: int
    avg_compression_ratio: float
    tokens_saved: int


@dataclass
class ToolCallRecord:
    """Individual tool call with timing and summarization data."""
    session_id: str
    turn_id: str
    timestamp: str
    tool: str
    duration_ms: int
    response_size: int
    is_cache_hit: bool
    summary_size: Optional[int]
    full_requested: Optional[bool]
    parent_uuid: Optional[str]
    is_sidechain: bool
    git_branch: Optional[str]


@dataclass
class SessionRecord:
    """Session-level aggregated data."""
    session_id: str
    date: date
    total_input_tokens: int
    total_output_tokens: int
    tool_calls: int
    cache_hits: int
    hook_count: int
    hook_errors: int
    is_sidechain: bool
    parent_uuid: Optional[str]


@dataclass
class ToolSummary:
    """Aggregated metrics for a specific tool."""
    tool: str
    total_calls: int
    avg_duration_ms: float
    p95_duration_ms: float
    avg_response_size: int
    summarization_rate: float
    full_request_rate: float


@dataclass
class ValidatedMetrics:
    """Metrics with validation status and warnings."""
    data: Any
    warnings: List[str]
    confidence: float  # 0.0-1.0


class AnalyticsStore(ABC):
    """Interface for aggregation and time-series queries.
    
    Suitable backends: DuckDB, PostgreSQL, SQLite
    """

    @abstractmethod
    def get_daily_summary(
        self, date_from: date, date_to: date
    ) -> List[DaySummary]:
        """Get daily aggregated metrics for date range."""
        pass

    @abstractmethod
    def aggregate_by_tool(self, metric: str) -> Dict[str, float]:
        """Aggregate a metric grouped by tool name."""
        pass

    @abstractmethod
    def get_tool_summaries(self) -> List[ToolSummary]:
        """Get per-tool aggregated statistics."""
        pass


class TraceStore(ABC):
    """Interface for individual record queries and filtering.
    
    Suitable backends: DuckDB, MongoDB, PostgreSQL
    """

    @abstractmethod
    def query_tool_calls(
        self,
        tool: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        session_id: Optional[str] = None,
    ) -> List[ToolCallRecord]:
        """Query tool calls with optional filters."""
        pass

    @abstractmethod
    def get_session_events(self, session_id: str) -> List[ToolCallRecord]:
        """Get all events for a specific session."""
        pass

    @abstractmethod
    def get_sessions(
        self, date_from: Optional[date] = None, date_to: Optional[date] = None
    ) -> List[SessionRecord]:
        """Get session records with optional date filter."""
        pass


class GraphStore(ABC):
    """Interface for relationship and pattern queries.
    
    FUTURE: Not implemented yet. Reserved for Neo4j or similar.
    
    Use cases:
    - Trace thoughts -> tool calls -> outcomes
    - Find patterns in summarization decisions
    - Parent-child session relationships
    """

    @abstractmethod
    def get_session_graph(self, session_id: str) -> Dict[str, Any]:
        """Get graph representation of session events."""
        pass

    @abstractmethod
    def find_pattern(self, pattern: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find matches for a graph pattern."""
        pass

    @abstractmethod
    def trace_path(
        self, from_node: str, to_node: str
    ) -> List[Dict[str, Any]]:
        """Find path between two nodes."""
        pass
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/test_stores.py -v`
Expected: PASS (all 4 tests)

**Step 6: Commit**

```bash
git add lib/stores/__init__.py lib/stores/interfaces.py tests/test_stores.py
git commit -m "feat(stores): add abstract store interfaces for telemetry data"
```

---

### Task 2: Add Validation Layer

**Files:**
- Modify: `lib/stores/interfaces.py`
- Create: `lib/stores/validation.py`
- Modify: `tests/test_stores.py`

**Step 1: Write the failing test**

Add to `tests/test_stores.py`:

```python
from lib.stores.validation import validate_day_summary, validate_tool_call


def test_validate_day_summary_clean():
    """Clean data passes validation with high confidence."""
    summary = DaySummary(
        date=date(2026, 1, 20),
        sessions=5,
        total_tokens=10000,
        tool_calls=50,
        cache_hits=30,
        cache_ratio=0.6,
        summarizations_offered=20,
        summarizations_accepted=15,
        avg_compression_ratio=0.1,
        tokens_saved=5000,
    )
    result = validate_day_summary(summary)
    assert result.confidence == 1.0
    assert len(result.warnings) == 0


def test_validate_day_summary_calls_no_tokens():
    """Calls without tokens triggers warning."""
    summary = DaySummary(
        date=date(2026, 1, 20),
        sessions=5,
        total_tokens=0,  # Suspicious!
        tool_calls=50,
        cache_hits=30,
        cache_ratio=0.6,
        summarizations_offered=20,
        summarizations_accepted=15,
        avg_compression_ratio=0.1,
        tokens_saved=0,
    )
    result = validate_day_summary(summary)
    assert result.confidence < 1.0
    assert any("calls but 0 tokens" in w for w in result.warnings)


def test_validate_day_summary_invalid_cache_ratio():
    """Cache ratio > 1.0 triggers warning."""
    summary = DaySummary(
        date=date(2026, 1, 20),
        sessions=5,
        total_tokens=10000,
        tool_calls=50,
        cache_hits=60,  # More hits than calls?
        cache_ratio=1.2,  # Invalid!
        summarizations_offered=20,
        summarizations_accepted=15,
        avg_compression_ratio=0.1,
        tokens_saved=5000,
    )
    result = validate_day_summary(summary)
    assert result.confidence < 1.0
    assert any("cache ratio" in w.lower() for w in result.warnings)


def test_validate_tool_call_missing_summary():
    """Tool call with summarization but no size triggers warning."""
    record = ToolCallRecord(
        session_id="abc123",
        turn_id="turn1",
        timestamp="2026-01-20T10:00:00Z",
        tool="mcp__router__serena__find_symbol",
        duration_ms=250,
        response_size=5000,
        is_cache_hit=False,
        summary_size=None,  # Missing
        full_requested=True,  # But this is set
        parent_uuid=None,
        is_sidechain=False,
        git_branch="main",
    )
    result = validate_tool_call(record)
    assert result.confidence < 1.0
    assert any("full_requested" in w for w in result.warnings)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_stores.py::test_validate_day_summary_clean -v`
Expected: FAIL with "cannot import name 'validate_day_summary'"

**Step 3: Write validation module**

```python
# lib/stores/validation.py
"""Validation layer for telemetry data.

Catches data inconsistencies and provides confidence scores.
Dashboard displays warnings to user when data quality is questionable.
"""
from typing import List
from .interfaces import DaySummary, ToolCallRecord, ValidatedMetrics


def validate_day_summary(summary: DaySummary) -> ValidatedMetrics:
    """Validate a daily summary and return with confidence score.
    
    Checks:
    - If calls > 0, tokens should be > 0
    - Cache ratio should be 0.0-1.0
    - Summarizations accepted <= offered
    - No negative values
    """
    warnings: List[str] = []
    
    # Calls without tokens
    if summary.tool_calls > 0 and summary.total_tokens == 0:
        warnings.append(
            f"Inconsistent: {summary.tool_calls} calls but 0 tokens"
        )
    
    # Invalid cache ratio
    if summary.cache_ratio < 0 or summary.cache_ratio > 1.0:
        warnings.append(
            f"Invalid cache ratio: {summary.cache_ratio:.2f} (expected 0.0-1.0)"
        )
    
    # Cache hits exceed calls
    if summary.cache_hits > summary.tool_calls:
        warnings.append(
            f"Cache hits ({summary.cache_hits}) exceed tool calls ({summary.tool_calls})"
        )
    
    # Summarizations accepted > offered
    if summary.summarizations_accepted > summary.summarizations_offered:
        warnings.append(
            f"Summarizations accepted ({summary.summarizations_accepted}) "
            f"exceeds offered ({summary.summarizations_offered})"
        )
    
    # No data
    if summary.total_tokens == 0 and summary.tool_calls == 0:
        warnings.append("No data recorded for this day")
    
    # Calculate confidence (reduce by 0.2 per warning, min 0.0)
    confidence = max(0.0, 1.0 - (len(warnings) * 0.2))
    
    return ValidatedMetrics(
        data=summary,
        warnings=warnings,
        confidence=confidence,
    )


def validate_tool_call(record: ToolCallRecord) -> ValidatedMetrics:
    """Validate a tool call record.
    
    Checks:
    - If full_requested is set, summary_size should exist
    - Duration should be positive
    - Response size should be positive for non-cache hits
    """
    warnings: List[str] = []
    
    # full_requested without summary data
    if record.full_requested is not None and record.summary_size is None:
        warnings.append(
            "full_requested is set but summary_size is missing"
        )
    
    # Negative duration
    if record.duration_ms < 0:
        warnings.append(f"Negative duration: {record.duration_ms}ms")
    
    # Zero response for non-cache hit
    if not record.is_cache_hit and record.response_size == 0:
        warnings.append(
            "Non-cache-hit call has 0 response_size"
        )
    
    # Suspiciously long duration (> 60 seconds)
    if record.duration_ms > 60000:
        warnings.append(
            f"Unusually long duration: {record.duration_ms}ms"
        )
    
    confidence = max(0.0, 1.0 - (len(warnings) * 0.2))
    
    return ValidatedMetrics(
        data=record,
        warnings=warnings,
        confidence=confidence,
    )
```

**Step 4: Update __init__.py exports**

Add to `lib/stores/__init__.py`:

```python
from .validation import validate_day_summary, validate_tool_call

__all__ = [
    # ... existing exports ...
    "validate_day_summary",
    "validate_tool_call",
]
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/test_stores.py -v`
Expected: PASS (all 8 tests)

**Step 6: Commit**

```bash
git add lib/stores/validation.py lib/stores/__init__.py tests/test_stores.py
git commit -m "feat(stores): add validation layer with confidence scores"
```

---

### Task 3: Implement DuckDB Store

**Files:**
- Create: `lib/stores/duckdb_store.py`
- Modify: `lib/stores/__init__.py`
- Create: `tests/test_duckdb_store.py`

**Step 1: Write the failing test**

```python
# tests/test_duckdb_store.py
"""Tests for DuckDB store implementation."""
import pytest
import json
import tempfile
from datetime import date
from pathlib import Path
from lib.stores.duckdb_store import DuckDBStore
from lib.stores.interfaces import DaySummary, ToolCallRecord


@pytest.fixture
def sample_jsonl(tmp_path):
    """Create sample JSONL data for testing."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    
    jsonl_file = project_dir / "session-abc123.jsonl"
    
    # Sample session data
    events = [
        {
            "type": "assistant",
            "timestamp": "2026-01-20T10:00:00Z",
            "uuid": "turn1",
            "sessionId": "abc123",
            "costUSD": 0.05,
            "durationMs": 1500,
            "message": {"usage": {"input_tokens": 1000, "output_tokens": 500}},
        },
        {
            "type": "tool_use",
            "timestamp": "2026-01-20T10:00:01Z",
            "uuid": "tool1",
            "sessionId": "abc123",
            "toolName": "mcp__router__serena__find_symbol",
            "durationMs": 250,
        },
        {
            "type": "tool_result",
            "timestamp": "2026-01-20T10:00:02Z",
            "uuid": "result1",
            "sessionId": "abc123",
            "toolUseResult": {"content": "x" * 5000},
        },
    ]
    
    with open(jsonl_file, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    
    return tmp_path


def test_duckdb_store_init(sample_jsonl):
    """DuckDBStore initializes with data directory."""
    store = DuckDBStore(str(sample_jsonl))
    assert store is not None


def test_duckdb_store_get_daily_summary(sample_jsonl):
    """DuckDBStore can aggregate daily summaries."""
    store = DuckDBStore(str(sample_jsonl))
    summaries = store.get_daily_summary(
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
    )
    assert len(summaries) >= 1
    assert summaries[0].date == date(2026, 1, 20)
    assert summaries[0].total_tokens > 0


def test_duckdb_store_query_tool_calls(sample_jsonl):
    """DuckDBStore can query individual tool calls."""
    store = DuckDBStore(str(sample_jsonl))
    calls = store.query_tool_calls()
    assert len(calls) >= 1
    assert calls[0].tool == "mcp__router__serena__find_symbol"


def test_duckdb_store_get_sessions(sample_jsonl):
    """DuckDBStore can list sessions."""
    store = DuckDBStore(str(sample_jsonl))
    sessions = store.get_sessions()
    assert len(sessions) >= 1
    assert sessions[0].session_id == "abc123"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_duckdb_store.py::test_duckdb_store_init -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'lib.stores.duckdb_store'"

**Step 3: Write DuckDB store implementation**

```python
# lib/stores/duckdb_store.py
"""DuckDB implementation of telemetry stores.

Queries JSONL files directly without requiring data import.
Implements both AnalyticsStore and TraceStore interfaces.
"""
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Any

try:
    import duckdb
except ImportError:
    duckdb = None

from .interfaces import (
    AnalyticsStore,
    TraceStore,
    DaySummary,
    ToolCallRecord,
    SessionRecord,
    ToolSummary,
)


class DuckDBStore(AnalyticsStore, TraceStore):
    """DuckDB-backed store that queries JSONL files directly.
    
    Attributes:
        data_dir: Directory containing JSONL session files
        conn: DuckDB connection (in-memory)
    """

    def __init__(self, data_dir: str):
        """Initialize store with path to data directory.
        
        Args:
            data_dir: Path to directory containing JSONL files
                     (e.g., ~/.claude/projects)
        """
        if duckdb is None:
            raise ImportError(
                "duckdb is required for DuckDBStore. "
                "Install with: pip install duckdb"
            )
        
        self.data_dir = Path(data_dir).expanduser()
        self.conn = duckdb.connect()  # In-memory database
        self._setup_views()

    def _setup_views(self):
        """Create views for querying JSONL data."""
        # Find all JSONL files
        jsonl_pattern = str(self.data_dir / "**" / "*.jsonl")
        
        # Create a view that reads all JSONL files
        self.conn.execute(f"""
            CREATE OR REPLACE VIEW raw_events AS
            SELECT * FROM read_json_auto('{jsonl_pattern}', 
                                          ignore_errors=true,
                                          maximum_object_size=10485760)
        """)

    def get_daily_summary(
        self, date_from: date, date_to: date
    ) -> List[DaySummary]:
        """Get daily aggregated metrics for date range."""
        query = """
            SELECT 
                CAST(timestamp AS DATE) as day,
                COUNT(DISTINCT sessionId) as sessions,
                SUM(CASE WHEN type = 'assistant' 
                    THEN COALESCE(
                        json_extract(message, '$.usage.input_tokens')::INT, 0
                    ) + COALESCE(
                        json_extract(message, '$.usage.output_tokens')::INT, 0
                    )
                    ELSE 0 END) as total_tokens,
                COUNT(CASE WHEN type = 'tool_use' THEN 1 END) as tool_calls,
                0 as cache_hits,  -- TODO: Parse from cache data
                0.0 as cache_ratio,
                0 as summarizations_offered,
                0 as summarizations_accepted,
                0.0 as avg_compression_ratio,
                0 as tokens_saved
            FROM raw_events
            WHERE timestamp >= ? AND timestamp < ?
            GROUP BY CAST(timestamp AS DATE)
            ORDER BY day
        """
        
        result = self.conn.execute(
            query, 
            [date_from.isoformat(), (date_to.isoformat())]
        ).fetchall()
        
        return [
            DaySummary(
                date=row[0],
                sessions=row[1],
                total_tokens=row[2] or 0,
                tool_calls=row[3] or 0,
                cache_hits=row[4] or 0,
                cache_ratio=row[5] or 0.0,
                summarizations_offered=row[6] or 0,
                summarizations_accepted=row[7] or 0,
                avg_compression_ratio=row[8] or 0.0,
                tokens_saved=row[9] or 0,
            )
            for row in result
        ]

    def aggregate_by_tool(self, metric: str) -> Dict[str, float]:
        """Aggregate a metric grouped by tool name."""
        valid_metrics = {"count", "avg_duration", "total_duration"}
        if metric not in valid_metrics:
            raise ValueError(f"Invalid metric: {metric}. Use: {valid_metrics}")
        
        if metric == "count":
            agg = "COUNT(*)"
        elif metric == "avg_duration":
            agg = "AVG(durationMs)"
        else:
            agg = "SUM(durationMs)"
        
        query = f"""
            SELECT toolName, {agg} as value
            FROM raw_events
            WHERE type = 'tool_use' AND toolName IS NOT NULL
            GROUP BY toolName
        """
        
        result = self.conn.execute(query).fetchall()
        return {row[0]: row[1] for row in result}

    def get_tool_summaries(self) -> List[ToolSummary]:
        """Get per-tool aggregated statistics."""
        query = """
            SELECT 
                toolName,
                COUNT(*) as total_calls,
                AVG(durationMs) as avg_duration_ms,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY durationMs) as p95_duration_ms,
                0 as avg_response_size,  -- TODO: Parse from result
                0.0 as summarization_rate,
                0.0 as full_request_rate
            FROM raw_events
            WHERE type = 'tool_use' AND toolName IS NOT NULL
            GROUP BY toolName
            ORDER BY total_calls DESC
        """
        
        result = self.conn.execute(query).fetchall()
        
        return [
            ToolSummary(
                tool=row[0],
                total_calls=row[1],
                avg_duration_ms=row[2] or 0.0,
                p95_duration_ms=row[3] or 0.0,
                avg_response_size=row[4] or 0,
                summarization_rate=row[5] or 0.0,
                full_request_rate=row[6] or 0.0,
            )
            for row in result
        ]

    def query_tool_calls(
        self,
        tool: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        session_id: Optional[str] = None,
    ) -> List[ToolCallRecord]:
        """Query tool calls with optional filters."""
        conditions = ["type = 'tool_use'"]
        params = []
        
        if tool:
            conditions.append("toolName = ?")
            params.append(tool)
        if date_from:
            conditions.append("timestamp >= ?")
            params.append(date_from.isoformat())
        if date_to:
            conditions.append("timestamp < ?")
            params.append(date_to.isoformat())
        if session_id:
            conditions.append("sessionId = ?")
            params.append(session_id)
        
        where_clause = " AND ".join(conditions)
        
        query = f"""
            SELECT 
                sessionId,
                uuid,
                timestamp,
                toolName,
                COALESCE(durationMs, 0) as durationMs,
                0 as response_size,  -- TODO: Join with tool_result
                false as is_cache_hit,
                NULL as summary_size,
                NULL as full_requested,
                parentUuid,
                COALESCE(isSidechain, false) as isSidechain,
                gitBranch
            FROM raw_events
            WHERE {where_clause}
            ORDER BY timestamp
        """
        
        result = self.conn.execute(query, params).fetchall()
        
        return [
            ToolCallRecord(
                session_id=row[0] or "",
                turn_id=row[1] or "",
                timestamp=str(row[2]) if row[2] else "",
                tool=row[3] or "",
                duration_ms=row[4] or 0,
                response_size=row[5] or 0,
                is_cache_hit=row[6] or False,
                summary_size=row[7],
                full_requested=row[8],
                parent_uuid=row[9],
                is_sidechain=row[10] or False,
                git_branch=row[11],
            )
            for row in result
        ]

    def get_session_events(self, session_id: str) -> List[ToolCallRecord]:
        """Get all tool calls for a specific session."""
        return self.query_tool_calls(session_id=session_id)

    def get_sessions(
        self, date_from: Optional[date] = None, date_to: Optional[date] = None
    ) -> List[SessionRecord]:
        """Get session records with optional date filter."""
        conditions = ["1=1"]
        params = []
        
        if date_from:
            conditions.append("MIN(timestamp) >= ?")
            params.append(date_from.isoformat())
        if date_to:
            conditions.append("MIN(timestamp) < ?")
            params.append(date_to.isoformat())
        
        having_clause = " AND ".join(conditions)
        
        query = f"""
            SELECT 
                sessionId,
                CAST(MIN(timestamp) AS DATE) as session_date,
                SUM(CASE WHEN type = 'assistant' 
                    THEN COALESCE(
                        json_extract(message, '$.usage.input_tokens')::INT, 0
                    ) ELSE 0 END) as input_tokens,
                SUM(CASE WHEN type = 'assistant' 
                    THEN COALESCE(
                        json_extract(message, '$.usage.output_tokens')::INT, 0
                    ) ELSE 0 END) as output_tokens,
                COUNT(CASE WHEN type = 'tool_use' THEN 1 END) as tool_calls,
                0 as cache_hits,
                0 as hook_count,
                0 as hook_errors,
                COALESCE(MAX(isSidechain), false) as is_sidechain,
                MAX(parentUuid) as parent_uuid
            FROM raw_events
            WHERE sessionId IS NOT NULL
            GROUP BY sessionId
            HAVING {having_clause}
            ORDER BY session_date DESC
        """
        
        result = self.conn.execute(query, params).fetchall()
        
        return [
            SessionRecord(
                session_id=row[0] or "",
                date=row[1] if row[1] else date.today(),
                total_input_tokens=row[2] or 0,
                total_output_tokens=row[3] or 0,
                tool_calls=row[4] or 0,
                cache_hits=row[5] or 0,
                hook_count=row[6] or 0,
                hook_errors=row[7] or 0,
                is_sidechain=row[8] or False,
                parent_uuid=row[9],
            )
            for row in result
        ]
```

**Step 4: Update __init__.py exports**

Add to `lib/stores/__init__.py`:

```python
from .duckdb_store import DuckDBStore

__all__ = [
    # ... existing exports ...
    "DuckDBStore",
]
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/test_duckdb_store.py -v`
Expected: PASS (all 4 tests)

**Step 6: Commit**

```bash
git add lib/stores/duckdb_store.py lib/stores/__init__.py tests/test_duckdb_store.py
git commit -m "feat(stores): add DuckDB store implementation"
```

---

### Task 4: Create Telemetry Service Facade

**Files:**
- Create: `lib/telemetry_service.py`
- Create: `tests/test_telemetry_service.py`

**Step 1: Write the failing test**

```python
# tests/test_telemetry_service.py
"""Tests for TelemetryService facade."""
import pytest
from datetime import date
from unittest.mock import Mock, MagicMock
from lib.telemetry_service import TelemetryService
from lib.stores.interfaces import (
    AnalyticsStore,
    TraceStore,
    DaySummary,
    ToolCallRecord,
)


@pytest.fixture
def mock_analytics():
    """Create mock analytics store."""
    store = Mock(spec=AnalyticsStore)
    store.get_daily_summary.return_value = [
        DaySummary(
            date=date(2026, 1, 20),
            sessions=5,
            total_tokens=10000,
            tool_calls=50,
            cache_hits=30,
            cache_ratio=0.6,
            summarizations_offered=20,
            summarizations_accepted=15,
            avg_compression_ratio=0.1,
            tokens_saved=5000,
        )
    ]
    return store


@pytest.fixture
def mock_traces():
    """Create mock trace store."""
    store = Mock(spec=TraceStore)
    store.query_tool_calls.return_value = [
        ToolCallRecord(
            session_id="abc123",
            turn_id="turn1",
            timestamp="2026-01-20T10:00:00Z",
            tool="find_symbol",
            duration_ms=250,
            response_size=5000,
            is_cache_hit=False,
            summary_size=500,
            full_requested=False,
            parent_uuid=None,
            is_sidechain=False,
            git_branch="main",
        )
    ]
    return store


def test_telemetry_service_init(mock_analytics):
    """TelemetryService initializes with analytics store."""
    service = TelemetryService(analytics=mock_analytics)
    assert service.analytics is mock_analytics


def test_telemetry_service_traces_defaults_to_analytics(mock_analytics):
    """If no trace store provided, analytics is used."""
    # Only works if analytics implements TraceStore too
    mock_analytics.query_tool_calls = Mock(return_value=[])
    service = TelemetryService(analytics=mock_analytics)
    assert service.traces is mock_analytics


def test_telemetry_service_separate_traces(mock_analytics, mock_traces):
    """Can provide separate trace store."""
    service = TelemetryService(
        analytics=mock_analytics,
        traces=mock_traces,
    )
    assert service.traces is mock_traces
    assert service.analytics is mock_analytics


def test_telemetry_service_get_validated_summary(mock_analytics):
    """get_validated_summary returns data with validation."""
    service = TelemetryService(analytics=mock_analytics)
    results = service.get_validated_daily_summary(
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
    )
    assert len(results) == 1
    assert results[0].confidence == 1.0
    assert results[0].data.sessions == 5


def test_telemetry_service_graph_optional():
    """Graph store is optional."""
    mock_analytics = Mock(spec=AnalyticsStore)
    service = TelemetryService(analytics=mock_analytics)
    assert service.graph is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_telemetry_service.py::test_telemetry_service_init -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'lib.telemetry_service'"

**Step 3: Write telemetry service**

```python
# lib/telemetry_service.py
"""Facade for telemetry data access.

Routes queries to appropriate backend stores. Dashboard code
should use this service rather than accessing stores directly.
"""
from datetime import date
from typing import List, Optional

from lib.stores.interfaces import (
    AnalyticsStore,
    TraceStore,
    GraphStore,
    DaySummary,
    ToolCallRecord,
    SessionRecord,
    ToolSummary,
    ValidatedMetrics,
)
from lib.stores.validation import validate_day_summary, validate_tool_call


class TelemetryService:
    """Unified interface for telemetry data.
    
    Attributes:
        analytics: Store for aggregation queries
        traces: Store for individual record queries
        graph: Optional store for relationship queries
    """

    def __init__(
        self,
        analytics: AnalyticsStore,
        traces: Optional[TraceStore] = None,
        graph: Optional[GraphStore] = None,
    ):
        """Initialize service with backend stores.
        
        Args:
            analytics: Required store for aggregations
            traces: Optional separate store for traces.
                   Defaults to analytics if it implements TraceStore.
            graph: Optional store for graph queries (future)
        """
        self.analytics = analytics
        self.traces = traces if traces is not None else analytics
        self.graph = graph

    def get_validated_daily_summary(
        self, date_from: date, date_to: date
    ) -> List[ValidatedMetrics]:
        """Get daily summaries with validation.
        
        Returns:
            List of ValidatedMetrics containing DaySummary data
            plus warnings and confidence scores.
        """
        summaries = self.analytics.get_daily_summary(date_from, date_to)
        return [validate_day_summary(s) for s in summaries]

    def get_daily_summary(
        self, date_from: date, date_to: date
    ) -> List[DaySummary]:
        """Get daily summaries without validation wrapper."""
        return self.analytics.get_daily_summary(date_from, date_to)

    def get_tool_summaries(self) -> List[ToolSummary]:
        """Get per-tool aggregated statistics."""
        return self.analytics.get_tool_summaries()

    def query_tool_calls(
        self,
        tool: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        session_id: Optional[str] = None,
        validate: bool = False,
    ) -> List[ToolCallRecord] | List[ValidatedMetrics]:
        """Query tool calls with optional validation.
        
        Args:
            validate: If True, return ValidatedMetrics wrappers
        """
        calls = self.traces.query_tool_calls(
            tool=tool,
            date_from=date_from,
            date_to=date_to,
            session_id=session_id,
        )
        
        if validate:
            return [validate_tool_call(c) for c in calls]
        return calls

    def get_sessions(
        self, date_from: Optional[date] = None, date_to: Optional[date] = None
    ) -> List[SessionRecord]:
        """Get session records."""
        return self.traces.get_sessions(date_from, date_to)

    def get_session_events(self, session_id: str) -> List[ToolCallRecord]:
        """Get all events for a specific session."""
        return self.traces.get_session_events(session_id)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_telemetry_service.py -v`
Expected: PASS (all 5 tests)

**Step 5: Commit**

```bash
git add lib/telemetry_service.py tests/test_telemetry_service.py
git commit -m "feat: add TelemetryService facade for data access"
```

---

## Phase 2: Dashboard Migration

### Task 5: Update charts.py to Use TelemetryService

**Files:**
- Modify: `lib/charts.py`
- Modify: `tests/test_charts.py` (if exists)

**Step 1: Read current charts.py structure**

Run: `python3 -c "from lib.stores.interfaces import DaySummary; print('imports work')"`
Expected: "imports work"

**Step 2: Add TelemetryService integration**

At the top of `lib/charts.py`, add:

```python
# Optional: Use new data layer if available
try:
    from lib.telemetry_service import TelemetryService
    from lib.stores.duckdb_store import DuckDBStore
    NEW_DATA_LAYER = True
except ImportError:
    NEW_DATA_LAYER = False
```

**Step 3: Create factory function**

Add function to `lib/charts.py`:

```python
def get_telemetry_service(data_dir: str = None) -> Optional[TelemetryService]:
    """Get TelemetryService instance if new data layer is available.
    
    Args:
        data_dir: Path to JSONL data. Defaults to ~/.claude/projects
    
    Returns:
        TelemetryService or None if not available
    """
    if not NEW_DATA_LAYER:
        return None
    
    if data_dir is None:
        data_dir = str(Path.home() / ".claude" / "projects")
    
    try:
        store = DuckDBStore(data_dir)
        return TelemetryService(analytics=store)
    except Exception as e:
        print(f"Warning: Could not initialize TelemetryService: {e}")
        return None
```

**Step 4: Run existing tests**

Run: `pytest tests/test_charts.py -v` (if exists)
Expected: PASS (no regressions)

**Step 5: Commit**

```bash
git add lib/charts.py
git commit -m "feat(charts): add TelemetryService integration"
```

---

## Phase 3: Future Work (Not in This Plan)

The following are documented for future implementation:

### Summarization v2
- Modify `hooks/mcp-summarizer.py` to send summary-only
- Add full content request mechanism
- Implement trace logging for acceptance tracking

### Graph Support
- Add Neo4j or NetworkX integration
- Implement GraphStore for session graphs
- Add pattern detection queries

### Connection/Timing Dashboard
- Surface MCP Router socket events
- Add per-backend latency charts
- Show timeout events

---

## Dependency Installation

Before starting, ensure DuckDB is installed:

```bash
pip install duckdb
```

Add to requirements.txt if it exists:
```
duckdb>=0.9.0
```

---

## Verification Checklist

After completing all tasks:

- [ ] All tests pass: `pytest tests/test_stores.py tests/test_duckdb_store.py tests/test_telemetry_service.py -v`
- [ ] Lint passes: `ruff check lib/stores/ lib/telemetry_service.py`
- [ ] Type check passes (if applicable): `mypy lib/stores/ lib/telemetry_service.py`
- [ ] Can query actual JSONL data: `python3 -c "from lib.stores.duckdb_store import DuckDBStore; s = DuckDBStore('~/.claude/projects'); print(s.get_sessions()[:3])"`
