#!/usr/bin/env python3
"""
Generate visual charts from agent-swarm metrics.

Usage:
    python3 charts.py efficiency          # Efficiency score over time
    python3 charts.py script-adoption     # Script adoption trend
    python3 charts.py tool-usage          # Tool usage breakdown
    python3 charts.py blocks              # Block reasons pie chart
    python3 charts.py subagents           # Subagent token usage
    python3 charts.py dashboard           # All charts in one HTML page

Output: HTML files with interactive charts (opens in browser)
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

def generate_html_chart(title, chart_type, data, labels, output_file, options=None):
    """Generate standalone HTML with Chart.js."""

    if options is None:
        options = {}

    # Prepare data for Chart.js
    if chart_type == "line":
        datasets = [{
            "label": data.get("label", "Value"),
            "data": data.get("values", []),
            "borderColor": "rgb(75, 192, 192)",
            "backgroundColor": "rgba(75, 192, 192, 0.2)",
            "tension": 0.1
        }]
    elif chart_type == "bar":
        datasets = [{
            "label": data.get("label", "Value"),
            "data": data.get("values", []),
            "backgroundColor": [
                "rgba(255, 99, 132, 0.5)",
                "rgba(54, 162, 235, 0.5)",
                "rgba(255, 206, 86, 0.5)",
                "rgba(75, 192, 192, 0.5)",
                "rgba(153, 102, 255, 0.5)",
                "rgba(255, 159, 64, 0.5)"
            ][:len(data.get("values", []))]
        }]
    elif chart_type == "pie":
        datasets = [{
            "data": data.get("values", []),
            "backgroundColor": [
                "rgba(255, 99, 132, 0.8)",
                "rgba(54, 162, 235, 0.8)",
                "rgba(255, 206, 86, 0.8)",
                "rgba(75, 192, 192, 0.8)",
                "rgba(153, 102, 255, 0.8)",
                "rgba(255, 159, 64, 0.8)",
                "rgba(201, 203, 207, 0.8)"
            ][:len(data.get("values", []))]
        }]

    chart_data = {
        "labels": labels,
        "datasets": datasets
    }

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
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            margin-bottom: 10px;
        }}
        .timestamp {{
            color: #666;
            font-size: 14px;
            margin-bottom: 30px;
        }}
        canvas {{
            max-height: 500px;
        }}
        .back-link {{
            display: inline-block;
            margin-top: 20px;
            color: #0066cc;
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
        <div class="timestamp">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
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
                    }},
                    title: {{
                        display: false
                    }}
                }}{(',' + 'scales:' + json.dumps(options.get('scales', {}))) if 'scales' in options else ''}
            }}
        }});
    </script>
</body>
</html>"""

    output_path = CHARTS_DIR / output_file
    output_path.write_text(html, encoding='utf-8')
    return output_path

