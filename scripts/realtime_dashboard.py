#!/usr/bin/env python3
"""
Real-time telemetry dashboard for MCP router.

Generates an auto-refreshing HTML dashboard that reads from telemetry.json.

Usage:
    python3 realtime_dashboard.py           # Generate and open dashboard
    python3 realtime_dashboard.py --serve   # Start live server with WebSocket updates
"""

import sys
from pathlib import Path

STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"
TELEMETRY_FILE = STATE_DIR / "telemetry.json"
DASHBOARD_FILE = STATE_DIR / "realtime_dashboard.html"


def generate_dashboard():
    """Generate auto-refreshing HTML dashboard."""

    html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>MCP Router - Real-Time Telemetry</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #16213e 0%, #1a1a2e 100%);
            padding: 20px 40px;
            border-bottom: 1px solid #333;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            font-size: 24px;
            color: #4cc9f0;
        }
        .status {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .status-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #4ade80;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .container {
            max-width: 1600px;
            margin: 0 auto;
            padding: 20px;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .card {
            background: #16213e;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid #333;
        }
        .card h2 {
            font-size: 14px;
            color: #888;
            text-transform: uppercase;
            margin-bottom: 10px;
        }
        .big-number {
            font-size: 48px;
            font-weight: bold;
            color: #4cc9f0;
        }
        .big-number.success { color: #4ade80; }
        .big-number.warning { color: #fbbf24; }
        .big-number.error { color: #f87171; }
        .sub-stat {
            font-size: 14px;
            color: #888;
            margin-top: 5px;
        }
        .trend {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
        }
        .trend.up { background: rgba(248, 113, 113, 0.2); color: #f87171; }
        .trend.down { background: rgba(74, 222, 128, 0.2); color: #4ade80; }
        .trend.stable { background: rgba(136, 136, 136, 0.2); color: #888; }
        .chart-container {
            height: 300px;
            margin-top: 20px;
        }
        .wide-card {
            grid-column: span 2;
        }
        @media (max-width: 900px) {
            .wide-card { grid-column: span 1; }
        }
        .tool-list {
            max-height: 300px;
            overflow-y: auto;
        }
        .tool-item {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #333;
        }
        .tool-item:last-child { border-bottom: none; }
        .tool-name {
            font-weight: 500;
            color: #ddd;
        }
        .tool-stats {
            text-align: right;
            color: #888;
            font-size: 14px;
        }
        .recommendations {
            margin-top: 10px;
        }
        .rec {
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 10px;
            border-left: 4px solid;
        }
        .rec.high {
            background: rgba(248, 113, 113, 0.1);
            border-color: #f87171;
        }
        .rec.medium {
            background: rgba(251, 191, 36, 0.1);
            border-color: #fbbf24;
        }
        .rec.success {
            background: rgba(74, 222, 128, 0.1);
            border-color: #4ade80;
        }
        .rec-issue {
            font-weight: 600;
            margin-bottom: 4px;
        }
        .rec-action {
            font-size: 14px;
            color: #aaa;
        }
        .event-log {
            max-height: 400px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 12px;
        }
        .event {
            padding: 8px;
            border-bottom: 1px solid #333;
            display: grid;
            grid-template-columns: 100px 200px 80px 80px auto;
            gap: 10px;
        }
        .event.error { background: rgba(248, 113, 113, 0.1); }
        .event-time { color: #888; }
        .event-tool { color: #4cc9f0; }
        .event-status { }
        .event-status.success { color: #4ade80; }
        .event-status.error { color: #f87171; }
        .no-data {
            text-align: center;
            padding: 40px;
            color: #666;
        }
        .last-update {
            font-size: 12px;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>MCP Router Telemetry</h1>
        <div class="status">
            <div class="status-dot"></div>
            <span>Live</span>
            <span class="last-update" id="lastUpdate">-</span>
        </div>
    </div>

    <div class="container">
        <div class="grid">
            <!-- Summary Cards -->
            <div class="card">
                <h2>Total Calls</h2>
                <div class="big-number" id="totalCalls">-</div>
                <div class="sub-stat" id="callsPerMin">- calls/min</div>
            </div>

            <div class="card">
                <h2>Estimated Tokens</h2>
                <div class="big-number" id="totalTokens">-</div>
                <div class="sub-stat" id="avgTokens">- avg/call</div>
            </div>

            <div class="card">
                <h2>Error Rate</h2>
                <div class="big-number" id="errorRate">-</div>
                <div class="sub-stat" id="totalErrors">- total errors</div>
            </div>

            <div class="card">
                <h2>Token Trend</h2>
                <div id="trendIndicator" class="trend stable">Calculating...</div>
                <div class="sub-stat" id="trendDetails">Need more data</div>
            </div>

            <!-- Charts -->
            <div class="card wide-card">
                <h2>Token Usage Over Time</h2>
                <div class="chart-container">
                    <canvas id="tokenChart"></canvas>
                </div>
            </div>

            <div class="card">
                <h2>Top Tools by Tokens</h2>
                <div class="tool-list" id="toolList">
                    <div class="no-data">Loading...</div>
                </div>
            </div>

            <div class="card">
                <h2>Subagent Usage</h2>
                <div class="chart-container">
                    <canvas id="subagentChart"></canvas>
                </div>
            </div>

            <!-- Recommendations -->
            <div class="card wide-card">
                <h2>Optimization Recommendations</h2>
                <div class="recommendations" id="recommendations">
                    <div class="no-data">Analyzing...</div>
                </div>
            </div>

            <!-- Event Log -->
            <div class="card wide-card">
                <h2>Recent Events</h2>
                <div class="event-log" id="eventLog">
                    <div class="no-data">No events yet</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let tokenChart = null;
        let subagentChart = null;

        const TELEMETRY_PATH = '""" + str(TELEMETRY_FILE) + """';

        async function fetchTelemetry() {
            try {
                const response = await fetch('file://' + TELEMETRY_PATH);
                return await response.json();
            } catch (e) {
                // For file:// protocol, use XMLHttpRequest
                return new Promise((resolve, reject) => {
                    const xhr = new XMLHttpRequest();
                    xhr.open('GET', TELEMETRY_PATH, true);
                    xhr.onload = () => {
                        if (xhr.status === 200 || xhr.status === 0) {
                            try {
                                resolve(JSON.parse(xhr.responseText));
                            } catch (e) {
                                resolve(null);
                            }
                        } else {
                            resolve(null);
                        }
                    };
                    xhr.onerror = () => resolve(null);
                    xhr.send();
                });
            }
        }

        function formatNumber(n) {
            if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
            if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
            return n.toString();
        }

        function updateDashboard(data) {
            if (!data) {
                document.getElementById('totalCalls').textContent = 'No data';
                return;
            }

            const agg = data.aggregates || {};
            const totals = agg.totals || {};
            const events = data.events || [];

            // Update summary cards
            document.getElementById('totalCalls').textContent = formatNumber(totals.calls || 0);
            document.getElementById('totalTokens').textContent = formatNumber(totals.tokens_est || 0);

            const avgTokens = totals.calls ? Math.round(totals.tokens_est / totals.calls) : 0;
            document.getElementById('avgTokens').textContent = formatNumber(avgTokens) + ' avg/call';

            const errorRate = totals.calls ? ((totals.errors / totals.calls) * 100).toFixed(1) : 0;
            const errorEl = document.getElementById('errorRate');
            errorEl.textContent = errorRate + '%';
            errorEl.className = 'big-number ' + (errorRate > 10 ? 'error' : errorRate > 5 ? 'warning' : 'success');
            document.getElementById('totalErrors').textContent = (totals.errors || 0) + ' total errors';

            // Calculate trend from events
            if (events.length >= 10) {
                const half = Math.floor(events.length / 2);
                const firstHalf = events.slice(0, half);
                const secondHalf = events.slice(half);

                const firstTokens = firstHalf.reduce((sum, e) => sum + (e.tokens_est || 0), 0) / firstHalf.length;
                const secondTokens = secondHalf.reduce((sum, e) => sum + (e.tokens_est || 0), 0) / secondHalf.length;

                const changePct = firstTokens ? ((secondTokens - firstTokens) / firstTokens * 100) : 0;

                const trendEl = document.getElementById('trendIndicator');
                if (changePct < -10) {
                    trendEl.className = 'trend down';
                    trendEl.textContent = '↓ ' + Math.abs(changePct).toFixed(0) + '% decrease';
                } else if (changePct > 10) {
                    trendEl.className = 'trend up';
                    trendEl.textContent = '↑ ' + changePct.toFixed(0) + '% increase';
                } else {
                    trendEl.className = 'trend stable';
                    trendEl.textContent = '→ Stable';
                }
                document.getElementById('trendDetails').textContent =
                    'Comparing first vs second half of ' + events.length + ' events';
            }

            // Update tool list
            const byTool = agg.by_tool || {};
            const toolList = Object.entries(byTool)
                .map(([name, data]) => ({ name, ...data }))
                .sort((a, b) => (b.tokens || 0) - (a.tokens || 0))
                .slice(0, 10);

            const toolListEl = document.getElementById('toolList');
            if (toolList.length > 0) {
                toolListEl.innerHTML = toolList.map(t => `
                    <div class="tool-item">
                        <div class="tool-name">${t.name}</div>
                        <div class="tool-stats">
                            ${formatNumber(t.tokens || 0)} tokens / ${t.count || 0} calls
                        </div>
                    </div>
                `).join('');
            } else {
                toolListEl.innerHTML = '<div class="no-data">No tool data yet</div>';
            }

            // Update token chart
            updateTokenChart(events);

            // Update subagent chart
            updateSubagentChart(agg.subagents || {});

            // Update recommendations
            updateRecommendations(data);

            // Update event log
            updateEventLog(events);

            // Update timestamp
            document.getElementById('lastUpdate').textContent =
                'Updated: ' + new Date().toLocaleTimeString();
        }

        function updateTokenChart(events) {
            const ctx = document.getElementById('tokenChart').getContext('2d');

            // Group events by time (last 20 data points)
            const buckets = {};
            events.slice(-100).forEach(e => {
                const time = e.ts ? e.ts.substring(11, 16) : 'unknown';
                if (!buckets[time]) buckets[time] = { tokens: 0, calls: 0 };
                buckets[time].tokens += e.tokens_est || 0;
                buckets[time].calls += 1;
            });

            const labels = Object.keys(buckets).slice(-20);
            const tokenData = labels.map(l => buckets[l].tokens);
            const callData = labels.map(l => buckets[l].calls);

            if (tokenChart) {
                tokenChart.data.labels = labels;
                tokenChart.data.datasets[0].data = tokenData;
                tokenChart.data.datasets[1].data = callData;
                tokenChart.update('none');
            } else {
                tokenChart = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [
                            {
                                label: 'Tokens',
                                data: tokenData,
                                borderColor: '#4cc9f0',
                                backgroundColor: 'rgba(76, 201, 240, 0.1)',
                                fill: true,
                                tension: 0.3,
                                yAxisID: 'y'
                            },
                            {
                                label: 'Calls',
                                data: callData,
                                borderColor: '#f72585',
                                backgroundColor: 'transparent',
                                tension: 0.3,
                                yAxisID: 'y1'
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { labels: { color: '#888' } } },
                        scales: {
                            x: { ticks: { color: '#666' }, grid: { color: '#333' } },
                            y: {
                                type: 'linear',
                                position: 'left',
                                ticks: { color: '#4cc9f0' },
                                grid: { color: '#333' }
                            },
                            y1: {
                                type: 'linear',
                                position: 'right',
                                ticks: { color: '#f72585' },
                                grid: { display: false }
                            }
                        }
                    }
                });
            }
        }

        function updateSubagentChart(subagents) {
            const ctx = document.getElementById('subagentChart').getContext('2d');

            const labels = Object.keys(subagents);
            const data = labels.map(l => subagents[l].tokens || 0);

            if (subagentChart) {
                subagentChart.data.labels = labels;
                subagentChart.data.datasets[0].data = data;
                subagentChart.update('none');
            } else if (labels.length > 0) {
                subagentChart = new Chart(ctx, {
                    type: 'doughnut',
                    data: {
                        labels: labels,
                        datasets: [{
                            data: data,
                            backgroundColor: [
                                '#4cc9f0', '#f72585', '#7209b7', '#3a0ca3',
                                '#4361ee', '#4895ef', '#4cc9f0', '#80ffdb'
                            ]
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                position: 'right',
                                labels: { color: '#888', padding: 10 }
                            }
                        }
                    }
                });
            }
        }

        function updateRecommendations(data) {
            const el = document.getElementById('recommendations');
            const agg = data.aggregates || {};
            const totals = agg.totals || {};
            const events = data.events || [];

            const recs = [];

            // Check average tokens
            const avgTokens = totals.calls ? totals.tokens_est / totals.calls : 0;
            if (avgTokens > 5000) {
                recs.push({
                    priority: 'high',
                    issue: 'High average tokens per call (' + formatNumber(avgTokens) + ')',
                    action: 'Consider using more targeted tool calls with smaller scopes'
                });
            }

            // Check error rate
            const errorRate = totals.calls ? (totals.errors / totals.calls) * 100 : 0;
            if (errorRate > 10) {
                recs.push({
                    priority: 'high',
                    issue: 'High error rate (' + errorRate.toFixed(1) + '%)',
                    action: 'Investigate frequent errors - they waste tokens on retries'
                });
            }

            // Check subagent usage
            const subagents = agg.subagents || {};
            const subagentTokens = Object.values(subagents).reduce((sum, s) => sum + (s.tokens || 0), 0);
            const subagentPct = totals.tokens_est ? (subagentTokens / totals.tokens_est) * 100 : 0;
            if (subagentPct > 70) {
                recs.push({
                    priority: 'medium',
                    issue: 'Subagents account for ' + subagentPct.toFixed(0) + '% of tokens',
                    action: 'Consider using lighter-weight agents (Explore instead of general-purpose)'
                });
            }

            // Check trend
            if (events.length >= 10) {
                const half = Math.floor(events.length / 2);
                const firstTokens = events.slice(0, half).reduce((sum, e) => sum + (e.tokens_est || 0), 0) / half;
                const secondTokens = events.slice(half).reduce((sum, e) => sum + (e.tokens_est || 0), 0) / (events.length - half);
                const changePct = firstTokens ? ((secondTokens - firstTokens) / firstTokens * 100) : 0;

                if (changePct < -10) {
                    recs.push({
                        priority: 'success',
                        issue: 'Token usage trending DOWN by ' + Math.abs(changePct).toFixed(0) + '%',
                        action: 'Token-saving measures are working! Keep it up.'
                    });
                } else if (changePct > 10) {
                    recs.push({
                        priority: 'high',
                        issue: 'Token usage trending UP by ' + changePct.toFixed(0) + '%',
                        action: 'Review recent changes - optimization measures may not be working'
                    });
                }
            }

            if (recs.length === 0) {
                el.innerHTML = '<div class="rec success"><div class="rec-issue">All metrics look good!</div><div class="rec-action">Keep monitoring as you make changes.</div></div>';
            } else {
                el.innerHTML = recs.map(r => `
                    <div class="rec ${r.priority}">
                        <div class="rec-issue">${r.issue}</div>
                        <div class="rec-action">${r.action}</div>
                    </div>
                `).join('');
            }
        }

        function updateEventLog(events) {
            const el = document.getElementById('eventLog');
            const recent = events.slice(-50).reverse();

            if (recent.length === 0) {
                el.innerHTML = '<div class="no-data">No events yet</div>';
                return;
            }

            el.innerHTML = recent.map(e => `
                <div class="event ${e.status === 'error' ? 'error' : ''}">
                    <span class="event-time">${e.ts ? e.ts.substring(11, 19) : '-'}</span>
                    <span class="event-tool">${e.tool || '-'}</span>
                    <span class="event-status ${e.status}">${e.status || '-'}</span>
                    <span>${formatNumber(e.tokens_est || 0)} tokens</span>
                    <span>${e.duration_ms || 0}ms</span>
                </div>
            `).join('');
        }

        // Initial load and auto-refresh
        async function refresh() {
            const data = await fetchTelemetry();
            updateDashboard(data);
        }

        // Refresh every 2 seconds
        refresh();
        setInterval(refresh, 2000);
    </script>
</body>
</html>"""

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    DASHBOARD_FILE.write_text(html, encoding='utf-8')

    print(f"Dashboard generated: {DASHBOARD_FILE}")
    print(f"\nOpen in browser:")
    print(f"  file://{DASHBOARD_FILE.absolute()}")

    return DASHBOARD_FILE


def serve_dashboard(port: int = 8765):
    """Start HTTP server for real-time dashboard.

    Serves:
    - / - Dashboard HTML
    - /telemetry - Live telemetry JSON
    """
    import http.server
    import json
    import socketserver
    import webbrowser

    class DashboardHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Suppress request logging

        def do_GET(self):
            if self.path == "/" or self.path == "/index.html":
                # Serve dashboard with correct API endpoint
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()

                # Modify dashboard to use HTTP endpoint
                html = DASHBOARD_FILE.read_text() if DASHBOARD_FILE.exists() else generate_dashboard().read_text()
                html = html.replace(
                    "const TELEMETRY_PATH = '" + str(TELEMETRY_FILE) + "';",
                    "const TELEMETRY_PATH = '/telemetry';"
                )
                html = html.replace(
                    "await fetch('file://' + TELEMETRY_PATH)",
                    "await fetch(TELEMETRY_PATH)"
                )
                # Remove the XHR fallback for file:// since we're using HTTP
                html = html.replace(
                    """} catch (e) {
                // For file:// protocol, use XMLHttpRequest
                return new Promise((resolve, reject) => {
                    const xhr = new XMLHttpRequest();
                    xhr.open('GET', TELEMETRY_PATH, true);
                    xhr.onload = () => {
                        if (xhr.status === 200 || xhr.status === 0) {
                            try {
                                resolve(JSON.parse(xhr.responseText));
                            } catch (e) {
                                resolve(null);
                            }
                        } else {
                            resolve(null);
                        }
                    };
                    xhr.onerror = () => resolve(null);
                    xhr.send();
                });
            }""",
                    """} catch (e) {
                console.error('Fetch error:', e);
                return null;
            }"""
                )
                self.wfile.write(html.encode())

            elif self.path == "/telemetry":
                # Serve live telemetry
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

                if TELEMETRY_FILE.exists():
                    data = TELEMETRY_FILE.read_text()
                else:
                    data = json.dumps({"events": [], "aggregates": {}})

                self.wfile.write(data.encode())
            else:
                self.send_error(404)

    # Generate dashboard first
    generate_dashboard()

    with socketserver.TCPServer(("", port), DashboardHandler) as httpd:
        url = f"http://localhost:{port}"
        print(f"\n{'='*50}")
        print(f"  MCP Router Dashboard Server")
        print(f"{'='*50}")
        print(f"\n  Dashboard: {url}")
        print(f"  Telemetry: {url}/telemetry")
        print(f"\n  Press Ctrl+C to stop")
        print(f"{'='*50}\n")

        # Open browser
        try:
            webbrowser.open(url)
        except:
            pass

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")


def main():
    if "--serve" in sys.argv:
        port = 8765
        # Check for port argument
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        serve_dashboard(port)
    else:
        path = generate_dashboard()
        print(f"\nNote: For real-time updates, run with --serve flag:")
        print(f"  python3 {__file__} --serve")

        # Try to open in browser
        import webbrowser
        try:
            webbrowser.open(f"file://{path.absolute()}")
        except:
            pass


if __name__ == "__main__":
    main()
