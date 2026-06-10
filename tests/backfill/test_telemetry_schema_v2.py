#!/usr/bin/env python3
"""Characterization tests for lib.telemetry_schema_v2."""

import json
from datetime import datetime, date, timedelta
from lib.telemetry_schema_v2 import (
    default_token_data, default_call_data, default_summarization_data,
    default_timing_data, default_day_data, default_aggregate_data, default_telemetry_v2,
    ensure_day, update_timing_stats, update_summarization_rate,
    add_to_filters, merge_tokens, merge_calls, recompute_aggregates, update_filter_options,
    load_telemetry_v2, save_telemetry_v2,
)


class TestDefaultTokenData:
    def test_returns_empty_structure(self):
        tokens = default_token_data()
        assert tokens["input"] == 0
        assert tokens["output"] == 0
        assert tokens["cache_read"] == 0
        assert tokens["cache_creation"] == 0
        assert tokens["source"] == "router"

    def test_accepts_source_parameter(self):
        tokens = default_token_data(source="jsonl")
        assert tokens["source"] == "jsonl"

    def test_returns_dict(self):
        tokens = default_token_data()
        assert isinstance(tokens, dict)


class TestDefaultCallData:
    def test_returns_empty_structure(self):
        calls = default_call_data()
        assert calls["total"] == 0
        assert calls["by_tool"] == {}
        assert calls["by_backend"] == {}

    def test_returns_dict(self):
        calls = default_call_data()
        assert isinstance(calls, dict)


class TestDefaultSummarizationData:
    def test_returns_empty_structure(self):
        summ = default_summarization_data()
        assert summ["offered"] == 0
        assert summ["accepted"] == 0
        assert summ["rejected"] == 0
        assert summ["acceptance_rate"] == 0.0
        assert summ["tokens_saved_est"] == 0


class TestDefaultTimingData:
    def test_returns_empty_structure(self):
        timing = default_timing_data()
        assert timing["avg_response_ms"] == 0.0
        assert timing["p95_response_ms"] == 0.0
        assert timing["by_backend"] == {}


class TestDefaultDayData:
    def test_returns_empty_structure(self):
        day = default_day_data()
        assert "tokens" in day
        assert "calls" in day
        assert "summarization" in day
        assert "timing" in day
        assert day["sessions"] == []
        assert day["by_session"] == {}


class TestDefaultAggregateData:
    def test_returns_empty_structure(self):
        agg = default_aggregate_data()
        assert "tokens" in agg
        assert "calls" in agg
        assert "summarization" in agg


class TestDefaultTelemetryV2:
    def test_returns_empty_structure(self):
        tel = default_telemetry_v2()
        assert tel["version"] == "2.0"
        assert isinstance(tel.get("days", {}), dict)
        assert isinstance(tel.get("aggregates", {}), dict)
        assert isinstance(tel.get("filters", {}), dict)

    def test_has_default_aggregates(self):
        tel = default_telemetry_v2()
        aggs = tel.get("aggregates", {})
        assert "all_time" in aggs
        assert "last_7_days" in aggs
        assert "last_30_days" in aggs


class TestEnsureDay:
    def test_creates_missing_day(self):
        tel = default_telemetry_v2()
        day_data = ensure_day(tel, "2026-06-10")
        assert "2026-06-10" in tel.get("days", {})
        assert day_data["tokens"]["input"] == 0

    def test_returns_existing_day_unchanged(self):
        tel = default_telemetry_v2()
        day_data1 = ensure_day(tel, "2026-06-10")
        day_data1["tokens"]["input"] = 100
        day_data2 = ensure_day(tel, "2026-06-10")
        assert day_data2["tokens"]["input"] == 100

    def test_creates_days_dict_if_missing(self):
        tel = {"version": "2.0"}
        ensure_day(tel, "2026-06-10")
        assert "days" in tel
        assert "2026-06-10" in tel["days"]


