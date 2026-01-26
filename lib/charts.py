"""Chart generation using TelemetryService.

Provides text-based chart rendering for telemetry data visualization.
Uses TelemetryService as the data source for validated metrics.
"""

from datetime import date, timedelta
from typing import Optional, TYPE_CHECKING

from lib.telemetry_service import TelemetryService

if TYPE_CHECKING:
    from lib.stores.duckdb_store import DuckDBStore


def _format_confidence(confidence: float) -> str:
    """Format confidence score as a visual indicator.

    Args:
        confidence: Score from 0.0 to 1.0.

    Returns:
        String indicator like "[OK]", "[WARN]", or "[LOW]".
    """
    if confidence >= 0.8:
        return "[OK]"
    elif confidence >= 0.5:
        return "[WARN]"
    else:
        return "[LOW]"


def _render_bar(value: int, max_value: int, width: int = 40) -> str:
    """Render a horizontal bar for text-based charts.

    Args:
        value: Current value to display.
        max_value: Maximum value for scaling.
        width: Character width of the bar.

    Returns:
        String representation of the bar.
    """
    if max_value == 0:
        return " " * width
    ratio = min(value / max_value, 1.0)
    filled = int(ratio * width)
    return "#" * filled + "-" * (width - filled)


def render_daily_summary(
    service: TelemetryService,
    date_str: str,
) -> str:
    """Render a daily summary chart with confidence indicators.

    Args:
        service: TelemetryService instance for data access.
        date_str: Date in ISO format (YYYY-MM-DD).

    Returns:
        Formatted string with daily metrics and confidence info.
    """
    result = service.get_summary(date_str)

    if result is None:
        return f"No data available for {date_str}"

    summary = result.data
    conf = _format_confidence(result.confidence)

    lines = [
        f"Daily Summary for {date_str} {conf}",
        "=" * 50,
        f"Sessions:      {summary.sessions:>10}",
        f"Tool Calls:    {summary.tool_calls:>10}",
        f"Total Tokens:  {summary.total_tokens:>10}",
        f"Cache Hits:    {summary.cache_hits:>10}",
        f"Cache Ratio:   {summary.cache_ratio:>10.1%}",
        f"Tokens Saved:  {summary.tokens_saved:>10}",
    ]

    if result.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in result.warnings:
            lines.append(f"  - {warning}")

    return "\n".join(lines)


def render_tool_breakdown(
    service: TelemetryService,
    limit: int = 10,
) -> str:
    """Render a tool usage breakdown chart.

    Args:
        service: TelemetryService instance for data access.
        limit: Maximum number of tools to display.

    Returns:
        Formatted string with tool statistics.
    """
    tools = service.get_tool_breakdown(limit=limit)

    if not tools:
        return "No tool data available"

    max_calls = max(t.call_count for t in tools) if tools else 1

    lines = [
        "Tool Usage Breakdown",
        "=" * 70,
        f"{'Tool':<25} {'Calls':>8} {'Avg(ms)':>8} {'Cache%':>7} {'Bar':<20}",
        "-" * 70,
    ]

    for tool in tools:
        bar = _render_bar(tool.call_count, max_calls, width=20)
        lines.append(
            f"{tool.tool_name:<25} "
            f"{tool.call_count:>8} "
            f"{tool.avg_duration_ms:>8.1f} "
            f"{tool.cache_hit_rate:>6.1%} "
            f"{bar}"
        )

    return "\n".join(lines)


