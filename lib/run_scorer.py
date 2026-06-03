"""run_scorer — score a workflow run on three independently-grounded axes.

OUTCOME    — did the run meet its declared criterion: tests-pass ratio parsed
             from the vault run ledger, or check_criteria() recomputed from
             eval metrics. Recomputing is the point: a workflow's self-declared
             "success" is never trusted; a claimed-vs-actual mismatch is itself
             a workflow-quality signal.
COMPLIANCE — did agents stay inside governance: PermissionDeniedError /
             WorkflowError counts (governance breaches) + per-agent tool
             sequence, from the SQLite events DB.
COST       — wallclock (event timestamps) + summed per-call duration_ms.
             Token cost is intentionally omitted: controller.record_event does
             not yet populate the token columns, so all rows read 0 today.

Every axis derives from artifacts that exist NOW — the events DB (compliance,
cost) and the run ledger (outcome) — so the first scored comparison needs no
new measured run. check_criteria() is reused from experiment_harness rather
than reimplemented, keeping outcome scoring identical to what a live
experiment run would compute.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from experiment_harness import check_criteria
except ImportError:  # pragma: no cover - allow standalone use without harness
    check_criteria = None


# Error types that mean the model/agent broke a phase rule (vs infra noise like
# RouterError / RequestTimeoutError, which are not the agent's fault).
_VIOLATION_ERRORS = {"PermissionDeniedError", "WorkflowError"}


# --- timestamp helpers ------------------------------------------------------

def _iso_to_ms(ts: Optional[str]) -> Optional[int]:
    """Parse an ISO-8601 timestamp to epoch-ms; None if unparseable."""
    if not ts:
        return None
    try:
        return int(datetime.fromisoformat(ts).timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


# --- OUTCOME ----------------------------------------------------------------

@dataclass
class OutcomeScore:
    tests_passed: int = 0
    tests_total: int = 0
    new_commits: int = 0
    branches: int = 0
    pass_ratio: float = 0.0
    per_branch: list = field(default_factory=list)


# | <branch> | <passed>/<total> [✓] | <new commits> | <note> |
_ROW_RE = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*(\d+)\s*/\s*(\d+)[^|]*\|\s*(\d+)\s*\|", re.MULTILINE
)


def parse_outcome_table(markdown: str) -> OutcomeScore:
    """Parse a run-ledger Outcome table into an OutcomeScore.

    Rows look like: ``| 02-autograd | 36/36 ✓ | 1 | note |``. The header
    (``| Branch | Tests | ...``) and separator (``|---|---|``) rows do not
    match the X/Y + integer-commits shape and are skipped naturally.
    """
    passed = total = commits = 0
    per_branch = []
    for m in _ROW_RE.finditer(markdown):
        branch = m.group(1).strip()
        p, t, c = int(m.group(2)), int(m.group(3)), int(m.group(4))
        if branch.lower() == "branch":
            continue
        passed += p
        total += t
        commits += c
        per_branch.append({"branch": branch, "tests_passed": p,
                           "tests_total": t, "new_commits": c})
    ratio = passed / total if total else 0.0
    return OutcomeScore(tests_passed=passed, tests_total=total, new_commits=commits,
                        branches=len(per_branch), pass_ratio=ratio, per_branch=per_branch)


def recompute_outcome(criteria: list, metrics: dict):
    """Independently recompute pass/fail from eval metrics (claimed-vs-actual).

    Thin wrapper over experiment_harness.check_criteria so the scorer never
    trusts a workflow's self-declared success. Returns a CriteriaResult.
    """
    if check_criteria is None:
        raise RuntimeError("experiment_harness.check_criteria unavailable on path")
    return check_criteria(criteria, metrics)


# --- COMPLIANCE -------------------------------------------------------------

@dataclass
class ComplianceScore:
    total_calls: int = 0
    errors: int = 0
    permission_denied: int = 0
    workflow_errors: int = 0
    router_errors: int = 0
    violation_rate: float = 0.0
    error_histogram: dict = field(default_factory=dict)
    tool_sequence: dict = field(default_factory=dict)


def score_compliance(events: list) -> ComplianceScore:
    """Score governance compliance from event rows.

    violation_rate counts genuine governance breaches (PermissionDeniedError +
    WorkflowError) over total calls — RouterError / timeouts are infra noise
    and excluded from the rate (but still surfaced in error_histogram).
    """
    total = len(events)
    errors = perm = wf = router = 0
    hist: dict = {}
    seqs: dict = {}
    for e in sorted(events, key=lambda r: r.get("timestamp") or ""):
        et = e.get("error_type")
        if e.get("status") == "error" or et:
            errors += 1
        if et:
            hist[et] = hist.get(et, 0) + 1
            if et == "PermissionDeniedError":
                perm += 1
            elif et == "WorkflowError":
                wf += 1
            elif et == "RouterError":
                router += 1
        aid = e.get("agent_id") or "(none)"
        seqs.setdefault(aid, []).append(e.get("tool"))
    violation_rate = (perm + wf) / total if total else 0.0
    return ComplianceScore(total_calls=total, errors=errors, permission_denied=perm,
                           workflow_errors=wf, router_errors=router,
                           violation_rate=violation_rate, error_histogram=hist,
                           tool_sequence=seqs)


# --- COST -------------------------------------------------------------------

@dataclass
class CostScore:
    wallclock_s: float = 0.0
    duration_ms_sum: int = 0
    calls_with_duration: int = 0
    total_calls: int = 0


def score_cost(events: list) -> CostScore:
    """Score cost: wallclock (first->last event) + summed per-call duration_ms."""
    ms_values = [m for m in (_iso_to_ms(e.get("timestamp")) for e in events) if m is not None]
    wall = (max(ms_values) - min(ms_values)) / 1000 if len(ms_values) >= 2 else 0.0
    dur_sum = 0
    dur_n = 0
    for e in events:
        d = e.get("duration_ms")
        if d:
            dur_sum += d
            dur_n += 1
    return CostScore(wallclock_s=wall, duration_ms_sum=dur_sum,
                     calls_with_duration=dur_n, total_calls=len(events))


# --- window query -----------------------------------------------------------

def query_window(conn: sqlite3.Connection, start_ms: int, end_ms: int) -> list:
    """Return event rows (as dicts) whose timestamp falls within [start_ms, end_ms].

    SQL bounds are loosened by 1s and the precise filter is applied in Python,
    so microsecond/format quirks in the text timestamps can never drop a valid
    in-window row.
    """
    lo = _ms_to_iso(start_ms - 1000)
    hi = _ms_to_iso(end_ms + 1000)
    cur = conn.execute(
        "SELECT * FROM events WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
        (lo, hi),
    )
    cols = [d[0] for d in cur.description]
    rows = []
    for r in cur.fetchall():
        row = dict(zip(cols, r))
        ms = _iso_to_ms(row.get("timestamp"))
        if ms is not None and start_ms <= ms <= end_ms:
            rows.append(row)
    return rows


def derive_window(conn: sqlite3.Connection, workflow_id: str,
                  match_prefix: bool = False):
    """Derive [start_ms, end_ms] for a run from its own tagged events.

    Returns (start_ms, end_ms) from the MIN/MAX event timestamp carrying this
    workflow_id, or None if nothing is tagged. With match_prefix=True the base
    name also matches its per-instance ids ('iterate' -> 'iterate:sub-1'), so
    `--workflow-id` alone can scope a run with no out-of-band timestamps. Only
    meaningful once controller.record_event tags events with workflow_id.
    """
    if match_prefix:
        row = conn.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM events "
            "WHERE workflow_id = ? OR workflow_id LIKE ?",
            (workflow_id, workflow_id + ":%"),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM events WHERE workflow_id = ?",
            (workflow_id,),
        ).fetchone()
    lo, hi = row or (None, None)
    if lo is None or hi is None:
        return None
    return _iso_to_ms(lo), _iso_to_ms(hi)


def score_by_phase(events: list) -> dict:
    """Group events by recorded phase and score compliance+cost within each.

    Makes a run sliceable per-phase. Phases only separate once events carry the
    phase column (controller wiring); pre-wiring events bucket under '(none)'.
    """
    buckets: dict = {}
    for e in events:
        buckets.setdefault(e.get("phase") or "(none)", []).append(e)
    out = {}
    for phase, evs in buckets.items():
        comp = asdict(score_compliance(evs))
        comp.pop("tool_sequence", None)  # keep per-phase output compact
        out[phase] = {"events": len(evs), "compliance": comp,
                      "cost": asdict(score_cost(evs))}
    return out


# --- compose ----------------------------------------------------------------

def score_run(conn: sqlite3.Connection, start_ms: Optional[int] = None,
              end_ms: Optional[int] = None, *,
              workflow_id: Optional[str] = None, match_prefix: bool = False,
              outcome_md: Optional[str] = None, outcome: Optional[OutcomeScore] = None,
              model: Optional[str] = None, label: Optional[str] = None,
              workflow: Optional[str] = None) -> dict:
    """Score one run, joining DB telemetry with ledger outcome.

    Scope by an explicit [start_ms, end_ms] window, OR pass workflow_id to
    derive the window from that run's own tagged events (self-describing — no
    out-of-band timestamps). Output carries a per-phase breakdown so the run is
    sliceable by phase, plus the distinct workflow_ids actually seen in-window.
    """
    if (start_ms is None or end_ms is None) and workflow_id:
        win = derive_window(conn, workflow_id, match_prefix=match_prefix)
        if win is None:
            raise ValueError(f"no events tagged with workflow_id={workflow_id!r}")
        start_ms, end_ms = win
    if start_ms is None or end_ms is None:
        raise ValueError("score_run needs an explicit window or a workflow_id to derive one")
    events = query_window(conn, start_ms, end_ms)
    compliance = score_compliance(events)
    cost = score_cost(events)
    if outcome is None and outcome_md is not None:
        outcome = parse_outcome_table(outcome_md)
    outcome_dict = asdict(outcome) if isinstance(outcome, OutcomeScore) else (outcome or {})
    workflows_seen = sorted({e.get("workflow_id") for e in events if e.get("workflow_id")})
    return {
        "label": label,
        "model": model,
        "workflow": workflow or workflow_id,
        "workflows_seen": workflows_seen,
        "window": {"start_ms": start_ms, "end_ms": end_ms,
                   "wallclock_s": (end_ms - start_ms) / 1000},
        "outcome": outcome_dict,
        "compliance": asdict(compliance),
        "cost": asdict(cost),
        "by_phase": score_by_phase(events),
        "events_in_window": len(events),
    }


def _sub(b, a):
    if a is None or b is None:
        return None
    return b - a


def _g(rec: dict, *keys):
    cur = rec
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def compare(run_a: dict, run_b: dict) -> dict:
    """Compute b-minus-a deltas on the scoring axes (b is the variant under test)."""
    return {
        "a": run_a.get("label"),
        "b": run_b.get("label"),
        "window_wallclock_s_delta": _sub(_g(run_b, "window", "wallclock_s"),
                                         _g(run_a, "window", "wallclock_s")),
        "wallclock_s_delta": _sub(_g(run_b, "cost", "wallclock_s"),
                                  _g(run_a, "cost", "wallclock_s")),
        "pass_ratio_delta": _sub(_g(run_b, "outcome", "pass_ratio"),
                                 _g(run_a, "outcome", "pass_ratio")),
        "new_commits_delta": _sub(_g(run_b, "outcome", "new_commits"),
                                  _g(run_a, "outcome", "new_commits")),
        "violation_rate_delta": _sub(_g(run_b, "compliance", "violation_rate"),
                                     _g(run_a, "compliance", "violation_rate")),
        "total_calls_delta": _sub(_g(run_b, "compliance", "total_calls"),
                                  _g(run_a, "compliance", "total_calls")),
    }


# --- CLI --------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Score a workflow run on outcome/compliance/cost from the events DB + ledger.")
    ap.add_argument("--db", required=True, help="path to datastore.db")
    ap.add_argument("--start", type=int, help="window start (epoch-ms)")
    ap.add_argument("--end", type=int, help="window end (epoch-ms)")
    ap.add_argument("--workflow-id",
                    help="derive the window from events tagged with this workflow_id "
                         "(self-describing; no --start/--end needed)")
    ap.add_argument("--match-prefix", action="store_true",
                    help="with --workflow-id, also match per-instance ids (base -> base:*)")
    ap.add_argument("--outcome-file", help="markdown file containing an Outcome table")
    ap.add_argument("--label")
    ap.add_argument("--model")
    ap.add_argument("--workflow")
    ap.add_argument("--no-tool-seq", action="store_true",
                    help="omit the (verbose) per-agent tool sequence from output")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(str(args.db))
    outcome_md = Path(args.outcome_file).read_text() if args.outcome_file else None
    rec = score_run(conn, args.start, args.end, workflow_id=args.workflow_id,
                    match_prefix=args.match_prefix, outcome_md=outcome_md,
                    model=args.model, label=args.label, workflow=args.workflow)
    if args.no_tool_seq:
        rec["compliance"].pop("tool_sequence", None)
    print(json.dumps(rec, indent=2, default=str))


if __name__ == "__main__":  # pragma: no cover
    main()
