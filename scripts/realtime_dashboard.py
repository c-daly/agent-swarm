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

        /* Timeline styles */
        .timeline-container {
            max-height: 600px;
            overflow-y: auto;
            padding: 10px;
        }
        .timeline-overall-summary {
            background: linear-gradient(135deg, #1e1e3f 0%, #252552 100%);
            border: 1px solid #4cc9f0;
            border-radius: 8px;
            padding: 16px 20px;
            margin-bottom: 20px;
        }
        .timeline-summary-main {
            font-size: 16px;
            font-weight: 600;
            color: #fff;
            margin-bottom: 8px;
        }
        .timeline-summary-detail {
            font-size: 13px;
            color: #a0a0c0;
            margin-top: 4px;
        }
        .timeline-prompts {
            margin-top: 12px;
            padding-top: 12px;
            border-top: 1px solid #333;
        }
        .timeline-prompts-label {
            font-size: 12px;
            color: #888;
            margin-bottom: 6px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .timeline-prompt-item {
            font-size: 13px;
            color: #e0e0e0;
            font-style: italic;
            padding: 4px 0;
            border-left: 2px solid #4cc9f0;
            padding-left: 10px;
            margin: 4px 0;
        }
        .timeline-prompt-more {
            font-size: 12px;
            color: #666;
            margin-top: 4px;
        }
        .session-group {
            margin-bottom: 16px;
            border: 1px solid #333;
            border-radius: 8px;
            overflow: hidden;
        }
        .session-header {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 16px;
            background: #252542;
            cursor: pointer;
            transition: background 0.2s;
        }
        .session-header:hover {
            background: #2d2d4a;
        }
        .session-toggle {
            font-size: 12px;
            color: #888;
            width: 16px;
        }
        .session-info {
            flex: 1;
        }
        .session-id {
            font-family: monospace;
            font-weight: bold;
            color: #4cc9f0;
            font-size: 14px;
        }
        .session-summary {
            font-size: 13px;
            color: #a0a0c0;
            margin-top: 4px;
        }
        .session-context {
            font-size: 12px;
            color: #6b7280;
            font-style: italic;
            margin-top: 2px;
            max-width: 500px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .session-meta {
            font-size: 11px;
            color: #666;
            margin-top: 4px;
        }
        .session-entries {
            padding: 8px;
            background: #1a1a2e;
        }
        .agent-tag {
            background: #7b2cbf;
            color: #fff;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 600;
            margin-left: 8px;
        }
        .subagent-tag {
            background: #0891b2;
            color: #fff;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 600;
            margin-left: 8px;
        }
        /* Subagent session styling (nested under Task tool calls) */
        .subagent-session {
            margin: 12px 0 12px 32px;
            border-left: 3px solid #0891b2;
            border-radius: 0 8px 8px 0;
            background: rgba(8, 145, 178, 0.05);
        }
        .subagent-session .session-header {
            background: linear-gradient(135deg, #1a3a42 0%, #1e2d3d 100%);
            border-radius: 0 8px 0 0;
        }
        .subagent-session .session-header:hover {
            background: linear-gradient(135deg, #1f4552 0%, #243648 100%);
        }
        .subagent-session .session-entries {
            background: rgba(8, 145, 178, 0.03);
            border-radius: 0 0 8px 0;
        }
        .subagent-badge {
            background: #0891b2;
            color: #fff;
            padding: 3px 10px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 600;
        }
        .subagent-file {
            font-size: 11px;
            color: #7dd3fc;
            font-family: monospace;
            margin-left: 8px;
        }
        .session-title-row {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .session-subagent-badge {
            background: #0891b2;
            color: #fff;
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }
        .session-subagent-count {
            background: #0891b2;
            color: #fff;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 600;
            margin-left: 8px;
        }
        /* Load More button */
        .load-more-container {
            text-align: center;
            padding: 20px;
            margin-top: 16px;
        }
        .load-more-btn {
            background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
            color: #fff;
            border: none;
            padding: 12px 32px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .load-more-btn:hover {
            background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
            transform: translateY(-1px);
        }
        .load-more-btn:active {
            transform: translateY(0);
        }
        /* Inline subagent display */
        .subagent-inline {
            margin: 12px 0 12px 24px;
            border-left: 3px solid #0891b2;
            background: linear-gradient(135deg, #1a2e38 0%, #1e2d3d 100%);
            border-radius: 0 8px 8px 0;
            overflow: hidden;
        }
        .subagent-inline-header {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 16px;
            background: rgba(8, 145, 178, 0.15);
            border-bottom: 1px solid rgba(8, 145, 178, 0.3);
        }
        .subagent-inline-badge {
            background: #0891b2;
            color: #fff;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }
        .subagent-inline-info {
            font-size: 12px;
            color: #7dd3fc;
        }
        .subagent-inline-entries {
            padding: 8px;
        }
        .nested-entry {
            margin-left: 0 !important;
            border-left: none !important;
        }
        .nested-entry .timeline-icon {
            opacity: 0.8;
        }
        .paired-result {
            margin-top: 8px;
            padding: 8px;
            background: rgba(76, 201, 240, 0.1);
            border-left: 3px solid #4cc9f0;
            border-radius: 4px;
            cursor: pointer;
        }
        .paired-result:hover {
            background: rgba(76, 201, 240, 0.2);
        }
        .paired-result-header {
            display: flex;
            align-items: center;
            gap: 6px;
            margin-bottom: 4px;
            font-size: 12px;
            color: #4cc9f0;
        }
        .paired-label {
            font-weight: 600;
        }
        .timeline-entry.has-result {
            border-left: 3px solid #4ade80;
        }
        .timeline-entry {
            display: flex;
            gap: 12px;
            padding: 12px;
            margin: 8px 0;
            background: #1a1a2e;
            border-radius: 8px;
            border-left: 4px solid #4cc9f0;
            cursor: pointer;
            transition: all 0.2s;
        }
        .timeline-entry:hover {
            background: #252542;
            transform: translateX(4px);
        }
        .timeline-entry.thinking { border-left-color: #a78bfa; }
        .timeline-entry.tool_use { border-left-color: #4ade80; }
        .timeline-entry.tool_result { border-left-color: #22d3ee; }
        .timeline-entry.response { border-left-color: #60a5fa; }
        .timeline-entry.user_message { border-left-color: #fbbf24; }
        .timeline-icon {
            font-size: 20px;
            width: 32px;
            text-align: center;
        }
        .timeline-content {
            flex: 1;
            min-width: 0;
        }
        .timeline-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 4px;
        }
        .timeline-type {
            font-weight: bold;
            text-transform: uppercase;
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 4px;
            background: rgba(255,255,255,0.1);
        }
        .timeline-type.thinking { background: rgba(167, 139, 250, 0.2); color: #a78bfa; }
        .timeline-type.tool_use { background: rgba(74, 222, 128, 0.2); color: #4ade80; }
        .timeline-type.tool_result { background: rgba(34, 211, 238, 0.2); color: #22d3ee; }
        .timeline-type.response { background: rgba(96, 165, 250, 0.2); color: #60a5fa; }
        .timeline-type.user_message { background: rgba(251, 191, 36, 0.2); color: #fbbf24; }
        .timeline-time {
            font-size: 11px;
            color: #666;
        }
        .timeline-preview {
            font-size: 13px;
            color: #aaa;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            max-width: 100%;
        }
        .timeline-tool {
            font-family: monospace;
            color: #4ade80;
            font-size: 12px;
        }
        .refresh-btn {
            background: #333;
            border: 1px solid #444;
            color: #fff;
            padding: 4px 12px;
            border-radius: 4px;
            cursor: pointer;
        }
        .refresh-btn:hover { background: #444; }

        /* Modal styles */
        .modal {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }
        .modal-content {
            background: #1a1a2e;
            border-radius: 12px;
            max-width: 800px;
            width: 90%;
            max-height: 80vh;
            display: flex;
            flex-direction: column;
        }
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            border-bottom: 1px solid #333;
        }
        .modal-header h3 { margin: 0; }
        .close-btn {
            background: none;
            border: none;
            color: #fff;
            font-size: 24px;
            cursor: pointer;
            padding: 0 8px;
        }
        .close-btn:hover { color: #f87171; }
        .modal-body {
            padding: 20px;
            overflow-y: auto;
            flex: 1;
        }
        .modal-meta {
            display: flex;
            gap: 16px;
            margin-bottom: 16px;
            font-size: 13px;
            color: #888;
        }
        .modal-code {
            background: #0d0d1a;
            padding: 16px;
            border-radius: 8px;
            overflow-x: auto;
            white-space: pre-wrap;
            word-break: break-word;
            font-size: 13px;
            line-height: 1.5;
            max-height: 400px;
            overflow-y: auto;
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

    <nav class="nav-bar">
        <div class="nav-links">
            <a href="#overview" class="active">Overview</a>
            <a href="#charts">Charts</a>
            <a href="#analysis">Analysis</a>
            <a href="#logs">Logs</a>
            <a href="#timeline">Timeline</a>
        </div>
    </nav>

    <div class="filters-bar">
        <div class="filter-group">
            <label>Time Range:</label>
            <select id="filterTimeRange" onchange="applyFilters()">
                <option value="session">Current session</option>
                <option value="1h">Last 1 hour</option>
                <option value="6h">Last 6 hours</option>
                <option value="24h" selected>Last 24 hours</option>
                <option value="7d">Last 7 days</option>
                <option value="30d">Last 30 days</option>
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
                <h2>Tokens Saved</h2>
                <div class="big-number success" id="summarizationRate">-</div>
                <div class="sub-stat" id="summarizationDetails">via summarization</div>
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
                            <option value="1">Last 24 hours</option>
                            <option value="7" selected>Last 7 days</option>
                            <option value="14">Last 14 days</option>
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

        <h3 id="timeline" class="section-title">Activity Timeline</h3>
        <div class="grid">
            <div class="card wide-card">
                <div class="card-header">
                    <h2>Agent Activity Timeline</h2>
                    <div class="chart-controls">
                        <select id="timelineSession" onchange="loadTimeline()">
                            <option value="">All Sessions</option>
                        </select>
                        <select id="timelineFilter" onchange="filterTimeline()">
                            <option value="all">All Activity</option>
                            <option value="thinking">Thinking Only</option>
                            <option value="tool_use">Tool Calls Only</option>
                            <option value="response">Responses Only</option>
                            <option value="user_message">User Messages Only</option>
                        </select>
                        <button onclick="loadTimeline()" class="refresh-btn">↻ Refresh</button>
                    </div>
                </div>
                <div class="timeline-container" id="timelineContainer">
                    <div class="no-data">Loading timeline...</div>
                </div>
            </div>
        </div>

        <!-- Timeline Detail Modal -->
        <div id="timelineModal" class="modal" style="display:none;">
            <div class="modal-content">
                <div class="modal-header">
                    <h3 id="modalTitle">Entry Details</h3>
                    <button onclick="closeTimelineModal()" class="close-btn">&times;</button>
                </div>
                <div class="modal-body">
                    <div class="modal-meta" id="modalMeta"></div>
                    <pre class="modal-code" id="modalContent"></pre>
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
            const sections = ['overview', 'charts', 'sessions', 'analysis', 'logs', 'timeline'];
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
                // Use ALL data (not filtered by main time range) - let tokenChartDays handle the slicing
                const events = allTelemetryData.events || [];
                updateTokenChart(events, allTelemetryData.daily_summaries || {}, allTelemetryData.historical_timeline || []);
            }
        }

        function populateFilterDropdowns(data) {
            // Tool/backend dropdowns removed - v2 telemetry doesn't support per-event filtering
            // Time range dropdown is static HTML, no population needed
        }

        function applyFilters() {
            currentFilters.timeRange = document.getElementById('filterTimeRange').value;
            console.log('Filter changed to:', currentFilters.timeRange);
            if (allTelemetryData) {
                const filtered = filterData(allTelemetryData);
                console.log('Filtered data:', {
                    dailySummaries: Object.keys(filtered.daily_summaries || {}).length,
                    historicalTimeline: (filtered.historical_timeline || []).length,
                    totals: filtered.aggregates?.totals
                });
                updateDashboard(filtered);
            }
        }

        function filterData(data) {
            if (!data) return data;
            const filtered = JSON.parse(JSON.stringify(data)); // Deep clone

            const timeRange = currentFilters.timeRange;

            // Handle session filter separately
            if (timeRange === 'session') {
                // Find most recent session_id from events
                const events = filtered.events || [];
                if (events.length > 0) {
                    const latestSession = events[0].session_id;
                    filtered.events = events.filter(e => e.session_id === latestSession);

                    // Recalculate totals from filtered events
                    const newTotals = { calls: 0, tokens: 0, errors: 0 };
                    filtered.events.forEach(e => {
                        newTotals.calls += 1;
                        newTotals.tokens += e.tokens || 0;
                        if (e.status === 'error') newTotals.errors += 1;
                    });
                    filtered.aggregates = filtered.aggregates || {};
                    filtered.aggregates.totals = newTotals;

                    // Clear daily summaries for session view (not meaningful)
                    filtered.daily_summaries = {};
                }
                return filtered;
            }

            // Time range filter
            const now = Date.now();
            const ranges = {
                '1h': 60 * 60 * 1000,
                '6h': 6 * 60 * 60 * 1000,
                '24h': 24 * 60 * 60 * 1000,
                '7d': 7 * 24 * 60 * 60 * 1000,
                '30d': 30 * 24 * 60 * 60 * 1000,
                'all': Infinity
            };
            const cutoff = now - (ranges[timeRange] || ranges['24h']);
            const cutoffDate = new Date(cutoff).toISOString().substring(0, 10);

            // Filter daily_summaries by date range
            if (filtered.daily_summaries && timeRange !== 'all') {
                const filteredSummaries = {};
                Object.entries(filtered.daily_summaries).forEach(([date, summary]) => {
                    if (date >= cutoffDate) {
                        filteredSummaries[date] = summary;
                    }
                });
                filtered.daily_summaries = filteredSummaries;
            }

            // Filter historical_timeline by date range
            if (filtered.historical_timeline && timeRange !== 'all') {
                filtered.historical_timeline = filtered.historical_timeline.filter(h => {
                    return h.date >= cutoffDate;
                });
            }

            // Recalculate totals from filtered daily_summaries
            if (timeRange !== 'all' && filtered.daily_summaries) {
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

            // Ensure aggregates exists
            data.aggregates = data.aggregates || {};
            const agg = data.aggregates;

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
            const tokensSaved = summ.tokens_saved || 0;
            data.aggregates.summarization = {
                offered: summ.offered || 0,
                accepted: summ.offered || 0,  // v3 auto-accepts summaries
                rejected: 0,
                full_content_requests: summ.full_requested || 0,
                tokens_before: 0,  // Not available in v3
                tokens_after: 0,   // Not available in v3
                tokens_saved: tokensSaved  // Direct tokens saved value
            };
            // Use daily_summaries from server (pre-aggregated from ALL events)
            // Fallback to building from events if server didn't provide them
            if (!data.daily_summaries || Object.keys(data.daily_summaries).length === 0) {
                const dailySummaries = {};
                const events = data.events || [];
                events.forEach(e => {
                    const date = e.ts ? e.ts.substring(0, 10) : (e.timestamp ? e.timestamp.substring(0, 10) : null);
                    if (date) {
                        if (!dailySummaries[date]) {
                            dailySummaries[date] = { calls: 0, tokens: 0, errors: 0 };
                        }
                        dailySummaries[date].calls += 1;
                        dailySummaries[date].tokens += e.tokens || 0;
                        if (e.status === 'error') dailySummaries[date].errors += 1;
                    }
                });
                data.daily_summaries = dailySummaries;
            }
            // Build historical_timeline from daily_summaries for trend calculation
            data.historical_timeline = Object.entries(data.daily_summaries || {})
                .map(([date, summary]) => ({
                    date: date,
                    tokens: summary.tokens || 0,
                    events: summary.calls || 0,
                    errors: summary.errors || 0
                }))
                .sort((a, b) => a.date.localeCompare(b.date));
            console.log('Built historical_timeline:', data.historical_timeline.length, 'days', data.historical_timeline);

            // Use sessions from server (pre-aggregated from ALL events)
            // Fallback to building from events if server didn't provide them
            if (!data.sessions || data.sessions.length === 0) {
                const sessionMap = {};
                const events = data.events || [];
                events.forEach(e => {
                    const sid = e.session_id;
                    if (sid) {
                        // Convert UTC timestamp to local time
                        const localTs = e.ts ? new Date(e.ts.replace(' ', 'T') + 'Z').toLocaleString() : e.ts;
                        const dateStr = e.ts ? e.ts.substring(0, 10) : null;
                        if (!sessionMap[sid]) {
                            sessionMap[sid] = {
                                id: sid,
                                calls: 0,
                                tokens: 0,
                                start_time: localTs,
                                end_time: localTs,
                                date: dateStr
                            };
                        }
                        sessionMap[sid].calls += 1;
                        sessionMap[sid].tokens += e.tokens || 0;
                        sessionMap[sid].end_time = localTs;
                    }
                });
                data.sessions = Object.values(sessionMap);
            } else {
                // Convert UTC timestamps in server-provided sessions to local time
                data.sessions = data.sessions.map(s => ({
                    ...s,
                    start_time: s.start_time ? new Date(s.start_time.replace(' ', 'T') + 'Z').toLocaleString() : s.start_time,
                    end_time: s.end_time ? new Date(s.end_time.replace(' ', 'T') + 'Z').toLocaleString() : s.end_time
                }));
            }
            
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
            // Use ALL historical data for trend (not filtered by main time range)
            const timeline = (allTelemetryData && allTelemetryData.historical_timeline) || data.historical_timeline || [];
            const trendEl = document.getElementById('trendIndicator');
            const trendDetailsEl = document.getElementById('trendDetails');
            console.log('Trend calculation using timeline with', timeline.length, 'days');
            
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
            updateSubagentChart(agg.by_agent_type || agg.subagents || {});

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
                    eventBuckets[date].tokens += e.tokens || e.response_size || e.tokens_est || 0;
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
            const tokensSaved = summarization.tokens_saved || 0;

            const summarizationRateEl = document.getElementById('summarizationRate');
            const summarizationDetailsEl = document.getElementById('summarizationDetails');

            // Format large numbers with K/M suffix
            function formatTokens(n) {
                if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
                if (n >= 1000) return (n / 1000).toFixed(0) + 'K';
                return n.toString();
            }

            if (summarizationRateEl) {
                if (tokensSaved > 0) {
                    // Show tokens saved as the primary metric
                    summarizationRateEl.textContent = formatTokens(tokensSaved);
                    summarizationRateEl.className = 'big-number success';
                } else if (offered > 0) {
                    summarizationRateEl.textContent = offered + ' summaries';
                    summarizationRateEl.className = 'big-number';
                } else {
                    summarizationRateEl.textContent = 'N/A';
                    summarizationRateEl.className = 'big-number';
                }
            }

            if (summarizationDetailsEl) {
                if (offered > 0 || tokensSaved > 0) {
                    let details = [];
                    if (offered > 0) details.push(`${offered} summaries`);
                    if (tokensSaved > 0) details.push(`${formatTokens(tokensSaved)} tokens saved`);
                    if (fullContentRequests > 0) details.push(`${fullContentRequests} full requests`);
                    summarizationDetailsEl.textContent = details.join(' / ');
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

        // ===== Timeline Functions =====
        let allTimelineData = [];
        let currentTimelineFilter = 'all';
        let timelineOffset = 0;
        let timelineTotal = 0;
        let isLoadingMore = false;
        const TIMELINE_PAGE_SIZE = 500;

        async function loadTimeline(append = false) {
            const container = document.getElementById('timelineContainer');
            const sessionSelect = document.getElementById('timelineSession');
            const session = sessionSelect.value;

            if (!append) {
                container.innerHTML = '<div class="no-data">Loading timeline...</div>';
                timelineOffset = 0;
                allTimelineData = [];
            }

            try {
                const url = session
                    ? `/timeline?session=${encodeURIComponent(session)}&limit=${TIMELINE_PAGE_SIZE}&offset=${timelineOffset}`
                    : `/timeline?limit=${TIMELINE_PAGE_SIZE}&offset=${timelineOffset}`;
                const response = await fetch(url);
                const data = await response.json();

                if (data.error) {
                    if (!append) {
                        container.innerHTML = `<div class="no-data">Error: ${data.error}</div>`;
                    } else {
                        console.error('Server error on load more:', data.error);
                        const btn = document.getElementById('loadMoreBtn');
                        if (btn) btn.textContent = `Error: ${data.error} - click to retry`;
                    }
                    return;
                }

                const newEntries = data.entries || [];
                timelineTotal = data.total || 0;

                if (append) {
                    allTimelineData = [...allTimelineData, ...newEntries];
                } else {
                    allTimelineData = newEntries;
                }

                timelineOffset += newEntries.length;

                // Populate session dropdown if not done
                if (sessionSelect.options.length <= 1 && data.sessions) {
                    data.sessions.forEach(s => {
                        const opt = document.createElement('option');
                        opt.value = s;
                        opt.textContent = s;
                        sessionSelect.appendChild(opt);
                    });
                }

                renderTimeline();
            } catch (e) {
                if (!append) {
                    container.innerHTML = `<div class="no-data">Failed to load timeline: ${e.message}</div>`;
                } else {
                    // On append error, just show error in button area, don't destroy existing content
                    console.error('Failed to load more:', e);
                    const btn = document.getElementById('loadMoreBtn');
                    if (btn) btn.textContent = `Error loading more - click to retry`;
                }
            }
        }

        async function loadMoreTimeline() {
            if (isLoadingMore) return;
            if (timelineOffset >= timelineTotal) return;

            isLoadingMore = true;
            const btn = document.getElementById('loadMoreBtn');
            if (btn) btn.textContent = 'Loading...';

            try {
                await loadTimeline(true);
            } finally {
                isLoadingMore = false;
            }
        }

        function filterTimeline() {
            currentTimelineFilter = document.getElementById('timelineFilter').value;
            renderTimeline();
        }

        function renderTimeline() {
            const container = document.getElementById('timelineContainer');
            let entries = allTimelineData;

            if (currentTimelineFilter !== 'all') {
                // When filtering by tool_use, also show matching tool_result
                if (currentTimelineFilter === 'tool_use') {
                    const toolUseIds = new Set(entries.filter(e => e.type === 'tool_use').map(e => e.tool_use_id).filter(Boolean));
                    entries = entries.filter(e => e.type === 'tool_use' || (e.type === 'tool_result' && toolUseIds.has(e.tool_use_id)));
                } else {
                    entries = entries.filter(e => e.type === currentTimelineFilter);
                }
            }

            if (entries.length === 0) {
                container.innerHTML = '<div class="no-data">No timeline entries found</div>';
                return;
            }

            // Build a map of tool_use_id -> tool_result for pairing
            const resultMap = {};
            entries.forEach(e => {
                if (e.type === 'tool_result' && e.tool_use_id) {
                    resultMap[e.tool_use_id] = e;
                }
            });

            // Filter out internal summarization sessions (Claude Code internal operations)
            // These have user messages like "Context: This summary will be shown..."
            const summarizationPatterns = [
                /^Context: This summary will be shown/i,
                /^Please write a concise.*summary/i,
                /^<summary>/i,
            ];
            const isSummarizationEntry = (e) => {
                if (e.type === 'user_message' || e.type === 'response') {
                    const preview = (e.preview || '').trim();
                    return summarizationPatterns.some(p => p.test(preview));
                }
                return false;
            };

            // Group entries by session to detect summarization sessions
            const sessionEntries = {};
            entries.forEach(e => {
                const sid = e.session_id || 'unknown';
                if (!sessionEntries[sid]) sessionEntries[sid] = [];
                sessionEntries[sid].push(e);
            });

            // Find sessions that are purely summarization (filter them out)
            const summarizationSessions = new Set();
            Object.entries(sessionEntries).forEach(([sid, ses]) => {
                // If session has <=3 entries and any is a summarization pattern, exclude it
                if (ses.length <= 3 && ses.some(isSummarizationEntry)) {
                    summarizationSessions.add(sid);
                }
            });

            // Filter entries: exclude subagent entries and summarization sessions
            const mainEntries = entries.filter(e =>
                !e.is_subagent && !summarizationSessions.has(e.session_id)
            );
            const subagentEntries = entries.filter(e => e.is_subagent);

            // Group subagent entries by their file (each file = one subagent invocation)
            const subagentByFile = {};
            subagentEntries.forEach(e => {
                const file = e.file || 'unknown';
                if (!subagentByFile[file]) {
                    subagentByFile[file] = {
                        entries: [],
                        firstTime: e.timestamp,
                        lastTime: e.timestamp,
                        type: ''
                    };
                    // Extract subagent type from filename (agent-TYPE-xxx.jsonl)
                    const match = file.match(/^agent-([^-]+)/);
                    if (match) subagentByFile[file].type = match[1];
                }
                subagentByFile[file].entries.push(e);
                if (e.timestamp < subagentByFile[file].firstTime) {
                    subagentByFile[file].firstTime = e.timestamp;
                }
                if (e.timestamp > subagentByFile[file].lastTime) {
                    subagentByFile[file].lastTime = e.timestamp;
                }
            });

            // Sort subagent entries within each file chronologically
            Object.values(subagentByFile).forEach(sg => {
                sg.entries.sort((a, b) => (a.timestamp || '').localeCompare(b.timestamp || ''));
            });

            // Create array of subagent groups sorted by start time for matching
            const subagentGroups = Object.entries(subagentByFile)
                .map(([file, data]) => ({file, ...data}))
                .sort((a, b) => (a.firstTime || '').localeCompare(b.firstTime || ''));

            // Track which subagent groups have been matched
            const matchedSubagents = new Set();

            // Group main entries by session, pairing tool_use with tool_result
            const sessionGroups = {};
            const processedResultIds = new Set();

            mainEntries.forEach((entry, idx) => {
                // Skip tool_results that will be paired with their tool_use
                if (entry.type === 'tool_result' && processedResultIds.has(entry.tool_use_id)) {
                    return;
                }

                const sessionId = entry.session_id || 'unknown';
                if (!sessionGroups[sessionId]) {
                    sessionGroups[sessionId] = {
                        entries: [],
                        firstTime: entry.timestamp,
                        lastTime: entry.timestamp
                    };
                }

                // If this is a tool_use, pair it with its result
                let pairedResult = null;
                if (entry.type === 'tool_use' && entry.tool_use_id && resultMap[entry.tool_use_id]) {
                    pairedResult = resultMap[entry.tool_use_id];
                    processedResultIds.add(entry.tool_use_id);
                }

                // If this is a Task tool call, try to match it with a subagent
                let matchedSubagent = null;
                if (entry.type === 'tool_use' && entry.tool === 'Task') {
                    // Find the first unmatched subagent that started after this Task call
                    const taskTime = entry.timestamp;
                    for (const sg of subagentGroups) {
                        if (!matchedSubagents.has(sg.file) && sg.firstTime >= taskTime) {
                            // Check if subagent started within 30 seconds of Task call
                            const taskDate = new Date(taskTime);
                            const subagentDate = new Date(sg.firstTime);
                            const diffMs = subagentDate - taskDate;
                            if (diffMs >= 0 && diffMs < 30000) {
                                matchedSubagent = sg;
                                matchedSubagents.add(sg.file);
                                break;
                            }
                        }
                    }
                }

                sessionGroups[sessionId].entries.push({...entry, globalIdx: idx, pairedResult, matchedSubagent});

                // Track time range
                if (entry.timestamp < sessionGroups[sessionId].firstTime) {
                    sessionGroups[sessionId].firstTime = entry.timestamp;
                }
                if (entry.timestamp > sessionGroups[sessionId].lastTime) {
                    sessionGroups[sessionId].lastTime = entry.timestamp;
                }
            });

            // Sort sessions by most recent first
            const sortedSessions = Object.entries(sessionGroups)
                .sort((a, b) => (b[1].lastTime || '').localeCompare(a[1].lastTime || ''));

            // Sort entries within each session chronologically (oldest first)
            sortedSessions.forEach(([sid, group]) => {
                group.entries.sort((a, b) => (a.timestamp || '').localeCompare(b.timestamp || ''));
            });

            const icons = {
                'thinking': '🧠',
                'tool_use': '🔧',
                'tool_result': '📋',
                'response': '💬',
                'user_message': '👤'
            };

            // Build overall summary for top of timeline
            const totalThinking = entries.filter(e => e.type === 'thinking').length;
            const totalToolUse = entries.filter(e => e.type === 'tool_use').length;
            const totalResponses = entries.filter(e => e.type === 'response').length;
            const subagentEntryCount = subagentEntries.length;
            const allTools = [...new Set(entries.filter(e => e.tool).map(e => e.tool))];
            const allAgents = [...new Set(entries.filter(e => e.agent_type).map(e => e.agent_type))];
            const sessionCount = sortedSessions.length;

            // Extract first real user prompt from each session
            const skipPatterns = [
                /^Base directory for this skill:/i,
                /^<command-name>/i,
                /^#\\s*(Debug|Workflow|Skill)/i,
                /^\\[BLOCKED\\]/i,
                /^<system/i,
                /^Usage:/i,
                /^This session is being continued/i,
            ];
            const sessionPrompts = sortedSessions.map(([sid, group]) => {
                const userMsgs = group.entries.filter(e => e.type === 'user_message');
                for (const msg of userMsgs) {
                    const preview = (msg.preview || '').trim();
                    const isSystem = skipPatterns.some(p => p.test(preview));
                    if (!isSystem && preview.length > 10) {
                        return { sessionId: sid, prompt: preview.substring(0, 80) };
                    }
                }
                return null;
            }).filter(Boolean);

            // Create overall summary text
            const overallParts = [];
            overallParts.push(`${sessionCount} session${sessionCount !== 1 ? 's' : ''}`);
            overallParts.push(`${totalToolUse} tool calls`);
            if (totalThinking > 0) overallParts.push(`${totalThinking} thinking blocks`);
            if (totalResponses > 0) overallParts.push(`${totalResponses} responses`);
            if (subagentEntryCount > 0) overallParts.push(`🤖 ${subagentEntryCount} subagent entries`);

            const toolsSummary = allTools.length > 0
                ? `Tools: ${allTools.slice(0, 5).join(', ')}${allTools.length > 5 ? ` (+${allTools.length - 5} more)` : ''}`
                : '';
            const agentsSummary = allAgents.length > 0
                ? `Agents: ${allAgents.join(', ')}`
                : '';

            const overallSummaryHtml = `
                <div class="timeline-overall-summary">
                    <div class="timeline-summary-main">${overallParts.join(' · ')}</div>
                    ${toolsSummary ? `<div class="timeline-summary-detail">${toolsSummary}</div>` : ''}
                    ${agentsSummary ? `<div class="timeline-summary-detail">${agentsSummary}</div>` : ''}
                </div>
            `;

            const sessionsHtml = sortedSessions.map(([sessionId, group], groupIdx) => {
                const startTime = group.firstTime ? new Date(group.firstTime).toLocaleString() : 'Unknown';
                const entryCount = group.entries.length;
                const typeCounts = {};
                const toolsUsed = new Set();
                const agentTypes = new Set();
                let firstUserMsg = '';
                let firstResponse = '';
                let subagentCount = 0;

                group.entries.forEach(e => {
                    // Count matched subagents
                    if (e.matchedSubagent) subagentCount++;
                    typeCounts[e.type] = (typeCounts[e.type] || 0) + 1;
                    if (e.tool) toolsUsed.add(e.tool);
                    if (e.agent_type) agentTypes.add(e.agent_type);
                    if (e.type === 'user_message' && !firstUserMsg) {
                        const preview = (e.preview || '').trim();
                        // Skip skill prompts, system messages, and hook outputs
                        const skipPatterns = [
                            /^Base directory for this skill:/i,
                            /^<command-name>/i,
                            /^#\\s*(Debug|Workflow|Skill)/i,
                            /^\\[BLOCKED\\]/i,
                            /^<system/i,
                            /^Usage:/i,
                            /^This session is being continued/i,
                        ];
                        const isSystemMessage = skipPatterns.some(p => p.test(preview));
                        if (!isSystemMessage && preview.length > 10) {
                            firstUserMsg = preview.substring(0, 100);
                        }
                    }
                    if (e.type === 'response' && !firstResponse) {
                        firstResponse = (e.preview || '').substring(0, 80);
                    }
                });

                // Generate natural language summary - include all entry types
                const summaryParts = [];
                if (typeCounts.thinking) summaryParts.push(`${typeCounts.thinking} thinking`);
                if (typeCounts.tool_use) {
                    const topTools = [...toolsUsed].slice(0, 3).join(', ');
                    summaryParts.push(`${typeCounts.tool_use} tools (${topTools}${toolsUsed.size > 3 ? '...' : ''})`);
                }
                if (typeCounts.response) summaryParts.push(`${typeCounts.response} responses`);
                if (typeCounts.user_message) summaryParts.push(`${typeCounts.user_message} prompts`);
                if (agentTypes.size > 0) {
                    summaryParts.push(`agents: ${[...agentTypes].join(', ')}`);
                }

                const sessionSummary = summaryParts.length > 0 ? summaryParts.join(' · ') : `${entryCount} entries`;

                const typesSummary = Object.entries(typeCounts)
                    .map(([t, c]) => `${icons[t] || '📌'}${c}`)
                    .join(' ');

                // Helper to render a single entry
                const renderEntry = (entry, isNested = false) => {
                    const time = entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : '';
                    const icon = icons[entry.type] || '📌';
                    const toolInfo = entry.tool ? `<div class="timeline-tool">${entry.tool}</div>` : '';

                    // Agent type tag
                    const agentTag = entry.agent_type ?
                        `<span class="agent-tag">${entry.agent_type}</span>` : '';

                    // Paired result (for tool_use entries)
                    let pairedHtml = '';
                    if (entry.pairedResult) {
                        const result = entry.pairedResult;
                        pairedHtml = `
                            <div class="paired-result" onclick="event.stopPropagation(); showTimelineDetailByContent(${JSON.stringify(result.full_content).replace(/"/g, '&quot;')})">
                                <div class="paired-result-header">
                                    <span class="timeline-icon">📋</span>
                                    <span class="paired-label">Result</span>
                                </div>
                                <div class="timeline-preview">${escapeHtml(result.preview || '')}</div>
                            </div>
                        `;
                    }

                    // Encode entry data for onclick
                    const entryData = JSON.stringify({
                        type: entry.type,
                        timestamp: entry.timestamp,
                        session_id: entry.session_id,
                        tool: entry.tool,
                        tokens: entry.tokens,
                        full_content: entry.full_content
                    }).replace(/"/g, '&quot;');

                    return `
                        <div class="timeline-entry ${entry.type} ${entry.pairedResult ? 'has-result' : ''} ${isNested ? 'nested-entry' : ''}" onclick="showTimelineDetailFromData(${entryData})">
                            <div class="timeline-icon">${icon}</div>
                            <div class="timeline-content">
                                <div class="timeline-header">
                                    <span class="timeline-type ${entry.type}">${entry.type.replace('_', ' ')}</span>
                                    ${agentTag}
                                    <span class="timeline-time">${time}</span>
                                </div>
                                ${toolInfo}
                                <div class="timeline-preview">${escapeHtml(entry.preview || '')}</div>
                                ${pairedHtml}
                            </div>
                        </div>
                    `;
                };

                const entriesHtml = group.entries.map((entry) => {
                    let html = renderEntry(entry, false);

                    // If this Task tool call has a matched subagent, render it as a nested session
                    if (entry.matchedSubagent) {
                        const sg = entry.matchedSubagent;
                        const subagentEntriesHtml = sg.entries.map(se => renderEntry(se, true)).join('');

                        // Build subagent session summary (like main sessions)
                        const sgTypeCounts = {};
                        const sgToolsUsed = new Set();
                        sg.entries.forEach(se => {
                            sgTypeCounts[se.type] = (sgTypeCounts[se.type] || 0) + 1;
                            if (se.tool) sgToolsUsed.add(se.tool);
                        });

                        const sgSummaryParts = [];
                        if (sgTypeCounts.thinking) sgSummaryParts.push(`${sgTypeCounts.thinking} thinking`);
                        if (sgTypeCounts.tool_use) {
                            const topTools = [...sgToolsUsed].slice(0, 3).join(', ');
                            sgSummaryParts.push(`${sgTypeCounts.tool_use} tools (${topTools}${sgToolsUsed.size > 3 ? '...' : ''})`);
                        }
                        if (sgTypeCounts.response) sgSummaryParts.push(`${sgTypeCounts.response} responses`);

                        const sgSummary = sgSummaryParts.length > 0 ? sgSummaryParts.join(' · ') : `${sg.entries.length} entries`;

                        const sgTypesSummary = Object.entries(sgTypeCounts)
                            .map(([t, c]) => `${icons[t] || '📌'}${c}`)
                            .join(' ');

                        const sgStartTime = sg.firstTime ? new Date(sg.firstTime).toLocaleTimeString() : '';
                        const sgEndTime = sg.lastTime ? new Date(sg.lastTime).toLocaleTimeString() : '';
                        const sgTimeRange = sgStartTime && sgEndTime && sgStartTime !== sgEndTime
                            ? `${sgStartTime} - ${sgEndTime}`
                            : sgStartTime;

                        html += `
                            <div class="subagent-session session-group collapsed">
                                <div class="session-header" onclick="toggleSession(this)">
                                    <div class="session-toggle">▶</div>
                                    <div class="session-info">
                                        <div class="session-title-row">
                                            <span class="subagent-badge">🤖 ${sg.type || 'subagent'}</span>
                                            <span class="subagent-file">${sg.file}</span>
                                        </div>
                                        <div class="session-summary">${sgSummary}</div>
                                        <div class="session-meta">${sgTimeRange} · ${sg.entries.length} entries · ${sgTypesSummary}</div>
                                    </div>
                                </div>
                                <div class="session-entries" style="display:none">
                                    ${subagentEntriesHtml}
                                </div>
                            </div>
                        `;
                    }

                    return html;
                }).join('');

                const isExpanded = false; // All sessions collapsed by default

                // Subagent count indicator
                const subagentIndicator = subagentCount > 0
                    ? `<span class="session-subagent-count">🤖 ${subagentCount} subagent${subagentCount > 1 ? 's' : ''}</span>`
                    : '';

                return `
                    <div class="session-group ${isExpanded ? 'expanded' : 'collapsed'}">
                        <div class="session-header" onclick="toggleSession(this)">
                            <div class="session-toggle">${isExpanded ? '▼' : '▶'}</div>
                            <div class="session-info">
                                <div class="session-title-row">
                                    <span class="session-id">${sessionId}</span>
                                    ${subagentIndicator}
                                </div>
                                <div class="session-summary">${sessionSummary}</div>
                                <div class="session-meta">${startTime} · ${entryCount} entries · ${typesSummary}</div>
                            </div>
                        </div>
                        <div class="session-entries" style="${isExpanded ? '' : 'display:none'}">
                            ${entriesHtml}
                        </div>
                    </div>
                `;
            }).join('');

            // Add "Load More" button if there are more entries
            const loadMoreHtml = timelineOffset < timelineTotal ? `
                <div class="load-more-container">
                    <button id="loadMoreBtn" class="load-more-btn" onclick="loadMoreTimeline()">
                        Load More (${timelineOffset} of ${timelineTotal} entries)
                    </button>
                </div>
            ` : '';

            container.innerHTML = overallSummaryHtml + sessionsHtml + loadMoreHtml;
        }

        function toggleSession(headerEl) {
            const group = headerEl.parentElement;
            const entries = group.querySelector('.session-entries');
            const toggle = group.querySelector('.session-toggle');

            if (group.classList.contains('expanded')) {
                group.classList.remove('expanded');
                group.classList.add('collapsed');
                entries.style.display = 'none';
                toggle.textContent = '▶';
            } else {
                group.classList.remove('collapsed');
                group.classList.add('expanded');
                entries.style.display = '';
                toggle.textContent = '▼';
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function showTimelineDetail(idx) {
            const entry = allTimelineData.filter(e =>
                currentTimelineFilter === 'all' || e.type === currentTimelineFilter
            )[idx];

            if (!entry) return;

            const modal = document.getElementById('timelineModal');
            const title = document.getElementById('modalTitle');
            const meta = document.getElementById('modalMeta');
            const content = document.getElementById('modalContent');

            const typeLabels = {
                'thinking': '🧠 Agent Thinking',
                'tool_use': '🔧 Tool Call',
                'tool_result': '📋 Tool Result',
                'response': '💬 Assistant Response',
                'user_message': '👤 User Message'
            };

            title.textContent = typeLabels[entry.type] || entry.type;

            const time = entry.timestamp ? new Date(entry.timestamp).toLocaleString() : 'Unknown';
            meta.innerHTML = `
                <span><strong>Time:</strong> ${time}</span>
                <span><strong>Session:</strong> ${entry.session_id || 'Unknown'}</span>
                ${entry.tool ? `<span><strong>Tool:</strong> ${entry.tool}</span>` : ''}
                ${entry.tokens ? `<span><strong>Tokens:</strong> ${entry.tokens}</span>` : ''}
            `;

            content.textContent = entry.full_content || entry.preview || 'No content available';

            modal.style.display = 'flex';
        }

        function closeTimelineModal() {
            document.getElementById('timelineModal').style.display = 'none';
        }

        function showTimelineDetailByContent(fullContent) {
            const modal = document.getElementById('timelineModal');
            const title = document.getElementById('modalTitle');
            const meta = document.getElementById('modalMeta');
            const content = document.getElementById('modalContent');

            title.textContent = '📋 Tool Result';
            meta.innerHTML = '<span>Result content from paired tool call</span>';
            content.textContent = fullContent || 'No content available';
            modal.style.display = 'flex';
        }

        function showTimelineDetailFromData(entry) {
            const modal = document.getElementById('timelineModal');
            const title = document.getElementById('modalTitle');
            const meta = document.getElementById('modalMeta');
            const content = document.getElementById('modalContent');

            const typeLabels = {
                'thinking': '🧠 Agent Thinking',
                'tool_use': '🔧 Tool Call',
                'tool_result': '📋 Tool Result',
                'response': '💬 Assistant Response',
                'user_message': '👤 User Message'
            };

            title.textContent = typeLabels[entry.type] || entry.type;

            const time = entry.timestamp ? new Date(entry.timestamp).toLocaleString() : 'Unknown';
            meta.innerHTML = `
                <span><strong>Time:</strong> ${time}</span>
                <span><strong>Session:</strong> ${entry.session_id || 'Unknown'}</span>
                ${entry.tool ? `<span><strong>Tool:</strong> ${entry.tool}</span>` : ''}
                ${entry.tokens ? `<span><strong>Tokens:</strong> ${entry.tokens}</span>` : ''}
            `;

            content.textContent = entry.full_content || 'No content available';
            modal.style.display = 'flex';
        }

        // Close modal on escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeTimelineModal();
        });

        // Close modal on backdrop click
        document.getElementById('timelineModal').addEventListener('click', (e) => {
            if (e.target.id === 'timelineModal') closeTimelineModal();
        });

        // Load timeline on page load (delayed slightly)
        setTimeout(loadTimeline, 1000);
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
                    # GROUP BY 1 refers to first SELECT column (the COALESCE expression)
                    by_subagent_rows = store.conn.execute("""
                        SELECT COALESCE(e.agent_type, agt.agent_type, 'main') as agent_type,
                               COUNT(*) as count,
                               SUM(COALESCE(e.input_tokens, 0) + COALESCE(e.output_tokens, 0)) as tokens
                        FROM events e
                        LEFT JOIN agent_types agt ON e.agent_id = agt.agent_id
                        GROUP BY 1
                        ORDER BY tokens DESC
                    """).fetchall()
                    by_subagent = {row[0]: {"count": row[1], "tokens": row[2]} for row in by_subagent_rows}
                    
                    # Get summarization stats from events table (was_summarized, original_size, summary_size)
                    summarization_stats = {"offered": 0, "full_requested": 0, "tokens_saved": 0}
                    try:
                        summ_result = store.conn.execute("""
                            SELECT
                                SUM(CASE WHEN was_summarized = true THEN 1 ELSE 0 END) as offered,
                                SUM(CASE WHEN was_summarized = true THEN COALESCE(original_size, 0) - COALESCE(summary_size, 0) ELSE 0 END) as tokens_saved
                            FROM events
                            WHERE original_size IS NOT NULL
                        """).fetchone()
                        if summ_result and summ_result[0]:
                            summarization_stats = {
                                "offered": summ_result[0] or 0,
                                "full_requested": 0,  # Not tracked in current schema
                                "tokens_saved": summ_result[1] or 0
                            }
                    except Exception:
                        pass  # Column might not exist in older DBs

                    # Fallback: merge summarization from v2 telemetry.json if DuckDB has none
                    if summarization_stats["offered"] == 0 and TELEMETRY_FILE.exists():
                        try:
                            v2_data = json.loads(TELEMETRY_FILE.read_text())
                            # Sum summarization.offered from all days
                            days = v2_data.get("days", {})
                            total_offered = 0
                            total_tokens_saved = 0
                            for day_data in days.values():
                                summ = day_data.get("summarization", {})
                                total_offered += summ.get("offered", 0)
                                total_tokens_saved += summ.get("tokens_saved", 0)
                            if total_offered > 0:
                                summarization_stats = {
                                    "offered": total_offered,
                                    "full_requested": 0,  # v2 didn't track this
                                    "tokens_saved": total_tokens_saved
                                }
                        except Exception:
                            pass

                    # Get daily summaries from ALL events (not just 500)
                    daily_rows = store.conn.execute("""
                        SELECT
                            CAST(timestamp AS DATE) as date,
                            COUNT(*) as calls,
                            SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)) as tokens,
                            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors
                        FROM events
                        GROUP BY CAST(timestamp AS DATE)
                        ORDER BY date
                    """).fetchall()
                    daily_summaries = {
                        str(row[0]): {"calls": row[1], "tokens": row[2] or 0, "errors": row[3] or 0}
                        for row in daily_rows
                    }

                    # Get all sessions with their aggregates
                    session_rows = store.conn.execute("""
                        SELECT
                            session_id,
                            COUNT(*) as calls,
                            SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)) as tokens,
                            MIN(timestamp) as start_time,
                            MAX(timestamp) as end_time,
                            CAST(MIN(timestamp) AS DATE) as date
                        FROM events
                        WHERE session_id IS NOT NULL
                        GROUP BY session_id
                        ORDER BY start_time DESC
                        LIMIT 200
                    """).fetchall()
                    sessions = [
                        {
                            "id": row[0],
                            "calls": row[1],
                            "tokens": row[2] or 0,
                            "start_time": str(row[3]),
                            "end_time": str(row[4]),
                            "date": str(row[5])
                        }
                        for row in session_rows
                    ]

                    data = json.dumps({
                        "events": events,
                        "schema_version": 3,
                        "daily_summaries": daily_summaries,
                        "sessions": sessions,
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

            elif self.path.startswith("/timeline"):
                # Serve activity timeline from JSONL conversation files
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

                try:
                    from pathlib import Path
                    import glob as glob_mod

                    # Parse query params
                    from urllib.parse import urlparse, parse_qs
                    parsed = urlparse(self.path)
                    params = parse_qs(parsed.query)
                    session_id = params.get('session', [None])[0]
                    limit = int(params.get('limit', [500])[0])
                    offset = int(params.get('offset', [0])[0])

                    # Find JSONL files in the project directory (including subagent files)
                    project_dir = Path.home() / ".claude/projects/-home-fearsidhe--claude-plugins-agent-swarm"

                    # Get all JSONL files - both main sessions and subagent sessions
                    all_jsonl_files = list(project_dir.glob("*.jsonl"))

                    # Separate main sessions from agent files
                    main_files = [f for f in all_jsonl_files if not f.name.startswith('agent-')]
                    agent_files = [f for f in all_jsonl_files if f.name.startswith('agent-')]

                    # Sort main files by modification time (most recent first)
                    main_files = sorted(main_files, key=lambda f: f.stat().st_mtime, reverse=True)

                    # For agent files, prioritize by SIZE (larger = more content) and filter out tiny files
                    # Many recent agent files are nearly empty (<1KB), so sort by size to get meaningful ones
                    agent_files_with_size = [(f, f.stat().st_size) for f in agent_files]
                    agent_files_by_size = sorted(agent_files_with_size, key=lambda x: x[1], reverse=True)
                    # Only include agent files with meaningful content (>500 bytes)
                    meaningful_agent_files = [f for f, size in agent_files_by_size if size > 500]

                    timeline_entries = []

                    # Process files - include main files and agent files with actual content
                    if session_id:
                        files_to_process = all_jsonl_files  # All files for specific session
                    else:
                        # Strategy: Include main files that span the time range of our agent files
                        # This ensures Task calls can be matched with their spawned subagents

                        # Get time range of agent files (first entry timestamps)
                        agent_timestamps = []
                        for af in meaningful_agent_files[:50]:
                            try:
                                with open(af, 'r') as f:
                                    for line in f:
                                        if line.strip():
                                            entry = json.loads(line)
                                            ts = entry.get('timestamp', '')
                                            if ts:
                                                agent_timestamps.append(ts)
                                            break
                            except:
                                pass

                        # Strategy: Include recent files FIRST, then add files that overlap with agent range
                        # This ensures we see recent sessions while also enabling subagent matching
                        selected_main = set()

                        # First: Always include the 30 most recent main files
                        for mf in main_files[:30]:
                            selected_main.add(mf)

                        # Second: Add files that overlap with agent time range (for subagent matching)
                        if agent_timestamps:
                            min_agent_time = min(agent_timestamps)
                            max_agent_time = max(agent_timestamps)

                            for mf in main_files:
                                if len(selected_main) >= 70:
                                    break
                                if mf in selected_main:
                                    continue
                                try:
                                    with open(mf, 'r') as f:
                                        for line in f:
                                            if line.strip():
                                                entry = json.loads(line)
                                                ts = entry.get('timestamp', '')
                                                if ts and min_agent_time <= ts <= max_agent_time:
                                                    selected_main.add(mf)
                                                break
                                except:
                                    pass

                        main_to_process = list(selected_main)

                        files_to_process = main_to_process + meaningful_agent_files[:50]

                    # Collect entries from all files first (with per-file limit to avoid memory issues)
                    per_file_limit = 100  # Limit entries per file to ensure variety

                    for jsonl_file in files_to_process:
                        # Detect if this is a subagent file
                        is_subagent = jsonl_file.name.startswith('agent-')
                        file_entry_count = 0

                        try:
                            with open(jsonl_file, 'r') as f:
                                for line in f:
                                    if file_entry_count >= per_file_limit:
                                        break
                                    if not line.strip():
                                        continue
                                    try:
                                        entry = json.loads(line)

                                        # Filter by session if specified
                                        entry_session = entry.get('sessionId', '')
                                        if session_id and entry_session != session_id:
                                            continue

                                        timestamp = entry.get('timestamp')
                                        if not timestamp:
                                            continue

                                        msg = entry.get('message', {})
                                        role = msg.get('role', '')
                                        content = msg.get('content', [])
                                        usage = msg.get('usage', {})

                                        if not isinstance(content, list):
                                            continue

                                        for item in content:
                                            if not isinstance(item, dict):
                                                continue

                                            item_type = item.get('type')

                                            if item_type == 'thinking':
                                                thinking = item.get('thinking', '')
                                                timeline_entries.append({
                                                    'timestamp': timestamp,
                                                    'session_id': entry_session,
                                                    'type': 'thinking',
                                                    'role': role,
                                                    'preview': thinking[:200] + ('...' if len(thinking) > 200 else ''),
                                                    'full_content': thinking,
                                                    'tokens': usage.get('input_tokens', 0) + usage.get('output_tokens', 0),
                                                    'file': jsonl_file.name,
                                                    'is_subagent': is_subagent
                                                })
                                                file_entry_count += 1

                                            elif item_type == 'tool_use':
                                                tool_name = item.get('name', 'unknown')
                                                tool_input = item.get('input', {})
                                                tool_use_id = item.get('id', '')
                                                input_preview = json.dumps(tool_input)[:150]
                                                # Extract agent_type from Task tool calls
                                                agent_type = None
                                                if tool_name == 'Task':
                                                    agent_type = tool_input.get('subagent_type', '')
                                                timeline_entries.append({
                                                    'timestamp': timestamp,
                                                    'session_id': entry_session,
                                                    'type': 'tool_use',
                                                    'role': role,
                                                    'tool': tool_name,
                                                    'tool_use_id': tool_use_id,
                                                    'agent_type': agent_type,
                                                    'preview': f"{tool_name}: {input_preview}",
                                                    'full_content': json.dumps(tool_input, indent=2),
                                                    'file': jsonl_file.name,
                                                    'is_subagent': is_subagent
                                                })
                                                file_entry_count += 1

                                            elif item_type == 'tool_result':
                                                result_content = item.get('content', '')
                                                tool_use_id = item.get('tool_use_id', '')
                                                if isinstance(result_content, list):
                                                    result_content = json.dumps(result_content)
                                                result_preview = str(result_content)[:200]
                                                timeline_entries.append({
                                                    'timestamp': timestamp,
                                                    'session_id': entry_session,
                                                    'type': 'tool_result',
                                                    'role': role,
                                                    'tool_use_id': tool_use_id,
                                                    'preview': result_preview,
                                                    'full_content': str(result_content)[:5000],
                                                    'file': jsonl_file.name,
                                                    'is_subagent': is_subagent
                                                })
                                                file_entry_count += 1

                                            elif item_type == 'text' and role == 'assistant':
                                                text = item.get('text', '')
                                                if text and len(text) > 10:
                                                    timeline_entries.append({
                                                        'timestamp': timestamp,
                                                        'session_id': entry_session,
                                                        'type': 'response',
                                                        'role': role,
                                                        'preview': text[:200] + ('...' if len(text) > 200 else ''),
                                                        'full_content': text[:5000],
                                                        'file': jsonl_file.name,
                                                        'is_subagent': is_subagent
                                                    })
                                                    file_entry_count += 1

                                            elif item_type == 'text' and role == 'user':
                                                text = item.get('text', '')
                                                if text and len(text) > 10:
                                                    timeline_entries.append({
                                                        'timestamp': timestamp,
                                                        'session_id': entry_session,
                                                        'type': 'user_message',
                                                        'role': role,
                                                        'preview': text[:200] + ('...' if len(text) > 200 else ''),
                                                        'full_content': text[:5000],
                                                        'file': jsonl_file.name,
                                                        'is_subagent': is_subagent
                                                    })
                                                    file_entry_count += 1

                                    except json.JSONDecodeError:
                                        continue
                        except Exception:
                            continue

                    # Sort by timestamp descending
                    timeline_entries.sort(key=lambda x: x['timestamp'], reverse=True)

                    # Get unique sessions for filter dropdown
                    sessions = list(set(e['session_id'] for e in timeline_entries if e.get('session_id')))
                    sessions.sort(reverse=True)

                    data = json.dumps({
                        'entries': timeline_entries[offset:offset + limit],
                        'sessions': sessions[:50],
                        'total': len(timeline_entries)
                    })
                except Exception as e:
                    data = json.dumps({
                        'entries': [],
                        'sessions': [],
                        'error': str(e)
                    })

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