def chart_efficiency_trend():
    """Chart efficiency score over time with daily/session view toggle."""
    history = load_history()

    if len(history["snapshots"]) < 2:
        print("⚠️  Need at least 2 snapshots for trend chart")
        print("   Run: python3 metrics.py report  (to capture current state)")
        return None

    # Prepare session view
    session_labels = []
    session_scores = []

    for snapshot in history["snapshots"]:
        session_labels.append(snapshot["date"])
        session_scores.append(snapshot["metrics"].get("efficiency_score", 0))

    # Prepare daily view (average by date)
    from collections import defaultdict
    daily_data = defaultdict(list)
    
    for snapshot in history["snapshots"]:
        full_date = snapshot.get("date", "Unknown")
        date_only = full_date.split()[0] if " " in full_date else full_date
        score = snapshot["metrics"].get("efficiency_score", 0)
        daily_data[date_only].append(score)
    
    # Average scores per day
    sorted_daily = sorted(daily_data.items())
    daily_labels = [date for date, _ in sorted_daily]
    daily_scores = [sum(scores) / len(scores) for _, scores in sorted_daily]

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
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
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
            color: #555;
        }}
        .controls select {{
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
            background: white;
            cursor: pointer;
        }}
        .timestamp {{
            color: #666;
            font-size: 14px;
            margin-bottom: 20px;
        }}
        canvas {{
            max-height: 500px;
        }}
        .back-link {{
            display: inline-block;
            margin-top: 20px;
            color: #0066cc;
            text-decoration: none;
        }}
        .back-link:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Efficiency Score Trend</h1>
        <div class="timestamp">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
        
        <div class="controls">
            <label for="viewSelect">View:</label>
            <select id="viewSelect" onchange="switchView()">
                <option value="daily">Daily Average</option>
                <option value="session">Per Session</option>
            </select>
        </div>
        
        <canvas id="chart"></canvas>
        <a href="dashboard.html" class="back-link">← Back to Dashboard</a>
    </div>

    <script>
        const dailyData = {{
            labels: {json.dumps(daily_labels)},
            datasets: [{{
                label: 'Efficiency Score (Daily Avg)',
                data: {json.dumps(daily_scores)},
                borderColor: 'rgb(75, 192, 192)',
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                tension: 0.1,
                fill: true
            }}]
        }};

        const sessionData = {{
            labels: {json.dumps(session_labels)},
            datasets: [{{
                label: 'Efficiency Score (Per Session)',
                data: {json.dumps(session_scores)},
                borderColor: 'rgb(54, 162, 235)',
                backgroundColor: 'rgba(54, 162, 235, 0.2)',
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
                    }},
                    title: {{
                        display: false
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        max: 100
                    }}
                }}
            }}
        }});

        function switchView() {{
            const view = document.getElementById('viewSelect').value;
            chart.data = view === 'daily' ? dailyData : sessionData;
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
    """Chart script adoption over time with daily/session view toggle."""
    history = load_history()

    if len(history["snapshots"]) < 2:
        print("⚠️  Need at least 2 snapshots for trend chart")
        return None

    # Prepare session view
    session_labels = []
    session_rates = []

    for snapshot in history["snapshots"]:
        session_labels.append(snapshot["date"])
        metrics = snapshot["metrics"]

        script_calls = metrics.get("script_calls", 0)
        direct_reads = metrics.get("tools_by_type", {}).get("Read", 0)
        total = script_calls + direct_reads

        if total > 0:
            rate = (script_calls / total) * 100
        else:
            rate = 0

        session_rates.append(rate)

    # Prepare daily view (aggregate by date)
    from collections import defaultdict
    daily_scripts = defaultdict(int)
    daily_reads = defaultdict(int)
    
    for snapshot in history["snapshots"]:
        full_date = snapshot.get("date", "Unknown")
        date_only = full_date.split()[0] if " " in full_date else full_date
        
        metrics = snapshot["metrics"]
        daily_scripts[date_only] += metrics.get("script_calls", 0)
        daily_reads[date_only] += metrics.get("tools_by_type", {}).get("Read", 0)
    
    # Calculate daily adoption rates
    sorted_daily = sorted(daily_scripts.keys())
    daily_labels = sorted_daily
    daily_rates = []
    for date in sorted_daily:
        scripts = daily_scripts[date]
        reads = daily_reads[date]
        total = scripts + reads
        rate = (scripts / total * 100) if total > 0 else 0
        daily_rates.append(rate)

    # Generate HTML with dropdown
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Script Adoption Trend</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            padding: 40px;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
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
            color: #555;
        }}
        .controls select {{
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
            background: white;
            cursor: pointer;
        }}
        .timestamp {{
            color: #666;
            font-size: 14px;
            margin-bottom: 20px;
        }}
        canvas {{
            max-height: 500px;
        }}
        .back-link {{
            display: inline-block;
            margin-top: 20px;
            color: #0066cc;
            text-decoration: none;
        }}
        .back-link:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Script Adoption Trend</h1>
        <div class="timestamp">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
        
        <div class="controls">
            <label for="viewSelect">View:</label>
            <select id="viewSelect" onchange="switchView()">
                <option value="daily">Daily Totals</option>
                <option value="session">Per Session</option>
            </select>
        </div>
        
        <canvas id="chart"></canvas>
        <a href="dashboard.html" class="back-link">← Back to Dashboard</a>
    </div>

    <script>
        const dailyData = {{
            labels: {json.dumps(daily_labels)},
            datasets: [{{
                label: 'Script Adoption % (Daily)',
                data: {json.dumps(daily_rates)},
                borderColor: 'rgb(75, 192, 192)',
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                tension: 0.1,
                fill: true
            }}]
        }};

        const sessionData = {{
            labels: {json.dumps(session_labels)},
            datasets: [{{
                label: 'Script Adoption % (Per Session)',
                data: {json.dumps(session_rates)},
                borderColor: 'rgb(54, 162, 235)',
                backgroundColor: 'rgba(54, 162, 235, 0.2)',
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
                    }},
                    title: {{
                        display: false
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        max: 100
                    }}
                }}
            }}
        }});

        function switchView() {{
            const view = document.getElementById('viewSelect').value;
            chart.data = view === 'daily' ? dailyData : sessionData;
            chart.update();
        }}
    </script>
