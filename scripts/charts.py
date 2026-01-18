#!/usr/bin/env python3
"""
Generate visual charts from agent-swarm telemetry.

Usage:
    python3 charts.py dashboard           # All charts dashboard
    python3 charts.py telemetry           # Real-time telemetry stats
    python3 charts.py tool-usage          # Tool usage breakdown
    python3 charts.py token-trend         # Token usage over time
    python3 charts.py efficiency          # Success rate trend
    python3 charts.py subagents           # Subagent token usage
    python3 charts.py latency             # Tool call latency
    python3 charts.py errors              # Error timeline
    python3 charts.py heatmap             # Activity by hour
    python3 charts.py native-vs-mcp       # Backend comparison
    python3 charts.py token-efficiency    # Tokens per call
    python3 charts.py blocked-tools       # Failed/blocked tools

Output: HTML files with interactive charts (opens in browser)
All times displayed in EST.
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"
CHARTS_DIR = STATE_DIR / "charts"
HISTORY_FILE = STATE_DIR / "metrics_history.json"
ACTIVITY_LOG = STATE_DIR / "activity.log"
SUBAGENT_METRICS = STATE_DIR / "subagent_metrics.json"
TELEMETRY_FILE = STATE_DIR / "telemetry.json"

def ensure_charts_dir():
    """Create charts directory if needed."""
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)

def load_history():
    """Load historical metrics."""
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return {"snapshots": []}

def save_snapshot(metrics_data):
    """Save current metrics to history."""
    history = load_history()

    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "metrics": metrics_data
    }

    history["snapshots"].append(snapshot)

    # Keep last 100 snapshots
    if len(history["snapshots"]) > 100:
        history["snapshots"] = history["snapshots"][-100:]

    HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding='utf-8')
    print(f"✅ Snapshot saved ({len(history['snapshots'])} total)")


def get_chart_dropdown_css():
    """Return CSS for chart dropdowns."""
    return """
        .controls {
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }
        .controls label {
            font-weight: 600;
            color: #888;
        }
        .controls select {
            padding: 8px 12px;
            border: 1px solid #333;
            border-radius: 4px;
            font-size: 14px;
            background: #0f0f1e;
            color: #eee;
            cursor: pointer;
        }
        .controls select:hover {
            border-color: #4cc9f0;
        }
"""


def get_chart_dropdown_html(options, default_value=None):
    """Generate dropdown HTML for chart timeframe selection.
    
    Args:
        options: List of tuples (value, label) for dropdown options
        default_value: Which option to select by default
    """
    option_html = []
    for value, label in options:
        selected = ' selected' if value == default_value else ''
        option_html.append(f'<option value="{value}"{selected}>{label}</option>')
    
    return f'''
        <div class="controls">
            <label for="viewSelect">View:</label>
            <select id="viewSelect" onchange="switchView()">
                {"".join(option_html)}
            </select>
        </div>
'''


# Standard dropdown options for different chart types
TIMEFRAME_OPTIONS_STANDARD = [
    ('7d', 'Last 7 Days'),
    ('30d', 'Last 30 Days'),
    ('all', 'All Time'),
]

TIMEFRAME_OPTIONS_WITH_SESSION = [
    ('7d', 'Last 7 Days'),
    ('30d', 'Last 30 Days'),
    ('all', 'All Time'),
    ('session', 'By Session'),
]

TIMEFRAME_OPTIONS_WITH_HOURLY = [
    ('7d', 'Last 7 Days'),
    ('30d', 'Last 30 Days'),
    ('all', 'All Time'),
    ('hourly', 'Hourly (Last 48h)'),
]

TIMEFRAME_OPTIONS_FULL = [
    ('7d', 'Last 7 Days'),
    ('30d', 'Last 30 Days'),
    ('all', 'All Time'),
    ('hourly', 'Hourly (Last 48h)'),
    ('session', 'By Session'),
]


def generate_html_chart(title, chart_type, data, labels, output_file, options=None):
    """Generate standalone HTML with Chart.js."""
    from datetime import timedelta, timezone

    # EST timezone offset (UTC-5)
    EST = timezone(timedelta(hours=-5))
    now_est = datetime.now(EST)

    if options is None:
        options = {}

    # Prepare data for Chart.js (using dark theme colors)
    if chart_type == "line":
        datasets = [{
            "label": data.get("label", "Value"),
            "data": data.get("values", []),
            "borderColor": "#4cc9f0",
            "backgroundColor": "rgba(76, 201, 240, 0.2)",
            "tension": 0.1
        }]
    elif chart_type == "bar":
        datasets = [{
            "label": data.get("label", "Value"),
            "data": data.get("values", []),
            "backgroundColor": [
                "rgba(76, 201, 240, 0.6)",
                "rgba(16, 185, 129, 0.6)",
                "rgba(251, 191, 36, 0.6)",
                "rgba(248, 113, 113, 0.6)",
                "rgba(167, 139, 250, 0.6)",
                "rgba(251, 146, 60, 0.6)"
            ][:len(data.get("values", []))]
        }]
    elif chart_type == "pie":
        datasets = [{
            "data": data.get("values", []),
            "backgroundColor": [
                "rgba(76, 201, 240, 0.8)",
                "rgba(16, 185, 129, 0.8)",
                "rgba(251, 191, 36, 0.8)",
                "rgba(248, 113, 113, 0.8)",
                "rgba(167, 139, 250, 0.8)",
                "rgba(251, 146, 60, 0.8)",
                "rgba(156, 163, 175, 0.8)"
            ][:len(data.get("values", []))]
        }]

    chart_data = {
        "labels": labels,
        "datasets": datasets
    }

    # Default scales for dark theme
    default_scales = {
        "y": {"ticks": {"color": "#888"}, "grid": {"color": "#333"}},
        "x": {"ticks": {"color": "#888"}, "grid": {"color": "#333"}}
    }
    scales_json = json.dumps(options.get('scales', default_scales)) if chart_type != "pie" else ""
    scales_section = f", scales: {scales_json}" if scales_json else ""

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            padding: 40px;
            background: #1a1a2e;
            color: #eee;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: #16213e;
            padding: 30px;
            border-radius: 8px;
            border: 1px solid #333;
        }}
        h1 {{
            color: #4cc9f0;
            margin-bottom: 10px;
        }}
        .timestamp {{
            color: #888;
            font-size: 14px;
            margin-bottom: 30px;
        }}
        canvas {{
            max-height: 500px;
        }}
        .back-link {{
            display: inline-block;
            margin-top: 20px;
            color: #4cc9f0;
            text-decoration: none;
        }}
        .back-link:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>
        <div class="timestamp">Generated: {now_est.strftime("%Y-%m-%d %H:%M:%S")} EST</div>
        <canvas id="chart"></canvas>
        <a href="dashboard.html" class="back-link">← Back to Dashboard</a>
    </div>

    <script>
        const ctx = document.getElementById('chart').getContext('2d');
        const chart = new Chart(ctx, {{
            type: '{chart_type}',
            data: {json.dumps(chart_data)},
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                plugins: {{
                    legend: {{
                        position: 'top',
                        labels: {{ color: '#888' }}
                    }},
                    title: {{
                        display: false
                    }}
                }}{scales_section}
            }}
        }});
    </script>
</body>
</html>"""

    output_path = CHARTS_DIR / output_file
    output_path.write_text(html, encoding='utf-8')
    return output_path

def chart_efficiency_trend():
    """Chart success rate trend over time with daily/hourly view toggle (uses telemetry.json)."""
    from datetime import datetime, timedelta, timezone
    from collections import defaultdict

    # EST timezone offset (UTC-5)
    EST = timezone(timedelta(hours=-5))

    if not TELEMETRY_FILE.exists():
        print("⚠️  No telemetry data found")
        return None

    telemetry = json.loads(TELEMETRY_FILE.read_text())
    events = telemetry.get("events", [])

    if len(events) < 2:
        print("⚠️  Need at least 2 events for trend chart")
        return None

    # Parse event timestamp and convert to EST
    def parse_event_time(event):
        try:
            ts = event.get("ts", "")
            if ts:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return dt.astimezone(EST)
        except:
            pass
        return None

    # Aggregate success rate by day
    daily_counts = defaultdict(lambda: {"success": 0, "total": 0})
    for event in events:
        dt = parse_event_time(event)
        if dt:
            date_str = dt.strftime("%Y-%m-%d")
            daily_counts[date_str]["total"] += 1
            if event.get("status") != "error":
                daily_counts[date_str]["success"] += 1

    # Aggregate success rate by hour (for recent view)
    hourly_counts = defaultdict(lambda: {"success": 0, "total": 0})
    for event in events:
        dt = parse_event_time(event)
        if dt:
            hour_str = dt.strftime("%Y-%m-%d %H:00")
            hourly_counts[hour_str]["total"] += 1
            if event.get("status") != "error":
                hourly_counts[hour_str]["success"] += 1

    # Calculate success rates
    sorted_daily = sorted(daily_counts.items())
    daily_labels = [date for date, _ in sorted_daily]
    daily_scores = [
        (data["success"] / data["total"] * 100) if data["total"] > 0 else 100
        for _, data in sorted_daily
    ]

    sorted_hourly = sorted(hourly_counts.items())[-48:]  # Last 48 hours
    hourly_labels = [hour for hour, _ in sorted_hourly]
    hourly_scores = [
        (data["success"] / data["total"] * 100) if data["total"] > 0 else 100
        for _, data in sorted_hourly
    ]

    # Current time in EST for display
    now = datetime.now(EST)

    # Generate HTML with dropdown
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Efficiency Score Trend</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            padding: 40px;
            background: #1a1a2e;
            color: #eee;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: #16213e;
            padding: 30px;
            border-radius: 8px;
            border: 1px solid #333;
        }}
        h1 {{
            color: #4cc9f0;
            margin-bottom: 10px;
        }}
        .controls {{
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .controls label {{
            font-weight: 600;
            color: #888;
        }}
        .controls select {{
            padding: 8px 12px;
            border: 1px solid #333;
            border-radius: 4px;
            font-size: 14px;
            background: #0f0f1e;
            color: #eee;
            cursor: pointer;
        }}
        .timestamp {{
            color: #888;
            font-size: 14px;
            margin-bottom: 20px;
        }}
        canvas {{
            max-height: 500px;
        }}
        .back-link {{
            display: inline-block;
            margin-top: 20px;
            color: #4cc9f0;
            text-decoration: none;
        }}
        .back-link:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📈 Success Rate Trend</h1>
        <div class="timestamp">Generated: {now.strftime("%Y-%m-%d %H:%M:%S")} EST</div>

        <div class="controls">
            <label for="viewSelect">View:</label>
            <select id="viewSelect" onchange="switchView()">
                <option value="daily">Daily Average</option>
                <option value="hourly">Hourly (Last 48h)</option>
            </select>
        </div>

        <canvas id="chart"></canvas>
        <a href="dashboard.html" class="back-link">← Back to Dashboard</a>
    </div>

    <script>
        const dailyData = {{
            labels: {json.dumps(daily_labels)},
            datasets: [{{
                label: 'Success Rate % (Daily)',
                data: {json.dumps(daily_scores)},
                borderColor: '#4cc9f0',
                backgroundColor: 'rgba(76, 201, 240, 0.2)',
                tension: 0.1,
                fill: true
            }}]
        }};

        const hourlyData = {{
            labels: {json.dumps(hourly_labels)},
            datasets: [{{
                label: 'Success Rate % (Hourly)',
                data: {json.dumps(hourly_scores)},
                borderColor: '#10b981',
                backgroundColor: 'rgba(16, 185, 129, 0.2)',
                tension: 0.1,
                fill: true
            }}]
        }};

        const ctx = document.getElementById('chart').getContext('2d');
        let chart = new Chart(ctx, {{
            type: 'line',
            data: dailyData,
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                plugins: {{
                    legend: {{
                        position: 'top',
                        labels: {{ color: '#888' }}
                    }},
                    title: {{
                        display: false
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        max: 100,
                        ticks: {{ color: '#888' }},
                        grid: {{ color: '#333' }}
                    }},
                    x: {{
                        ticks: {{ color: '#888' }},
                        grid: {{ color: '#333' }}
                    }}
                }}
            }}
        }});

        function switchView() {{
            const view = document.getElementById('viewSelect').value;
            chart.data = view === 'daily' ? dailyData : hourlyData;
            chart.update();
        }}
    </script>