class TestUpdateTimingStats:
    def test_creates_backend_entry(self):
        timing = default_timing_data()
        update_timing_stats(timing, "claude", 100)
        assert "claude" in timing["by_backend"]
        assert timing["by_backend"]["claude"]["count"] == 1
        assert timing["by_backend"]["claude"]["avg_ms"] == 100
        assert timing["by_backend"]["claude"]["total_ms"] == 100

    def test_accumulates_multiple_latencies(self):
        timing = default_timing_data()
        update_timing_stats(timing, "claude", 100)
        update_timing_stats(timing, "claude", 200)
        update_timing_stats(timing, "claude", 300)
        stats = timing["by_backend"]["claude"]
        assert stats["count"] == 3
        assert stats["total_ms"] == 600
        assert stats["avg_ms"] == 200.0
        assert stats["p95_ms"] == 300

    def test_multiple_backends_independent(self):
        timing = default_timing_data()
        update_timing_stats(timing, "claude", 100)
        update_timing_stats(timing, "gpt", 200)
        assert timing["by_backend"]["claude"]["avg_ms"] == 100
        assert timing["by_backend"]["gpt"]["avg_ms"] == 200


class TestUpdateSummarizationRate:
    def test_calculates_acceptance_rate(self):
        summ = default_summarization_data()
        summ["offered"] = 10
        summ["accepted"] = 7
        update_summarization_rate(summ)
        assert summ["acceptance_rate"] == 0.7

    def test_rounds_to_three_decimals(self):
        summ = default_summarization_data()
        summ["offered"] = 3
        summ["accepted"] = 1
        update_summarization_rate(summ)
        assert summ["acceptance_rate"] == 0.333

    def test_handles_zero_offered(self):
        summ = default_summarization_data()
        summ["offered"] = 0
        summ["accepted"] = 0
        update_summarization_rate(summ)
        assert summ["acceptance_rate"] == 0.0


class TestAddToFilters:
    def test_adds_tool(self):
        filters = {}
        add_to_filters(filters, tool="grep")
        assert "grep" in filters.get("available_tools", [])

    def test_adds_backend(self):
        filters = {}
        add_to_filters(filters, backend="claude")
        assert "claude" in filters.get("available_backends", [])

    def test_adds_session(self):
        filters = {}
        add_to_filters(filters, session="sess-123")
        assert "sess-123" in filters.get("available_sessions", [])

    def test_deduplicates_tools(self):
        filters = {}
        add_to_filters(filters, tool="grep")
        add_to_filters(filters, tool="grep")
        assert filters.get("available_tools", []).count("grep") == 1

    def test_deduplicates_backends(self):
        filters = {}
        add_to_filters(filters, backend="claude")
        add_to_filters(filters, backend="claude")
        assert filters.get("available_backends", []).count("claude") == 1

    def test_deduplicates_sessions(self):
        filters = {}
        add_to_filters(filters, session="sess-123")
        add_to_filters(filters, session="sess-123")
        assert filters.get("available_sessions", []).count("sess-123") == 1


class TestMergeTokens:
    def test_merges_token_counts(self):
        target = default_token_data()
        source = default_token_data()
        source["input"] = 100
        source["output"] = 50
        merge_tokens(target, source)
        assert target["input"] == 100
        assert target["output"] == 50

    def test_merges_cache_counts(self):
        target = default_token_data()
        source = default_token_data()
        source["cache_read"] = 10
        source["cache_creation"] = 5
        merge_tokens(target, source)
        assert target["cache_read"] == 10
        assert target["cache_creation"] == 5

    def test_prefers_jsonl_source(self):
        target = default_token_data(source="estimated")
        source = default_token_data(source="jsonl")
        merge_tokens(target, source)
        assert target["source"] == "jsonl"


class TestMergeCalls:
    def test_merges_total_calls(self):
        target = default_call_data()
        source = default_call_data()
        source["total"] = 100
        merge_calls(target, source)
        assert target["total"] == 100

    def test_merges_by_tool(self):
        target = default_call_data()
        source = default_call_data()
        source["by_tool"] = {"grep": 10, "find": 5}
        merge_calls(target, source)
        assert target["by_tool"]["grep"] == 10
        assert target["by_tool"]["find"] == 5

    def test_merges_by_backend(self):
        target = default_call_data()
        source = default_call_data()
        source["by_backend"] = {"claude": 20, "gpt": 30}
        merge_calls(target, source)
        assert target["by_backend"]["claude"] == 20
        assert target["by_backend"]["gpt"] == 30

    def test_accumulates_different_tools(self):
        target = default_call_data()
        target["by_tool"] = {"grep": 10}
        source = default_call_data()
        source["by_tool"] = {"find": 5}
        merge_calls(target, source)
        assert target["by_tool"]["grep"] == 10
        assert target["by_tool"]["find"] == 5