</body>
</html>"""

    output_path = CHARTS_DIR / "script_adoption.html"
    output_path.write_text(html, encoding='utf-8')
    
    print(f"✅ Chart generated: {output_path}")
    return output_path

def chart_tool_usage():
    """Chart tool usage breakdown with time range filtering."""
    from datetime import datetime, timedelta
    from collections import defaultdict

    history = load_history()
    snapshots = history.get("snapshots", [])

    if len(snapshots) < 1:
        print("⚠️  Need at least 1 snapshot for chart")
        return None

    # Helper to aggregate tool usage for a time range
    def aggregate_tools(snapshots_subset):
        aggregated = defaultdict(int)
        for snapshot in snapshots_subset:
            snapshot_tools = snapshot.get("metrics", {}).get("tools_by_type", {})
            for tool, count in snapshot_tools.items():
                aggregated[tool] += count
        return aggregated

    # Parse dates and filter snapshots
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    def parse_snapshot_date(snapshot):
        try:
            date_str = snapshot.get("timestamp") or snapshot.get("date", "")
            if "T" in date_str:  # ISO format
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            else:  # "YYYY-MM-DD HH:MM" format
                return datetime.strptime(date_str, "%Y-%m-%d %H:%M")
        except:
            return None

    # Filter snapshots by time range
    session_snapshots = snapshots[-1:] if snapshots else []
    today_snapshots = [s for s in snapshots if parse_snapshot_date(s) and parse_snapshot_date(s) >= today_start]
    week_snapshots = [s for s in snapshots if parse_snapshot_date(s) and parse_snapshot_date(s) >= week_ago]
    month_snapshots = [s for s in snapshots if parse_snapshot_date(s) and parse_snapshot_date(s) >= month_ago]
    all_snapshots = snapshots

    # Aggregate for each time range
    session_tools = aggregate_tools(session_snapshots)
    today_tools = aggregate_tools(today_snapshots)
    week_tools = aggregate_tools(week_snapshots)
    month_tools = aggregate_tools(month_snapshots)
    all_tools = aggregate_tools(all_snapshots)

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
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
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
            color: #555;
        }}
        .controls select {{
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
            background: white;
            cursor: pointer;
        }}
        .timestamp {{
            color: #666;
            font-size: 14px;
            margin-bottom: 20px;
        }}
        canvas {{
            max-height: 500px;
        }}
        .back-link {{
            display: inline-block;
            margin-top: 20px;
            color: #0066cc;
            text-decoration: none;
        }}
        .back-link:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Tool Usage Breakdown</h1>
        <div class="timestamp">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>

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
            'rgba(255, 99, 132, 0.5)',
            'rgba(54, 162, 235, 0.5)',
            'rgba(255, 206, 86, 0.5)',
            'rgba(75, 192, 192, 0.5)',
            'rgba(153, 102, 255, 0.5)',
            'rgba(255, 159, 64, 0.5)',
            'rgba(201, 203, 207, 0.5)',
            'rgba(255, 99, 71, 0.5)',
            'rgba(60, 179, 113, 0.5)',
            'rgba(123, 104, 238, 0.5)'
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
                    }},
                    title: {{
                        display: false
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true
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
    """Chart block reasons pie chart."""
    from metrics import analyze_activity_log
    metrics = analyze_activity_log()

    blocks = metrics.get("blocks_by_reason", {})

    if not blocks:
        print("⚠️  No block data found")
        return None

    # Top 6 reasons
    sorted_blocks = sorted(blocks.items(), key=lambda x: -x[1])[:6]

    labels = [reason for reason, _ in sorted_blocks]
    values = [count for _, count in sorted_blocks]

    data = {
        "values": values
    }

    path = generate_html_chart(
        "Block Reasons Distribution",
        "pie",
        data,
        labels,
        "blocks.html"
    )

    print(f"✅ Chart generated: {path}")
    return path

def chart_token_impact():
    """Chart actionable token impact metrics with recommendations."""
    from datetime import datetime
    
    # Get token impact analysis
    from metrics import analyze_activity_log, calculate_token_impact
    log_metrics = analyze_activity_log()
    impact = calculate_token_impact(log_metrics)
    
    impact_score = impact["impact_score"]
    data_volume = impact["data_volume"]
    efficiency = impact["efficiency"]
    recommendations = impact["recommendations"]
    
    # Determine impact level and color
    if impact_score >= 50:
        level = "HIGH"
        color = "#dc3545"
        emoji = "🔴"
    elif impact_score >= 25:
        level = "MEDIUM"
        color = "#ffc107"
        emoji = "🟡"
    else:
        level = "LOW"
        color = "#28a745"
        emoji = "🟢"
    
    # Build recommendations HTML
    rec_html = ""
    for rec in recommendations:
        priority = rec["priority"]
        icon = {"HIGH": "🔴", "MEDIUM": "🟡", "INFO": "ℹ️", "SUCCESS": "✅"}.get(priority, "•")
        issue = rec["issue"]
        action = rec["action"]
        
        rec_html += f"""
            <div class="recommendation {priority.lower()}">
                <div class="rec-header">{icon} {issue}</div>
                <div class="rec-action">→ {action}</div>
            </div>
        """
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Token Impact Analysis</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            padding: 40px;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            margin-bottom: 10px;
        }}
        .timestamp {{
            color: #666;
            font-size: 14px;
            margin-bottom: 20px;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }}
        .metric-card {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #0066cc;
        }}
        .metric-card h3 {{
            margin: 0 0 10px 0;
            font-size: 14px;
            color: #666;
            text-transform: uppercase;
        }}
        .metric-value {{
            font-size: 28px;
            font-weight: bold;
            color: #333;
        }}
        .gauge-container {{
            text-align: center;
            margin: 30px 0;
        }}
        .gauge {{
            width: 200px;
            height: 200px;
            margin: 0 auto;
        }}
        .impact-level {{
            font-size: 24px;
            font-weight: bold;
            margin-top: 10px;
        }}
        .recommendations {{
            margin-top: 30px;
        }}
        .recommendations h2 {{
            color: #333;
            margin-bottom: 15px;
        }}
        .recommendation {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 10px;
            border-left: 4px solid #ccc;
        }}
        .recommendation.high {{
            border-left-color: #dc3545;
            background: #fff5f5;
        }}
        .recommendation.medium {{
            border-left-color: #ffc107;
            background: #fffef5;
        }}
        .recommendation.info {{
            border-left-color: #17a2b8;
            background: #f5feff;
        }}
        .recommendation.success {{
            border-left-color: #28a745;
            background: #f5fff8;
        }}
        .rec-header {{
            font-weight: 600;
            margin-bottom: 5px;
            color: #333;
        }}
        .rec-action {{
            color: #555;
            font-size: 14px;
            margin-left: 20px;
        }}
        .back-link {{
            display: inline-block;
            margin-top: 20px;
            color: #0066cc;
            text-decoration: none;
        }}
        .back-link:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🎯 Token Impact Analysis</h1>
        <div class="timestamp">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
        
        <div class="gauge-container">
            <canvas id="gauge" class="gauge"></canvas>
            <div class="impact-level" style="color: {color};">
                {emoji} {level} IMPACT ({impact_score:.0f}/100)
            </div>
            <p style="color: #666; margin-top: 10px;">
                {level} optimization potential detected
            </p>
        </div>
        
        <h2 style="margin-top: 30px;">📊 Data Volume</h2>
        <div class="grid">
            <div class="metric-card">
                <h3>Total Reads</h3>
                <div class="metric-value">{data_volume['total_reads']}</div>
            </div>
            <div class="metric-card">
                <h3>Estimated Lines</h3>
                <div class="metric-value">{data_volume['estimated_lines']:,}</div>
            </div>
            <div class="metric-card">
                <h3>Searches</h3>
                <div class="metric-value">{data_volume['searches']}</div>
            </div>
        </div>
        
        <h2 style="margin-top: 30px;">⚡ Efficiency Metrics</h2>
        <div class="grid">
            <div class="metric-card">
                <h3>Duplicate Rate</h3>
                <div class="metric-value">{efficiency['duplicate_rate']:.1f}%</div>
            </div>
            <div class="metric-card">
                <h3>Script Adoption</h3>
                <div class="metric-value">{efficiency['script_adoption']:.1f}%</div>
            </div>
            <div class="metric-card">
                <h3>Direct Reads</h3>
                <div class="metric-value">{efficiency['direct_reads']}</div>
            </div>
            <div class="metric-card">
                <h3>Script Calls</h3>
                <div class="metric-value">{efficiency['script_calls']}</div>
            </div>
            <div class="metric-card">
                <h3>Subagents</h3>
                <div class="metric-value">{efficiency['subagent_count']}</div>
            </div>
        </div>
        
        <div class="recommendations">
            <h2>💡 Recommendations</h2>
            {rec_html if rec_html else '<p style="color: #666;">No recommendations - keep up the good work!</p>'}
        </div>
        
        <a href="dashboard.html" class="back-link">← Back to Dashboard</a>
    </div>

    <script>
        const ctx = document.getElementById('gauge').getContext('2d');
        const impactScore = {impact_score:.0f};
        
        new Chart(ctx, {{
            type: 'doughnut',
            data: {{
                labels: ['Impact', 'Remaining'],
                datasets: [{{
                    data: [impactScore, 100 - impactScore],
                    backgroundColor: ['{color}', '#e9ecef'],
                    borderWidth: 0
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                circumference: 180,
                rotation: 270,
                cutout: '75%',
                plugins: {{
                    legend: {{
                        display: false
                    }},
                    tooltip: {{
                        enabled: false
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>"""

    output_path = CHARTS_DIR / "token_impact.html"
    output_path.write_text(html, encoding='utf-8')
    
    print(f"✅ Chart generated: {output_path}")
    return output_path

