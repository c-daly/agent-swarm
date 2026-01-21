"""Chart generation using TelemetryService.

Provides text-based chart rendering for telemetry data visualization.
Uses TelemetryService as the data source for validated metrics.
"""

from datetime import date, timedelta
from typing import Optional

from lib.telemetry_service import TelemetryService


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
