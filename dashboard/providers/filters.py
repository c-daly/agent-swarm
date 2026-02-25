"""Shared filter and SQL builder utilities for dashboard providers."""

from datetime import datetime, timezone


def build_where(filters: dict) -> tuple[str, list]:
    """Build WHERE clause and params from filters dict.

    All timestamps in the database and API are UTC. The frontend handles
    EST timezone conversion via JavaScript.

    Returns:
        (where_clause, params) where where_clause includes 'WHERE' prefix
        or empty string if no filters.
    """
    clauses: list[str] = []
    params: list = []

    if "from" in filters:
        clauses.append("timestamp >= ?")
        params.append(filters["from"])
    if "to" in filters:
        clauses.append("timestamp <= ?")
        params.append(filters["to"])
    if "tool" in filters:
        tools = [t.strip() for t in filters["tool"].split(",")]
        placeholders = ",".join("?" * len(tools))
        clauses.append(f"tool IN ({placeholders})")
        params.extend(tools)
    if "backend" in filters:
        backends = [b.strip() for b in filters["backend"].split(",")]
        placeholders = ",".join("?" * len(backends))
        clauses.append(f"backend IN ({placeholders})")
        params.extend(backends)
    if "status" in filters:
        clauses.append("status = ?")
        params.append(filters["status"])
    if "session" in filters:
        clauses.append("session_id = ?")
        params.append(filters["session"])
    if "agent_type" in filters:
        val = filters["agent_type"]
        if val == "main":
            clauses.append("agent_id = session_id")
        elif val == "subagent":
            clauses.append("agent_id != session_id")
        else:
            clauses.append("agent_type = ?")
            params.append(val)
    if "import_source" in filters:
        clauses.append("import_source = ?")
        params.append(filters["import_source"])

    if not clauses:
        return "", []
    return "WHERE " + " AND ".join(clauses), params


def period_group_expr(period: str) -> str:
    """Return SQL expression for grouping timestamps by period.

    Timestamps are stored and grouped in UTC. The frontend converts
    to EST (UTC-5) for display.
    """
    if period == "hour":
        return "strftime('%Y-%m-%d %H:00', timestamp)"
    elif period == "day":
        return "strftime('%Y-%m-%d', timestamp)"
    elif period == "week":
        return "strftime('%Y-W%W', timestamp)"
    elif period == "month":
        return "strftime('%Y-%m', timestamp)"
    return "strftime('%Y-%m-%d', timestamp)"