</body>
</html>"""

    output_path = CHARTS_DIR / "efficiency_trend.html"
    output_path.write_text(html, encoding='utf-8')
    
    print(f"✅ Chart generated: {output_path}")
    return output_path

def chart_script_adoption():
    """DEPRECATED: Script adoption tracking not available in telemetry.json.

    The new telemetry system tracks tool calls but not script usage patterns.
    Use chart_tool_usage() or chart_native_vs_mcp() instead.
    """
    print("⚠️  chart_script_adoption is DEPRECATED")
    print("   Script usage tracking is not available in the new telemetry system.")
    print("   Use these alternatives:")
    print("     - tool-usage: See tool call breakdown")
    print("     - native-vs-mcp: Compare native vs MCP tools")
    return None

def chart_tool_usage():
    """Chart tool usage breakdown with time range filtering (uses telemetry.json)."""
    from datetime import datetime, timedelta, timezone
    from collections import defaultdict

    # EST timezone offset (UTC-5)
    EST = timezone(timedelta(hours=-5))

    if not TELEMETRY_FILE.exists():
        print("⚠️  No telemetry data found")
        return None

    telemetry = json.loads(TELEMETRY_FILE.read_text())
    events = telemetry.get("events", [])
    aggregates = telemetry.get("aggregates", {})

    if not events and not aggregates.get("by_tool"):
        print("⚠️  No tool usage data found")
        return None

    # Helper to aggregate tool usage from events
    def aggregate_tools_from_events(events_subset):
        aggregated = defaultdict(int)
        for event in events_subset:
            tool = event.get("tool", "unknown")
            aggregated[tool] += 1
        return aggregated

    # Parse event timestamp (ISO format in UTC, convert to EST)
    def parse_event_time(event):
        try:
            ts = event.get("ts", "")
            if ts:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return dt.astimezone(EST)
        except:
            pass
        return None

    # Current time in EST
    now = datetime.now(EST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # Filter events by time range
    session_events = events[-50:] if events else []  # Last 50 events as "session"
    today_events = [e for e in events if parse_event_time(e) and parse_event_time(e) >= today_start]
    week_events = [e for e in events if parse_event_time(e) and parse_event_time(e) >= week_ago]
    month_events = [e for e in events if parse_event_time(e) and parse_event_time(e) >= month_ago]

    # Aggregate for each time range
    session_tools = aggregate_tools_from_events(session_events)
    today_tools = aggregate_tools_from_events(today_events)
    week_tools = aggregate_tools_from_events(week_events)
    month_tools = aggregate_tools_from_events(month_events)

    # For all-time, use aggregates (includes data beyond the 500-event window)
    all_tools = {tool: data.get("count", 0) for tool, data in aggregates.get("by_tool", {}).items()}

    # Prepare sorted top 10 for each view
    def get_top_10(tools_dict):
        sorted_tools = sorted(tools_dict.items(), key=lambda x: -x[1])[:10]
        labels = [tool for tool, _ in sorted_tools]
        values = [count for _, count in sorted_tools]
        return labels, values

    session_labels, session_values = get_top_10(session_tools)
    today_labels, today_values = get_top_10(today_tools)
    week_labels, week_values = get_top_10(week_tools)
    month_labels, month_values = get_top_10(month_tools)
    all_labels, all_values = get_top_10(all_tools)

    # Generate HTML with dropdown for all time ranges
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Tool Usage Breakdown</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            padding: 40px;
            background: #1a1a2e;
            color: #eee;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: #16213e;
            padding: 30px;
            border-radius: 8px;
            border: 1px solid #333;
        }}
        h1 {{
            color: #4cc9f0;
            margin-bottom: 10px;
        }}
        .controls {{
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .controls label {{
            font-weight: 600;
            color: #888;
        }}
        .controls select {{
            padding: 8px 12px;
            border: 1px solid #333;
            border-radius: 4px;
            font-size: 14px;
            background: #0f0f1e;
            color: #eee;
            cursor: pointer;
        }}
        .timestamp {{
            color: #888;
            font-size: 14px;
            margin-bottom: 20px;
        }}
        canvas {{
            max-height: 500px;
        }}
        .back-link {{
            display: inline-block;
            margin-top: 20px;
            color: #4cc9f0;
            text-decoration: none;
        }}
        .back-link:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔧 Tool Usage Breakdown</h1>
        <div class="timestamp">Generated: {now.strftime("%Y-%m-%d %H:%M:%S")} EST</div>

        <div class="controls">
            <label for="viewSelect">Time Range:</label>
            <select id="viewSelect" onchange="switchView()">
                <option value="session" selected>Session</option>
                <option value="today">Today</option>
                <option value="week">Last Week</option>
                <option value="month">Last Month</option>
                <option value="all">All Time</option>
            </select>
        </div>

        <canvas id="chart"></canvas>
        <a href="dashboard.html" class="back-link">← Back to Dashboard</a>
    </div>

    <script>
        const colors = [
            'rgba(76, 201, 240, 0.6)',
            'rgba(16, 185, 129, 0.6)',
            'rgba(251, 191, 36, 0.6)',
            'rgba(248, 113, 113, 0.6)',
            'rgba(167, 139, 250, 0.6)',
            'rgba(251, 146, 60, 0.6)',
            'rgba(156, 163, 175, 0.6)',
            'rgba(236, 72, 153, 0.6)',
            'rgba(34, 211, 238, 0.6)',
            'rgba(163, 230, 53, 0.6)'
        ];

        const sessionData = {{
            labels: {json.dumps(session_labels)},
            datasets: [{{
                label: 'Tool Calls (Session)',
                data: {json.dumps(session_values)},
                backgroundColor: colors.slice(0, {len(session_labels)})
            }}]
        }};

        const todayData = {{
            labels: {json.dumps(today_labels)},
            datasets: [{{
                label: 'Tool Calls (Today)',
                data: {json.dumps(today_values)},
                backgroundColor: colors.slice(0, {len(today_labels)})
            }}]
        }};

        const weekData = {{
            labels: {json.dumps(week_labels)},
            datasets: [{{
                label: 'Tool Calls (Last Week)',
                data: {json.dumps(week_values)},
                backgroundColor: colors.slice(0, {len(week_labels)})
            }}]
        }};

        const monthData = {{
            labels: {json.dumps(month_labels)},
            datasets: [{{
                label: 'Tool Calls (Last Month)',
                data: {json.dumps(month_values)},
                backgroundColor: colors.slice(0, {len(month_labels)})
            }}]
        }};

        const allData = {{
            labels: {json.dumps(all_labels)},
            datasets: [{{
                label: 'Tool Calls (All Time)',
                data: {json.dumps(all_values)},
                backgroundColor: colors.slice(0, {len(all_labels)})
            }}]
        }};

        const ctx = document.getElementById('chart').getContext('2d');
        let chart = new Chart(ctx, {{
            type: 'bar',
            data: sessionData,
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                plugins: {{
                    legend: {{
                        position: 'top',
                        labels: {{ color: '#888' }}
                    }},
                    title: {{
                        display: false
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        ticks: {{ color: '#888' }},
                        grid: {{ color: '#333' }}
                    }},
                    x: {{
                        ticks: {{ color: '#888' }},
                        grid: {{ color: '#333' }}
                    }}
                }}
            }}
        }});

        function switchView() {{
            const view = document.getElementById('viewSelect').value;
            const dataMap = {{
                'session': sessionData,
                'today': todayData,
                'week': weekData,
                'month': monthData,
                'all': allData
            }};
            chart.data = dataMap[view];
            chart.update();
        }}
    </script>
</body>
</html>"""

    output_path = CHARTS_DIR / "tool_usage.html"
    output_path.write_text(html, encoding='utf-8')

    print(f"✅ Chart generated: {output_path}")
    return output_path

def chart_blocks():
    """DEPRECATED: Replaced by chart_blocked_tools() which uses telemetry.json.

    The new telemetry system tracks errors/blocks per tool directly.
    Use chart_blocked_tools() for the equivalent functionality.
    """
    print("⚠️  chart_blocks is DEPRECATED")
    print("   Use 'blocked-tools' instead, which uses telemetry.json")
    return None

def chart_token_impact():
    """DEPRECATED: Replaced by telemetry-based charts.

    The new telemetry system provides better token analysis through:
    - token-efficiency: Tokens per call by tool
    - native-vs-mcp: Backend comparison
    - latency: Tool performance

    Use these alternatives for token impact insights.
    """
    print("⚠️  chart_token_impact is DEPRECATED")
    print("   The new telemetry system provides better alternatives:")
    print("     - token-efficiency: Tokens per call by tool")
    print("     - native-vs-mcp: Compare native vs MCP tools")
    print("     - latency: Tool call durations")
    return None

def chart_subagents(session_filter=None):
    """Chart subagent token usage by type (uses telemetry.json)."""
    from datetime import datetime, timedelta, timezone

    # EST timezone offset (UTC-5)
    EST = timezone(timedelta(hours=-5))

    if not TELEMETRY_FILE.exists():
        print("⚠️  No telemetry data found")
        return None

    telemetry = json.loads(TELEMETRY_FILE.read_text())
    subagents = telemetry.get("aggregates", {}).get("subagents", {})

    if not subagents:
        print("⚠️  No subagent data found in telemetry")
        return None

    # Extract type name (remove prefix if present) and collect data
    results = {}
    for agent_type, data in subagents.items():
        type_name = agent_type.split(':')[-1] if ':' in agent_type else agent_type
        tokens = data.get("tokens", 0)
        count = data.get("count", 0)

        # Accumulate if type already exists (for renamed types)
        if type_name in results:
            results[type_name]["tokens"] += tokens
            results[type_name]["count"] += count
        else:
            results[type_name] = {"tokens": tokens, "count": count}

    if not results:
        print("⚠️  No subagent data to chart")
        return None

    # Sort by tokens and prepare for chart
    sorted_results = sorted(results.items(), key=lambda x: -x[1]["tokens"])
    labels = [name for name, _ in sorted_results]
    values = [data["tokens"] for _, data in sorted_results]

    data = {
        "label": "Estimated Tokens",
        "values": values
    }

    title = "Subagent Token Usage by Type"
    path = generate_html_chart(
        title,
        "bar",
        data,
        labels,
        "subagents.html"
    )

    print(f"✅ Chart generated: {path}")
    return path

