"""Tests for run_scorer — three-axis workflow-run scoring.

Fixtures encode the REAL shapes verified against disk: the run-1 ledger
Outcome table (230/230) and the live events DB error types
(PermissionDeniedError / WorkflowError / RouterError).
"""
import datetime as dt
import sqlite3

import pytest

from run_scorer import (
    OutcomeScore, parse_outcome_table,
    ComplianceScore, score_compliance,
    CostScore, score_cost,
    query_window, score_run, compare, recompute_outcome,
    derive_window, score_by_phase, _iso_to_ms,
)


# --- real run-1 Outcome table (from workflow-runs.md) -----------------------

RUN1_OUTCOME_MD = """\
### Outcome

| Branch | Tests | New commits | Note |
|---|---|---|---|
| 01-skiplist | 29/29 ✓ | 0 | subagent took no action |
| 02-autograd | 36/36 ✓ | 1 | added coverage |
| 03-compiler | 76/76 ✓ | 1 | added adversarial coverage |
| 04-allocator | 42/42 ✓ | 1 | buddy stress |
| 05-vector-clocks | 47/47 ✓ | 1 | invariant tests |

**Total: 230/230 tests pass.**
"""


def test_parse_outcome_table_real_format():
    o = parse_outcome_table(RUN1_OUTCOME_MD)
    assert isinstance(o, OutcomeScore)
    assert o.tests_passed == 230
    assert o.tests_total == 230
    assert o.pass_ratio == 1.0
    assert o.new_commits == 4
    assert o.branches == 5


def test_parse_outcome_table_ignores_header_and_separator():
    o = parse_outcome_table(RUN1_OUTCOME_MD)
    branches = {b["branch"] for b in o.per_branch}
    assert "Branch" not in branches
    assert "---" not in branches
    assert branches == {"01-skiplist", "02-autograd", "03-compiler",
                        "04-allocator", "05-vector-clocks"}


def test_parse_outcome_table_partial_fail():
    md = """
| Branch | Tests | New commits | Note |
|---|---|---|---|
| a | 8/10 | 2 | two failing |
| b | 5/5 ✓ | 0 | ok |
"""
    o = parse_outcome_table(md)
    assert o.tests_passed == 13
    assert o.tests_total == 15
    assert o.new_commits == 2
    assert o.branches == 2
    assert o.pass_ratio == pytest.approx(13 / 15)


# --- compliance -------------------------------------------------------------

def _ev(agent_id="a1", tool="native__bash", backend="native", status="success",
        error_type=None, duration_ms=None, ts="2026-05-03T15:00:00+00:00",
        agent_type="implementer"):
    return {"agent_id": agent_id, "tool": tool, "backend": backend, "status": status,
            "error_type": error_type, "duration_ms": duration_ms, "timestamp": ts,
            "agent_type": agent_type}


def test_score_compliance_counts_governance_violations():
    events = [
        _ev(status="success"),
        _ev(status="error", error_type="PermissionDeniedError"),
        _ev(status="error", error_type="WorkflowError"),
        _ev(status="error", error_type="RouterError"),
        _ev(status="success"),
    ]
    c = score_compliance(events)
    assert isinstance(c, ComplianceScore)
    assert c.total_calls == 5
    assert c.errors == 3
    assert c.permission_denied == 1
    assert c.workflow_errors == 1
    assert c.router_errors == 1
    # violation_rate counts governance breaches (perm + workflow), NOT infra (router)
    assert c.violation_rate == pytest.approx(2 / 5)
    assert c.error_histogram["PermissionDeniedError"] == 1


def test_score_compliance_tool_sequence_per_agent_ordered():
    events = [
        _ev(agent_id="a1", tool="native__read_file", ts="2026-05-03T15:00:02+00:00"),
        _ev(agent_id="a1", tool="native__write_file", ts="2026-05-03T15:00:00+00:00"),
        _ev(agent_id="a2", tool="native__bash", ts="2026-05-03T15:00:05+00:00"),
    ]
    c = score_compliance(events)
    # ordered by timestamp regardless of input order
    assert c.tool_sequence["a1"] == ["native__write_file", "native__read_file"]
    assert c.tool_sequence["a2"] == ["native__bash"]


# --- cost -------------------------------------------------------------------

def test_score_cost_wallclock_and_duration():
    events = [
        _ev(ts="2026-05-03T15:00:00+00:00", duration_ms=100),
        _ev(ts="2026-05-03T15:05:00+00:00", duration_ms=None),
        _ev(ts="2026-05-03T15:10:00+00:00", duration_ms=250),
    ]
    cost = score_cost(events)
    assert isinstance(cost, CostScore)
    assert cost.wallclock_s == pytest.approx(600.0)  # 10 minutes first->last
    assert cost.duration_ms_sum == 350
    assert cost.calls_with_duration == 2
    assert cost.total_calls == 3