def chart_subagents(session_filter=None):
    """Chart subagent token usage by type (or by individual agent if session filtered)."""
    if not SUBAGENT_METRICS.exists():
        print("⚠️  No subagent metrics found")
        print("   Subagent tracking is automatic via post-tool-tracking.py hook")
        print("   Spawn some agents and they'll be tracked automatically")
        return None

    metrics = json.loads(SUBAGENT_METRICS.read_text())

    if not metrics:
        print("⚠️  No subagent data found")
        return None

    # Token estimates per agent type (from metrics.py)
    TOKEN_ESTIMATES = {
        "explorer": 25000,
        "implementer": 100000,
        "reviewer": 40000,
        "architect": 120000,
        "debugger": 150000,
        "researcher": 150000,
        "git-agent": 30000,
        "default": 50000
    }

    # Filter by session if requested
    if session_filter:
        # Filter metrics to only agents from specific session
        # (Assuming session info will be added to metrics in future)
        filtered_metrics = {k: v for k, v in metrics.items()
                          if v.get("session") == session_filter}
        if not filtered_metrics:
            print(f"⚠️  No agents found for session: {session_filter}")
            return None
        metrics = filtered_metrics
        show_individual = True
        title = f"Subagent Tokens - Session {session_filter}"
    else:
        show_individual = False
        title = "Subagent Token Usage by Type"

    if show_individual:
        # Show individual agents (for session view)
        results = {}
        for agent_id, data in metrics.items():
            agent_type = data.get("agent_type", "unknown")
            tokens = TOKEN_ESTIMATES.get("default", 50000)
            for key in TOKEN_ESTIMATES:
                if key in agent_type.lower():
                    tokens = TOKEN_ESTIMATES[key]
                    break

            type_name = agent_type.split(':')[-1] if ':' in agent_type else agent_type
            label = f"{type_name} ({agent_id[:7]})"
            results[label] = tokens
    else:
        # Group by agent type (default view)
        by_type = {}
        for agent_id, data in metrics.items():
            agent_type = data.get("agent_type", "unknown")

            # Extract type name (remove prefix if present)
            type_name = agent_type.split(':')[-1] if ':' in agent_type else agent_type

            # Estimate tokens for this agent
            tokens = TOKEN_ESTIMATES.get("default", 50000)
            for key in TOKEN_ESTIMATES:
                if key in agent_type.lower():
                    tokens = TOKEN_ESTIMATES[key]
                    break

            by_type[type_name] = by_type.get(type_name, 0) + tokens

        results = by_type

    if not results:
        print("⚠️  No subagent data to chart")
        return None

    labels = list(results.keys())
    values = list(results.values())

    data = {
        "label": "Estimated Tokens",
        "values": values
    }

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
    """Chart token usage trend over time with daily/session view toggle."""
    history = load_history()
    snapshots = history.get("snapshots", [])

    if len(snapshots) < 2:
        print("⚠️  Need at least 2 snapshots for trend. Run: charts.py snapshot")
        return None

    # Prepare session view (existing logic)
    session_labels = []
    session_tokens = []
    prev_tools = {}

    for snapshot in snapshots:
        session_labels.append(snapshot.get("date", "Unknown"))
        metrics = snapshot.get("metrics", {})
        current_tools = metrics.get("tools_by_type", {})

        # Calculate tokens for this session only (delta from previous)
        tokens = 0
        for tool, count in current_tools.items():
            prev_count = prev_tools.get(tool, 0)
            delta = count - prev_count

            estimate = {
                "Bash": 500, "Read": 2000, "Edit": 1500,
                "Write": 1000, "Task": 5000, "Grep": 1000,
                "Glob": 500
            }.get(tool, 500)
            tokens += estimate * delta

        session_tokens.append(max(0, tokens))
        prev_tools = current_tools.copy()

    # Prepare daily view (aggregate by date)
    from collections import defaultdict
    daily_data = defaultdict(int)
    
    prev_tools_daily = {}
    for snapshot in snapshots:
        # Extract date only (YYYY-MM-DD)
        full_date = snapshot.get("date", "Unknown")
        date_only = full_date.split()[0] if " " in full_date else full_date
        
        metrics = snapshot.get("metrics", {})
        current_tools = metrics.get("tools_by_type", {})
        
        # Calculate token delta
        tokens = 0
        for tool, count in current_tools.items():
            prev_count = prev_tools_daily.get(tool, 0)
            delta = count - prev_count
            
            estimate = {
                "Bash": 500, "Read": 2000, "Edit": 1500,
                "Write": 1000, "Task": 5000, "Grep": 1000,
                "Glob": 500
            }.get(tool, 500)
            tokens += estimate * delta
        
        daily_data[date_only] += max(0, tokens)
        prev_tools_daily = current_tools.copy()
    
    # Sort daily data by date
    sorted_daily = sorted(daily_data.items())
    daily_labels = [date for date, _ in sorted_daily]
    daily_tokens = [tokens for _, tokens in sorted_daily]

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
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
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
            color: #555;
        }}
        .controls select {{
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
            background: white;
            cursor: pointer;
        }}
        .timestamp {{
            color: #666;
            font-size: 14px;
            margin-bottom: 20px;
        }}
        canvas {{
            max-height: 500px;
        }}
        .back-link {{
            display: inline-block;
            margin-top: 20px;
            color: #0066cc;
            text-decoration: none;
        }}
        .back-link:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Token Usage Trend</h1>
        <div class="timestamp">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
        
        <div class="controls">
            <label for="viewSelect">View:</label>
            <select id="viewSelect" onchange="switchView()">
                <option value="daily">Daily Totals</option>
                <option value="session">Per Session</option>
            </select>
        </div>
        
        <canvas id="chart"></canvas>
        <a href="dashboard.html" class="back-link">← Back to Dashboard</a>
    </div>

    <script>
        const dailyData = {{
            labels: {json.dumps(daily_labels)},
            datasets: [{{
                label: 'Tokens per Day',
                data: {json.dumps(daily_tokens)},
                borderColor: 'rgb(75, 192, 192)',
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                tension: 0.1,
                fill: true
            }}]
        }};

        const sessionData = {{
            labels: {json.dumps(session_labels)},
            datasets: [{{
                label: 'Tokens per Session',
                data: {json.dumps(session_tokens)},
                borderColor: 'rgb(54, 162, 235)',
                backgroundColor: 'rgba(54, 162, 235, 0.2)',
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
                    }},
                    title: {{
                        display: false
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true
                    }}
                }}
            }}
        }});

        function switchView() {{
            const view = document.getElementById('viewSelect').value;
            chart.data = view === 'daily' ? dailyData : sessionData;
            chart.update();
        }}
    </script>