def chart_token_trend():
    """Chart token usage trend over time with daily/hourly view toggle (uses telemetry.json).

    Uses daily_summaries for historical daily data (persists forever).
    Uses events[] for hourly granularity (recent data only).
    """
    from datetime import datetime, timedelta, timezone
    from collections import defaultdict

    # EST timezone offset (UTC-5)
    EST = timezone(timedelta(hours=-5))

    if not TELEMETRY_FILE.exists():
        print("⚠️  No telemetry data found")
        return None

    telemetry = json.loads(TELEMETRY_FILE.read_text())
    # Prefer actual data if available
    daily_summaries = telemetry.get("daily_summaries_actual", telemetry.get("daily_summaries", {}))
    events = telemetry.get("events", [])

    if not daily_summaries and len(events) < 2:
        print("⚠️  Need data for trend")
        return None

    # Use daily_summaries for daily view (historical data that persists)
    # Format: {"2025-01-15": {"calls": 50, "tokens": 125000, ...}, ...}
    daily_data = {}
    daily_efficiency = {}  # tokens per call
    daily_calls = {}
    for date_str, summary in daily_summaries.items():
        tokens = summary.get("tokens", summary.get("total_tokens", 0))
        calls = summary.get("calls", 1)
        daily_data[date_str] = tokens
        daily_calls[date_str] = calls
        daily_efficiency[date_str] = round(tokens / max(calls, 1))

    # Parse event timestamp and convert to EST (for hourly view)
    def parse_event_time(event):
        try:
            ts = event.get("ts", "")
            if ts:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return dt.astimezone(EST)
        except:
            pass
        return None

    # Aggregate tokens by hour from events (for recent granular view)
    hourly_data = defaultdict(int)
    for event in events:
        dt = parse_event_time(event)
        if dt:
            hour_str = dt.strftime("%Y-%m-%d %H:00")
            hourly_data[hour_str] += event.get("tokens_est", 0)

    # Fallback: if no daily_summaries yet, aggregate from events
    if not daily_data and events:
        for event in events:
            dt = parse_event_time(event)
            if dt:
                date_str = dt.strftime("%Y-%m-%d")
                if date_str not in daily_data:
                    daily_data[date_str] = 0
                daily_data[date_str] += event.get("tokens_est", 0)

    # Current time in EST for display
    now = datetime.now(EST)

    # Sort data by time - All Time
    sorted_daily = sorted(daily_data.items())
    all_labels = [date for date, _ in sorted_daily]
    all_tokens = [tokens for _, tokens in sorted_daily]
    all_efficiency = [daily_efficiency.get(date, 0) for date, _ in sorted_daily]

    # Last 7 days
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    week_data = [(d, t) for d, t in sorted_daily if d >= week_ago]
    week_labels = [date for date, _ in week_data]
    week_tokens = [tokens for _, tokens in week_data]
    week_efficiency = [daily_efficiency.get(date, 0) for date, _ in week_data]

    # Last 30 days
    month_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    month_data = [(d, t) for d, t in sorted_daily if d >= month_ago]
    month_labels = [date for date, _ in month_data]
    month_tokens = [tokens for _, tokens in month_data]
    month_efficiency = [daily_efficiency.get(date, 0) for date, _ in month_data]

    # Hourly (Last 48h) - no efficiency for hourly view
    sorted_hourly = sorted(hourly_data.items())[-48:]
    hourly_labels = [hour for hour, _ in sorted_hourly]
    hourly_tokens = [tokens for _, tokens in sorted_hourly]

    # By Session - aggregate across all days
    session_totals = {}
    for date_str, summary in daily_summaries.items():
        by_session = summary.get("by_session", {})
        for sid, sdata in by_session.items():
            if sid not in session_totals:
                session_totals[sid] = {"tokens": 0, "calls": 0}
            session_totals[sid]["tokens"] += sdata.get("tokens", 0)
            session_totals[sid]["calls"] += sdata.get("calls", 0)

    # Sort sessions by tokens (top 30)
    sorted_sessions = sorted(session_totals.items(), key=lambda x: x[1]["tokens"], reverse=True)[:30]
    session_labels = [sid[:8] + "..." for sid, _ in sorted_sessions]
    session_tokens = [data["tokens"] for _, data in sorted_sessions]
    session_efficiency = [round(data["tokens"] / max(data["calls"], 1)) for _, data in sorted_sessions]

    # Generate HTML with dropdown selector
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Token Usage Trend</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            padding: 40px;
            background: #1a1a2e;
            color: #eee;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: #16213e;
            padding: 30px;
            border-radius: 8px;
            border: 1px solid #333;
        }}
        h1 {{
            color: #4cc9f0;
            margin-bottom: 10px;
        }}
        .controls {{
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .controls label {{
            font-weight: 600;
            color: #888;
        }}
        .controls select {{
            padding: 8px 12px;
            border: 1px solid #333;
            border-radius: 4px;
            font-size: 14px;
            background: #0f0f1e;
            color: #eee;
            cursor: pointer;
        }}
        .timestamp {{
            color: #888;
            font-size: 14px;
            margin-bottom: 20px;
        }}
        canvas {{
            max-height: 500px;
        }}
        .back-link {{
            display: inline-block;
            margin-top: 20px;
            color: #4cc9f0;
            text-decoration: none;
        }}
        .back-link:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>💰 Token Usage Trend</h1>
        <div class="timestamp">Generated: {now.strftime("%Y-%m-%d %H:%M:%S")} EST</div>

        <div class="controls">
            <label for="viewSelect">View:</label>
            <select id="viewSelect" onchange="switchView()">
                <option value="week">Last 7 Days</option>
                <option value="month">Last 30 Days</option>
                <option value="all">All Time</option>
                <option value="hourly">Hourly (Last 48h)</option>
                <option value="session">By Session (Top 30)</option>
            </select>
        </div>

        <canvas id="chart"></canvas>
        <a href="dashboard.html" class="back-link">← Back to Dashboard</a>
    </div>

    <script>
        const weekData = {{
            labels: {json.dumps(week_labels)},
            datasets: [{{
                label: 'Total Tokens',
                data: {json.dumps(week_tokens)},
                borderColor: '#4cc9f0',
                backgroundColor: 'rgba(76, 201, 240, 0.2)',
                tension: 0.1,
                fill: true,
                yAxisID: 'y'
            }}, {{
                label: 'Tokens/Call (Efficiency)',
                data: {json.dumps(week_efficiency)},
                borderColor: '#f59e0b',
                backgroundColor: 'transparent',
                tension: 0.1,
                fill: false,
                borderDash: [5, 5],
                yAxisID: 'y1'
            }}]
        }};

        const monthData = {{
            labels: {json.dumps(month_labels)},
            datasets: [{{
                label: 'Total Tokens',
                data: {json.dumps(month_tokens)},
                borderColor: '#8b5cf6',
                backgroundColor: 'rgba(139, 92, 246, 0.2)',
                tension: 0.1,
                fill: true,
                yAxisID: 'y'
            }}, {{
                label: 'Tokens/Call (Efficiency)',
                data: {json.dumps(month_efficiency)},
                borderColor: '#f59e0b',
                backgroundColor: 'transparent',
                tension: 0.1,
                fill: false,
                borderDash: [5, 5],
                yAxisID: 'y1'
            }}]
        }};

        const allData = {{
            labels: {json.dumps(all_labels)},
            datasets: [{{
                label: 'Total Tokens',
                data: {json.dumps(all_tokens)},
                borderColor: '#4cc9f0',
                backgroundColor: 'rgba(76, 201, 240, 0.2)',
                tension: 0.1,
                fill: true,
                yAxisID: 'y'
            }}, {{
                label: 'Tokens/Call (Efficiency)',
                data: {json.dumps(all_efficiency)},
                borderColor: '#f59e0b',
                backgroundColor: 'transparent',
                tension: 0.1,
                fill: false,
                borderDash: [5, 5],
                yAxisID: 'y1'
            }}]
        }};

        const hourlyData = {{
            labels: {json.dumps(hourly_labels)},
            datasets: [{{
                label: 'Tokens per Hour',
                data: {json.dumps(hourly_tokens)},
                borderColor: '#10b981',
                backgroundColor: 'rgba(16, 185, 129, 0.2)',
                tension: 0.1,
                fill: true,
                yAxisID: 'y'
            }}]
        }};

        const sessionData = {{
            labels: {json.dumps(session_labels)},
            datasets: [{{
                label: 'Total Tokens',
                data: {json.dumps(session_tokens)},
                backgroundColor: 'rgba(76, 201, 240, 0.8)',
                yAxisID: 'y'
            }}, {{
                label: 'Tokens/Call',
                data: {json.dumps(session_efficiency)},
                backgroundColor: 'rgba(245, 158, 11, 0.8)',
                yAxisID: 'y1'
            }}]
        }};

        const ctx = document.getElementById('chart').getContext('2d');
        let chart = new Chart(ctx, {{
            type: 'line',
            data: weekData,
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                plugins: {{
                    legend: {{
                        position: 'top',
                        labels: {{ color: '#888' }}
                    }},
                    title: {{
                        display: false
                    }}
                }},
                scales: {{
                    y: {{
                        type: 'linear',
                        display: true,
                        position: 'left',
                        beginAtZero: true,
                        ticks: {{ color: '#4cc9f0' }},
                        grid: {{ color: '#333' }},
                        title: {{ display: true, text: 'Total Tokens', color: '#4cc9f0' }}
                    }},
                    y1: {{
                        type: 'linear',
                        display: true,
                        position: 'right',
                        beginAtZero: true,
                        ticks: {{ color: '#f59e0b' }},
                        grid: {{ drawOnChartArea: false }},
                        title: {{ display: true, text: 'Tokens/Call', color: '#f59e0b' }}
                    }},
                    x: {{
                        ticks: {{ color: '#888' }},
                        grid: {{ color: '#333' }}
                    }}
                }}
            }}
        }});

        function switchView() {{
            const view = document.getElementById('viewSelect').value;
            const dataMap = {{
                'week': weekData,
                'month': monthData,
                'all': allData,
                'hourly': hourlyData,
                'session': sessionData
            }};
            chart.data = dataMap[view] || weekData;
            // Use bar chart for session view, line for others
            chart.config.type = (view === 'session') ? 'bar' : 'line';
            chart.update();
        }}
    </script>
</body>
</html>"""

    output_path = CHARTS_DIR / "token_trend.html"
    output_path.write_text(html, encoding='utf-8')
    
    print(f"✅ Chart generated: {output_path}")
    return output_path

def chart_realtime_telemetry():
    """Chart real-time telemetry from hook-based tracking."""
    if not TELEMETRY_FILE.exists():
        print("⚠️  No telemetry data found")
        print("   Telemetry hooks track all tool calls automatically")
        return None

    telemetry = json.loads(TELEMETRY_FILE.read_text())
    events = telemetry.get("events", [])
    aggregates = telemetry.get("aggregates", {})

    if not events:
        print("⚠️  No telemetry events found")
        return None

    # Create a comprehensive telemetry HTML page
    totals = aggregates.get("totals", {})
    by_tool = aggregates.get("by_tool", {})
    by_backend = aggregates.get("by_backend", {})
    subagents = aggregates.get("subagents", {})

    # Sort tools by token usage
    sorted_tools = sorted(by_tool.items(), key=lambda x: x[1].get("tokens", 0), reverse=True)[:15]
    tool_labels = [t[0][:30] for t in sorted_tools]  # Truncate long names
    tool_tokens = [t[1].get("tokens", 0) for t in sorted_tools]

    # Backend breakdown
    backend_labels = list(by_backend.keys())
    backend_tokens = [by_backend[b].get("tokens", 0) for b in backend_labels]

    # Subagent breakdown
    subagent_labels = list(subagents.keys())
    subagent_tokens = [subagents[s].get("tokens", 0) for s in subagent_labels]

    # Recent events timeline (last 50)
    recent = events[-50:]
    timeline_data = []
    for e in recent:
        timeline_data.append({
            "ts": e.get("ts", "")[:19],
            "tool": e.get("tool", "")[:25],
            "tokens": e.get("tokens_est", 0),
            "duration": e.get("duration_ms", 0),
            "status": e.get("status", "")
        })

    # Calculate trend
    trend_verdict = "N/A"
    trend_pct = 0
    if len(events) >= 10:
        mid = len(events) // 2
        first_tokens = sum(e.get("tokens_est", 0) for e in events[:mid])
        second_tokens = sum(e.get("tokens_est", 0) for e in events[mid:])
        if first_tokens > 0:
            trend_pct = ((second_tokens - first_tokens) / first_tokens) * 100
            if trend_pct < -10:
                trend_verdict = "IMPROVING ↓"
            elif trend_pct > 10:
                trend_verdict = "INCREASING ↑"
            else:
                trend_verdict = "STABLE →"

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Real-Time Telemetry</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            padding: 20px;
            background: #1a1a2e;
            color: #eee;
            margin: 0;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }}
        h1 {{ color: #4cc9f0; margin: 0; }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .stat-card {{
            background: #16213e;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }}
        .stat-value {{
            font-size: 32px;
            font-weight: bold;
            color: #4cc9f0;
        }}
        .stat-value.success {{ color: #4ade80; }}
        .stat-value.warning {{ color: #fbbf24; }}
        .stat-value.error {{ color: #f87171; }}
        .stat-label {{
            font-size: 12px;
            color: #888;
            text-transform: uppercase;
        }}
        .charts {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
        }}
        .chart-card {{
            background: #16213e;
            padding: 20px;
            border-radius: 8px;
        }}
        .chart-card h2 {{
            margin-top: 0;
            font-size: 16px;
            color: #888;
        }}
        .events-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
            margin-top: 20px;
        }}
        .events-table th, .events-table td {{
            padding: 8px;
            text-align: left;
            border-bottom: 1px solid #333;
        }}
        .events-table th {{
            color: #888;
            text-transform: uppercase;
        }}
        .status-success {{ color: #4ade80; }}
        .status-error {{ color: #f87171; }}
        .back-link {{
            color: #4cc9f0;
            text-decoration: none;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📡 Real-Time Telemetry</h1>
        <a href="dashboard.html" class="back-link">← Back to Dashboard</a>
    </div>

    <div class="stats">
        <div class="stat-card">
            <div class="stat-value">{totals.get('calls', 0):,}</div>
            <div class="stat-label">Total Calls</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{totals.get('tokens_est', 0):,}</div>
            <div class="stat-label">Est. Tokens</div>
        </div>
        <div class="stat-card">
            <div class="stat-value {'error' if totals.get('errors', 0) > 0 else 'success'}">{totals.get('errors', 0)}</div>
            <div class="stat-label">Errors</div>
        </div>
        <div class="stat-card">
            <div class="stat-value {'success' if 'IMPROVING' in trend_verdict else 'warning' if 'INCREASING' in trend_verdict else ''}">{trend_verdict}</div>
            <div class="stat-label">Token Trend ({trend_pct:+.1f}%)</div>
        </div>
    </div>

    <div class="charts">
        <div class="chart-card">
            <h2>Token Usage by Tool (Top 15)</h2>
            <canvas id="toolChart"></canvas>
        </div>
        <div class="chart-card">
            <h2>Token Usage by Backend</h2>
            <canvas id="backendChart"></canvas>
        </div>
        <div class="chart-card">
            <h2>Subagent Token Usage</h2>
            <canvas id="subagentChart"></canvas>
        </div>
    </div>

    <div class="chart-card" style="margin-top: 20px;">
        <h2>Recent Events (Last 50)</h2>
        <table class="events-table">
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Tool</th>
                    <th>Tokens</th>
                    <th>Duration</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {''.join(f'''<tr>
                    <td>{e['ts']}</td>
                    <td>{e['tool']}</td>
                    <td>{e['tokens']:,}</td>
                    <td>{e['duration']}ms</td>
                    <td class="status-{e['status']}">{e['status']}</td>
                </tr>''' for e in reversed(timeline_data))}
            </tbody>
        </table>
    </div>

    <script>
        const toolCtx = document.getElementById('toolChart').getContext('2d');
        new Chart(toolCtx, {{
            type: 'bar',
            data: {{
                labels: {json.dumps(tool_labels)},
                datasets: [{{
                    label: 'Tokens',
                    data: {json.dumps(tool_tokens)},
                    backgroundColor: 'rgba(76, 201, 240, 0.6)',
                    borderColor: 'rgba(76, 201, 240, 1)',
                    borderWidth: 1
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }},
                    y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }}
                }}
            }}
        }});

        const backendCtx = document.getElementById('backendChart').getContext('2d');
        new Chart(backendCtx, {{
            type: 'pie',
            data: {{
                labels: {json.dumps(backend_labels)},
                datasets: [{{
                    data: {json.dumps(backend_tokens)},
                    backgroundColor: [
                        'rgba(76, 201, 240, 0.8)',
                        'rgba(74, 222, 128, 0.8)',
                        'rgba(251, 191, 36, 0.8)',
                        'rgba(248, 113, 113, 0.8)',
                        'rgba(167, 139, 250, 0.8)'
                    ]
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{ position: 'right', labels: {{ color: '#888' }} }}
                }}
            }}
        }});

        const subagentCtx = document.getElementById('subagentChart').getContext('2d');
        new Chart(subagentCtx, {{
            type: 'bar',
            data: {{
                labels: {json.dumps(subagent_labels) if subagent_labels else ['No subagents']},
                datasets: [{{
                    label: 'Tokens',
                    data: {json.dumps(subagent_tokens) if subagent_tokens else [0]},
                    backgroundColor: 'rgba(167, 139, 250, 0.6)',
                    borderColor: 'rgba(167, 139, 250, 1)',
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }},
                    y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }}
                }}
            }}
        }});
    </script>
</body>
</html>"""

    path = CHARTS_DIR / "telemetry.html"
    path.write_text(html, encoding='utf-8')
    print(f"✅ Telemetry chart generated: {path}")
    return path


