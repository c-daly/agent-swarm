#!/usr/bin/env python3
"""
Real-time telemetry dashboard for MCP router.

Generates an auto-refreshing HTML dashboard that reads from telemetry.json.

Usage:
    python3 realtime_dashboard.py           # Generate and open dashboard
    python3 realtime_dashboard.py --serve   # Start live server with WebSocket updates
"""

import sys
import json
from pathlib import Path

# Add project root and lib to path for service imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "lib"))

from lib.telemetry_service import TelemetryService

STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"
TELEMETRY_FILE = STATE_DIR / "telemetry.json"  # Keep for fallback
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

            <div class="card">
                <h2>Summarization</h2>
                <div class="big-number" id="summarizationRate">-</div>
                <div class="sub-stat" id="summarizationDetails">- offered / - accepted</div>
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

        <h3 id="sessions" class="section-title">Sessions</h3>
        <div class="grid">
            <div class="card wide-card">
                <h2>Recent Sessions</h2>
                <div class="tool-list" id="sessionsList">
                    <div class="no-data">Loading sessions...</div>
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
            const sections = ['overview', 'charts', 'sessions', 'analysis', 'logs'];
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
            timeRange: '24h'
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
            // Tool/backend dropdowns removed - v2 telemetry doesn't support per-event filtering
            // Time range dropdown is static HTML, no population needed
        }

        function applyFilters() {
            currentFilters.timeRange = document.getElementById('filterTimeRange').value;
            if (allTelemetryData) {
                updateDashboard(filterData(allTelemetryData));
            }
        }

        function filterData(data) {
            if (!data) return data;
            const filtered = JSON.parse(JSON.stringify(data)); // Deep clone

            // Time filter only (tool/backend filters removed - not supported in v2)
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

            // Recalculate totals from filtered daily_summaries
            if (currentFilters.timeRange !== 'all' && filtered.daily_summaries) {
                const newTotals = { calls: 0, tokens: 0, errors: 0 };
                Object.values(filtered.daily_summaries).forEach(summary => {
                    newTotals.calls += summary.calls || 0;
                    newTotals.tokens += summary.tokens || 0;
                    newTotals.errors += summary.errors || 0;
                });
                filtered.aggregates = filtered.aggregates || {};
                filtered.aggregates.totals = newTotals;
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

        // Normalize v3 telemetry schema (DuckDB-based)
        function normalizeV3Data(data) {
            if (!data) return data;
            if (data.schema_version !== 3) {
                return data;
            }

            const agg = data.aggregates || {};
            
            // Build normalized structure
            data.aggregates.totals = {
                calls: agg.total_calls || 0,
                tokens: agg.total_tokens || 0,
                sessions: agg.total_sessions || 0,
                errors: 0
            };
            
            // by_tool already in correct format: {tool: {count, tokens}}
            data.aggregates.by_tool = agg.by_tool || {};
            
            // by_agent_type -> subagents
            data.aggregates.subagents = agg.by_agent_type || {};
            
            // Empty placeholders for features v3 doesn't have yet
            data.aggregates.by_backend = {};
            
            // Use summarization stats from API (router tracks these)
            const summ = agg.summarization || {};
            data.aggregates.summarization = {
                offered: summ.offered || 0,
                accepted: summ.offered || 0,  // Router always accepts summaries
                rejected: 0,
                full_content_requests: summ.full_requested || 0,
                tokens_before: 0,
                tokens_after: 0
            };
            data.daily_summaries = {};
            data.historical_timeline = [];
            data.sessions = [];
            
            // Compute sequences.summary_effectiveness from summarization data
            const offered = summ.offered || 0;
            const fullRequested = summ.full_requested || 0;
            const sequencesData = {
                summary_effectiveness: {
                    drill_down_rate: offered > 0 ? fullRequested / offered : null,
                    offered: offered,
                    full_requested: fullRequested
                }
            };
            data.sequences = sequencesData;
            data.aggregates.sequences = sequencesData;

            return data;
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

            // Calculate trend using 7-day moving average comparison
            const timeline = data.historical_timeline || [];
            const trendEl = document.getElementById('trendIndicator');
            const trendDetailsEl = document.getElementById('trendDetails');
            
            if (timeline.length >= 7) {
                // 7-day moving average: compare last 7 days vs previous 7 days
                const recent7 = timeline.slice(-7);
                const previous7 = timeline.slice(-14, -7);
                
                const recentAvg = recent7.reduce((sum, d) => sum + (d.tokens || 0), 0) / recent7.length;
                
                if (previous7.length >= 7) {
                    const previousAvg = previous7.reduce((sum, d) => sum + (d.tokens || 0), 0) / previous7.length;
                    const changePct = previousAvg ? ((recentAvg - previousAvg) / previousAvg * 100) : 0;

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
                    trendDetailsEl.textContent = '7-day moving avg: ' + Math.round(recentAvg).toLocaleString() + ' tokens/day';
                } else {
                    // Not enough data for comparison, just show current average
                    trendEl.className = 'trend stable';
                    trendEl.textContent = '→ ' + Math.round(recentAvg).toLocaleString() + '/day';
                    trendDetailsEl.textContent = '7-day avg (need 14 days for trend)';
                }
            } else if (timeline.length >= 2) {
                // Less than 7 days - use simple comparison of available data
                const recentAvg = timeline.slice(-Math.ceil(timeline.length/2)).reduce((sum, d) => sum + (d.tokens || 0), 0) / Math.ceil(timeline.length/2);
                trendEl.className = 'trend stable';
                trendEl.textContent = '→ ' + Math.round(recentAvg).toLocaleString() + '/day';
                trendDetailsEl.textContent = 'Need 7+ days for trend';
            } else if (timeline.length === 1) {
                trendEl.className = 'trend stable';
                trendEl.textContent = '→ First day';
                trendDetailsEl.textContent = 'Need more days for trend';
            } else {
                trendEl.className = 'trend stable';
                trendEl.textContent = '→ No data';
                trendDetailsEl.textContent = '';
            }

            // Update tool list - sort by call count (v2 schema doesn't have per-tool tokens)
            const byTool = agg.by_tool || {};
            const toolList = Object.entries(byTool)
                .map(([name, data]) => ({ name, ...data }))
                .sort((a, b) => (b.count || 0) - (a.count || 0))
                .slice(0, 10);

            const toolListEl = document.getElementById('toolList');
            if (toolList.length > 0) {
                toolListEl.innerHTML = toolList.map(t => `
                    <div class="tool-item">
                        <div class="tool-name">${t.name}</div>
                        <div class="tool-stats">
                            ${formatNumber(t.count || 0)} calls
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
            updateSessionsTable(data.sessions || []);

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
            
            // Calculate 7-day moving average for tokens
            const movingAvg = tokenData.map((_, i, arr) => {
                const start = Math.max(0, i - 6);
                const window = arr.slice(start, i + 1);
                return Math.round(window.reduce((a, b) => a + b, 0) / window.length);
            });

            if (tokenChart) {
                tokenChart.data.labels = labels;
                tokenChart.data.datasets[0].data = tokenData;
                tokenChart.data.datasets[1].data = movingAvg;
                tokenChart.data.datasets[2].data = callData;
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
                                borderColor: 'rgba(76, 201, 240, 0.4)',
                                backgroundColor: 'rgba(76, 201, 240, 0.1)',
                                fill: true,
                                tension: 0.3,
                                yAxisID: 'y',
                                borderWidth: 1
                            },
                            {
                                label: '7-day Avg',
                                data: movingAvg,
                                borderColor: '#4cc9f0',
                                backgroundColor: 'transparent',
                                fill: false,
                                tension: 0.4,
                                yAxisID: 'y',
                                borderWidth: 2
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

            // Drill-down rate (only show % if we have summarization data)
            const summarization = agg.summarization || {};
            const offered = summarization.offered || 0;
            const drillDownRate = effectiveness.drill_down_rate;
            const drillDownEl = document.getElementById('drillDownRate');
            if (drillDownEl) {
                if (offered > 0 && drillDownRate !== undefined && drillDownRate !== null) {
                    drillDownEl.textContent = (drillDownRate * 100).toFixed(0) + '%';
                    drillDownEl.className = 'big-number ' + (drillDownRate > 0.5 ? 'warning' : 'success');
                } else {
                    drillDownEl.textContent = 'N/A';
                    drillDownEl.className = 'big-number';
                }
            }
            
            // Full retrievals
            const fullRetrievals = agg.full_retrievals || 0;
            const fullRetrievalsEl = document.getElementById('fullRetrievals');
            if (fullRetrievalsEl) {
                fullRetrievalsEl.textContent = fullRetrievals + ' full retrievals';
            }

            // Update summarization card (from v2 normalized data - reuse summarization/offered from above)
            const accepted = summarization.accepted || 0;
            const fullContentRequests = summarization.full_content_requests || 0;
            const tokensBefore = summarization.tokens_before || 0;
            const tokensAfter = summarization.tokens_after || 0;

            const summarizationRateEl = document.getElementById('summarizationRate');
            const summarizationDetailsEl = document.getElementById('summarizationDetails');

            if (summarizationRateEl) {
                if (offered > 0) {
                    const acceptRate = (accepted / offered * 100).toFixed(0);
                    summarizationRateEl.textContent = acceptRate + '%';
                    // Green if high acceptance, yellow if moderate, red if low
                    summarizationRateEl.className = 'big-number ' + 
                        (acceptRate >= 70 ? 'success' : acceptRate >= 40 ? 'warning' : 'error');
                } else {
                    summarizationRateEl.textContent = 'N/A';
                    summarizationRateEl.className = 'big-number';
                }
            }

            if (summarizationDetailsEl) {
                if (offered > 0) {
                    const savings = tokensBefore > 0 ? ((tokensBefore - tokensAfter) / tokensBefore * 100).toFixed(0) : 0;
                    summarizationDetailsEl.textContent = `${offered} offered / ${accepted} accepted` + 
                        (fullContentRequests > 0 ? ` / ${fullContentRequests} full requests` : '') +
                        (tokensBefore > 0 ? ` (${savings}% saved)` : '');
                } else {
                    summarizationDetailsEl.textContent = 'No summarizations yet';
                }
            }
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

        function formatDuration(startTime, endTime) {
            if (!startTime || !endTime) return 'N/A';
            const start = new Date(startTime).getTime();
            const end = new Date(endTime).getTime();
            const durationMs = end - start;
            
            if (durationMs < 0) return 'N/A';
            
            const seconds = Math.floor(durationMs / 1000);
            const minutes = Math.floor(seconds / 60);
            const hours = Math.floor(minutes / 60);
            
            if (hours > 0) {
                const remainingMinutes = minutes % 60;
                return hours + 'h ' + remainingMinutes + 'm';
            } else if (minutes > 0) {
                const remainingSeconds = seconds % 60;
                return minutes + 'm ' + remainingSeconds + 's';
            } else {
                return seconds + 's';
            }
        }

        function updateSessionsTable(sessions) {
            const el = document.getElementById('sessionsList');
            
            if (!sessions || sessions.length === 0) {
                el.innerHTML = '<div class="no-data">No sessions recorded yet</div>';
                return;
            }
            
            // Take max 20 most recent sessions
            const recentSessions = sessions.slice(0, 20);
            
            el.innerHTML = recentSessions.map(s => {
                const sessionIdShort = s.id.substring(0, 8);
                const duration = formatDuration(s.start_time, s.end_time);
                const dateDisplay = s.date || 'Unknown';
                
                return `
                    <div class="tool-item">
                        <div class="tool-name">${sessionIdShort}... (${dateDisplay})</div>
                        <div class="tool-stats">
                            ${formatNumber(s.tokens || 0)} tokens / ${s.calls || 0} calls / ${duration}
                        </div>
                    </div>
                `;
            }).join('');
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

            // Check subagent usage (skip if 100% - means we only have subagent data, not a problem)
            const subagents = agg.subagents || {};
            const subagentTokens = Object.values(subagents).reduce((sum, s) => sum + (s.tokens || 0), 0);
            const subagentPct = (totals.tokens || totals.tokens_est) ? (subagentTokens / (totals.tokens || totals.tokens_est)) * 100 : 0;
            if (subagentPct > 70 && subagentPct < 100) {
                recs.push({
                    priority: 'medium',
                    issue: 'Subagents account for ' + subagentPct.toFixed(0) + '% of tokens',
                    action: 'Consider using lighter-weight agents (Explore instead of general-purpose)'
                });
            }

            // Check trend using rolling window (last 50 events vs previous 50)
            if (events.length >= 100) {
                const recent50 = events.slice(-50);
                const previous50 = events.slice(-100, -50);
                const recentAvg = recent50.reduce((sum, e) => sum + (e.response_size || e.tokens_est || 0), 0) / 50;
                const previousAvg = previous50.reduce((sum, e) => sum + (e.response_size || e.tokens_est || 0), 0) / 50;
                const changePct = previousAvg ? ((recentAvg - previousAvg) / previousAvg * 100) : 0;

                if (changePct < -10) {
                    recs.push({
                        priority: 'success',
                        issue: 'Token usage trending DOWN by ' + Math.abs(changePct).toFixed(0) + '% (50-event moving avg)',
                        action: 'Token-saving measures are working! Keep it up.'
                    });
                } else if (changePct > 10) {
                    recs.push({
                        priority: 'high',
                        issue: 'Token usage trending UP by ' + changePct.toFixed(0) + '% (50-event moving avg)',
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

        // Initial load and auto-refresh
        let filtersPopulated = false;

        async function refresh() {
            const rawData = await fetchTelemetry();
            const data = normalizeV3Data(rawData);
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

                try:
                    # Query DuckDB via TelemetryService
                    service = TelemetryService(data_dir=str(STATE_DIR))
                    store = service._store
                    
                    # Get recent events
                    events = []
                    recent = store.conn.execute("""
                        SELECT timestamp, tool, backend, status, duration_ms,
                               COALESCE(input_tokens, 0) as input_tokens,
                               COALESCE(output_tokens, 0) as output_tokens,
                               session_id
                        FROM events
                        ORDER BY timestamp DESC
                        LIMIT 500
                    """).fetchall()
                    for row in recent:
                        events.append({
                            "ts": str(row[0]),
                            "tool": row[1],
                            "backend": row[2] or "native",
                            "status": row[3] or "success",
                            "duration_ms": row[4] or 0,
                            "tokens": (row[5] or 0) + (row[6] or 0),
                            "session_id": row[7],
                        })
                    
                    # Get aggregates
                    totals = store.conn.execute("""
                        SELECT 
                            COUNT(*) as calls,
                            SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)) as tokens,
                            COUNT(DISTINCT session_id) as sessions
                        FROM events
                    """).fetchone()
                    
                    # Get by_tool breakdown
                    by_tool_rows = store.conn.execute("""
                        SELECT tool,
                               COUNT(*) as count,
                               SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)) as tokens
                        FROM events
                        GROUP BY tool
                        ORDER BY tokens DESC
                    """).fetchall()
                    by_tool = {row[0]: {"count": row[1], "tokens": row[2]} for row in by_tool_rows}
                    
                    # Get by_subagent breakdown (agent_type)
                    # Note: 'at' is a reserved keyword in DuckDB (AT TIME ZONE), so use 'agt' alias
                    by_subagent_rows = store.conn.execute("""
                        SELECT COALESCE(e.agent_type, agt.agent_type, 'main') as agent_type,
                               COUNT(*) as count,
                               SUM(COALESCE(e.input_tokens, 0) + COALESCE(e.output_tokens, 0)) as tokens
                        FROM events e
                        LEFT JOIN agent_types agt ON e.agent_id = agt.agent_id
                        GROUP BY agent_type
                        ORDER BY tokens DESC
                    """).fetchall()
                    by_subagent = {row[0]: {"count": row[1], "tokens": row[2]} for row in by_subagent_rows}
                    
                    # Get summarization stats from DuckDB content_retrievals table
                    summarization_stats = {"offered": 0, "full_requested": 0}
                    try:
                        summ_result = store.conn.execute("""
                            SELECT 
                                COUNT(*) as offered,
                                SUM(CASE WHEN was_retrieved THEN 1 ELSE 0 END) as full_requested
                            FROM content_retrievals
                        """).fetchone()
                        if summ_result:
                            summarization_stats = {
                                "offered": summ_result[0] or 0,
                                "full_requested": summ_result[1] or 0
                            }
                    except Exception:
                        pass  # Table might not exist in older DBs
                    
                    data = json.dumps({
                        "events": events,
                        "schema_version": 3,
                        "aggregates": {
                            "total_calls": totals[0] if totals else 0,
                            "total_tokens": totals[1] if totals else 0,
                            "total_sessions": totals[2] if totals else 0,
                            "by_tool": by_tool,
                            "by_agent_type": by_subagent,
                            "summarization": summarization_stats,
                        }
                    })
                except Exception as e:
                    # Return error response when DuckDB fails (no JSON fallback)
                    data = json.dumps({
                        "events": [],
                        "schema_version": 3,
                        "aggregates": {
                            "total_calls": 0,
                            "total_tokens": 0,
                            "total_sessions": 0,
                            "by_tool": {},
                            "by_agent_type": {},
                            "summarization": {"offered": 0, "full_requested": 0},
                        },
                        "error": f"DuckDB query failed: {str(e)}"
                    })

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