# --- window query -----------------------------------------------------------

@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp TEXT, tool TEXT, "
        "backend TEXT, status TEXT, duration_ms INTEGER, session_id TEXT, "
        "agent_id TEXT, agent_type TEXT, workflow_id TEXT, error_type TEXT, "
        "input_tokens INTEGER, output_tokens INTEGER, phase TEXT)"
    )
    rows = [
        ("2026-05-03T14:00:00.000000+00:00", "native__bash", "native", "success", 10, "a1"),       # before
        ("2026-05-03T15:00:00.123456+00:00", "native__read_file", "native", "success", 20, "a1"),  # in
        ("2026-05-03T15:30:00.500000+00:00", "native__bash", "native", "error", 30, "a1"),         # in
        ("2026-05-03T16:00:00.000000+00:00", "native__bash", "native", "success", 40, "a1"),       # after
    ]
    for ts, tool, backend, status, dur, aid in rows:
        conn.execute(
            "INSERT INTO events (timestamp,tool,backend,status,duration_ms,agent_id) "
            "VALUES (?,?,?,?,?,?)", (ts, tool, backend, status, dur, aid))
    conn.commit()
    return conn


def _ms(y, mo, d, h, mi, s=0):
    return int(dt.datetime(y, mo, d, h, mi, s, tzinfo=dt.timezone.utc).timestamp() * 1000)


def test_query_window_filters_by_time(mem_db):
    start = _ms(2026, 5, 3, 15, 0, 0)
    end = _ms(2026, 5, 3, 15, 59, 0)
    rows = query_window(mem_db, start, end)
    assert len(rows) == 2
    assert {r["tool"] for r in rows} == {"native__read_file", "native__bash"}


# --- compose ----------------------------------------------------------------

def test_score_run_composes_three_axes(mem_db):
    start = _ms(2026, 5, 3, 15, 0, 0)
    end = _ms(2026, 5, 3, 15, 59, 0)
    rec = score_run(mem_db, start, end, outcome_md=RUN1_OUTCOME_MD,
                    model="claude-opus-4-7", label="run-x", workflow="orchestrate")
    assert rec["label"] == "run-x"
    assert rec["model"] == "claude-opus-4-7"
    assert rec["outcome"]["tests_passed"] == 230
    assert rec["compliance"]["total_calls"] == 2
    assert rec["cost"]["total_calls"] == 2
    assert rec["events_in_window"] == 2
    assert rec["window"]["wallclock_s"] == pytest.approx((end - start) / 1000)


# --- compare ----------------------------------------------------------------

def test_compare_surfaces_deltas():
    a = {"label": "run2", "window": {"wallclock_s": 4610.0}, "cost": {"wallclock_s": 4600.0},
         "outcome": {"pass_ratio": 1.0, "new_commits": 4}, "compliance": {"violation_rate": 0.0, "total_calls": 500}}
    b = {"label": "run4", "window": {"wallclock_s": 690.0}, "cost": {"wallclock_s": 680.0},
         "outcome": {"pass_ratio": 1.0, "new_commits": 0}, "compliance": {"violation_rate": 0.1, "total_calls": 50}}
    d = compare(a, b)
    assert d["window_wallclock_s_delta"] == pytest.approx(690.0 - 4610.0)
    assert d["new_commits_delta"] == -4          # run4 did NO commits despite being 6x faster
    assert d["pass_ratio_delta"] == 0.0
    assert d["violation_rate_delta"] == pytest.approx(0.1)


# --- independence hook (claimed vs actual) ----------------------------------

def test_recompute_outcome_flags_claimed_vs_actual():
    criteria = [{"metric": "accuracy", "threshold": 0.9, "primary": True}]
    # a workflow may CLAIM success, but recomputed criteria say otherwise
    assert recompute_outcome(criteria, {"accuracy": 0.5}).primary_passed is False
    assert recompute_outcome(criteria, {"accuracy": 0.95}).primary_passed is True


# --- self-describing runs: derive window from tagged events -----------------

def _tag(conn, ts, workflow_id, phase="", tool="native__bash", status="success",
         error_type=None, agent_id="a1"):
    conn.execute(
        "INSERT INTO events (timestamp, tool, status, error_type, workflow_id, "
        "phase, agent_id) VALUES (?,?,?,?,?,?,?)",
        (ts, tool, status, error_type, workflow_id, phase, agent_id))
    conn.commit()


def test_derive_window_from_tagged_events(mem_db):
    _tag(mem_db, "2026-05-03T15:10:00.000000+00:00", "iterate:sub-1", "implement")
    _tag(mem_db, "2026-05-03T15:20:00.000000+00:00", "iterate:sub-1", "test")
    win = derive_window(mem_db, "iterate:sub-1")
    assert win == (_iso_to_ms("2026-05-03T15:10:00.000000+00:00"),
                   _iso_to_ms("2026-05-03T15:20:00.000000+00:00"))


