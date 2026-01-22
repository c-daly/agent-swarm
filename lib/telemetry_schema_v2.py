#!/usr/bin/env python3
"""
Telemetry Schema v2.0 - Unified telemetry data structure.

This module defines the v2.0 telemetry schema which consolidates:
- daily_summaries
- historical_timeline
- aggregates
- cache_stats

Into a single coherent structure with:
- days{} for per-day data with session drill-down
- aggregates{} for rolling time windows
- filters{} for dashboard dropdowns
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from typing import TypedDict, Optional, Any
import json
from pathlib import Path


# ─────────────────────────────────────────────────────────────────
# Type Definitions
# ─────────────────────────────────────────────────────────────────

class TokenData(TypedDict, total=False):
    """Token usage data."""
    input: int
    output: int
    cache_read: int
    cache_creation: int
    source: str  # "jsonl" | "router" | "estimated"


class CallData(TypedDict, total=False):
    """Call statistics."""
    total: int
    by_tool: dict[str, int]
    by_backend: dict[str, int]


class SummarizationData(TypedDict, total=False):
    """Summarization tracking."""
    offered: int
    accepted: int
    rejected: int
    acceptance_rate: float
    tokens_saved_est: int


class BackendTiming(TypedDict, total=False):
    """Timing stats for a backend."""
    avg_ms: float
    p95_ms: float
    count: int
    total_ms: int  # For incremental updates


class TimingData(TypedDict, total=False):
    """Response timing data."""
    avg_response_ms: float
    p95_response_ms: float
    by_backend: dict[str, BackendTiming]


class SessionData(TypedDict, total=False):
    """Per-session data within a day."""
    start: str  # ISO timestamp
    end: str    # ISO timestamp
    tokens: TokenData
    calls: CallData
    summarization: SummarizationData


class DayData(TypedDict, total=False):
    """Data for a single day."""
    tokens: TokenData
    calls: CallData
    summarization: SummarizationData
    timing: TimingData
    sessions: list[str]
    by_session: dict[str, SessionData]


class AggregateData(TypedDict, total=False):
    """Aggregated statistics."""
    tokens: TokenData
    calls: CallData
    summarization: SummarizationData


class FilterData(TypedDict, total=False):
    """Available filter options for dashboard."""
    available_tools: list[str]
    available_backends: list[str]
    available_sessions: list[str]


class ProcessedFiles(TypedDict, total=False):
    """Tracking of processed JSONL files."""
    session_logs: list[str]
    last_scan: str  # ISO timestamp


class TelemetryV2(TypedDict, total=False):
    """Root telemetry structure v2.0."""
    version: str
    last_updated: str
    processed_files: ProcessedFiles
    days: dict[str, DayData]
    aggregates: dict[str, AggregateData]  # all_time, last_7_days, last_30_days
    filters: FilterData


# ─────────────────────────────────────────────────────────────────
# Factory Functions
# ─────────────────────────────────────────────────────────────────

def default_token_data(source: str = "router") -> TokenData:
    """Create empty token data structure."""
    return {
        "input": 0,
        "output": 0,
        "cache_read": 0,
        "cache_creation": 0,
        "source": source,
    }


def default_call_data() -> CallData:
    """Create empty call data structure."""
    return {
        "total": 0,
        "by_tool": {},
        "by_backend": {},
    }


def default_summarization_data() -> SummarizationData:
    """Create empty summarization data structure."""
    return {
        "offered": 0,
        "accepted": 0,
        "rejected": 0,
        "acceptance_rate": 0.0,
        "tokens_saved_est": 0,
    }


def default_timing_data() -> TimingData:
    """Create empty timing data structure."""
    return {
        "avg_response_ms": 0.0,
        "p95_response_ms": 0.0,
        "by_backend": {},
    }


def default_day_data() -> DayData:
    """Create empty day data structure."""
    return {
        "tokens": default_token_data(),
        "calls": default_call_data(),
        "summarization": default_summarization_data(),
        "timing": default_timing_data(),
        "sessions": [],
        "by_session": {},
    }


def default_aggregate_data() -> AggregateData:
    """Create empty aggregate data structure."""
    return {
        "tokens": default_token_data(),
        "calls": default_call_data(),
        "summarization": default_summarization_data(),
    }


def default_telemetry_v2() -> TelemetryV2:
    """Create empty v2.0 telemetry structure."""
    return {
        "version": "2.0",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "processed_files": {
            "session_logs": [],
            "last_scan": "",
        },
        "days": {},
        "aggregates": {
            "all_time": default_aggregate_data(),
            "last_7_days": default_aggregate_data(),
            "last_30_days": default_aggregate_data(),
        },
        "filters": {
            "available_tools": [],
            "available_backends": [],
            "available_sessions": [],
        },
    }


# ─────────────────────────────────────────────────────────────────
# Update Functions
# ─────────────────────────────────────────────────────────────────

def ensure_day(telemetry: TelemetryV2, day_key: str) -> DayData:
    """Ensure a day entry exists and return it."""
    if "days" not in telemetry:
        telemetry["days"] = {}
    if day_key not in telemetry["days"]:
        telemetry["days"][day_key] = default_day_data()
    return telemetry["days"][day_key]


def update_timing_stats(timing: TimingData, backend: str, latency_ms: int) -> None:
    """Update timing statistics with a new latency measurement."""
    by_backend = timing.setdefault("by_backend", {})
    
    if backend not in by_backend:
        by_backend[backend] = {
            "avg_ms": latency_ms,
            "p95_ms": latency_ms,
            "count": 1,
            "total_ms": latency_ms,
        }
    else:
        stats = by_backend[backend]
        stats["count"] = stats.get("count", 0) + 1
        stats["total_ms"] = stats.get("total_ms", 0) + latency_ms
        stats["avg_ms"] = stats["total_ms"] / stats["count"]
        # p95 approximation: use max as rough estimate
        stats["p95_ms"] = max(stats.get("p95_ms", 0), latency_ms)


def update_summarization_rate(summarization: SummarizationData) -> None:
    """Recalculate acceptance rate."""
    offered = summarization.get("offered", 0)
    if offered > 0:
        accepted = summarization.get("accepted", 0)
        summarization["acceptance_rate"] = round(accepted / offered, 3)


def add_to_filters(filters: FilterData, tool: str = None, backend: str = None, session: str = None) -> None:
    """Add items to filter lists (deduplicating)."""
    if tool and tool not in filters.get("available_tools", []):
        filters.setdefault("available_tools", []).append(tool)
    if backend and backend not in filters.get("available_backends", []):
        filters.setdefault("available_backends", []).append(backend)
    if session and session not in filters.get("available_sessions", []):
        filters.setdefault("available_sessions", []).append(session)


def merge_tokens(target: TokenData, source: TokenData) -> None:
    """Merge token data from source into target."""
    for key in ["input", "output", "cache_read", "cache_creation"]:
        target[key] = target.get(key, 0) + source.get(key, 0)
    # Prefer actual source over estimates
    if source.get("source") == "jsonl":
        target["source"] = "jsonl"


def merge_calls(target: CallData, source: CallData) -> None:
    """Merge call data from source into target."""
    target["total"] = target.get("total", 0) + source.get("total", 0)
    
    for tool, count in source.get("by_tool", {}).items():
        # Handle corrupted data where count might be a dict instead of int
        if isinstance(count, dict):
            count = count.get("count", 0)
        target.setdefault("by_tool", {})[tool] = target.get("by_tool", {}).get(tool, 0) + count

    for backend, count in source.get("by_backend", {}).items():
        # Handle corrupted data where count might be a dict instead of int
        if isinstance(count, dict):
            count = count.get("count", 0)
        target.setdefault("by_backend", {})[backend] = target.get("by_backend", {}).get(backend, 0) + count


# ─────────────────────────────────────────────────────────────────
# Aggregate Functions
# ─────────────────────────────────────────────────────────────────

def recompute_aggregates(telemetry: TelemetryV2) -> None:
    """Recompute all aggregate statistics from days data."""
    from datetime import timedelta
    
    today = date.today()
    days = telemetry.get("days", {})
    
    # Reset aggregates
    all_time = default_aggregate_data()
    last_7 = default_aggregate_data()
    last_30 = default_aggregate_data()
    
    for day_key, day_data in days.items():
        try:
            day_date = date.fromisoformat(day_key)
        except ValueError:
            continue
        
        days_ago = (today - day_date).days
        
        # All time
        merge_tokens(all_time["tokens"], day_data.get("tokens", {}))
        merge_calls(all_time["calls"], day_data.get("calls", {}))
        
        # Last 7 days
        if days_ago <= 7:
            merge_tokens(last_7["tokens"], day_data.get("tokens", {}))
            merge_calls(last_7["calls"], day_data.get("calls", {}))
        
        # Last 30 days
        if days_ago <= 30:
            merge_tokens(last_30["tokens"], day_data.get("tokens", {}))
            merge_calls(last_30["calls"], day_data.get("calls", {}))
    
    telemetry["aggregates"] = {
        "all_time": all_time,
        "last_7_days": last_7,
        "last_30_days": last_30,
    }


def update_filter_options(telemetry: TelemetryV2) -> None:
    """Rebuild filter options from all days data."""
    tools = set()
    backends = set()
    sessions = set()
    
    for day_data in telemetry.get("days", {}).values():
        tools.update(day_data.get("calls", {}).get("by_tool", {}).keys())
        backends.update(day_data.get("calls", {}).get("by_backend", {}).keys())
        sessions.update(day_data.get("sessions", []))
    
    telemetry["filters"] = {
        "available_tools": sorted(tools),
        "available_backends": sorted(backends),
        "available_sessions": sorted(sessions),
    }


# ─────────────────────────────────────────────────────────────────
# I/O Functions
# ─────────────────────────────────────────────────────────────────

def load_telemetry_v2(path: Path) -> TelemetryV2:
    """Load telemetry from file, returning default if not found or invalid."""
    if not path.exists():
        return default_telemetry_v2()
    
    try:
        with open(path) as f:
            data = json.load(f)
        
        # Check version
        if data.get("version") != "2.0":
            # Not v2, return default (migration should handle conversion)
            return default_telemetry_v2()
        
        return data
    except (json.JSONDecodeError, IOError):
        return default_telemetry_v2()


def save_telemetry_v2(telemetry: TelemetryV2, path: Path) -> None:
    """Save telemetry to file."""
    telemetry["last_updated"] = datetime.now(timezone.utc).isoformat()
    
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, "w") as f:
        json.dump(telemetry, f, indent=2)


if __name__ == "__main__":
    # Test: create and print default structure
    t = default_telemetry_v2()
    print(json.dumps(t, indent=2))