class TestRecomputeAggregates:
    def test_computes_all_time(self):
        tel = default_telemetry_v2()
        day1 = ensure_day(tel, "2026-06-08")
        day1["tokens"]["input"] = 100
        day1["calls"]["total"] = 10
        day2 = ensure_day(tel, "2026-06-09")
        day2["tokens"]["input"] = 50
        day2["calls"]["total"] = 5
        recompute_aggregates(tel)
        all_time = tel["aggregates"]["all_time"]
        assert all_time["tokens"]["input"] == 150
        assert all_time["calls"]["total"] == 15

    def test_computes_last_7_days(self):
        tel = default_telemetry_v2()
        today = date.today()
        day_recent = ensure_day(tel, today.isoformat())
        day_recent["tokens"]["input"] = 100
        day_old = ensure_day(tel, (today - timedelta(days=10)).isoformat())
        day_old["tokens"]["input"] = 1000
        recompute_aggregates(tel)
        last_7 = tel["aggregates"]["last_7_days"]
        assert last_7["tokens"]["input"] == 100


class TestUpdateFilterOptions:
    def test_extracts_tools_from_days(self):
        tel = default_telemetry_v2()
        day = ensure_day(tel, "2026-06-10")
        day["calls"]["by_tool"] = {"grep": 5, "find": 3}
        update_filter_options(tel)
        filters = tel.get("filters", {})
        tools = filters.get("available_tools", [])
        assert "grep" in tools
        assert "find" in tools

    def test_extracts_backends_from_days(self):
        tel = default_telemetry_v2()
        day = ensure_day(tel, "2026-06-10")
        day["calls"]["by_backend"] = {"claude": 5, "gpt": 3}
        update_filter_options(tel)
        filters = tel.get("filters", {})
        backends = filters.get("available_backends", [])
        assert "claude" in backends
        assert "gpt" in backends


class TestLoadTelemetryV2:
    def test_returns_default_for_missing_file(self, tmp_path):
        path = tmp_path / "missing.json"
        result = load_telemetry_v2(path)
        assert result["version"] == "2.0"
        assert isinstance(result.get("days", {}), dict)

    def test_returns_default_for_invalid_json(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("{invalid json")
        result = load_telemetry_v2(path)
        assert result["version"] == "2.0"

    def test_returns_default_for_wrong_version(self, tmp_path):
        path = tmp_path / "v1.json"
        path.write_text(json.dumps({"version": "1.0", "data": "old"}))
        result = load_telemetry_v2(path)
        assert result["version"] == "2.0"

    def test_loads_valid_v2_telemetry(self, tmp_path):
        path = tmp_path / "valid.json"
        original = default_telemetry_v2()
        original["custom_field"] = "test_value"
        path.write_text(json.dumps(original))
        result = load_telemetry_v2(path)
        assert result["version"] == "2.0"
        assert result["custom_field"] == "test_value"


class TestSaveTelemetryV2:
    def test_saves_telemetry_to_file(self, tmp_path):
        path = tmp_path / "saved.json"
        tel = default_telemetry_v2()
        tel["test_key"] = "test_value"
        save_telemetry_v2(tel, path)
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded["test_key"] == "test_value"

    def test_sets_last_updated(self, tmp_path):
        path = tmp_path / "saved.json"
        tel = default_telemetry_v2()
        save_telemetry_v2(tel, path)
        loaded = json.loads(path.read_text())
        assert "last_updated" in loaded
        datetime.fromisoformat(loaded["last_updated"])

    def test_creates_parent_directory(self, tmp_path):
        path = tmp_path / "subdir" / "nested" / "saved.json"
        tel = default_telemetry_v2()
        save_telemetry_v2(tel, path)
        assert path.exists()
        assert path.parent.exists()

    def test_round_trip(self, tmp_path):
        path = tmp_path / "roundtrip.json"
        original = default_telemetry_v2()
        original["custom"] = "data"
        day = ensure_day(original, "2026-06-10")
        day["tokens"]["input"] = 123
        save_telemetry_v2(original, path)
        loaded = load_telemetry_v2(path)
        assert loaded["custom"] == "data"
        assert loaded["days"]["2026-06-10"]["tokens"]["input"] == 123
        assert "last_updated" in loaded