def render_weekly_trend(
    service: TelemetryService,
    end_date: Optional[str] = None,
) -> str:
    """Render a 7-day trend chart for key metrics.

    Args:
        service: TelemetryService instance for data access.
        end_date: End date in ISO format. Defaults to today.

    Returns:
        Formatted string with weekly trend data and confidence.
    """
    if end_date is None:
        end = date.today()
    else:
        end = date.fromisoformat(end_date)

    dates = [(end - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]

    lines = [
        "Weekly Trend (Last 7 Days)",
        "=" * 60,
        f"{'Date':<12} {'Calls':>8} {'Tokens':>10} {'Cache%':>8} {'Conf':>6}",
        "-" * 60,
    ]

    total_calls = 0
    total_tokens = 0
    valid_days = 0
    warnings_count = 0

    for date_str in dates:
        result = service.get_summary(date_str)

        if result is None:
            lines.append(f"{date_str:<12} {'--':>8} {'--':>10} {'--':>8} {'--':>6}")
            continue

        summary = result.data
        conf = _format_confidence(result.confidence)

        lines.append(
            f"{date_str:<12} "
            f"{summary.tool_calls:>8} "
            f"{summary.total_tokens:>10} "
            f"{summary.cache_ratio:>7.1%} "
            f"{conf:>6}"
        )

        total_calls += summary.tool_calls
        total_tokens += summary.total_tokens
        valid_days += 1
        warnings_count += len(result.warnings)

    lines.append("-" * 60)
    if valid_days > 0:
        avg_calls = total_calls // valid_days
        avg_tokens = total_tokens // valid_days
        lines.append(f"{'Average':<12} {avg_calls:>8} {avg_tokens:>10}")
    else:
        lines.append("No data available for the period")

    if warnings_count > 0:
        lines.append(f"\nTotal warnings across period: {warnings_count}")

    return "\n".join(lines)


def render_dashboard(
    service: Optional[TelemetryService] = None,
    date_str: Optional[str] = None,
    data_dir: str = "logs",
) -> str:
    """Render a full dashboard with all charts.

    Args:
        service: Optional TelemetryService instance. Created if not provided.
        date_str: Date for daily summary. Defaults to today.
        data_dir: Directory for data storage when creating service.

    Returns:
        Formatted string with complete dashboard output.
    """
    if service is None:
        service = TelemetryService(data_dir=data_dir)

    if date_str is None:
        date_str = date.today().isoformat()

    sections = [
        render_daily_summary(service, date_str),
        "",
        render_tool_breakdown(service, limit=10),
        "",
        render_weekly_trend(service, date_str),
    ]

    return "\n".join(sections)




def get_callback_rate_chart(service: TelemetryService) -> str:
    """Render summarization callback rate stats.

    Args:
        service: TelemetryService instance.

    Returns:
        Formatted string showing callback rate metrics.
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

# -----------------------------------------------------------------------------
# JSON Chart Endpoints (Telemetry v3)
# -----------------------------------------------------------------------------

def get_token_spend_chart(
    store: "DuckDBStore",
    days: int = 30,
) -> list[dict]:
    """Get token spend data for charting.

    Returns daily token totals with 7-day moving average,
    suitable for line chart visualization.

    Args:
        store: DuckDBStore instance with chart query methods.
        days: Number of days to look back (default 30).

    Returns:
        List of dicts with keys: day, total_tokens, moving_avg_7d.
        Empty list if no data exists.
    """
    return store.get_token_spend_by_day(days=days)


def get_agent_token_chart(store: "DuckDBStore") -> list[dict]:
    """Get token spend by agent type for charting.

    Returns token totals grouped by agent type (main, Explore, etc.),
    suitable for pie/bar chart visualization.

    Args:
        store: DuckDBStore instance with chart query methods.

    Returns:
        List of dicts with keys: agent_type, total_tokens, sessions.
        Empty list if no data exists.
    """
    return store.get_token_spend_by_agent_type()


def get_cache_efficiency_chart(
    store: "DuckDBStore",
    days: int = 30,
) -> list[dict]:
    """Get cache efficiency trend for charting.

    Returns daily cache hit percentages,
    suitable for line chart visualization.

    Args:
        store: DuckDBStore instance with chart query methods.
        days: Number of days to look back (default 30).

    Returns:
        List of dicts with keys: day, cached, total_input, cache_pct.
        Empty list if no data exists.
    """
    return store.get_cache_efficiency_trend(days=days)


def get_tool_latency_chart(store: "DuckDBStore") -> list[dict]:
    """Get tool latency by backend for charting.

    Returns average and P95 latency per backend,
    suitable for bar chart visualization.

    Args:
        store: DuckDBStore instance with chart query methods.

    Returns:
        List of dicts with keys: backend, avg_latency, p95.
        Empty list if no data exists.
    """
    return store.get_tool_latency_by_backend()


def get_error_rate_chart(
    store: "DuckDBStore",
    limit: int = 20,
) -> list[dict]:
    """Get error rates by tool for charting.

    Returns error percentages per tool, ordered by error rate descending,
    suitable for bar chart visualization.

    Args:
        store: DuckDBStore instance with chart query methods.
        limit: Maximum number of tools to return (default 20).

    Returns:
        List of dicts with keys: tool, total_calls, errors, error_pct.
        Empty list if no data exists.
    """
    return store.get_error_rate_by_tool(limit=limit)