def test_derive_window_prefix_matches_instances(mem_db):
    _tag(mem_db, "2026-05-03T15:05:00+00:00", "iterate")
    _tag(mem_db, "2026-05-03T15:25:00+00:00", "iterate:sub-9")
    win = derive_window(mem_db, "iterate", match_prefix=True)
    assert win == (_iso_to_ms("2026-05-03T15:05:00+00:00"),
                   _iso_to_ms("2026-05-03T15:25:00+00:00"))


def test_derive_window_none_when_untagged(mem_db):
    assert derive_window(mem_db, "no-such-run") is None


def test_score_by_phase_groups_compliance(mem_db):
    events = [
        _ev(ts="2026-05-03T15:00:00+00:00", agent_id="a1"),
        _ev(ts="2026-05-03T15:00:01+00:00", status="error",
            error_type="PermissionDeniedError", agent_id="a1"),
    ]
    events[0]["phase"] = "implement"
    events[1]["phase"] = "test"
    by_phase = score_by_phase(events)
    assert by_phase["implement"]["compliance"]["total_calls"] == 1
    assert by_phase["test"]["compliance"]["permission_denied"] == 1


def test_score_run_scopes_by_workflow_id_and_breaks_down_by_phase(mem_db):
    _tag(mem_db, "2026-05-03T15:15:00+00:00", "iterate:sub-1", "implement")
    _tag(mem_db, "2026-05-03T15:16:00+00:00", "iterate:sub-1", "test",
         status="error", error_type="PermissionDeniedError")
    rec = score_run(mem_db, workflow_id="iterate:sub-1")
    assert rec["workflows_seen"] == ["iterate:sub-1"]
    assert set(rec["by_phase"]) == {"implement", "test"}
    assert rec["by_phase"]["test"]["compliance"]["permission_denied"] == 1
    # window was derived, not supplied
    assert rec["window"]["start_ms"] == _iso_to_ms("2026-05-03T15:15:00+00:00")


# --- PR #120 review fixes ---------------------------------------------------

def test_score_cost_counts_zero_duration():
    # duration_ms == 0 is a real (instantaneous) call and must be counted;
    # the old `if d:` guard silently dropped it. None still means "unknown".
    events = [
        _ev(ts="2026-05-03T15:00:00+00:00", duration_ms=0),
        _ev(ts="2026-05-03T15:00:01+00:00", duration_ms=None),
        _ev(ts="2026-05-03T15:00:02+00:00", duration_ms=120),
    ]
    cost = score_cost(events)
    assert cost.calls_with_duration == 2   # the 0 and the 120, NOT the None
    assert cost.duration_ms_sum == 120


def test_iso_to_ms_treats_naive_timestamp_as_utc():
    # A naive (tz-less) ISO timestamp must be read as UTC, not host-local, so
    # the result is reproducible regardless of where the scorer runs.
    naive = _iso_to_ms("2026-05-03T00:00:00")
    aware = _iso_to_ms("2026-05-03T00:00:00+00:00")
    assert naive == aware
    expected = int(dt.datetime(2026, 5, 3, 0, 0, 0,
                               tzinfo=dt.timezone.utc).timestamp() * 1000)
    assert naive == expected


def test_derive_window_prefix_escapes_like_wildcards(mem_db):
    # workflow_id containing a literal _ must not be treated as a LIKE
    # single-char wildcard: 'run_a' must NOT match 'runXa:1'.
    _tag(mem_db, "2026-05-03T15:10:00+00:00", "run_a")
    _tag(mem_db, "2026-05-03T15:11:00+00:00", "run_a:sub-1")
    _tag(mem_db, "2026-05-03T15:40:00+00:00", "runXa:sub-9")  # unrelated decoy
    win = derive_window(mem_db, "run_a", match_prefix=True)
    # window spans only the run_a rows, never the runXa decoy at 15:40
    assert win == (_iso_to_ms("2026-05-03T15:10:00+00:00"),
                   _iso_to_ms("2026-05-03T15:11:00+00:00"))


def test_score_run_partial_window_not_clobbered_by_workflow_id(mem_db):
    # Only start_ms supplied (no end_ms) + a workflow_id: the partially-given
    # window must NOT be silently replaced by the derived one. With end_ms
    # missing the run is under-specified, so score_run raises rather than
    # quietly overriding the caller's start_ms.
    _tag(mem_db, "2026-05-03T15:15:00+00:00", "iterate:sub-1")
    start = _ms(2026, 5, 3, 15, 0, 0)
    with pytest.raises(ValueError):
        score_run(mem_db, start_ms=start, end_ms=None, workflow_id="iterate:sub-1")
