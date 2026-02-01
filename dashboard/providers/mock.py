"""Mock data provider for dashboard development. Deterministic with seed=42."""

import random
from datetime import datetime, timedelta, timezone


# Tool distribution approximating real data
TOOLS = [
    ("Bash", "native", 0.20),
    ("Read", "native", 0.15),
    ("mcp__router__serena__read_file", "router", 0.10),
    ("mcp__router__serena__search_for_pattern", "router", 0.08),
    ("mcp__router__serena__find_symbol", "router", 0.06),
    ("mcp__router__native__bash", "router", 0.05),
    ("Edit", "native", 0.05),
    ("Write", "native", 0.04),
    ("Glob", "native", 0.04),
    ("Grep", "native", 0.04),
    ("Task", "claude", 0.05),
    ("mcp__router__serena__replace_content", "router", 0.03),
    ("mcp__router__serena__execute_shell_command", "router", 0.03),
    ("mcp__plugin_memory__search", "plugin", 0.02),
    ("WebFetch", "claude", 0.02),
    ("mcp__context7__query-docs", "mcp", 0.02),
    ("Skill", "claude", 0.01),
    ("AskUserQuestion", "claude", 0.01),
]


class MockProvider:
    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)
        self._events: list[dict] = []
        self._sessions: list[str] = []
        self._generate_data()

    def _generate_data(self) -> None:
        """Generate 5000 synthetic events across 200 sessions over 14 days."""
        start = datetime(2026, 1, 17, 8, 0, 0, tzinfo=timezone.utc)
        self._sessions = [f"sess-{i:04d}" for i in range(200)]

        # Distribute events across sessions (power law-ish)
        session_sizes = []
        for _ in range(200):
            size = max(1, int(self._rng.paretovariate(1.5) * 5))
            session_sizes.append(size)

        # Normalize to ~5000 total
        total = sum(session_sizes)
        session_sizes = [max(1, int(s / total * 5000)) for s in session_sizes]

        for sid, count in zip(self._sessions, session_sizes):
            session_start = start + timedelta(
                days=self._rng.uniform(0, 14),
                hours=self._rng.uniform(0, 16),
            )
            # Some sessions have subagents
            has_subagents = self._rng.random() < 0.3
            agent_ids = [sid]
            if has_subagents:
                n_sub = self._rng.randint(1, 4)
                agent_ids += [f"agent-{self._rng.randint(1000, 9999)}" for _ in range(n_sub)]

            for i in range(count):
                ts = session_start + timedelta(seconds=i * self._rng.uniform(1, 30))
                tool, backend, _ = self._rng.choices(TOOLS, weights=[t[2] for t in TOOLS])[0]
                is_error = self._rng.random() < 0.12
                duration = int(self._rng.expovariate(1 / 2000))
                was_summarized = self._rng.random() < 0.06
                original_size = self._rng.randint(100, 15000) if was_summarized else self._rng.randint(10, 2000)

                self._events.append({
                    "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z",
                    "session_id": sid,
                    "agent_id": self._rng.choice(agent_ids),
                    "tool": tool,
                    "backend": backend,
                    "duration_ms": duration,
                    "status": "error" if is_error else "success",
                    "input_tokens": self._rng.randint(5, 500),
                    "output_tokens": self._rng.randint(5, 300),
                    "cache_read_tokens": self._rng.randint(0, 50000),
                    "cache_creation_tokens": self._rng.randint(0, 5000),
                    "agent_type": "",
                    "was_summarized": was_summarized,
                    "original_size": original_size,
                    "summary_size": min(original_size, 2000) if was_summarized else None,
                    "error_type": f"Error: mock error {self._rng.randint(1, 20)}" if is_error else "",
                    "import_source": "mock",
                })

        self._events.sort(key=lambda e: e["timestamp"])

    def _filter_events(self, filters: dict) -> list[dict]:
        """Apply filters to the in-memory event list."""
        result = self._events
        if "from" in filters:
            result = [e for e in result if e["timestamp"] >= filters["from"]]
        if "to" in filters:
            result = [e for e in result if e["timestamp"] <= filters["to"]]
        if "tool" in filters:
            tools = {t.strip() for t in filters["tool"].split(",")}
            result = [e for e in result if e["tool"] in tools]
        if "backend" in filters:
            backends = {b.strip() for b in filters["backend"].split(",")}
            result = [e for e in result if e["backend"] in backends]
        if "status" in filters:
            result = [e for e in result if e["status"] == filters["status"]]
        if "session" in filters:
            result = [e for e in result if e["session_id"] == filters["session"]]
        if "agent_type" in filters:
            val = filters["agent_type"]
            if val == "main":
                result = [e for e in result if e["agent_id"] == e["session_id"]]
            elif val == "subagent":
                result = [e for e in result if e["agent_id"] != e["session_id"]]
        return result

    def health(self) -> dict:
        return {
            "status": "ok",
            "db_path": ":mock:",
            "db_size_bytes": 0,
            "total_events": len(self._events),
            "total_sessions": len(self._sessions),
            "first_event": self._events[0]["timestamp"] if self._events else "",
            "last_event": self._events[-1]["timestamp"] if self._events else "",
            "imports": [{"source": "mock", "last_import": "2026-01-31T00:00:00Z", "total_inserted": len(self._events)}],
        }

    def overview(self, filters: dict) -> dict:
        events = self._filter_events(filters)
        total = len(events)
        errors = sum(1 for e in events if e["status"] == "error")
        return {
            "total_events": total,
            "total_sessions": len(set(e["session_id"] for e in events)),
            "total_input_tokens": sum(e["input_tokens"] for e in events),
            "total_output_tokens": sum(e["output_tokens"] for e in events),
            "total_cache_read": sum(e["cache_read_tokens"] for e in events),
            "total_cache_creation": sum(e["cache_creation_tokens"] for e in events),
            "total_errors": errors,
            "error_rate": round(errors / total, 3) if total else 0,
            "first_event": events[0]["timestamp"] if events else "",
            "last_event": events[-1]["timestamp"] if events else "",
            "avg_duration_ms": round(sum(e["duration_ms"] for e in events) / total, 1) if total else 0,
            "total_summarized": sum(1 for e in events if e["was_summarized"]),
            "unique_tools": len(set(e["tool"] for e in events)),
            "subagent_count": len(set(e["agent_id"] for e in events if e["agent_id"] != e["session_id"])),
        }

    def tokens(self, filters: dict) -> dict:
        group_by = filters.pop("group_by", "day")
        limit = int(filters.pop("limit", 50))
        events = self._filter_events(filters)

        if group_by == "tool":
            groups: dict[str, dict] = {}
            for e in events:
                t = e["tool"]
                if t not in groups:
                    groups[t] = {"tool": t, "total_tokens": 0, "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "event_count": 0}
                g = groups[t]
                g["total_tokens"] += e["input_tokens"] + e["output_tokens"]
                g["input"] += e["input_tokens"]
                g["output"] += e["output_tokens"]
                g["cache_read"] += e["cache_read_tokens"]
                g["cache_creation"] += e["cache_creation_tokens"]
                g["event_count"] += 1
            data = sorted(groups.values(), key=lambda x: x["total_tokens"], reverse=True)[:limit]
            return {"group_by": "tool", "data": data}

        elif group_by == "agent":
            roles: dict[str, dict] = {}
            for e in events:
                role = "main" if e["agent_id"] == e["session_id"] else "subagent"
                if role not in roles:
                    roles[role] = {"agent_role": role, "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "event_count": 0}
                r = roles[role]
                r["input"] += e["input_tokens"]
                r["output"] += e["output_tokens"]
                r["cache_read"] += e["cache_read_tokens"]
                r["cache_creation"] += e["cache_creation_tokens"]
                r["event_count"] += 1
            return {"group_by": "agent", "data": list(roles.values())}

        else:
            period = filters.get("period", "day")
            groups = {}
            for e in events:
                ts = e["timestamp"][:10]  # day grouping
                if period == "hour":
                    ts = e["timestamp"][:13] + ":00"
                elif period == "week":
                    dt = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))
                    ts = f"{dt.year}-W{dt.isocalendar()[1]:02d}"
                elif period == "month":
                    ts = e["timestamp"][:7]
                if ts not in groups:
                    groups[ts] = {"period": ts, "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "event_count": 0}
                g = groups[ts]
                g["input"] += e["input_tokens"]
                g["output"] += e["output_tokens"]
                g["cache_read"] += e["cache_read_tokens"]
                g["cache_creation"] += e["cache_creation_tokens"]
                g["event_count"] += 1
            data = sorted(groups.values(), key=lambda x: x["period"])
            return {"group_by": group_by, "period": period, "data": data}

    def tools(self, filters: dict) -> dict:
        sort = filters.pop("sort", "count")
        limit = int(filters.pop("limit", 50))
        events = self._filter_events(filters)

        groups: dict[str, dict] = {}
        for e in events:
            t = e["tool"]
            if t not in groups:
                groups[t] = {"tool": t, "call_count": 0, "error_count": 0, "total_tokens": 0, "total_duration": 0, "summarized_count": 0}
            g = groups[t]
            g["call_count"] += 1
            if e["status"] == "error":
                g["error_count"] += 1
            g["total_tokens"] += e["input_tokens"] + e["output_tokens"]
            g["total_duration"] += e["duration_ms"]
            if e["was_summarized"]:
                g["summarized_count"] += 1

        data = []
        for g in groups.values():
            data.append({
                "tool": g["tool"],
                "call_count": g["call_count"],
                "error_count": g["error_count"],
                "error_rate": round(g["error_count"] / g["call_count"], 3) if g["call_count"] else 0,
                "total_tokens": g["total_tokens"],
                "avg_duration_ms": round(g["total_duration"] / g["call_count"], 1) if g["call_count"] else 0,
                "summarized_count": g["summarized_count"],
            })

        sort_key = {"count": "call_count", "errors": "error_count", "tokens": "total_tokens"}.get(sort, "call_count")
        data.sort(key=lambda x: x[sort_key], reverse=True)
        return {"sort": sort, "data": data[:limit]}

    def concurrency(self, filters: dict) -> dict:
        session_id = filters.get("session", "")
        events = [e for e in self._events if e["session_id"] == session_id]
        if not events:
            return {"session_id": session_id, "events": [], "max_concurrency": 0, "avg_concurrency": 0}

        parsed = []
        for e in events:
            try:
                start = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))
                end = start + timedelta(milliseconds=e["duration_ms"])
            except (ValueError, TypeError):
                start = end = None
            parsed.append({**e, "_start": start, "_end": end})

        for i, evt in enumerate(parsed):
            if evt["_start"] is None:
                evt["concurrent_count"] = 0
                continue
            count = sum(
                1 for j, o in enumerate(parsed)
                if i != j and o["_start"] is not None and o["_start"] < evt["_end"] and o["_end"] > evt["_start"]
            )
            evt["concurrent_count"] = count

        result = []
        for p in parsed:
            del p["_start"]
            del p["_end"]
            result.append(p)

        cc = [r["concurrent_count"] for r in result]
        return {
            "session_id": session_id,
            "events": result,
            "max_concurrency": max(cc) if cc else 0,
            "avg_concurrency": round(sum(cc) / len(cc), 1) if cc else 0,
        }

    def summarization(self, filters: dict) -> dict:
        period = filters.get("period", "day")
        events = self._filter_events(filters)
        total = len(events)
        summarized = [e for e in events if e["was_summarized"]]
        full_reqs = sum(1 for e in events if "get_full" in e["tool"].lower())
        s_count = len(summarized)
        effective = s_count - full_reqs

        by_role: dict[str, dict] = {}
        for e in events:
            role = "main" if e["agent_id"] == e["session_id"] else "subagent"
            if role not in by_role:
                by_role[role] = {"agent_role": role, "summarized_count": 0, "total_events": 0}
            by_role[role]["total_events"] += 1
            if e["was_summarized"]:
                by_role[role]["summarized_count"] += 1

        over_time: dict[str, dict] = {}
        for e in events:
            p = e["timestamp"][:10]
            if p not in over_time:
                over_time[p] = {"period": p, "summarized_count": 0, "total_events": 0}
            over_time[p]["total_events"] += 1
            if e["was_summarized"]:
                over_time[p]["summarized_count"] += 1

        avg_cr = 0
        if summarized:
            ratios = [min(e["original_size"], 2000) / max(e["original_size"], 1) for e in summarized]
            avg_cr = round(sum(ratios) / len(ratios), 2)

        gf_rate = round(full_reqs / s_count, 3) if s_count and full_reqs else None

        return {
            "total_events": total,
            "summarized_count": s_count,
            "summarization_rate": round(s_count / total, 3) if total else 0,
            "full_content_requests": full_reqs,
            "effective_summarized": effective,
            "rejection_rate": round(full_reqs / s_count, 3) if s_count else 0,
            "get_full_rate": gf_rate,
            "get_full_since": None,
            "summaries_since_get_full": 0,
            "avg_compression_ratio": avg_cr,
            "avg_original_size": round(sum(e["original_size"] for e in summarized) / len(summarized)) if summarized else 0,
            "avg_summary_size": 2000 if summarized else 0,
            "by_agent_role": list(by_role.values()),
            "over_time": sorted(over_time.values(), key=lambda x: x["period"]),
        }

    def sessions(self, filters: dict) -> dict:
        page = int(filters.pop("page", 1))
        sort = filters.pop("sort", "tokens")
        limit = 50
        events = self._filter_events(filters)

        sess: dict[str, dict] = {}
        for e in events:
            sid = e["session_id"]
            if sid not in sess:
                sess[sid] = {"session_id": sid, "events": [], "tokens": 0, "errors": 0, "tools": set(), "subagents": set()}
            s = sess[sid]
            s["events"].append(e)
            s["tokens"] += e["input_tokens"] + e["output_tokens"]
            if e["status"] == "error":
                s["errors"] += 1
            s["tools"].add(e["tool"])
            if e["agent_id"] != sid:
                s["subagents"].add(e["agent_id"])

        rows = []
        for s in sess.values():
            evts = s["events"]
            rows.append({
                "session_id": s["session_id"],
                "start_time": evts[0]["timestamp"],
                "end_time": evts[-1]["timestamp"],
                "event_count": len(evts),
                "total_tokens": s["tokens"],
                "error_count": s["errors"],
                "unique_tools": len(s["tools"]),
                "subagent_count": len(s["subagents"]),
                "duration_ms": 0,
            })

        sort_key = {"tokens": "total_tokens", "errors": "error_count", "events": "event_count", "duration": "duration_ms"}.get(sort, "total_tokens")
        rows.sort(key=lambda x: x[sort_key], reverse=True)

        offset = (page - 1) * limit
        total_sessions = len(rows)

        return {
            "page": page,
            "total_sessions": total_sessions,
            "total_pages": max(1, (total_sessions + limit - 1) // limit),
            "sort": sort,
            "sessions": rows[offset:offset + limit],
        }

    def session_detail(self, session_id: str) -> dict:
        events = [e for e in self._events if e["session_id"] == session_id]
        if not events:
            return {"session_id": session_id, "events": [], "summary": {}}

        total_tokens = sum(e["input_tokens"] + e["output_tokens"] for e in events)
        error_count = sum(1 for e in events if e["status"] == "error")
        subagents = set(e["agent_id"] for e in events if e["agent_id"] != session_id)

        detail_events = []
        for e in events:
            detail_events.append({
                "timestamp": e["timestamp"],
                "tool": e["tool"],
                "backend": e["backend"],
                "status": e["status"],
                "duration_ms": e["duration_ms"],
                "agent_id": e["agent_id"],
                "agent_type": e["agent_type"],
                "input_tokens": e["input_tokens"],
                "output_tokens": e["output_tokens"],
                "cache_read_tokens": e["cache_read_tokens"],
                "cache_creation_tokens": e["cache_creation_tokens"],
                "was_summarized": e["was_summarized"],
                "original_size": e["original_size"],
                "summary_size": e["summary_size"],
                "error_type": e["error_type"],
            })

        return {
            "session_id": session_id,
            "events": detail_events,
            "summary": {
                "total_events": len(events),
                "total_tokens": total_tokens,
                "error_count": error_count,
                "duration_ms": 0,
                "subagent_count": len(subagents),
            },
        }

    def session_replay(self, session_id: str, jsonl_dir: str) -> dict:
        return {"session_id": session_id, "messages": [], "error": "Replay not available for mock data"}

    def compare(self, filters_a: dict, filters_b: dict) -> dict:
        data_a = self.overview(filters_a)
        data_b = self.overview(filters_b)

        def pct_change(a, b):
            if not a:
                return 0
            return round((b - a) / a * 100, 1)

        return {
            "range_a": {"from": filters_a.get("from", ""), "to": filters_a.get("to", ""), "data": data_a},
            "range_b": {"from": filters_b.get("from", ""), "to": filters_b.get("to", ""), "data": data_b},
            "deltas": {
                "total_events": data_b.get("total_events", 0) - data_a.get("total_events", 0),
                "total_tokens_pct": pct_change(
                    data_a.get("total_input_tokens", 0) + data_a.get("total_output_tokens", 0),
                    data_b.get("total_input_tokens", 0) + data_b.get("total_output_tokens", 0),
                ),
                "error_rate_pct": pct_change(data_a.get("error_rate", 0), data_b.get("error_rate", 0)),
                "avg_duration_ms_pct": pct_change(data_a.get("avg_duration_ms", 0), data_b.get("avg_duration_ms", 0)),
            },
        }

    def activity_heatmap(self, filters: dict) -> dict:
        events = self._filter_events(filters)
        grid: dict[tuple, int] = {}
        for e in events:
            try:
                dt = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))
                key = (dt.weekday(), dt.hour)
                # Convert Python weekday (Mon=0) to JS weekday (Sun=0)
                js_day = (dt.isoweekday() % 7)
                key = (js_day, dt.hour)
            except (ValueError, TypeError):
                continue
            grid[key] = grid.get(key, 0) + 1
        return {"data": [{"day": k[0], "hour": k[1], "count": v} for k, v in sorted(grid.items())]}

    def latency(self, filters: dict) -> dict:
        limit = int(filters.pop("limit", 50))
        events = self._filter_events(filters)

        groups: dict[str, list] = {}
        for e in events:
            t = e["tool"]
            if t not in groups:
                groups[t] = []
            groups[t].append(e["duration_ms"])

        data = []
        for tool, durations in sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)[:limit]:
            data.append({
                "tool": tool,
                "call_count": len(durations),
                "avg_ms": round(sum(durations) / len(durations)),
                "min_ms": min(durations),
                "max_ms": max(durations),
                "histogram": {
                    "<100ms": sum(1 for d in durations if d < 100),
                    "100-500ms": sum(1 for d in durations if 100 <= d < 500),
                    "500ms-1s": sum(1 for d in durations if 500 <= d < 1000),
                    "1-5s": sum(1 for d in durations if 1000 <= d < 5000),
                    "5-30s": sum(1 for d in durations if 5000 <= d < 30000),
                    "30s+": sum(1 for d in durations if d >= 30000),
                },
            })
        return {"data": data}

    def errors(self, filters: dict) -> dict:
        group_by = filters.pop("group_by", "type")
        limit = int(filters.pop("limit", 50))
        events = self._filter_events(filters)

        if group_by == "tool":
            tool_totals: dict[str, int] = {}
            tool_errors: dict[str, int] = {}
            for e in events:
                t = e["tool"]
                tool_totals[t] = tool_totals.get(t, 0) + 1
                if e["status"] == "error":
                    tool_errors[t] = tool_errors.get(t, 0) + 1
            data = []
            for tool, err_count in sorted(tool_errors.items(), key=lambda x: x[1], reverse=True)[:limit]:
                total = tool_totals.get(tool, 1)
                data.append({
                    "tool": tool,
                    "error_count": err_count,
                    "total_count": total,
                    "error_rate": round(err_count / total, 3),
                })
            return {"group_by": "tool", "data": data}

        else:
            type_counts: dict[str, int] = {}
            for e in events:
                if e["status"] == "error" and e["error_type"]:
                    et = e["error_type"]
                    type_counts[et] = type_counts.get(et, 0) + 1
            data = [{"error_type": k, "count": v} for k, v in sorted(type_counts.items(), key=lambda x: x[1], reverse=True)][:limit]
            return {"group_by": "type", "data": data}