def chart_latency_by_tool():
    """Chart average latency (duration) by tool - find slow tools with time filtering."""
    from datetime import datetime, timedelta, timezone
    
    if not TELEMETRY_FILE.exists():
        print("⚠️  No telemetry data found")
        return None

    telemetry = json.loads(TELEMETRY_FILE.read_text())
    events = telemetry.get("events", [])
    by_tool_all = telemetry.get("aggregates", {}).get("by_tool", {})

    if not by_tool_all and not events:
        print("⚠️  No tool data found")
        return None

    # Helper to calculate latency from events for a time range
    def calc_latency_from_events(events_list, cutoff_hours=None):
        """Calculate average latency per tool from events."""
        now = datetime.now(timezone.utc)
        tool_stats = defaultdict(lambda: {"duration": 0, "count": 0})
        
        for e in events_list:
            ts_str = e.get("ts", "")
            if cutoff_hours and ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if (now - ts).total_seconds() > cutoff_hours * 3600:
                        continue
                except:
                    pass
            
            tool = e.get("tool", "unknown")
            duration = e.get("duration_ms", 0)
            if duration > 0:
                tool_stats[tool]["duration"] += duration
                tool_stats[tool]["count"] += 1
        
        result = []
        for tool, data in tool_stats.items():
            if data["count"] > 0:
                avg = data["duration"] / data["count"]
                result.append((tool[:25], round(avg, 1), data["count"]))
        result.sort(key=lambda x: x[1], reverse=True)
        return result[:20]

    # Calculate for different time ranges
    data_7d = calc_latency_from_events(events, 24 * 7)
    data_30d = calc_latency_from_events(events, 24 * 30)
    data_all_events = calc_latency_from_events(events, None)
    
    # All-time from aggregates (more complete)
    latency_all = []
    for tool, data in by_tool_all.items():
        count = data.get("count", 0)
        duration = data.get("duration_ms", 0)
        if count > 0:
            latency_all.append((tool[:25], round(duration / count, 1), count))
    latency_all.sort(key=lambda x: x[1], reverse=True)
    data_all = latency_all[:20] if latency_all else data_all_events

    # By session - aggregate latency per session
    session_latency = defaultdict(lambda: {"duration": 0, "count": 0})
    for e in events:
        sid = e.get("session_id", "unknown")[:8]
        duration = e.get("duration_ms", 0)
        if duration > 0:
            session_latency[sid]["duration"] += duration
            session_latency[sid]["count"] += 1
    
    session_data = []
    for sid, data in session_latency.items():
        if data["count"] > 0:
            avg = data["duration"] / data["count"]
            session_data.append((sid + "...", round(avg, 1), data["count"]))
    session_data.sort(key=lambda x: x[1], reverse=True)
    data_session = session_data[:20]

    # Convert to JSON-safe format
    def to_chart_data(data):
        if not data:
            return {"labels": ["No data"], "values": [0], "counts": [0]}
        return {
            "labels": [d[0] for d in data],
            "values": [d[1] for d in data],
            "counts": [d[2] for d in data]
        }

    week_data = to_chart_data(data_7d)
    month_data = to_chart_data(data_30d)
    all_data = to_chart_data(data_all)
    session_chart_data = to_chart_data(data_session)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Latency by Tool</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: -apple-system, sans-serif; padding: 20px; background: #1a1a2e; color: #eee; }}
        h1 {{ color: #4cc9f0; }}
        .back {{ color: #4cc9f0; text-decoration: none; }}
        .chart-container {{ max-width: 900px; margin: 20px auto; }}
        .note {{ color: #888; font-size: 14px; margin-top: 10px; }}
        {get_chart_dropdown_css()}
    </style>
</head>
<body>
    <a href="dashboard.html" class="back">← Back to Dashboard</a>
    <h1>⏱️ Latency by Tool (Slowest First)</h1>
    
    <div class="controls">
        <label for="viewSelect">View:</label>
        <select id="viewSelect" onchange="switchView()">
            <option value="week">Last 7 Days</option>
            <option value="month">Last 30 Days</option>
            <option value="all" selected>All Time</option>
            <option value="session">By Session</option>
        </select>
    </div>
    
    <p class="note">Average duration in milliseconds. Hover for call counts.</p>
    <div class="chart-container">
        <canvas id="chart"></canvas>
    </div>
    <script>
        const weekData = {json.dumps(week_data)};
        const monthData = {json.dumps(month_data)};
        const allData = {json.dumps(all_data)};
        const sessionData = {json.dumps(session_chart_data)};
        
        let chart = null;
        
        function createChart(data, title) {{
            const ctx = document.getElementById('chart').getContext('2d');
            if (chart) chart.destroy();
            
            chart = new Chart(ctx, {{
                type: 'bar',
                data: {{
                    labels: data.labels,
                    datasets: [{{
                        label: title,
                        data: data.values,
                        backgroundColor: 'rgba(248, 113, 113, 0.6)',
                        borderColor: 'rgba(248, 113, 113, 1)',
                        borderWidth: 1
                    }}]
                }},
                options: {{
                    indexAxis: 'y',
                    responsive: true,
                    plugins: {{
                        tooltip: {{
                            callbacks: {{
                                afterLabel: function(ctx) {{
                                    return 'Calls: ' + data.counts[ctx.dataIndex];
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }}, title: {{ display: true, text: 'Milliseconds', color: '#888' }} }},
                        y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }}
                    }}
                }}
            }});
        }}
        
        function switchView() {{
            const view = document.getElementById('viewSelect').value;
            switch(view) {{
                case 'week': createChart(weekData, 'Avg Latency (7d)'); break;
                case 'month': createChart(monthData, 'Avg Latency (30d)'); break;
                case 'all': createChart(allData, 'Avg Latency (All Time)'); break;
                case 'session': createChart(sessionData, 'Avg Latency (By Session)'); break;
            }}
        }}
        
        // Initial render
        switchView();
    </script>
</body>
</html>"""

    path = CHARTS_DIR / "latency.html"
    path.write_text(html, encoding='utf-8')
    print(f"✅ Latency chart generated: {path}")
    return path


def chart_error_timeline():
    """Chart errors over time to spot error spikes."""
    if not TELEMETRY_FILE.exists():
        print("⚠️  No telemetry data found")
        return None

    telemetry = json.loads(TELEMETRY_FILE.read_text())
    events = telemetry.get("events", [])
    daily_summaries = telemetry.get("daily_summaries", {})

    if not events and not daily_summaries:
        print("⚠️  No events found")
        return None

    # Group events by hour for current session
    hourly_data = defaultdict(lambda: {"total": 0, "errors": 0})
    session_data = defaultdict(lambda: {"total": 0, "errors": 0})

    for e in events:
        ts = e.get("ts", "")[:13]  # YYYY-MM-DDTHH
        session_id = e.get("session_id", "unknown")
        if ts:
            hourly_data[ts]["total"] += 1
            session_data[session_id]["total"] += 1
            if e.get("status") == "error":
                hourly_data[ts]["errors"] += 1
                session_data[session_id]["errors"] += 1

    # Add historical data from daily_summaries
    for date_str, summary in daily_summaries.items():
        # Create a midday entry for each day
        ts_key = f"{date_str}T12"
        if ts_key not in hourly_data:
            hourly_data[ts_key]["total"] = summary.get("total_calls", 0)
            hourly_data[ts_key]["errors"] = summary.get("errors", 0)

    # Sort all data by time
    all_sorted = sorted(hourly_data.items())

    # Prepare data for different time ranges
    def get_range_data(hours):
        if hours == 0:  # All time
            return all_sorted
        return all_sorted[-hours:] if len(all_sorted) >= hours else all_sorted

    # Prepare session data
    session_labels = list(session_data.keys())
    session_totals = [session_data[s]["total"] for s in session_labels]
    session_errors = [session_data[s]["errors"] for s in session_labels]
    # Truncate long session IDs for display
    session_display = [s[:8] + "..." if len(s) > 11 else s for s in session_labels]

    # Default view: last 48 hours
    sorted_hours = get_range_data(48)
    labels = [h[0][5:] for h in sorted_hours]  # MM-DDTHH
    totals = [h[1]["total"] for h in sorted_hours]
    errors = [h[1]["errors"] for h in sorted_hours]

    # Prepare all data ranges for JS
    data_7d = get_range_data(168)  # 7 days * 24 hours
    data_30d = get_range_data(720)  # 30 days * 24 hours
    data_all = all_sorted

    dropdown_css = get_chart_dropdown_css()

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Error Timeline</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: -apple-system, sans-serif; padding: 20px; background: #1a1a2e; color: #eee; }}
        h1 {{ color: #4cc9f0; }}
        .back {{ color: #4cc9f0; text-decoration: none; }}
        .chart-container {{ max-width: 1200px; margin: 20px auto; }}
        {dropdown_css}
    </style>
</head>
<body>
    <a href="dashboard.html" class="back">← Back to Dashboard</a>
    <h1>🚨 Error Timeline</h1>
    <div class="controls">
        <label for="timeRange">Time Range:</label>
        <select id="timeRange" onchange="switchView(this.value)">
            <option value="48h">Last 48 Hours</option>
            <option value="7d">Last 7 Days</option>
            <option value="30d">Last 30 Days</option>
            <option value="all">All Time</option>
            <option value="session">By Session</option>
        </select>
    </div>
    <div class="chart-container">
        <canvas id="chart"></canvas>
    </div>
    <script>
        const chartData = {{
            '48h': {{
                labels: {json.dumps(labels)},
                totals: {json.dumps(totals)},
                errors: {json.dumps(errors)}
            }},
            '7d': {{
                labels: {json.dumps([h[0][5:] for h in data_7d])},
                totals: {json.dumps([h[1]["total"] for h in data_7d])},
                errors: {json.dumps([h[1]["errors"] for h in data_7d])}
            }},
            '30d': {{
                labels: {json.dumps([h[0][5:] for h in data_30d])},
                totals: {json.dumps([h[1]["total"] for h in data_30d])},
                errors: {json.dumps([h[1]["errors"] for h in data_30d])}
            }},
            'all': {{
                labels: {json.dumps([h[0][5:] for h in data_all])},
                totals: {json.dumps([h[1]["total"] for h in data_all])},
                errors: {json.dumps([h[1]["errors"] for h in data_all])}
            }},
            'session': {{
                labels: {json.dumps(session_display)},
                totals: {json.dumps(session_totals)},
                errors: {json.dumps(session_errors)}
            }}
        }};

        let chart = new Chart(document.getElementById('chart'), {{
            type: 'line',
            data: {{
                labels: chartData['48h'].labels,
                datasets: [
                    {{
                        label: 'Total Calls',
                        data: chartData['48h'].totals,
                        borderColor: 'rgba(76, 201, 240, 1)',
                        backgroundColor: 'rgba(76, 201, 240, 0.1)',
                        fill: true,
                        tension: 0.3
                    }},
                    {{
                        label: 'Errors',
                        data: chartData['48h'].errors,
                        borderColor: 'rgba(248, 113, 113, 1)',
                        backgroundColor: 'rgba(248, 113, 113, 0.3)',
                        fill: true,
                        tension: 0.3
                    }}
                ]
            }},
            options: {{
                responsive: true,
                plugins: {{ legend: {{ labels: {{ color: '#888' }} }} }},
                scales: {{
                    x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }},
                    y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }}
                }}
            }}
        }});

        function switchView(range) {{
            const data = chartData[range];
            const isSession = range === 'session';
            
            chart.config.type = isSession ? 'bar' : 'line';
            chart.data.labels = data.labels;
            chart.data.datasets[0].data = data.totals;
            chart.data.datasets[1].data = data.errors;
            chart.data.datasets[0].fill = !isSession;
            chart.data.datasets[1].fill = !isSession;
            chart.data.datasets[0].tension = isSession ? 0 : 0.3;
            chart.data.datasets[1].tension = isSession ? 0 : 0.3;
            chart.update();
        }}
    </script>
</body>
</html>"""

    path = CHARTS_DIR / "error_timeline.html"
    path.write_text(html, encoding='utf-8')
    print(f"✅ Error timeline generated: {path}")
    return path


def chart_activity_heatmap():
    """Chart activity by hour of day - see work patterns."""
    if not TELEMETRY_FILE.exists():
        print("⚠️  No telemetry data found")
        return None

    telemetry = json.loads(TELEMETRY_FILE.read_text())
    events = telemetry.get("events", [])
    daily_summaries = telemetry.get("daily_summaries", {})

    if not events and not daily_summaries:
        print("⚠️  No events found")
        return None

    # Parse events with timestamps for filtering
    parsed_events = []
    for e in events:
        ts = e.get("ts", "")
        if len(ts) >= 13:
            try:
                hour = int(ts[11:13])
                date_str = ts[:10]
                parsed_events.append({"hour": hour, "date": date_str})
            except (ValueError, IndexError):
                pass

    def count_by_hour(events_list):
        """Count events by hour of day (0-23)."""
        hourly_counts = [0] * 24
        for e in events_list:
            hourly_counts[e["hour"]] += 1
        return hourly_counts

    def filter_by_days(events_list, days):
        """Filter events to last N days."""
        if days == 0:  # All time
            return events_list
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return [e for e in events_list if e["date"] >= cutoff]

    # Calculate for different time ranges
    data_7d = count_by_hour(filter_by_days(parsed_events, 7))
    data_30d = count_by_hour(filter_by_days(parsed_events, 30))
    data_all = count_by_hour(parsed_events)

    labels = [f"{h:02d}:00" for h in range(24)]

    def generate_colors(hourly_counts):
        """Generate colors based on intensity."""
        max_count = max(hourly_counts) if hourly_counts else 1
        colors = []
        for count in hourly_counts:
            intensity = count / max_count if max_count > 0 else 0
            r = int(76 + (248 - 76) * intensity)
            g = int(201 - (201 - 113) * intensity)
            b = int(240 - (240 - 113) * intensity)
            colors.append(f"rgba({r}, {g}, {b}, 0.8)")
        return colors

    dropdown_css = get_chart_dropdown_css()

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Activity Heatmap</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: -apple-system, sans-serif; padding: 20px; background: #1a1a2e; color: #eee; }}
        h1 {{ color: #4cc9f0; }}
        .back {{ color: #4cc9f0; text-decoration: none; }}
        .chart-container {{ max-width: 1000px; margin: 20px auto; }}
        .note {{ color: #888; font-size: 14px; }}
        {dropdown_css}
    </style>
</head>
<body>
    <a href="dashboard.html" class="back">← Back to Dashboard</a>
    <h1>🕐 Activity by Hour of Day</h1>
    <p class="note">Tool calls distribution across hours (brighter = more activity)</p>
    <div class="controls">
        <label for="timeRange">Time Range:</label>
        <select id="timeRange" onchange="switchView(this.value)">
            <option value="7d">Last 7 Days</option>
            <option value="30d" selected>Last 30 Days</option>
            <option value="all">All Time</option>
        </select>
    </div>
    <div class="chart-container">
        <canvas id="chart"></canvas>
    </div>
    <script>
        const chartData = {{
            '7d': {json.dumps(data_7d)},
            '30d': {json.dumps(data_30d)},
            'all': {json.dumps(data_all)}
        }};

        function generateColors(data) {{
            const maxCount = Math.max(...data) || 1;
            return data.map(count => {{
                const intensity = count / maxCount;
                const r = Math.round(76 + (248 - 76) * intensity);
                const g = Math.round(201 - (201 - 113) * intensity);
                const b = Math.round(240 - (240 - 113) * intensity);
                return `rgba(${{r}}, ${{g}}, ${{b}}, 0.8)`;
            }});
        }}

        let chart = new Chart(document.getElementById('chart'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(labels)},
                datasets: [{{
                    label: 'Tool Calls',
                    data: chartData['30d'],
                    backgroundColor: generateColors(chartData['30d']),
                    borderColor: 'rgba(255,255,255,0.2)',
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }},
                    y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }}, title: {{ display: true, text: 'Calls', color: '#888' }} }}
                }}
            }}
        }});

        function switchView(range) {{
            const data = chartData[range];
            chart.data.datasets[0].data = data;
            chart.data.datasets[0].backgroundColor = generateColors(data);
            chart.update();
        }}
    </script>
</body>
</html>"""

    path = CHARTS_DIR / "activity_heatmap.html"
    path.write_text(html, encoding='utf-8')
    print(f"✅ Activity heatmap generated: {path}")
    return path


def chart_native_vs_mcp():
    """Compare native Claude tools vs MCP tools with time filtering."""
    from datetime import datetime, timedelta, timezone

    if not TELEMETRY_FILE.exists():
        print("⚠️  No telemetry data found")
        return None

    telemetry = json.loads(TELEMETRY_FILE.read_text())
    events = telemetry.get("events", [])
    by_backend = telemetry.get("aggregates", {}).get("by_backend", {})

    if not by_backend and not events:
        print("⚠️  No backend data found")
        return None

    def calc_backend_stats(events_list, cutoff_hours=None):
        """Calculate backend stats from events for a time range."""
        now = datetime.now(timezone.utc)
        native = {"calls": 0, "tokens": 0}
        mcp = {"calls": 0, "tokens": 0}

        for e in events_list:
            ts_str = e.get("ts", "")
            if cutoff_hours and ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if (now - ts).total_seconds() > cutoff_hours * 3600:
                        continue
                except:
                    pass

            backend = e.get("backend", "unknown")
            tokens = e.get("tokens_est", 0)

            if backend == "claude-native":
                native["calls"] += 1
                native["tokens"] += tokens
            else:
                mcp["calls"] += 1
                mcp["tokens"] += tokens

        return native, mcp

    # Calculate for different time ranges
    native_7d, mcp_7d = calc_backend_stats(events, 24 * 7)
    native_30d, mcp_30d = calc_backend_stats(events, 24 * 30)
    native_events, mcp_events = calc_backend_stats(events, None)

    # All-time from aggregates (more complete)
    native_all = {"calls": 0, "tokens": 0}
    mcp_all = {"calls": 0, "tokens": 0}
    for backend, data in by_backend.items():
        calls = data.get("count", 0)
        tokens = data.get("tokens", 0)
        if backend == "claude-native":
            native_all["calls"] += calls
            native_all["tokens"] += tokens
        else:
            mcp_all["calls"] += calls
            mcp_all["tokens"] += tokens

    # Use aggregates for all-time if available, else events
    if native_all["calls"] == 0 and mcp_all["calls"] == 0:
        native_all, mcp_all = native_events, mcp_events

    def to_json(native, mcp):
        return {
            "native_calls": native["calls"],
            "native_tokens": native["tokens"],
            "mcp_calls": mcp["calls"],
            "mcp_tokens": mcp["tokens"]
        }

    data_7d = to_json(native_7d, mcp_7d)
    data_30d = to_json(native_30d, mcp_30d)
    data_all = to_json(native_all, mcp_all)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Native vs MCP</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: -apple-system, sans-serif; padding: 20px; background: #1a1a2e; color: #eee; }}
        h1 {{ color: #4cc9f0; }}
        .back {{ color: #4cc9f0; text-decoration: none; }}
        .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; max-width: 1000px; margin: 20px auto; }}
        .chart-box {{ background: #16213e; padding: 20px; border-radius: 8px; }}
        .chart-box h2 {{ color: #888; font-size: 14px; margin-top: 0; }}
        .stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; max-width: 1000px; margin: 20px auto; }}
        .stat {{ background: #16213e; padding: 20px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 36px; font-weight: bold; }}
        .stat-value.native {{ color: #4cc9f0; }}
        .stat-value.mcp {{ color: #a78bfa; }}
        .stat-label {{ color: #888; font-size: 12px; text-transform: uppercase; }}
        {get_chart_dropdown_css()}
    </style>
</head>
<body>
    <a href="dashboard.html" class="back">← Back to Dashboard</a>
    <h1>🔌 Native vs MCP Tools</h1>

    <div class="controls">
        <label for="viewSelect">Time Range:</label>
        <select id="viewSelect" onchange="switchView()">
            <option value="week">Last 7 Days</option>
            <option value="month">Last 30 Days</option>
            <option value="all" selected>All Time</option>
        </select>
    </div>

    <div class="stats">
        <div class="stat">
            <div class="stat-value native" id="nativeCalls">-</div>
            <div class="stat-label">Native Calls</div>
        </div>
        <div class="stat">
            <div class="stat-value mcp" id="mcpCalls">-</div>
            <div class="stat-label">MCP Calls</div>
        </div>
        <div class="stat">
            <div class="stat-value native" id="nativeTokens">-</div>
            <div class="stat-label">Native Tokens</div>
        </div>
        <div class="stat">
            <div class="stat-value mcp" id="mcpTokens">-</div>
            <div class="stat-label">MCP Tokens</div>
        </div>
    </div>

    <div class="charts">
        <div class="chart-box">
            <h2>Calls Distribution</h2>
            <canvas id="callsChart"></canvas>
        </div>
        <div class="chart-box">
            <h2>Token Distribution</h2>
            <canvas id="tokensChart"></canvas>
        </div>
    </div>

    <script>
        const weekData = {json.dumps(data_7d)};
        const monthData = {json.dumps(data_30d)};
        const allData = {json.dumps(data_all)};

        let callsChart = null;
        let tokensChart = null;

        function formatNumber(n) {{
            return n.toLocaleString();
        }}

        function updateView(data) {{
            document.getElementById('nativeCalls').textContent = formatNumber(data.native_calls);
            document.getElementById('mcpCalls').textContent = formatNumber(data.mcp_calls);
            document.getElementById('nativeTokens').textContent = formatNumber(data.native_tokens);
            document.getElementById('mcpTokens').textContent = formatNumber(data.mcp_tokens);

            if (callsChart) callsChart.destroy();
            if (tokensChart) tokensChart.destroy();

            callsChart = new Chart(document.getElementById('callsChart'), {{
                type: 'doughnut',
                data: {{
                    labels: ['Native', 'MCP'],
                    datasets: [{{
                        data: [data.native_calls, data.mcp_calls],
                        backgroundColor: ['rgba(76, 201, 240, 0.8)', 'rgba(167, 139, 250, 0.8)']
                    }}]
                }},
                options: {{ plugins: {{ legend: {{ labels: {{ color: '#888' }} }} }} }}
            }});

            tokensChart = new Chart(document.getElementById('tokensChart'), {{
                type: 'doughnut',
                data: {{
                    labels: ['Native', 'MCP'],
                    datasets: [{{
                        data: [data.native_tokens, data.mcp_tokens],
                        backgroundColor: ['rgba(76, 201, 240, 0.8)', 'rgba(167, 139, 250, 0.8)']
                    }}]
                }},
                options: {{ plugins: {{ legend: {{ labels: {{ color: '#888' }} }} }} }}
            }});
        }}

        function switchView() {{
            const view = document.getElementById('viewSelect').value;
            switch(view) {{
                case 'week': updateView(weekData); break;
                case 'month': updateView(monthData); break;
                case 'all': updateView(allData); break;
            }}
        }}

        switchView();
    </script>
</body>
</html>"""

    path = CHARTS_DIR / "native_vs_mcp.html"
    path.write_text(html, encoding='utf-8')
    print(f"✅ Native vs MCP chart generated: {path}")
    return path


def chart_token_efficiency():
    """Chart token efficiency - tokens per call ratio by tool with time filtering."""
    from datetime import datetime, timezone

    if not TELEMETRY_FILE.exists():
        print("⚠️  No telemetry data found")
        return None

    telemetry = json.loads(TELEMETRY_FILE.read_text())
    events = telemetry.get("events", [])
    by_tool = telemetry.get("aggregates", {}).get("by_tool", {})

    if not by_tool and not events:
        print("⚠️  No tool data found")
        return None

    def calc_efficiency_from_events(events_list, cutoff_hours=None):
        """Calculate tokens per call from events for a time range."""
        now = datetime.now(timezone.utc)
        tool_stats = defaultdict(lambda: {"calls": 0, "tokens": 0})

        for e in events_list:
            ts_str = e.get("ts", "")
            if cutoff_hours and ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if (now - ts).total_seconds() > cutoff_hours * 3600:
                        continue
                except:
                    pass

            tool = e.get("tool", "unknown")
            tokens = e.get("tokens_est", 0)
            tool_stats[tool]["calls"] += 1
            tool_stats[tool]["tokens"] += tokens

        result = []
        for tool, data in tool_stats.items():
            if data["calls"] >= 2:  # Reduced threshold for time-filtered data
                tpc = data["tokens"] / data["calls"]
                result.append({"tool": tool[:25], "tpc": round(tpc, 0), "calls": data["calls"]})
        result.sort(key=lambda x: x["tpc"], reverse=True)
        return result[:20]

    # Calculate for different time ranges
    data_7d = calc_efficiency_from_events(events, 24 * 7)
    data_30d = calc_efficiency_from_events(events, 24 * 30)
    data_events = calc_efficiency_from_events(events, None)

    # All-time from aggregates
    data_all = []
    for tool, data in by_tool.items():
        calls = data.get("count", 0)
        tokens = data.get("tokens", 0)
        if calls >= 3:
            tpc = tokens / calls
            data_all.append({"tool": tool[:25], "tpc": round(tpc, 0), "calls": calls})
    data_all.sort(key=lambda x: x["tpc"], reverse=True)
    data_all = data_all[:20] if data_all else data_events

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Token Efficiency</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: -apple-system, sans-serif; padding: 20px; background: #1a1a2e; color: #eee; }}
        h1 {{ color: #4cc9f0; }}
        .back {{ color: #4cc9f0; text-decoration: none; }}
        .chart-container {{ max-width: 900px; margin: 20px auto; }}
        .note {{ color: #888; font-size: 14px; }}
        .legend {{ margin-top: 20px; display: flex; gap: 20px; justify-content: center; }}
        .legend-item {{ display: flex; align-items: center; gap: 5px; }}
        .legend-color {{ width: 16px; height: 16px; border-radius: 4px; }}
        {get_chart_dropdown_css()}
    </style>
</head>
<body>
    <a href="dashboard.html" class="back">← Back to Dashboard</a>
    <h1>💰 Token Efficiency (Tokens per Call)</h1>

    <div class="controls">
        <label for="viewSelect">Time Range:</label>
        <select id="viewSelect" onchange="switchView()">
            <option value="week">Last 7 Days</option>
            <option value="month">Last 30 Days</option>
            <option value="all" selected>All Time</option>
        </select>
    </div>

    <p class="note">Lower is better. Tools with fewer than 3 calls excluded.</p>
    <div class="legend">
        <div class="legend-item"><div class="legend-color" style="background: rgba(74, 222, 128, 0.8)"></div> Efficient</div>
        <div class="legend-item"><div class="legend-color" style="background: rgba(251, 191, 36, 0.8)"></div> Moderate</div>
        <div class="legend-item"><div class="legend-color" style="background: rgba(248, 113, 113, 0.8)"></div> Expensive</div>
    </div>
    <div class="chart-container">
        <canvas id="chart"></canvas>
    </div>
    <script>
        const weekData = {json.dumps(data_7d)};
        const monthData = {json.dumps(data_30d)};
        const allData = {json.dumps(data_all)};

        let chart = null;

        function getColors(values) {{
            const max = Math.max(...values) || 1;
            return values.map(v => {{
                const ratio = v / max;
                if (ratio < 0.3) return 'rgba(74, 222, 128, 0.8)';
                if (ratio < 0.6) return 'rgba(251, 191, 36, 0.8)';
                return 'rgba(248, 113, 113, 0.8)';
            }});
        }}

        function createChart(data) {{
            if (chart) chart.destroy();
            const labels = data.map(d => d.tool);
            const values = data.map(d => d.tpc);
            const colors = getColors(values);

            chart = new Chart(document.getElementById('chart'), {{
                type: 'bar',
                data: {{
                    labels: labels,
                    datasets: [{{
                        label: 'Tokens per Call',
                        data: values,
                        backgroundColor: colors,
                        borderWidth: 1
                    }}]
                }},
                options: {{
                    indexAxis: 'y',
                    responsive: true,
                    plugins: {{
                        legend: {{ display: false }},
                        tooltip: {{
                            callbacks: {{
                                afterLabel: function(ctx) {{
                                    return 'Calls: ' + data[ctx.dataIndex].calls;
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }}, title: {{ display: true, text: 'Tokens/Call', color: '#888' }} }},
                        y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }}
                    }}
                }}
            }});
        }}

        function switchView() {{
            const view = document.getElementById('viewSelect').value;
            switch(view) {{
                case 'week': createChart(weekData); break;
                case 'month': createChart(monthData); break;
                case 'all': createChart(allData); break;
            }}
        }}

        switchView();
    </script>
</body>
</html>"""

    path = CHARTS_DIR / "token_efficiency.html"
    path.write_text(html, encoding='utf-8')
    print(f"✅ Token efficiency chart generated: {path}")
    return path


def chart_compression_ratio():
    """Chart summarization compression ratio with time filtering."""
    from datetime import datetime, timezone

    if not TELEMETRY_FILE.exists():
        print("⚠️  No telemetry data found")
        return None

    telemetry = json.loads(TELEMETRY_FILE.read_text())
    events = telemetry.get("events", [])
    efficiency = telemetry.get("aggregates", {}).get("efficiency", {})

    # Filter events with efficiency data
    efficiency_events = [e for e in events if e.get("full_size", 0) > 0]

    if not efficiency and not efficiency_events:
        print("⚠️  No efficiency data found (no summarized calls yet)")
        return None

    def calc_compression_from_events(events_list, cutoff_hours=None):
        """Calculate compression stats from events for a time range."""
        now = datetime.now(timezone.utc)
        full_chars = 0
        summary_chars = 0
        calls = 0

        for e in events_list:
            ts_str = e.get("ts", "")
            if cutoff_hours and ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if (now - ts).total_seconds() > cutoff_hours * 3600:
                        continue
                except:
                    pass

            full_chars += e.get("full_size", 0)
            summary_chars += e.get("summary_size", 0)
            calls += 1

        chars_saved = full_chars - summary_chars
        compression_ratio = summary_chars / full_chars if full_chars > 0 else 0
        savings_pct = (1 - compression_ratio) * 100
        tokens_saved_est = chars_saved // 4

        return {
            "savings_pct": round(savings_pct, 1),
            "tokens_saved": tokens_saved_est,
            "calls": calls,
            "ratio": round(compression_ratio, 2),
            "summary_chars": summary_chars,
            "chars_saved": chars_saved
        }

    # Calculate for different time ranges
    data_7d = calc_compression_from_events(efficiency_events, 24 * 7)
    data_30d = calc_compression_from_events(efficiency_events, 24 * 30)
    data_events = calc_compression_from_events(efficiency_events, None)

    # All-time from aggregates (more accurate)
    if efficiency and efficiency.get("calls_summarized", 0) > 0:
        full_chars = efficiency.get("full_chars", 0)
        summary_chars = efficiency.get("summary_chars", 0)
        chars_saved = efficiency.get("chars_saved", 0)
        calls = efficiency.get("calls_summarized", 0)
        compression_ratio = summary_chars / full_chars if full_chars > 0 else 0
        data_all = {
            "savings_pct": round((1 - compression_ratio) * 100, 1),
            "tokens_saved": chars_saved // 4,
            "calls": calls,
            "ratio": round(compression_ratio, 2),
            "summary_chars": summary_chars,
            "chars_saved": chars_saved
        }
    else:
        data_all = data_events

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Compression Efficiency</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: -apple-system, sans-serif; padding: 20px; background: #1a1a2e; color: #eee; }}
        h1 {{ color: #4cc9f0; }}
        .back {{ color: #4cc9f0; text-decoration: none; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 30px 0; }}
        .stat-card {{ background: #16213e; border-radius: 12px; padding: 24px; text-align: center; }}
        .stat-value {{ font-size: 2.5rem; font-weight: bold; color: #4ade80; }}
        .stat-value.highlight {{ color: #f472b6; }}
        .stat-label {{ color: #888; margin-top: 8px; font-size: 14px; }}
        .chart-container {{ max-width: 400px; margin: 30px auto; }}
        .note {{ color: #888; font-size: 14px; margin-top: 20px; }}
        {get_chart_dropdown_css()}
    </style>
</head>
<body>
    <a href="dashboard.html" class="back">← Back to Dashboard</a>
    <h1>📦 Compression Efficiency</h1>

    <div class="controls">
        <label for="viewSelect">Time Range:</label>
        <select id="viewSelect" onchange="switchView()">
            <option value="week">Last 7 Days</option>
            <option value="month">Last 30 Days</option>
            <option value="all" selected>All Time</option>
        </select>
    </div>

    <p class="note">MCP Router summarization savings - lower ratio = more compression</p>

    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value" id="savingsPct">-</div>
            <div class="stat-label">Context Saved</div>
        </div>
        <div class="stat-card">
            <div class="stat-value highlight" id="tokensSaved">-</div>
            <div class="stat-label">Tokens Saved (est)</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="callsCount">-</div>
            <div class="stat-label">Calls Summarized</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="ratioValue">-</div>
            <div class="stat-label">Compression Ratio</div>
        </div>
    </div>

    <div class="chart-container">
        <canvas id="chart"></canvas>
    </div>

    <script>
        const weekData = {json.dumps(data_7d)};
        const monthData = {json.dumps(data_30d)};
        const allData = {json.dumps(data_all)};

        let chart = null;

        function updateView(data) {{
            document.getElementById('savingsPct').textContent = data.savings_pct + '%';
            document.getElementById('tokensSaved').textContent = data.tokens_saved.toLocaleString();
            document.getElementById('callsCount').textContent = data.calls.toLocaleString();
            document.getElementById('ratioValue').textContent = data.ratio.toFixed(2);

            if (chart) chart.destroy();

            chart = new Chart(document.getElementById('chart'), {{
                type: 'doughnut',
                data: {{
                    labels: ['Summary (kept)', 'Compressed (saved)'],
                    datasets: [{{
                        data: [data.summary_chars, data.chars_saved],
                        backgroundColor: ['rgba(248, 113, 113, 0.8)', 'rgba(74, 222, 128, 0.8)'],
                        borderWidth: 2,
                        borderColor: '#1a1a2e'
                    }}]
                }},
                options: {{
                    responsive: true,
                    plugins: {{
                        legend: {{ position: 'bottom', labels: {{ color: '#888' }} }},
                        title: {{ display: true, text: 'Character Distribution', color: '#888' }}
                    }}
                }}
            }});
        }}

        function switchView() {{
            const view = document.getElementById('viewSelect').value;
            switch(view) {{
                case 'week': updateView(weekData); break;
                case 'month': updateView(monthData); break;
                case 'all': updateView(allData); break;
            }}
        }}

        switchView();
    </script>
</body>
</html>"""

    path = CHARTS_DIR / "compression_ratio.html"
    path.write_text(html, encoding='utf-8')
    print(f"✅ Compression ratio chart generated: {path}")
    return path


def chart_tokens_saved():
    """Chart cumulative tokens saved over time via summarization with time filtering."""
    from datetime import datetime, timezone

    if not TELEMETRY_FILE.exists():
        print("⚠️  No telemetry data found")
        return None

    telemetry = json.loads(TELEMETRY_FILE.read_text())
    events = telemetry.get("events", [])

    # Filter events with efficiency data
    efficiency_events = [e for e in events if e.get("full_size", 0) > 0]

    if not efficiency_events:
        print("⚠️  No efficiency events found")
        return None

    def calc_savings(events_list, cutoff_hours=None):
        """Calculate cumulative savings for a time range."""
        now = datetime.now(timezone.utc)
        cumulative = []
        running_total = 0

        for event in events_list:
            ts_str = event.get("ts", "")
            if cutoff_hours and ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if (now - ts).total_seconds() > cutoff_hours * 3600:
                        continue
                except:
                    pass

            saved = event.get("full_size", 0) - event.get("summary_size", 0)
            running_total += saved // 4  # Convert to tokens
            ts = event.get("ts", "")[:19]
            cumulative.append({"ts": ts, "tokens_saved": running_total})

        # Take last 50 points max for readability
        if len(cumulative) > 50:
            step = len(cumulative) // 50
            cumulative = cumulative[::step]

        return {
            "labels": [c["ts"][-8:] for c in cumulative] if cumulative else [],
            "values": [c["tokens_saved"] for c in cumulative] if cumulative else [],
            "total": cumulative[-1]["tokens_saved"] if cumulative else 0
        }

    # Calculate for different time ranges
    data_7d = calc_savings(efficiency_events, 24 * 7)
    data_30d = calc_savings(efficiency_events, 24 * 30)
    data_all = calc_savings(efficiency_events, None)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Tokens Saved</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: -apple-system, sans-serif; padding: 20px; background: #1a1a2e; color: #eee; }}
        h1 {{ color: #4cc9f0; }}
        .back {{ color: #4cc9f0; text-decoration: none; }}
        .chart-container {{ max-width: 900px; margin: 20px auto; }}
        .note {{ color: #888; font-size: 14px; }}
        .total {{ font-size: 1.5rem; color: #4ade80; margin: 20px 0; }}
        {get_chart_dropdown_css()}
    </style>
</head>
<body>
    <a href="dashboard.html" class="back">← Back to Dashboard</a>
    <h1>💰 Tokens Saved Over Time</h1>

    <div class="controls">
        <label for="viewSelect">Time Range:</label>
        <select id="viewSelect" onchange="switchView()">
            <option value="week">Last 7 Days</option>
            <option value="month">Last 30 Days</option>
            <option value="all" selected>All Time</option>
        </select>
    </div>

    <p class="note">Cumulative token savings from MCP Router summarization</p>
    <p class="total">Total saved: <strong id="totalSaved">-</strong> tokens (estimated)</p>

    <div class="chart-container">
        <canvas id="chart"></canvas>
    </div>

    <script>
        const weekData = {json.dumps(data_7d)};
        const monthData = {json.dumps(data_30d)};
        const allData = {json.dumps(data_all)};

        let chart = null;

        function createChart(data) {{
            document.getElementById('totalSaved').textContent = data.total.toLocaleString();

            if (chart) chart.destroy();

            chart = new Chart(document.getElementById('chart'), {{
                type: 'line',
                data: {{
                    labels: data.labels,
                    datasets: [{{
                        label: 'Cumulative Tokens Saved',
                        data: data.values,
                        borderColor: 'rgba(74, 222, 128, 1)',
                        backgroundColor: 'rgba(74, 222, 128, 0.2)',
                        fill: true,
                        tension: 0.3
                    }}]
                }},
                options: {{
                    responsive: true,
                    plugins: {{ legend: {{ display: false }} }},
                    scales: {{
                        x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }},
                        y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }}, title: {{ display: true, text: 'Tokens', color: '#888' }} }}
                    }}
                }}
            }});
        }}

        function switchView() {{
            const view = document.getElementById('viewSelect').value;
            switch(view) {{
                case 'week': createChart(weekData); break;
                case 'month': createChart(monthData); break;
                case 'all': createChart(allData); break;
            }}
        }}

        switchView();
    </script>
</body>
</html>"""

    path = CHARTS_DIR / "tokens_saved.html"
    path.write_text(html, encoding='utf-8')
    print(f"✅ Tokens saved chart generated: {path}")
    return path


def chart_cache_efficiency():
    """Chart cache hit rate over time using actual token data."""
    if not TELEMETRY_FILE.exists():
        print("⚠️  No telemetry data found")
        return None

    telemetry = json.loads(TELEMETRY_FILE.read_text())

    # Try daily_summaries_actual first, then fall back to daily_summaries
    daily = telemetry.get("daily_summaries_actual", {})
    if not daily:
        daily = telemetry.get("daily_summaries", {})

    if not daily:
        print("⚠️  No daily summary data found")
        return None

    # Extract cache data by date
    dates = sorted(daily.keys())
    cache_reads = []
    cache_creates = []
    hit_rates = []

    for date in dates:
        data = daily[date]
        cr = data.get("cache_read", 0)
        cc = data.get("cache_create", 0)
        cache_reads.append(cr)
        cache_creates.append(cc)
        if cr + cc > 0:
            hit_rates.append(round(cr / (cr + cc) * 100, 1))
        else:
            hit_rates.append(0)

    # Format labels as short dates
    labels = [d[5:] for d in dates]  # MM-DD format

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Cache Efficiency</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: -apple-system, sans-serif; padding: 20px; background: #1a1a2e; color: #eee; }}
        h1 {{ color: #4cc9f0; }}
        .back {{ color: #4cc9f0; text-decoration: none; }}
        .chart-container {{ max-width: 1000px; margin: 20px auto; }}
        .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; max-width: 1000px; margin: 30px auto; }}
        .stat {{ background: #2a2a4e; padding: 20px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 28px; font-weight: bold; color: #4cc9f0; }}
        .stat-label {{ color: #888; font-size: 14px; margin-top: 5px; }}
        .controls {{ text-align: center; margin: 20px; }}
        .controls select {{ padding: 8px 16px; border-radius: 4px; background: #2a2a4e; color: #eee; border: 1px solid #4cc9f0; }}
    </style>
</head>
<body>
    <a href="dashboard.html" class="back">← Back to Dashboard</a>
    <h1>📊 Cache Efficiency</h1>

    <div class="stats">
        <div class="stat">
            <div class="stat-value">{sum(cache_reads)/1_000_000:.1f}M</div>
            <div class="stat-label">Cache Hits (tokens)</div>
        </div>
        <div class="stat">
            <div class="stat-value">{sum(cache_creates)/1_000_000:.1f}M</div>
            <div class="stat-label">Cache Misses (tokens)</div>
        </div>
        <div class="stat">
            <div class="stat-value">{round(sum(cache_reads)/(sum(cache_reads)+sum(cache_creates))*100 if sum(cache_reads)+sum(cache_creates) > 0 else 0, 1)}%</div>
            <div class="stat-label">Hit Rate</div>
        </div>
        <div class="stat">
            <div class="stat-value">${sum(cache_reads) * 0.90 * 8 / 1_000_000:.0f}</div>
            <div class="stat-label">Est. Savings (API)</div>
        </div>
    </div>
    <p style="color: #666; text-align: center; font-size: 12px; margin-top: -10px;">
        Savings estimate: cache hits × 90% discount × $8/M avg input price (blend of Opus $15 + Sonnet $3).
        Subscription users pay flat rate but benefit from faster responses and lower latency.
    </p>

    <div class="controls">
        <select id="viewSelect" onchange="switchView()">
            <option value="hitrate">Hit Rate %</option>
            <option value="volume">Cache Volume</option>
        </select>
    </div>

    <div class="chart-container">
        <canvas id="chart"></canvas>
    </div>

    <script>
        const labels = {json.dumps(labels)};
        const cacheReads = {json.dumps(cache_reads)};
        const cacheCreates = {json.dumps(cache_creates)};
        const hitRates = {json.dumps(hit_rates)};

        let chart = null;

        function createChart(type) {{
            if (chart) chart.destroy();

            const ctx = document.getElementById('chart');
            const config = type === 'hitrate' ? {{
                type: 'line',
                data: {{
                    labels: labels,
                    datasets: [{{
                        label: 'Cache Hit Rate %',
                        data: hitRates,
                        borderColor: '#4cc9f0',
                        backgroundColor: 'rgba(76, 201, 240, 0.1)',
                        fill: true,
                        tension: 0.4
                    }}]
                }},
                options: {{
                    responsive: true,
                    plugins: {{ legend: {{ labels: {{ color: '#888' }} }} }},
                    scales: {{
                        x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }},
                        y: {{ min: 0, max: 100, ticks: {{ color: '#888' }}, grid: {{ color: '#333' }}, title: {{ display: true, text: 'Hit Rate %', color: '#888' }} }}
                    }}
                }}
            }} : {{
                type: 'bar',
                data: {{
                    labels: labels,
                    datasets: [
                        {{
                            label: 'Cache Hits',
                            data: cacheReads,
                            backgroundColor: 'rgba(74, 222, 128, 0.8)'
                        }},
                        {{
                            label: 'Cache Misses',
                            data: cacheCreates,
                            backgroundColor: 'rgba(248, 113, 113, 0.8)'
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    plugins: {{ legend: {{ labels: {{ color: '#888' }} }} }},
                    scales: {{
                        x: {{ stacked: true, ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }},
                        y: {{ stacked: true, ticks: {{ color: '#888' }}, grid: {{ color: '#333' }}, title: {{ display: true, text: 'Tokens', color: '#888' }} }}
                    }}
                }}
            }};

            chart = new Chart(ctx, config);
        }}

        function switchView() {{
            createChart(document.getElementById('viewSelect').value);
        }}

        createChart('hitrate');
    </script>
</body>
</html>"""

    path = CHARTS_DIR / "cache_efficiency.html"
    path.write_text(html, encoding='utf-8')
    print(f"✅ Cache efficiency chart generated: {path}")
    return path


def chart_session_comparison():
    """Compare metrics across sessions."""
    if not TELEMETRY_FILE.exists():
        print("⚠️  No telemetry data found")
        return None

    telemetry = json.loads(TELEMETRY_FILE.read_text())
    events = telemetry.get("events", [])

    if not events:
        print("⚠️  No events found")
        return None

    # Group by date (session proxy)
    daily_data = defaultdict(lambda: {"calls": 0, "tokens": 0, "errors": 0, "duration": 0})

    for e in events:
        ts = e.get("ts", "")[:10]  # YYYY-MM-DD
        if ts:
            daily_data[ts]["calls"] += 1
            daily_data[ts]["tokens"] += e.get("tokens_est", 0)
            daily_data[ts]["duration"] += e.get("duration_ms", 0)
            if e.get("status") == "error":
                daily_data[ts]["errors"] += 1

    # Sort by date
    sorted_days = sorted(daily_data.items())[-14:]  # Last 14 days

    labels = [d[0][5:] for d in sorted_days]  # MM-DD
    calls = [d[1]["calls"] for d in sorted_days]
    tokens = [d[1]["tokens"] for d in sorted_days]
    errors = [d[1]["errors"] for d in sorted_days]

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Session Comparison</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: -apple-system, sans-serif; padding: 20px; background: #1a1a2e; color: #eee; }}
        h1 {{ color: #4cc9f0; }}
        .back {{ color: #4cc9f0; text-decoration: none; }}
        .charts {{ display: grid; grid-template-columns: 1fr; gap: 20px; max-width: 1200px; margin: 20px auto; }}
        .chart-box {{ background: #16213e; padding: 20px; border-radius: 8px; }}
        .chart-box h2 {{ color: #888; font-size: 14px; margin-top: 0; }}
    </style>
</head>
<body>
    <a href="dashboard.html" class="back">← Back to Dashboard</a>
    <h1>📅 Session Comparison (Last 14 Days)</h1>

    <div class="charts">
        <div class="chart-box">
            <h2>Daily Activity</h2>
            <canvas id="activityChart"></canvas>
        </div>
        <div class="chart-box">
            <h2>Daily Token Usage</h2>
            <canvas id="tokensChart"></canvas>
        </div>
    </div>

    <script>
        new Chart(document.getElementById('activityChart'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(labels)},
                datasets: [
                    {{
                        label: 'Calls',
                        data: {json.dumps(calls)},
                        backgroundColor: 'rgba(76, 201, 240, 0.6)'
                    }},
                    {{
                        label: 'Errors',
                        data: {json.dumps(errors)},
                        backgroundColor: 'rgba(248, 113, 113, 0.6)'
                    }}
                ]
            }},
            options: {{
                responsive: true,
                plugins: {{ legend: {{ labels: {{ color: '#888' }} }} }},
                scales: {{
                    x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }},
                    y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }}
                }}
            }}
        }});

        new Chart(document.getElementById('tokensChart'), {{
            type: 'line',
            data: {{
                labels: {json.dumps(labels)},
                datasets: [{{
                    label: 'Tokens',
                    data: {json.dumps(tokens)},
                    borderColor: 'rgba(74, 222, 128, 1)',
                    backgroundColor: 'rgba(74, 222, 128, 0.2)',
                    fill: true,
                    tension: 0.3
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{ legend: {{ labels: {{ color: '#888' }} }} }},
                scales: {{
                    x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }},
                    y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }}
                }}
            }}
        }});
    </script>
</body>
</html>"""

    path = CHARTS_DIR / "session_comparison.html"
    path.write_text(html, encoding='utf-8')
    print(f"✅ Session comparison chart generated: {path}")
    return path


def chart_blocked_tools():
    """Chart blocked/errored tools with time filtering."""
    from datetime import datetime, timezone

    if not TELEMETRY_FILE.exists():
        print("⚠️  No telemetry data found")
        return None

    telemetry = json.loads(TELEMETRY_FILE.read_text())
    events = telemetry.get("events", [])
    by_tool = telemetry.get("aggregates", {}).get("by_tool", {})

    if not by_tool and not events:
        print("⚠️  No tool data found")
        return None

    def calc_errors_from_events(events_list, cutoff_hours=None):
        """Calculate error stats from events for a time range."""
        now = datetime.now(timezone.utc)
        tool_stats = defaultdict(lambda: {"calls": 0, "errors": 0})
        recent = []

        for e in events_list:
            ts_str = e.get("ts", "")
            if cutoff_hours and ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if (now - ts).total_seconds() > cutoff_hours * 3600:
                        continue
                except:
                    pass

            tool = e.get("tool", "unknown")
            tool_stats[tool]["calls"] += 1
            if e.get("status") == "error":
                tool_stats[tool]["errors"] += 1
                recent.append({"ts": ts_str[:19], "tool": tool[:20], "msg": (e.get("error_msg", "") or "Unknown")[:50]})

        result = []
        for tool, data in tool_stats.items():
            if data["errors"] > 0:
                rate = (data["errors"] / data["calls"] * 100) if data["calls"] > 0 else 0
                result.append({"tool": tool[:25], "errors": data["errors"], "calls": data["calls"], "rate": round(rate, 1)})
        result.sort(key=lambda x: x["errors"], reverse=True)
        return {"data": result[:15], "recent": recent[-10:]}

    # Calculate for different time ranges
    data_7d = calc_errors_from_events(events, 24 * 7)
    data_30d = calc_errors_from_events(events, 24 * 30)
    data_events = calc_errors_from_events(events, None)

    # All-time from aggregates
    all_data = []
    for tool, data in by_tool.items():
        errors = data.get("errors", 0)
        if errors > 0:
            calls = data.get("count", 0)
            rate = (errors / calls * 100) if calls > 0 else 0
            all_data.append({"tool": tool[:25], "errors": errors, "calls": calls, "rate": round(rate, 1)})
    all_data.sort(key=lambda x: x["errors"], reverse=True)
    data_all = {"data": all_data[:15] if all_data else data_events["data"], "recent": data_events["recent"]}

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Blocked Tools</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: -apple-system, sans-serif; padding: 20px; background: #1a1a2e; color: #eee; }}
        h1 {{ color: #4cc9f0; }}
        .back {{ color: #4cc9f0; text-decoration: none; }}
        .content {{ max-width: 1200px; margin: 0 auto; }}
        .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 20px 0; }}
        .chart-box {{ background: #16213e; padding: 20px; border-radius: 8px; }}
        .chart-box h2 {{ color: #888; font-size: 14px; margin-top: 0; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #333; }}
        th {{ color: #888; text-transform: uppercase; font-size: 12px; }}
        .no-errors {{ color: #4ade80; text-align: center; padding: 40px; }}
        {get_chart_dropdown_css()}
    </style>
</head>
<body>
    <a href="dashboard.html" class="back">← Back to Dashboard</a>
    <h1>🚫 Blocked/Errored Tools</h1>

    <div class="controls">
        <label for="viewSelect">Time Range:</label>
        <select id="viewSelect" onchange="switchView()">
            <option value="week">Last 7 Days</option>
            <option value="month">Last 30 Days</option>
            <option value="all" selected>All Time</option>
        </select>
    </div>

    <div class="content">
        <div class="charts">
            <div class="chart-box">
                <h2>Error Counts by Tool</h2>
                <canvas id="countChart"></canvas>
            </div>
            <div class="chart-box">
                <h2>Error Rate by Tool (%)</h2>
                <canvas id="rateChart"></canvas>
            </div>
        </div>

        <div class="chart-box">
            <h2>Recent Errors</h2>
            <table>
                <thead><tr><th>Time</th><th>Tool</th><th>Message</th></tr></thead>
                <tbody id="errorTable"></tbody>
            </table>
        </div>
    </div>

    <script>
        const weekData = {json.dumps(data_7d)};
        const monthData = {json.dumps(data_30d)};
        const allData = {json.dumps(data_all)};

        let countChart = null;
        let rateChart = null;

        function updateView(viewData) {{
            const data = viewData.data;
            const recent = viewData.recent;

            // Update error table
            const tbody = document.getElementById('errorTable');
            if (recent.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="3" style="color: #4ade80; text-align: center;">✅ No recent errors</td></tr>';
            }} else {{
                tbody.innerHTML = recent.reverse().map(e =>
                    `<tr><td>${{e.ts}}</td><td>${{e.tool}}</td><td>${{e.msg}}</td></tr>`
                ).join('');
            }}

            if (data.length === 0) {{
                if (countChart) countChart.destroy();
                if (rateChart) rateChart.destroy();
                document.getElementById('countChart').parentElement.innerHTML = '<p style="color: #4ade80; text-align: center; padding: 40px;">✅ No errors recorded!</p>';
                document.getElementById('rateChart').parentElement.innerHTML = '<p style="color: #4ade80; text-align: center; padding: 40px;">✅ No errors recorded!</p>';
                return;
            }}

            const labels = data.map(d => d.tool);
            const errors = data.map(d => d.errors);
            const rates = data.map(d => d.rate);

            if (countChart) countChart.destroy();
            if (rateChart) rateChart.destroy();

            countChart = new Chart(document.getElementById('countChart'), {{
                type: 'bar',
                data: {{
                    labels: labels,
                    datasets: [{{
                        label: 'Errors',
                        data: errors,
                        backgroundColor: 'rgba(248, 113, 113, 0.6)',
                        borderColor: 'rgba(248, 113, 113, 1)',
                        borderWidth: 1
                    }}]
                }},
                options: {{
                    indexAxis: 'y',
                    responsive: true,
                    plugins: {{ legend: {{ display: false }} }},
                    scales: {{
                        x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }},
                        y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }}
                    }}
                }}
            }});

            rateChart = new Chart(document.getElementById('rateChart'), {{
                type: 'bar',
                data: {{
                    labels: labels,
                    datasets: [{{
                        label: 'Error Rate %',
                        data: rates,
                        backgroundColor: 'rgba(251, 191, 36, 0.6)',
                        borderColor: 'rgba(251, 191, 36, 1)',
                        borderWidth: 1
                    }}]
                }},
                options: {{
                    indexAxis: 'y',
                    responsive: true,
                    plugins: {{ legend: {{ display: false }} }},
                    scales: {{
                        x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }}, max: 100 }},
                        y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }}
                    }}
                }}
            }});
        }}

        function switchView() {{
            const view = document.getElementById('viewSelect').value;
            switch(view) {{
                case 'week': updateView(weekData); break;
                case 'month': updateView(monthData); break;
                case 'all': updateView(allData); break;
            }}
        }}

        switchView();
    </script>
</body>
</html>"""

    path = CHARTS_DIR / "blocked_tools.html"
    path.write_text(html, encoding='utf-8')
    print(f"✅ Blocked tools chart generated: {path}")
    return path


def generate_dashboard():
    """Generate a dashboard with all charts."""
    from datetime import timedelta, timezone

    # EST timezone offset (UTC-5)
    EST = timezone(timedelta(hours=-5))
    now_est = datetime.now(EST)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Agent-Swarm Dashboard</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            padding: 40px;
            background: #1a1a2e;
            margin: 0;
            color: #eee;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        h1 {{
            color: #4cc9f0;
            margin-bottom: 10px;
        }}
        .timestamp {{
            color: #888;
            font-size: 14px;
            margin-bottom: 30px;
        }}
        .section-title {{
            color: #4cc9f0;
            font-size: 16px;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin: 30px 0 15px 0;
            padding-bottom: 8px;
            border-bottom: 1px solid #333;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}
        .chart-card {{
            background: #16213e;
            padding: 20px;
            border-radius: 8px;
            border: 1px solid #333;
            transition: border-color 0.2s;
        }}
        .chart-card:hover {{
            border-color: #4cc9f0;
        }}
        .chart-card h2 {{
            margin-top: 0;
            font-size: 18px;
            color: #eee;
        }}
        .chart-card p {{
            color: #888;
            font-size: 14px;
            margin: 10px 0;
        }}
        .chart-link {{
            display: inline-block;
            margin-top: 10px;
            padding: 8px 16px;
            background: #4cc9f0;
            color: #1a1a2e;
            text-decoration: none;
            border-radius: 4px;
            font-size: 14px;
            font-weight: 500;
        }}
        .chart-link:hover {{
            background: #7dd8f5;
        }}
        .refresh {{
            background: #10b981;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
            margin-left: 15px;
        }}
        .refresh:hover {{
            background: #059669;
        }}
        .commands-box {{
            margin-top: 40px;
            padding: 20px;
            background: #16213e;
            border-radius: 8px;
            border: 1px solid #333;
        }}
        .commands-box h2 {{
            color: #4cc9f0;
            margin-top: 0;
        }}
        .commands-box pre {{
            background: #0f0f1e;
            padding: 15px;
            border-radius: 4px;
            overflow-x: auto;
            color: #10b981;
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Agent-Swarm Performance Dashboard</h1>
        <div class="timestamp">
            Last updated: {now_est.strftime("%Y-%m-%d %H:%M:%S")} EST
            <button class="refresh" onclick="location.reload()">Refresh</button>
        </div>

        <div class="section-title">Real-Time Telemetry</div>
        <div class="grid">
            <div class="chart-card">
                <h2>📡 Live Telemetry</h2>
                <p>All tool calls tracked by hooks in real-time</p>
                <a href="telemetry.html" class="chart-link">View Live Data →</a>
            </div>

            <div class="chart-card">
                <h2>⏱️ Latency by Tool</h2>
                <p>Average duration per tool - find slow tools</p>
                <a href="latency.html" class="chart-link">View Chart →</a>
            </div>

            <div class="chart-card">
                <h2>🚨 Error Timeline</h2>
                <p>Error spikes over time</p>
                <a href="error_timeline.html" class="chart-link">View Chart →</a>
            </div>

            <div class="chart-card">
                <h2>📅 Activity Heatmap</h2>
                <p>Work patterns by hour and day</p>
                <a href="activity_heatmap.html" class="chart-link">View Chart →</a>
            </div>

            <div class="chart-card">
                <h2>🔌 Native vs MCP</h2>
                <p>Compare tool ecosystems</p>
                <a href="native_vs_mcp.html" class="chart-link">View Chart →</a>
            </div>

            <div class="chart-card">
                <h2>💡 Token Efficiency</h2>
                <p>Tokens per call ratio by tool</p>
                <a href="token_efficiency.html" class="chart-link">View Chart →</a>
            </div>

            <div class="chart-card">
                <h2>📊 Session Comparison</h2>
                <p>Compare metrics across days</p>
                <a href="session_comparison.html" class="chart-link">View Chart →</a>
            </div>

            <div class="chart-card">
                <h2>🚫 Blocked Tools</h2>
                <p>Failed and blocked tool calls</p>
                <a href="blocked_tools.html" class="chart-link">View Chart →</a>
            </div>

            <div class="chart-card">
                <h2>📊 Cache Efficiency</h2>
                <p>Cache hit rate and savings</p>
                <a href="cache_efficiency.html" class="chart-link">View Chart →</a>
            </div>
        </div>

        <div class="section-title">Router Efficiency</div>
        <div class="grid">
            <div class="chart-card">
                <h2>📦 Compression Ratio</h2>
                <p>Context saved via MCP Router summarization</p>
                <a href="compression_ratio.html" class="chart-link">View Chart →</a>
            </div>

            <div class="chart-card">
                <h2>💰 Tokens Saved</h2>
                <p>Cumulative token savings over time</p>
                <a href="tokens_saved.html" class="chart-link">View Chart →</a>
            </div>
        </div>

        <div class="section-title">Trend Analysis</div>
        <div class="grid">
            <div class="chart-card">
                <h2>📈 Success Rate Trend</h2>
                <p>Success rate over time (daily/hourly)</p>
                <a href="efficiency_trend.html" class="chart-link">View Chart →</a>
            </div>

            <div class="chart-card">
                <h2>💰 Token Trend</h2>
                <p>Actual token usage with efficiency overlay</p>
                <a href="token_trend.html" class="chart-link">View Chart →</a>
            </div>

            <div class="chart-card">
                <h2>🔧 Tool Usage</h2>
                <p>Top tools by call count</p>
                <a href="tool_usage.html" class="chart-link">View Chart →</a>
            </div>

            <div class="chart-card">
                <h2>🤖 Subagent Tokens</h2>
                <p>Token usage by agent type</p>
                <a href="subagents.html" class="chart-link">View Chart →</a>
            </div>
        </div>

        <div class="commands-box">
            <h2>Quick Commands</h2>
            <pre>
# Capture current metrics
python3 ~/.claude/plugins/agent-swarm/scripts/charts.py snapshot

# Regenerate all charts
python3 ~/.claude/plugins/agent-swarm/scripts/charts.py dashboard

# Individual charts
python3 ~/.claude/plugins/agent-swarm/scripts/charts.py telemetry
python3 ~/.claude/plugins/agent-swarm/scripts/charts.py latency
python3 ~/.claude/plugins/agent-swarm/scripts/charts.py errors
python3 ~/.claude/plugins/agent-swarm/scripts/charts.py efficiency
            </pre>
        </div>
    </div>
</body>
</html>"""

    dashboard_path = CHARTS_DIR / "dashboard.html"
    dashboard_path.write_text(html, encoding='utf-8')

    print(f"\n✅ Dashboard generated: {dashboard_path}")
    print(f"\n🌐 Open in browser:")
    print(f"   file://{dashboard_path.absolute()}")

    return dashboard_path

def capture_snapshot():
    """Capture current metrics as snapshot."""
    from metrics import analyze_activity_log

    metrics = analyze_activity_log()

    # Calculate efficiency score
    from metrics import calculate_efficiency_score
    efficiency = calculate_efficiency_score(metrics)
    metrics["efficiency_score"] = efficiency

    save_snapshot(metrics)

def main():
    ensure_charts_dir()

    if len(sys.argv) < 2:
        print("Usage: charts.py <command>")
        print("\nTelemetry Charts (recommended):")
        print("  telemetry         - Real-time telemetry overview")
        print("  latency           - Latency by tool")
        print("  errors            - Error timeline")
        print("  heatmap           - Activity heatmap (EST)")
        print("  native-vs-mcp     - Native vs MCP comparison")
        print("  token-efficiency  - Token efficiency by tool")
        print("  session-compare   - Session comparison")
        print("  blocked-tools     - Blocked/failed tools")
        print("\nRouter Efficiency:")
        print("  compression       - Compression ratio (savings %)")
        print("  tokens-saved      - Cumulative tokens saved")
        print("\nTrend Charts:")
        print("  efficiency        - Success rate trend (EST)")
        print("  token-trend       - Token usage trend (EST)")
        print("  tool-usage        - Tool usage breakdown (EST)")
        print("  subagents         - Subagent token usage")
        print("\nMeta Commands:")
        print("  dashboard         - Generate all charts")
        print("\nAll times displayed in EST.")
        return

    cmd = sys.argv[1]

    if cmd == "snapshot":
        capture_snapshot()

    elif cmd == "efficiency":
        chart_efficiency_trend()

    elif cmd == "script-adoption":
        chart_script_adoption()

    elif cmd == "tool-usage":
        chart_tool_usage()

    elif cmd == "token-impact":
        chart_token_impact()

    elif cmd == "blocks":
        chart_blocks()

    elif cmd == "subagents":
        chart_subagents()

    elif cmd == "token-trend":
        chart_token_trend()

    elif cmd == "telemetry":
        chart_realtime_telemetry()

    elif cmd == "latency":
        chart_latency_by_tool()

    elif cmd == "errors":
        chart_error_timeline()

    elif cmd == "heatmap":
        chart_activity_heatmap()

    elif cmd == "native-vs-mcp":
        chart_native_vs_mcp()

    elif cmd == "token-efficiency":
        chart_token_efficiency()

    elif cmd == "session-compare":
        chart_session_comparison()

    elif cmd == "blocked-tools":
        chart_blocked_tools()

    elif cmd == "cache":
        chart_cache_efficiency()

    elif cmd == "compression":
        chart_compression_ratio()

    elif cmd == "tokens-saved":
        chart_tokens_saved()

    elif cmd == "dashboard":
        # Generate all charts
        print("Generating charts...")
        # Telemetry charts
        chart_realtime_telemetry()
        chart_latency_by_tool()
        chart_error_timeline()
        chart_activity_heatmap()
        chart_native_vs_mcp()
        chart_token_efficiency()
        chart_session_comparison()
        chart_blocked_tools()
        chart_cache_efficiency()
        # Router efficiency charts
        chart_compression_ratio()
        chart_tokens_saved()
        # Trend charts
        chart_efficiency_trend()
        chart_token_trend()
        chart_tool_usage()
        chart_subagents()
        generate_dashboard()

    elif cmd == "all":
        print("📊 Generating all charts...")
        # Telemetry charts
        chart_realtime_telemetry()
        chart_latency_by_tool()
        chart_error_timeline()
        chart_activity_heatmap()
        chart_native_vs_mcp()
        chart_token_efficiency()
        chart_session_comparison()
        chart_blocked_tools()
        chart_cache_efficiency()
        # Router efficiency charts
        chart_compression_ratio()
        chart_tokens_saved()
        # Trend charts
        chart_efficiency_trend()
        chart_token_trend()
        chart_tool_usage()
        chart_subagents()
        generate_dashboard()

    else:
        print(f"Unknown command: {cmd}")

if __name__ == "__main__":
    main()
