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

    HISTORY_FILE.write_text(json.dumps(history, indent=2))
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
    output_path.write_text(html)
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
    output_path.write_text(html)
    
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
    output_path.write_text(html)
    
    print(f"✅ Chart generated: {output_path}")
    return output_path

def chart_tool_usage():
    """Chart current tool usage breakdown."""
    # Get latest metrics
    from metrics import analyze_activity_log
    metrics = analyze_activity_log()

    tools = metrics.get("tools_by_type", {})

    if not tools:
        print("⚠️  No tool usage data found")
        return None

    # Sort by usage
    sorted_tools = sorted(tools.items(), key=lambda x: -x[1])[:10]

    labels = [tool for tool, _ in sorted_tools]
    values = [count for _, count in sorted_tools]

    data = {
        "label": "Tool Calls",
        "values": values
    }

    path = generate_html_chart(
        "Tool Usage Breakdown",
        "bar",
        data,
        labels,
        "tool_usage.html"
    )

    print(f"✅ Chart generated: {path}")
    return path

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
    output_path.write_text(html)
    
    print(f"✅ Chart generated: {output_path}")
    return output_path

def generate_dashboard():
    """Generate a dashboard with all charts."""

    html = f"""<!DOCTYPE html>
<html>
<head>
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
    dashboard_path.write_text(html)

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
        chart_blocks()
        chart_subagents()
        generate_dashboard()

    else:
        print(f"Unknown command: {cmd}")

if __name__ == "__main__":
    main()