</body>
</html>"""

    output_path = CHARTS_DIR / "token_trend.html"
    output_path.write_text(html, encoding='utf-8')
    
    print(f"✅ Chart generated: {output_path}")
    return output_path

def generate_dashboard():
    """Generate a dashboard with all charts."""

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Agent-Swarm Dashboard</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            padding: 40px;
            background: #f5f5f5;
            margin: 0;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        h1 {{
            color: #333;
            margin-bottom: 10px;
        }}
        .timestamp {{
            color: #666;
            font-size: 14px;
            margin-bottom: 30px;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}
        .chart-card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .chart-card h2 {{
            margin-top: 0;
            font-size: 18px;
            color: #333;
        }}
        .chart-link {{
            display: inline-block;
            margin-top: 10px;
            padding: 8px 16px;
            background: #0066cc;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-size: 14px;
        }}
        .chart-link:hover {{
            background: #0052a3;
        }}
        iframe {{
            width: 100%;
            height: 300px;
            border: none;
        }}
        .refresh {{
            background: #28a745;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
        }}
        .refresh:hover {{
            background: #218838;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 Agent-Swarm Performance Dashboard</h1>
        <div class="timestamp">
            Last updated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            <button class="refresh" onclick="location.reload()">🔄 Refresh</button>
        </div>

        <div class="grid">
            <div class="chart-card">
                <h2>📊 Efficiency Trend</h2>
                <p>Overall efficiency score over time</p>
                <a href="efficiency_trend.html" class="chart-link">View Full Chart →</a>
            </div>

            <div class="chart-card">
                <h2>📜 Script Adoption</h2>
                <p>Script usage vs direct reads trend</p>
                <a href="script_adoption.html" class="chart-link">View Full Chart →</a>
            </div>

            <div class="chart-card">
                <h2>💰 Token Trend</h2>
                <p>Estimated tokens per session</p>
                <a href="token_trend.html" class="chart-link">View Full Chart →</a>
            </div>

            <div class="chart-card">
                <h2>🔧 Tool Usage</h2>
                <p>Which tools are used most</p>
                <a href="tool_usage.html" class="chart-link">View Full Chart →</a>
            </div>

            <div class="chart-card">
                <h2>🎯 Token Impact</h2>
                <p>Actionable optimization metrics</p>
                <a href="token_impact.html" class="chart-link">View Full Chart →</a>
            </div>

            <div class="chart-card">
                <h2>🚫 Block Reasons</h2>
                <p>What's being blocked and why</p>
                <a href="blocks.html" class="chart-link">View Full Chart →</a>
            </div>

            <div class="chart-card">
                <h2>🤖 Subagent Tokens</h2>
                <p>Token usage by agent type</p>
                <a href="subagents.html" class="chart-link">View Full Chart →</a>
            </div>
        </div>

        <div style="margin-top: 40px; padding: 20px; background: white; border-radius: 8px;">
            <h2>📈 Quick Commands</h2>
            <pre style="background: #f8f9fa; padding: 15px; border-radius: 4px; overflow-x: auto;">
# Capture current metrics
python3 ~/.claude/plugins/agent-swarm/scripts/charts.py snapshot

# Regenerate all charts
python3 ~/.claude/plugins/agent-swarm/scripts/charts.py dashboard

# Individual charts
python3 ~/.claude/plugins/agent-swarm/scripts/charts.py efficiency
python3 ~/.claude/plugins/agent-swarm/scripts/charts.py script-adoption
python3 ~/.claude/plugins/agent-swarm/scripts/charts.py tool-usage
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
        print("\nCommands:")
        print("  snapshot          - Capture current metrics")
        print("  efficiency        - Efficiency trend chart")
        print("  script-adoption   - Script adoption chart")
        print("  tool-usage        - Tool usage breakdown")
        print("  blocks            - Block reasons chart")
        print("  subagents         - Subagent token usage")
        print("  dashboard         - Generate all charts")
        print("  all               - Snapshot + generate all")
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

    elif cmd == "dashboard":
        # Generate all charts
        print("Generating charts...")
        chart_efficiency_trend()
        chart_script_adoption()
        chart_token_trend()
        chart_tool_usage()
        chart_token_impact()
        chart_blocks()
        chart_subagents()
        generate_dashboard()

    elif cmd == "all":
        print("📸 Capturing snapshot...")
        capture_snapshot()
        print("\n📊 Generating charts...")
        chart_efficiency_trend()
        chart_script_adoption()
        chart_token_trend()
        chart_tool_usage()
        chart_token_impact()
        chart_blocks()
        chart_subagents()
        generate_dashboard()

    else:
        print(f"Unknown command: {cmd}")

if __name__ == "__main__":
    main()
