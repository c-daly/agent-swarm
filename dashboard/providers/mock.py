"""Mock data provider for dashboard development. Deterministic with seed=42."""

import random
from datetime import datetime, timedelta, timezone

TOOLS = [
    ("Bash", "native", 0.20), ("Read", "native", 0.15),
    ("mcp__router__serena__read_file", "router", 0.10),
    ("mcp__router__serena__search_for_pattern", "router", 0.08),
    ("mcp__router__serena__find_symbol", "router", 0.06),
    ("mcp__router__native__bash", "router", 0.05),
    ("Edit", "native", 0.05), ("Write", "native", 0.04),
    ("Glob", "native", 0.04), ("Grep", "native", 0.04),
    ("Task", "claude", 0.05),
    ("mcp__router__serena__replace_content", "router", 0.03),
    ("mcp__router__serena__execute_shell_command", "router", 0.03),
    ("mcp__plugin_memory__search", "plugin", 0.02),
    ("WebFetch", "claude", 0.02),
    ("mcp__context7__query-docs", "mcp", 0.02),
    ("Skill", "claude", 0.01), ("AskUserQuestion", "claude", 0.01),
]


class MockProvider:
    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)
        self._events: list[dict] = []
        self._sessions: list[str] = []
        self._generate_data()

    def _generate_data(self) -> None:
        start = datetime(2026, 1, 17, 8, 0, 0, tzinfo=timezone.utc)
        self._sessions = [f"sess-{i:04d}" for i in range(200)]
        sizes = [max(1, int(self._rng.paretovariate(1.5) * 5)) for _ in range(200)]
        total = sum(sizes)
        sizes = [max(1, int(s / total * 5000)) for s in sizes]

        for sid, count in zip(self._sessions, sizes):
            t0 = start + timedelta(days=self._rng.uniform(0, 14), hours=self._rng.uniform(0, 16))
            aids = [sid]
            if self._rng.random() < 0.3:
                aids += [f"agent-{self._rng.randint(1000, 9999)}" for _ in range(self._rng.randint(1, 4))]
            for i in range(count):
                ts = t0 + timedelta(seconds=i * self._rng.uniform(1, 30))
                tool, backend, _ = self._rng.choices(TOOLS, weights=[t[2] for t in TOOLS])[0]
                is_err = self._rng.random() < 0.12
                ws = self._rng.random() < 0.06
                osz = self._rng.randint(100, 15000) if ws else self._rng.randint(10, 2000)
                self._events.append({
                    "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z",
                    "session_id": sid, "agent_id": self._rng.choice(aids),
                    "tool": tool, "backend": backend,
                    "duration_ms": int(self._rng.expovariate(1 / 2000)),
                    "status": "error" if is_err else "success",
                    "input_tokens": self._rng.randint(5, 500),
                    "output_tokens": self._rng.randint(5, 300),
                    "cache_read_tokens": self._rng.randint(0, 50000),
                    "cache_creation_tokens": self._rng.randint(0, 5000),
                    "agent_type": "", "was_summarized": ws,
                    "original_size": osz,
                    "summary_size": min(osz, 2000) if ws else None,
                    "error_type": f"Error: mock {self._rng.randint(1, 20)}" if is_err else "",
                    "import_source": "mock",
                })
        self._events.sort(key=lambda e: e["timestamp"])

    def _filter(self, filters: dict) -> list[dict]:
        r = self._events
        if "from" in filters:
            r = [e for e in r if e["timestamp"] >= filters["from"]]
        if "to" in filters:
            r = [e for e in r if e["timestamp"] <= filters["to"]]
        if "tool" in filters:
            ts = {t.strip() for t in filters["tool"].split(",")}
            r = [e for e in r if e["tool"] in ts]
        if "backend" in filters:
            bs = {b.strip() for b in filters["backend"].split(",")}
            r = [e for e in r if e["backend"] in bs]
        if "status" in filters:
            r = [e for e in r if e["status"] == filters["status"]]
        if "session" in filters:
            r = [e for e in r if e["session_id"] == filters["session"]]
        if "agent_type" in filters:
            v = filters["agent_type"]
            if v == "main":
                r = [e for e in r if e["agent_id"] == e["session_id"]]
            elif v == "subagent":
                r = [e for e in r if e["agent_id"] != e["session_id"]]
        return r

    def health(self) -> dict:
        return {"status": "ok", "db_path": ":mock:", "db_size_bytes": 0,
                "total_events": len(self._events), "total_sessions": len(self._sessions),
                "first_event": self._events[0]["timestamp"] if self._events else "",
                "last_event": self._events[-1]["timestamp"] if self._events else "",
                "imports": [{"source": "mock", "last_import": "2026-01-31T00:00:00Z",
                             "total_inserted": len(self._events)}]}

    def overview(self, filters: dict) -> dict:
        evts = self._filter(filters)
        n = len(evts)
        errs = sum(1 for e in evts if e["status"] == "error")
        return {
            "total_events": n,
            "total_sessions": len(set(e["session_id"] for e in evts)),
            "total_input_tokens": sum(e["input_tokens"] for e in evts),
            "total_output_tokens": sum(e["output_tokens"] for e in evts),
            "total_cache_read": sum(e["cache_read_tokens"] for e in evts),
            "total_cache_creation": sum(e["cache_creation_tokens"] for e in evts),
            "total_errors": errs,
            "error_rate": round(errs / n, 3) if n else 0,
            "first_event": evts[0]["timestamp"] if evts else "",
            "last_event": evts[-1]["timestamp"] if evts else "",
            "avg_duration_ms": round(sum(e["duration_ms"] for e in evts) / n, 1) if n else 0,
            "total_summarized": sum(1 for e in evts if e["was_summarized"]),
            "unique_tools": len(set(e["tool"] for e in evts)),
            "subagent_count": len(set(e["agent_id"] for e in evts if e["agent_id"] != e["session_id"])),
        }

    def tokens(self, filters: dict) -> dict:
        gb = filters.pop("group_by", "day")
        lim = int(filters.pop("limit", 50))
        evts = self._filter(filters)
        if gb == "tool":
            g: dict = {}
            for e in evts:
                t = e["tool"]
                if t not in g:
                    g[t] = {"tool": t, "total_tokens": 0, "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "event_count": 0}
                d = g[t]; d["total_tokens"] += e["input_tokens"] + e["output_tokens"]
                d["input"] += e["input_tokens"]; d["output"] += e["output_tokens"]
                d["cache_read"] += e["cache_read_tokens"]; d["cache_creation"] += e["cache_creation_tokens"]
                d["event_count"] += 1
            return {"group_by": "tool", "data": sorted(g.values(), key=lambda x: x["total_tokens"], reverse=True)[:lim]}
        elif gb == "agent":
            g = {}
            for e in evts:
                role = "main" if e["agent_id"] == e["session_id"] else "subagent"
                if role not in g:
                    g[role] = {"agent_role": role, "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "event_count": 0}
                d = g[role]; d["input"] += e["input_tokens"]; d["output"] += e["output_tokens"]
                d["cache_read"] += e["cache_read_tokens"]; d["cache_creation"] += e["cache_creation_tokens"]; d["event_count"] += 1
            return {"group_by": "agent", "data": list(g.values())}
        else:
            p = filters.get("period", "day"); g = {}
            for e in evts:
                k = e["timestamp"][:10]
                if p == "hour": k = e["timestamp"][:13] + ":00"
                elif p == "month": k = e["timestamp"][:7]
                if k not in g:
                    g[k] = {"period": k, "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "event_count": 0}
                d = g[k]; d["input"] += e["input_tokens"]; d["output"] += e["output_tokens"]
                d["cache_read"] += e["cache_read_tokens"]; d["cache_creation"] += e["cache_creation_tokens"]; d["event_count"] += 1
            return {"group_by": gb, "period": p, "data": sorted(g.values(), key=lambda x: x["period"])}

    def tools(self, filters: dict) -> dict:
        sort = filters.pop("sort", "count"); lim = int(filters.pop("limit", 50))
        evts = self._filter(filters); g: dict = {}
        for e in evts:
            t = e["tool"]
            if t not in g:
                g[t] = {"tool": t, "call_count": 0, "error_count": 0, "total_tokens": 0, "dur": 0, "summarized_count": 0}
            d = g[t]; d["call_count"] += 1; d["total_tokens"] += e["input_tokens"] + e["output_tokens"]
            d["dur"] += e["duration_ms"]
            if e["status"] == "error": d["error_count"] += 1
            if e["was_summarized"]: d["summarized_count"] += 1
        data = [{"tool": d["tool"], "call_count": d["call_count"], "error_count": d["error_count"],
                 "error_rate": round(d["error_count"] / d["call_count"], 3) if d["call_count"] else 0,
                 "total_tokens": d["total_tokens"],
                 "avg_duration_ms": round(d["dur"] / d["call_count"], 1) if d["call_count"] else 0,
                 "summarized_count": d["summarized_count"]} for d in g.values()]
        sk = {"count": "call_count", "errors": "error_count", "tokens": "total_tokens"}.get(sort, "call_count")
        data.sort(key=lambda x: x[sk], reverse=True)
        return {"sort": sort, "data": data[:lim]}

    def concurrency(self, filters: dict) -> dict:
        sid = filters.get("session", "")
        evts = [e for e in self._events if e["session_id"] == sid]
        if not evts:
            return {"session_id": sid, "events": [], "max_concurrency": 0, "avg_concurrency": 0}
        parsed = []
        for e in evts:
            try:
                s = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))
                parsed.append({**e, "_s": s, "_e": s + timedelta(milliseconds=e["duration_ms"])})
            except (ValueError, TypeError):
                parsed.append({**e, "_s": None, "_e": None})
        for i, ev in enumerate(parsed):
            if ev["_s"] is None: ev["concurrent_count"] = 0; continue
            ev["concurrent_count"] = sum(1 for j, o in enumerate(parsed) if i != j and o["_s"] and o["_s"] < ev["_e"] and o["_e"] > ev["_s"])
        result = [{k: v for k, v in p.items() if k not in ("_s", "_e")} for p in parsed]
        cc = [r["concurrent_count"] for r in result]
        return {"session_id": sid, "events": result, "max_concurrency": max(cc) if cc else 0,
                "avg_concurrency": round(sum(cc) / len(cc), 1) if cc else 0}

    def summarization(self, filters: dict) -> dict:
        p = filters.get("period", "day"); evts = self._filter(filters)
        n = len(evts); s_evts = [e for e in evts if e["was_summarized"]]
        sc = len(s_evts); fr = sum(1 for e in evts if "get_full" in e["tool"].lower())
        by_role: dict = {}
        for e in evts:
            role = "main" if e["agent_id"] == e["session_id"] else "subagent"
            if role not in by_role: by_role[role] = {"agent_role": role, "summarized_count": 0, "total_events": 0}
            by_role[role]["total_events"] += 1
            if e["was_summarized"]: by_role[role]["summarized_count"] += 1
        ot: dict = {}
        for e in evts:
            k = e["timestamp"][:10]
            if k not in ot: ot[k] = {"period": k, "summarized_count": 0, "total_events": 0}
            ot[k]["total_events"] += 1
            if e["was_summarized"]: ot[k]["summarized_count"] += 1
        return {
            "total_events": n, "summarized_count": sc,
            "summarization_rate": round(sc / n, 3) if n else 0,
            "full_content_requests": fr, "effective_summarized": sc - fr,
            "rejection_rate": round(fr / sc, 3) if sc else 0,
            "avg_compression_ratio": round(sum(min(e["original_size"], 2000) / max(e["original_size"], 1) for e in s_evts) / len(s_evts), 2) if s_evts else 0,
            "avg_original_size": round(sum(e["original_size"] for e in s_evts) / len(s_evts)) if s_evts else 0,
            "avg_summary_size": 2000 if s_evts else 0,
            "by_agent_role": list(by_role.values()),
            "over_time": sorted(ot.values(), key=lambda x: x["period"]),
        }

    def sessions(self, filters: dict) -> dict:
        page = int(filters.pop("page", 1)); sort = filters.pop("sort", "tokens")
        evts = self._filter(filters); sess: dict = {}
        for e in evts:
            sid = e["session_id"]
            if sid not in sess:
                sess[sid] = {"sid": sid, "evts": [], "tok": 0, "err": 0, "tools": set(), "subs": set()}
            s = sess[sid]; s["evts"].append(e); s["tok"] += e["input_tokens"] + e["output_tokens"]
            if e["status"] == "error": s["err"] += 1
            s["tools"].add(e["tool"])
            if e["agent_id"] != sid: s["subs"].add(e["agent_id"])
        rows = [{"session_id": s["sid"], "start_time": s["evts"][0]["timestamp"],
                 "end_time": s["evts"][-1]["timestamp"], "event_count": len(s["evts"]),
                 "total_tokens": s["tok"], "error_count": s["err"],
                 "unique_tools": len(s["tools"]), "subagent_count": len(s["subs"]),
                 "duration_ms": 0} for s in sess.values()]
        sk = {"tokens": "total_tokens", "errors": "error_count", "events": "event_count"}.get(sort, "total_tokens")
        rows.sort(key=lambda x: x[sk], reverse=True)
        off = (page - 1) * 50; ts = len(rows)
        return {"page": page, "total_sessions": ts, "total_pages": max(1, (ts + 49) // 50),
                "sort": sort, "sessions": rows[off:off + 50]}

    def session_detail(self, session_id: str) -> dict:
        evts = [e for e in self._events if e["session_id"] == session_id]
        if not evts:
            return {"session_id": session_id, "events": [], "summary": {}}
        det = [{"timestamp": e["timestamp"], "tool": e["tool"], "backend": e["backend"],
                "status": e["status"], "duration_ms": e["duration_ms"], "agent_id": e["agent_id"],
                "agent_type": e["agent_type"], "input_tokens": e["input_tokens"],
                "output_tokens": e["output_tokens"], "cache_read_tokens": e["cache_read_tokens"],
                "cache_creation_tokens": e["cache_creation_tokens"],
                "was_summarized": e["was_summarized"], "original_size": e["original_size"],
                "summary_size": e["summary_size"], "error_type": e["error_type"]} for e in evts]
        return {"session_id": session_id, "events": det, "summary": {
            "total_events": len(evts),
            "total_tokens": sum(e["input_tokens"] + e["output_tokens"] for e in evts),
            "error_count": sum(1 for e in evts if e["status"] == "error"),
            "duration_ms": 0,
            "subagent_count": len(set(e["agent_id"] for e in evts if e["agent_id"] != session_id))}}

    def session_replay(self, session_id: str, jsonl_dir: str) -> dict:
        return {"session_id": session_id, "messages": [], "error": "Replay not available for mock data"}

    def compare(self, filters_a: dict, filters_b: dict) -> dict:
        a, b = self.overview(filters_a), self.overview(filters_b)
        def pc(x, y): return round((y - x) / x * 100, 1) if x else 0
        return {"range_a": {"from": filters_a.get("from", ""), "to": filters_a.get("to", ""), "data": a},
                "range_b": {"from": filters_b.get("from", ""), "to": filters_b.get("to", ""), "data": b},
                "deltas": {"total_events": b["total_events"] - a["total_events"],
                           "total_tokens_pct": pc(a.get("total_input_tokens", 0) + a.get("total_output_tokens", 0),
                                                  b.get("total_input_tokens", 0) + b.get("total_output_tokens", 0)),
                           "error_rate_pct": pc(a.get("error_rate", 0), b.get("error_rate", 0)),
                           "avg_duration_ms_pct": pc(a.get("avg_duration_ms", 0), b.get("avg_duration_ms", 0))}}

    def activity_heatmap(self, filters: dict) -> dict:
        evts = self._filter(filters); grid: dict = {}
        for e in evts:
            try:
                dt = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))
                k = (dt.isoweekday() % 7, dt.hour)
            except (ValueError, TypeError): continue
            grid[k] = grid.get(k, 0) + 1
        return {"data": [{"day": k[0], "hour": k[1], "count": v} for k, v in sorted(grid.items())]}

    def latency(self, filters: dict) -> dict:
        lim = int(filters.pop("limit", 50)); evts = self._filter(filters); g: dict = {}
        for e in evts:
            t = e["tool"]
            if t not in g: g[t] = []
            g[t].append(e["duration_ms"])
        data = []
        for tool, ds in sorted(g.items(), key=lambda x: len(x[1]), reverse=True)[:lim]:
            data.append({"tool": tool, "call_count": len(ds), "avg_ms": round(sum(ds) / len(ds)),
                         "min_ms": min(ds), "max_ms": max(ds), "histogram": {
                             "<100ms": sum(1 for d in ds if d < 100),
                             "100-500ms": sum(1 for d in ds if 100 <= d < 500),
                             "500ms-1s": sum(1 for d in ds if 500 <= d < 1000),
                             "1-5s": sum(1 for d in ds if 1000 <= d < 5000),
                             "5-30s": sum(1 for d in ds if 5000 <= d < 30000),
                             "30s+": sum(1 for d in ds if d >= 30000)}})
        return {"data": data}

    def errors(self, filters: dict) -> dict:
        gb = filters.pop("group_by", "type"); lim = int(filters.pop("limit", 50))
        evts = self._filter(filters)
        if gb == "tool":
            tt: dict = {}; te: dict = {}
            for e in evts:
                t = e["tool"]; tt[t] = tt.get(t, 0) + 1
                if e["status"] == "error": te[t] = te.get(t, 0) + 1
            data = [{"tool": t, "error_count": c, "total_count": tt.get(t, 1),
                     "error_rate": round(c / tt.get(t, 1), 3)}
                    for t, c in sorted(te.items(), key=lambda x: x[1], reverse=True)[:lim]]
            return {"group_by": "tool", "data": data}
        else:
            tc: dict = {}
            for e in evts:
                if e["status"] == "error" and e["error_type"]:
                    tc[e["error_type"]] = tc.get(e["error_type"], 0) + 1
            return {"group_by": "type", "data": [{"error_type": k, "count": v}
                    for k, v in sorted(tc.items(), key=lambda x: x[1], reverse=True)][:lim]}
