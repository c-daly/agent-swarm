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
METRICS_HISTORY_FILE = STATE_DIR / "metrics_history.json"
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
        .nav-bar {
            background: #16213e;
            border-bottom: 1px solid #333;
            padding: 0 40px;
            position: sticky;
            top: 0;
            z-index: 100;
        }
        .nav-links {
            display: flex;
            gap: 0;
            max-width: 1600px;
            margin: 0 auto;
        }
        .nav-links a {
            color: #888;
            text-decoration: none;
            padding: 12px 20px;
            font-size: 14px;
            border-bottom: 2px solid transparent;
            transition: all 0.2s;
        }
        .nav-links a:hover {
            color: #4cc9f0;
            background: rgba(76, 201, 240, 0.1);
        }
        .nav-links a.active {
            color: #4cc9f0;
            border-bottom-color: #4cc9f0;
        }
        .filters-bar {
            background: #0f0f1e;
            padding: 15px 40px;
            border-bottom: 1px solid #333;
            display: flex;
            gap: 20px;
            align-items: center;
            flex-wrap: wrap;
        }
        .filter-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .filter-group label {
            color: #888;
            font-size: 13px;
        }
        .filter-group select {
            background: #16213e;
            color: #eee;
            border: 1px solid #333;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 13px;
            cursor: pointer;
        }
        .filter-group select:hover {
            border-color: #4cc9f0;
        }
        .chart-links {
            display: flex;
            gap: 10px;
            margin-left: auto;
        }
        .chart-link-btn {
            background: #16213e;
            color: #4cc9f0;
            border: 1px solid #333;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 12px;
            text-decoration: none;
            transition: all 0.2s;
        }
        .chart-link-btn:hover {
            background: #4cc9f0;
            color: #1a1a2e;
        }
        .section-title {
            font-size: 18px;
            color: #4cc9f0;
            margin: 30px 0 15px 0;
            padding-bottom: 10px;
            border-bottom: 1px solid #333;
        }
        .section-title:first-of-type {
            margin-top: 0;
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
        .alert-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .alert-item {
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 13px;
        }
        .alert-item.ok {
            background: rgba(74, 222, 128, 0.1);
            border-left: 3px solid #4ade80;
            color: #4ade80;
        }
        .alert-item.warning {
            background: rgba(251, 191, 36, 0.1);
            border-left: 3px solid #fbbf24;
            color: #fbbf24;
        }
        .alert-item.error {
            background: rgba(248, 113, 113, 0.1);
            border-left: 3px solid #f87171;
            color: #f87171;
        }
        .metric-row {
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            border-bottom: 1px solid #333;
        }
        .metric-label { color: #888; }
        .metric-value { color: #4cc9f0; font-weight: bold; }
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

    <nav class="nav-bar">
        <div class="nav-links">
            <a href="#overview" class="active">Overview</a>
            <a href="#charts">Charts</a>
            <a href="#analysis">Analysis</a>
            <a href="#logs">Logs</a>
        </div>
    </nav>

    <div class="filters-bar">
        <div class="filter-group">
            <label>Time Range:</label>
            <select id="filterTimeRange" onchange="applyFilters()">
                <option value="1h">Last 1 hour</option>
                <option value="6h">Last 6 hours</option>
                <option value="24h" selected>Last 24 hours</option>
                <option value="7d">Last 7 days</option>
                <option value="all">All time</option>
            </select>
        </div>
        <div class="filter-group">
            <label>Tool:</label>
            <select id="filterTool" onchange="applyFilters()">
                <option value="all">All tools</option>
            </select>
        </div>
        <div class="filter-group">
            <label>Backend:</label>
            <select id="filterBackend" onchange="applyFilters()">
                <option value="all">All backends</option>
            </select>
        </div>
        <div class="chart-links">
            <a href="charts/telemetry.html" class="chart-link-btn">📡 Telemetry</a>
            <a href="charts/latency.html" class="chart-link-btn">⏱️ Latency</a>
            <a href="charts/activity_heatmap.html" class="chart-link-btn">📅 Heatmap</a>
            <a href="charts/token_trend.html" class="chart-link-btn">📈 Tokens</a>
            <a href="charts/tool_usage.html" class="chart-link-btn">🔧 Tools</a>
            <a href="charts/dashboard.html" class="chart-link-btn">📊 All Charts</a>
        </div>
    </div>

    <div class="container">
        <h3 id="overview" class="section-title">Overview</h3>
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

        </div>

        <h3 id="charts" class="section-title">Charts</h3>
        <div class="grid">
            <div class="card wide-card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <h2>Token Usage Over Time</h2>
                    <div class="filter-group" style="margin: 0;">
                        <label>Show:</label>
                        <select id="tokenChartRange" onchange="updateTokenChartRange()">
                            <option value="7">Last 7 days</option>
                            <option value="14" selected>Last 14 days</option>
                            <option value="30">Last 30 days</option>
                            <option value="all">All data</option>
                        </select>
                    </div>
                </div>
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

        </div>

        <h3 id="analysis" class="section-title">Analysis</h3>
        <div class="grid">
            <div class="card">
                <h2>Summary Effectiveness</h2>
                <div class="big-number" id="drillDownRate">-</div>
                <div class="sub-stat">drill-down rate</div>
                <div class="sub-stat" id="fullRetrievals">- full retrievals</div>
            </div>

            <!-- Sequence Alerts -->
            <div class="card">
                <h2>Sequence Alerts</h2>
                <div class="alert-list" id="sequenceAlerts">
                    <div class="no-data">Analyzing patterns...</div>
                </div>
            </div>

            <!-- Concurrency Stats -->
            <div class="card">
                <h2>Concurrency</h2>
                <div class="big-number" id="peakInFlight">-</div>
                <div class="sub-stat">peak in-flight</div>
                <div class="sub-stat" id="backpressureEvents">- backpressure events</div>
            </div>

        </div>

        <h3 id="logs" class="section-title">Logs & Recommendations</h3>
        <div class="grid">
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

        // Navigation handling
        document.querySelectorAll('.nav-links a').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const targetId = link.getAttribute('href').slice(1);
                const target = document.getElementById(targetId);
                if (target) {
                    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    // Update active state
                    document.querySelectorAll('.nav-links a').forEach(l => l.classList.remove('active'));
                    link.classList.add('active');
                }
            });
        });

        // Update nav on scroll
        window.addEventListener('scroll', () => {
            const sections = ['overview', 'charts', 'analysis', 'logs'];
            let current = sections[0];
            for (const id of sections) {
                const el = document.getElementById(id);
                if (el && el.getBoundingClientRect().top <= 100) {
                    current = id;
                }
            }
            document.querySelectorAll('.nav-links a').forEach(link => {
                link.classList.toggle('active', link.getAttribute('href') === '#' + current);
            });
        });

        // Filter state
        let currentFilters = {
            timeRange: '24h',
            tool: 'all',
            backend: 'all'
        };
        let allTelemetryData = null;
        let tokenChartDays = 14; // Chart-specific range

        function updateTokenChartRange() {
            const value = document.getElementById('tokenChartRange').value;
            tokenChartDays = value === 'all' ? Infinity : parseInt(value);
            if (allTelemetryData) {
                const filtered = filterData(allTelemetryData);
                const events = filtered.events || [];
                updateTokenChart(events, filtered.daily_summaries || {}, filtered.historical_timeline || []);
            }
        }

        function populateFilterDropdowns(data) {
            // Populate tools dropdown
            const toolSelect = document.getElementById('filterTool');
            const tools = new Set();
            if (data.aggregates?.by_tool) {
                Object.keys(data.aggregates.by_tool).forEach(t => tools.add(t));
            }
            if (data.events) {
                data.events.forEach(e => e.tool && tools.add(e.tool));
            }
            const sortedTools = [...tools].sort();
            toolSelect.innerHTML = '<option value="all">All tools</option>' +
                sortedTools.map(t => `<option value="${t}">${t}</option>`).join('');

            // Populate backends dropdown
            const backendSelect = document.getElementById('filterBackend');
            const backends = new Set();
            if (data.aggregates?.by_backend) {
                Object.keys(data.aggregates.by_backend).forEach(b => backends.add(b));
            }
            if (data.events) {
                data.events.forEach(e => e.backend && backends.add(e.backend));
            }
            const sortedBackends = [...backends].sort();
            backendSelect.innerHTML = '<option value="all">All backends</option>' +
                sortedBackends.map(b => `<option value="${b}">${b}</option>`).join('');
        }

        function applyFilters() {
            currentFilters.timeRange = document.getElementById('filterTimeRange').value;
            currentFilters.tool = document.getElementById('filterTool').value;
            currentFilters.backend = document.getElementById('filterBackend').value;
            if (allTelemetryData) {
                updateDashboard(filterData(allTelemetryData));
            }
        }

        function filterData(data) {
            if (!data) return data;
            const filtered = JSON.parse(JSON.stringify(data)); // Deep clone

            // Time filter
            const now = Date.now();
            const ranges = {
                '1h': 60 * 60 * 1000,
                '6h': 6 * 60 * 60 * 1000,
                '24h': 24 * 60 * 60 * 1000,
                '7d': 7 * 24 * 60 * 60 * 1000,
                'all': Infinity
            };
            const cutoff = now - (ranges[currentFilters.timeRange] || ranges['24h']);
            const cutoffDate = new Date(cutoff).toISOString().substring(0, 10);

            // Filter events by time, tool, and backend
            if (filtered.events) {
                filtered.events = filtered.events.filter(e => {
                    const ts = new Date(e.timestamp || e.ts).getTime();
                    if (ts < cutoff) return false;
                    if (currentFilters.tool !== 'all' && e.tool !== currentFilters.tool) return false;
                    if (currentFilters.backend !== 'all' && e.backend !== currentFilters.backend) return false;
                    return true;
                });
            }

            // Filter daily_summaries by date range
            if (filtered.daily_summaries && currentFilters.timeRange !== 'all') {
                const filteredSummaries = {};
                Object.entries(filtered.daily_summaries).forEach(([date, summary]) => {
                    if (date >= cutoffDate) {
                        filteredSummaries[date] = summary;
                    }
                });
                filtered.daily_summaries = filteredSummaries;
            }

            // Filter historical_timeline by date range
            if (filtered.historical_timeline && currentFilters.timeRange !== 'all') {
                filtered.historical_timeline = filtered.historical_timeline.filter(h => {
                    return h.date >= cutoffDate;
                });
            }

            return filtered;
        }

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
            document.getElementById('totalTokens').textContent = formatNumber(totals.tokens || totals.tokens_est || 0);

            const avgTokens = totals.calls ? Math.round((totals.tokens || totals.tokens_est || 0) / totals.calls) : 0;
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

                const firstTokens = firstHalf.reduce((sum, e) => sum + (e.response_size || e.tokens_est || 0), 0) / firstHalf.length;
                const secondTokens = secondHalf.reduce((sum, e) => sum + (e.response_size || e.tokens_est || 0), 0) / secondHalf.length;

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

            // Update token chart (use daily_summaries as primary, with historical_timeline fallback)
            updateTokenChart(events, data.daily_summaries || {}, data.historical_timeline || []);

            // Update subagent chart
            updateSubagentChart(agg.subagents || {});

            // Update recommendations
            updateRecommendations(data);

            // Update new metrics
            updateSummaryEffectiveness(data);
            updateSequenceAlerts(data);
            updateConcurrency(data);

            // Update event log
            updateEventLog(events);

            // Update timestamp
            document.getElementById('lastUpdate').textContent =
                'Updated: ' + new Date().toLocaleTimeString();
        }

        function updateTokenChart(events, dailySummaries, historicalTimeline) {
            const ctx = document.getElementById('tokenChart').getContext('2d');

            // Combine all data sources: daily_summaries (primary), historical_timeline, and events
            const allDataPoints = {};

            // 1. Add daily_summaries data (primary source - contains imported historical data)
            if (dailySummaries && typeof dailySummaries === 'object') {
                Object.entries(dailySummaries).forEach(([date, summary]) => {
                    if (date && date !== 'unknown') {
                        allDataPoints[date] = {
                            tokens: summary.tokens || 0,
                            calls: summary.calls || 0,
                            source: 'daily_summaries'
                        };
                    }
                });
            }

            // 2. Add historical timeline data (fallback for older format)
            if (historicalTimeline && historicalTimeline.length > 0) {
                historicalTimeline.forEach(h => {
                    if (h.date && !allDataPoints[h.date]) {
                        allDataPoints[h.date] = {
                            tokens: h.tokens || 0,
                            calls: h.events || 0,
                            source: 'historical_timeline'
                        };
                    }
                });
            }

            // 3. Add current session events grouped by date
            const eventBuckets = {};
            events.forEach(e => {
                const date = e.ts ? e.ts.substring(0, 10) : (e.timestamp ? e.timestamp.substring(0, 10) : 'unknown');
                if (date && date !== 'unknown') {
                    if (!eventBuckets[date]) eventBuckets[date] = { tokens: 0, calls: 0 };
                    eventBuckets[date].tokens += e.response_size || e.tokens_est || 0;
                    eventBuckets[date].calls += 1;
                }
            });

            // Merge event data into allDataPoints (add to existing or create new)
            Object.entries(eventBuckets).forEach(([date, data]) => {
                if (allDataPoints[date]) {
                    // If source is daily_summaries, don't double-count (it already includes today's events)
                    // Only add if this is historical_timeline or missing
                    if (allDataPoints[date].source !== 'daily_summaries') {
                        allDataPoints[date].tokens += data.tokens;
                        allDataPoints[date].calls += data.calls;
                    }
                } else {
                    allDataPoints[date] = { tokens: data.tokens, calls: data.calls, source: 'events' };
                }
            });

            // Convert to array, sort by date, and take based on filter (up to 30 days for 'all')
            const pointsArray = Object.entries(allDataPoints)
                .map(([date, data]) => ({ label: date, ...data }))
                .sort((a, b) => a.label.localeCompare(b.label));
            
            // Use chart-specific range (tokenChartDays) - controlled by its own dropdown
            const maxPoints = tokenChartDays === Infinity ? pointsArray.length : tokenChartDays;
            const recentPoints = pointsArray.slice(-maxPoints);

            const labels = recentPoints.map(p => p.label.substring(5)); // MM-DD format
            const tokenData = recentPoints.map(p => p.tokens);
            const callData = recentPoints.map(p => p.calls);

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

        function updateSummaryEffectiveness(data) {
            const agg = data.aggregates || {};
            const sequences = agg.sequences || data.sequences || {};
            const effectiveness = sequences.summary_effectiveness || {};
            
            // Drill-down rate
            const drillDownRate = effectiveness.drill_down_rate || 0;
            const drillDownEl = document.getElementById('drillDownRate');
            drillDownEl.textContent = (drillDownRate * 100).toFixed(0) + '%';
            drillDownEl.className = 'big-number ' + (drillDownRate > 0.5 ? 'warning' : 'success');
            
            // Full retrievals
            const fullRetrievals = agg.full_retrievals || 0;
            document.getElementById('fullRetrievals').textContent = fullRetrievals + ' full retrievals';
        }

        function updateSequenceAlerts(data) {
            const el = document.getElementById('sequenceAlerts');
            const agg = data.aggregates || {};
            const sequences = agg.sequences || data.sequences || {};
            const alerts = [];
            
            // Check for thrashing
            if (sequences.thrashing && sequences.thrashing.detected) {
                alerts.push({
                    level: 'error',
                    text: '⚠️ Thrashing detected: ' + (sequences.thrashing.pattern || 'repeated patterns')
                });
            }
            
            // Check for error cascades
            if (sequences.error_cascades && sequences.error_cascades.count > 0) {
                alerts.push({
                    level: 'error',
                    text: '🔴 Error cascade: ' + sequences.error_cascades.count + ' consecutive failures'
                });
            }
            
            // Check for retries
            if (sequences.retries && sequences.retries.count > 0) {
                alerts.push({
                    level: 'warning',
                    text: '🔄 Retries detected: ' + sequences.retries.count + ' error→retry sequences'
                });
            }
            
            // Check for repeats
            if (sequences.repeats && sequences.repeats.count > 3) {
                alerts.push({
                    level: 'warning',
                    text: '🔁 Repeated calls: ' + sequences.repeats.count + ' identical requests'
                });
            }
            
            // Drill-downs info
            if (sequences.drill_downs && sequences.drill_downs.count > 0) {
                alerts.push({
                    level: 'ok',
                    text: '📥 ' + sequences.drill_downs.count + ' drill-downs (summary→detail)'
                });
            }
            
            if (alerts.length === 0) {
                el.innerHTML = '<div class="alert-item ok">✓ No problematic patterns detected</div>';
            } else {
                el.innerHTML = alerts.map(a => 
                    '<div class="alert-item ' + a.level + '">' + a.text + '</div>'
                ).join('');
            }
        }

        function updateConcurrency(data) {
            const agg = data.aggregates || {};
            const conc = agg.concurrency || {};
            
            // Peak in-flight
            const peakEl = document.getElementById('peakInFlight');
            const peak = conc.peak_in_flight || 0;
            peakEl.textContent = peak;
            peakEl.className = 'big-number ' + (peak > 8 ? 'warning' : 'success');
            
            // Backpressure events
            const backpressure = conc.backpressure_events || 0;
            const bpEl = document.getElementById('backpressureEvents');
            bpEl.textContent = backpressure + ' backpressure events';
            if (backpressure > 0) {
                bpEl.style.color = '#fbbf24';
            }
        }

        function updateRecommendations(data) {
            const el = document.getElementById('recommendations');
            const agg = data.aggregates || {};
            const totals = agg.totals || {};
            const events = data.events || [];

            const recs = [];

            // Check average tokens
            const avgTokens = totals.calls ? (totals.tokens || totals.tokens_est || 0) / totals.calls : 0;
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
            const subagentPct = (totals.tokens || totals.tokens_est) ? (subagentTokens / (totals.tokens || totals.tokens_est)) * 100 : 0;
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
                const firstTokens = events.slice(0, half).reduce((sum, e) => sum + (e.response_size || e.tokens_est || 0), 0) / half;
                const secondTokens = events.slice(half).reduce((sum, e) => sum + (e.response_size || e.tokens_est || 0), 0) / (events.length - half);
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
                    <span>${formatNumber(e.response_size || e.tokens_est || 0)} chars</span>
                    <span>${e.duration_ms || 0}ms</span>
                </div>
            `).join('');
        }

        // Initial load and auto-refresh
        let filtersPopulated = false;

        async function refresh() {
            const data = await fetchTelemetry();
            allTelemetryData = data;

            if (!filtersPopulated && data) {
                populateFilterDropdowns(data);
                filtersPopulated = true;
            }
            updateDashboard(filterData(data));
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

                # Always regenerate dashboard to pick up code changes
                generate_dashboard()
                html = DASHBOARD_FILE.read_text()
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

            elif self.path == "/history":
                # Serve historical metrics
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

                if METRICS_HISTORY_FILE.exists():
                    data = METRICS_HISTORY_FILE.read_text()
                else:
                    data = json.dumps({"snapshots": []})

                self.wfile.write(data.encode())
            else:
                # Serve static files from STATE_DIR (charts, etc.)
                # Strip leading slash and resolve path
                rel_path = self.path.lstrip("/")
                file_path = STATE_DIR / rel_path

                # Security: ensure path is within STATE_DIR
                try:
                    file_path = file_path.resolve()
                    if not str(file_path).startswith(str(STATE_DIR.resolve())):
                        self.send_error(403, "Forbidden")
                        return
                except:
                    self.send_error(400, "Bad request")
                    return

                if file_path.is_file():
                    # Determine content type
                    content_types = {
                        ".html": "text/html",
                        ".css": "text/css",
                        ".js": "application/javascript",
                        ".json": "application/json",
                        ".png": "image/png",
                        ".svg": "image/svg+xml",
                    }
                    ext = file_path.suffix.lower()
                    content_type = content_types.get(ext, "application/octet-stream")

                    self.send_response(200)
                    self.send_header("Content-type", content_type)
                    self.end_headers()

                    if ext in [".png"]:
                        self.wfile.write(file_path.read_bytes())
                    else:
                        self.wfile.write(file_path.read_text().encode())
                else:
                    self.send_error(404, f"File not found: {rel_path}")

    # Generate dashboard first
    generate_dashboard()

    with socketserver.TCPServer(("", port), DashboardHandler) as httpd:
        url = f"http://localhost:{port}"
        print(f"\n{'='*50}")
        print(f"  MCP Router Dashboard Server")
        print(f"{'='*50}")
        print(f"\n  Dashboard: {url}")
        print(f"  Charts:    {url}/charts/dashboard.html")
        print(f"  Telemetry: {url}/telemetry")
        print(f"  History:   {url}/history")
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
