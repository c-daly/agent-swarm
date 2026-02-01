/* Dashboard Alpine.js application */

const COLORS = {
    accent: '#29b6f6', error: '#ff5252', success: '#69f0ae',
    input: '#42a5f5', output: '#ea80fc', cacheRead: '#69f0ae', cacheCreate: '#ffd740',
    palette: ['#29b6f6','#ea80fc','#69f0ae','#ffd740','#ff5252','#18ffff','#ffab40','#ce93d8','#ff4081','#b388ff']
};
const DAYS = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];

// -- Helpers --
async function api(endpoint, params = {}) {
    const clean = {};
    for (const [k, v] of Object.entries(params)) { if (v !== '' && v != null) clean[k] = v; }
    const qs = new URLSearchParams(clean).toString();
    const url = qs ? `/api/${endpoint}?${qs}` : `/api/${endpoint}`;
    const res = await fetch(url);
    return res.json();
}

// Store chart configs for re-rendering in modal
const _chartConfigs = {};

function renderChart(canvasId, type, data, options = {}) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    if (canvas._chart) canvas._chart.destroy();
    const mergedOpts = {
        responsive: true, maintainAspectRatio: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
            legend: { labels: { color: '#ccc', font: { size: 11 } } },
            tooltip: {
                enabled: true,
                backgroundColor: 'rgba(20,20,40,0.95)',
                titleColor: '#4fc3f7',
                bodyColor: '#e0e0e0',
                borderColor: '#2a3a5e',
                borderWidth: 1,
                padding: 10,
                titleFont: { size: 12, weight: 'bold' },
                bodyFont: { size: 11 },
                displayColors: true,
                callbacks: {
                    label: function(ctx) {
                        let label = ctx.dataset.label || '';
                        let val = ctx.parsed.y != null ? ctx.parsed.y : ctx.parsed;
                        if (typeof val === 'number') {
                            if (Math.abs(val) >= 1e6) val = (val/1e6).toFixed(1) + 'M';
                            else if (Math.abs(val) >= 1e3) val = (val/1e3).toFixed(1) + 'K';
                            else val = val.toLocaleString();
                        }
                        return label ? `${label}: ${val}` : val;
                    }
                }
            }
        },
        scales: type === 'pie' || type === 'doughnut' ? {} : {
            x: { ticks: { color: '#999', font: { size: 10 } }, grid: { color: '#333' } },
            y: { beginAtZero: true, ticks: { color: '#999', font: { size: 10 } }, grid: { color: '#333' } }
        },
        ...options
    };
    // Make bar charts more visible by default
    if (type === 'bar') {
        for (const ds of data.datasets) {
            if (!ds.borderWidth) ds.borderWidth = 1;
            if (!ds.borderColor && ds.backgroundColor) ds.borderColor = ds.backgroundColor;
        }
    }
    canvas._chart = new Chart(canvas, { type, data, options: mergedOpts });
    _chartConfigs[canvasId] = { type, data, options: mergedOpts };
}

let _expandedChartId = null;

function expandChart(canvasId) {
    const cfg = _chartConfigs[canvasId];
    if (!cfg) return;
    _expandedChartId = canvasId;
    const overlay = document.getElementById('chart-modal-overlay');
    const modalCanvas = document.getElementById('chart-modal-canvas');
    const title = document.getElementById(canvasId)?.closest('.chart-card')?.querySelector('h3')?.textContent || '';
    document.getElementById('chart-modal-title').textContent = title;
    overlay.style.display = 'flex';
    _renderExpandedChart(cfg);
}

function _renderExpandedChart(cfg) {
    const modalCanvas = document.getElementById('chart-modal-canvas');
    if (modalCanvas._chart) modalCanvas._chart.destroy();
    const expandedOpts = {
        ...cfg.options,
        maintainAspectRatio: false,
        plugins: {
            ...cfg.options.plugins,
            zoom: {
                pan: { enabled: true, mode: 'x' },
                zoom: {
                    wheel: { enabled: true },
                    pinch: { enabled: true },
                    mode: 'x',
                }
            }
        }
    };
    modalCanvas._chart = new Chart(modalCanvas, { type: cfg.type, data: cfg.data, options: expandedOpts });
}

function modalChangeType(newType) {
    const cfg = _chartConfigs[_expandedChartId];
    if (!cfg) return;
    const updated = { ...cfg, type: newType };
    _renderExpandedChart(updated);
}

function modalResetZoom() {
    const modalCanvas = document.getElementById('chart-modal-canvas');
    if (modalCanvas._chart?.resetZoom) modalCanvas._chart.resetZoom();
}

function modalToggleLog() {
    const modalCanvas = document.getElementById('chart-modal-canvas');
    const chart = modalCanvas._chart;
    if (!chart) return;
    const yScale = chart.options.scales?.y;
    if (!yScale) return;
    yScale.type = yScale.type === 'logarithmic' ? 'linear' : 'logarithmic';
    chart.update();
}

function closeChartModal() {
    const overlay = document.getElementById('chart-modal-overlay');
    const modalCanvas = document.getElementById('chart-modal-canvas');
    overlay.style.display = 'none';
    if (modalCanvas._chart) { modalCanvas._chart.destroy(); modalCanvas._chart = null; }
}

function toEST(ts) {
    if (!ts) return '';
    try {
        const d = new Date(ts.endsWith('Z') ? ts : ts + 'Z');
        return d.toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch { return ts; }
}

// -- Main Alpine component --
function dashboard() {
    return {
        view: 'overview',
        filters: { from: '', to: '', period: 'day' },
        // Overview
        overview: null,
        // Tokens
        tokensTimeData: null, tokensToolData: null, tokensAgentData: null,
        // Concurrency
        concData: null, concDrillSession: '', concDrillData: null,
        // Summarization
        summData: null,
        // Sessions
        sessData: null, sessSort: 'tokens', sessPage: 1,
        sessDetail: null, replayData: null, sessAgg: null,
        // Compare
        cmpA: { from: '', to: '' }, cmpB: { from: '', to: '' }, cmpData: null,

        init() { this.loadOverview(); },

        getParams(extra = {}) {
            return { ...this.filters, ...extra };
        },

        async refresh() {
            if (this.view === 'overview') await this.loadOverview();
            else if (this.view === 'tokens') await this.loadTokens();
            else if (this.view === 'tools') await this.loadTools();
            else if (this.view === 'summarization') await this.loadSummarization();
            else if (this.view === 'concurrency') await this.loadConcurrency();
            else if (this.view === 'sessions') await this.loadSessions();
        },

        // -- Formatters --
        fmt(n) { if (n == null) return '-'; return Number(n).toLocaleString(); },
        fmtTokens(n) {
            if (n == null) return '-';
            if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
            if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
            if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
            return String(n);
        },
        pct(n) { if (n == null) return '-'; return (n * 100).toFixed(1) + '%'; },
        fmtDuration(ms) {
            if (ms == null) return '-';
            if (ms < 1000) return ms + 'ms';
            if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
            if (ms < 3600000) return (ms / 60000).toFixed(1) + 'm';
            return (ms / 3600000).toFixed(1) + 'h';
        },
        toEST,
        cmpDelta(key) {
            if (!this.cmpData) return '-';
            const a = this.cmpData.range_a?.data?.[key] || 0;
            const b = this.cmpData.range_b?.data?.[key] || 0;
            const d = b - a;
            return (d >= 0 ? '+' : '') + this.fmt(d);
        },

        // -- Overview --
        async loadOverview() {
            const p = this.getParams();
            const [ov, tokData, heatData, latData] = await Promise.all([
                api('overview', p),
                api('tokens', { ...p, group_by: 'day' }),
                api('activity_heatmap', p),
                api('latency', p)
            ]);
            this.overview = ov;

            // Events over time
            const days = tokData.data || [];
            renderChart('c-overview-events', 'line', {
                labels: days.map(d => d.period),
                datasets: [{ label: 'Events', data: days.map(d => d.event_count), borderColor: COLORS.accent, backgroundColor: COLORS.accent, tension: 0.3, fill: false }]
            });

            // Token spend (input/output as lines, cache_read on right axis)
            renderChart('c-overview-tokens', 'line', {
                labels: days.map(d => d.period),
                datasets: [
                    { label: 'Input', data: days.map(d => d.input), borderColor: COLORS.input, backgroundColor: COLORS.input, tension: 0.3, fill: false, yAxisID: 'y' },
                    { label: 'Output', data: days.map(d => d.output), borderColor: COLORS.output, backgroundColor: COLORS.output, tension: 0.3, fill: false, yAxisID: 'y' },
                    { label: 'Cache Read', data: days.map(d => d.cache_read), borderColor: COLORS.cacheRead, backgroundColor: COLORS.cacheRead, borderDash: [5,3], tension: 0.3, fill: false, yAxisID: 'y1' },
                ]
            }, { scales: {
                y: { type: 'linear', position: 'left', beginAtZero: true, title: { display: true, text: 'Input / Output', color: '#999' }, ticks: { color: '#999' }, grid: { color: '#333' } },
                y1: { type: 'linear', position: 'right', beginAtZero: true, title: { display: true, text: 'Cache Read', color: '#999' }, ticks: { color: '#999' }, grid: { drawOnChartArea: false } },
                x: { ticks: { color: '#999' }, grid: { color: '#333' } }
            } });

            // Heatmap (canvas-based)
            this.renderHeatmap(heatData.data || []);

            // Latency overview
            const latItems = (latData.data || []).slice(0, 10);
            renderChart('c-overview-latency', 'bar', {
                labels: latItems.map(d => d.tool?.substring(0, 20)),
                datasets: [{ label: 'Avg ms', data: latItems.map(d => d.avg_ms), backgroundColor: COLORS.accent, borderColor: COLORS.accent, borderWidth: 1 }]
            });
        },

        renderHeatmap(data) {
            const container = document.getElementById('heatmap-container');
            if (!container) return;
            container.innerHTML = '';
            const grid = document.createElement('div');
            grid.className = 'heatmap';
            const maxCount = Math.max(1, ...data.map(d => d.count));

            // Hour labels row
            const corner = document.createElement('div');
            corner.className = 'label';
            corner.textContent = 'EST';
            corner.style.fontSize = '9px';
            grid.appendChild(corner);
            for (let h = 0; h < 24; h++) {
                const hlabel = document.createElement('div');
                hlabel.className = 'label';
                hlabel.style.fontSize = '9px';
                hlabel.style.textAlign = 'center';
                hlabel.textContent = h % 3 === 0 ? (h === 0 ? '12a' : h < 12 ? h + 'a' : h === 12 ? '12p' : (h-12) + 'p') : '';
                grid.appendChild(hlabel);
            }

            for (let day = 0; day < 7; day++) {
                const label = document.createElement('div');
                label.className = 'label';
                label.textContent = DAYS[day];
                grid.appendChild(label);
                for (let hour = 0; hour < 24; hour++) {
                    const cell = document.createElement('div');
                    cell.className = 'cell';
                    const entry = data.find(d => d.day === day && d.hour === hour);
                    const count = entry ? entry.count : 0;
                    if (count === 0) {
                        cell.style.background = 'rgba(255,255,255,0.03)';
                    } else {
                        // sqrt scale for better low-value visibility
                        const intensity = Math.sqrt(count / maxCount);
                        cell.style.background = `rgba(41,182,246,${intensity * 0.7 + 0.25})`;
                    }
                    cell.dataset.day = DAYS[day];
                    cell.dataset.hour = hour;
                    cell.dataset.count = count;
                    cell.addEventListener('mouseenter', function(e) {
                        let tip = document.getElementById('heatmap-tooltip');
                        if (!tip) {
                            tip = document.createElement('div');
                            tip.id = 'heatmap-tooltip';
                            tip.className = 'heatmap-tooltip';
                            document.body.appendChild(tip);
                        }
                        tip.textContent = `${this.dataset.day} ${this.dataset.hour}:00 — ${Number(this.dataset.count).toLocaleString()} events`;
                        tip.style.display = 'block';
                        const rect = this.getBoundingClientRect();
                        tip.style.left = rect.left + rect.width/2 + 'px';
                        tip.style.top = rect.top - 32 + 'px';
                    });
                    cell.addEventListener('mouseleave', function() {
                        const tip = document.getElementById('heatmap-tooltip');
                        if (tip) tip.style.display = 'none';
                    });
                    grid.appendChild(cell);
                }
            }
            container.appendChild(grid);
        },

        // -- Tokens --
        async loadTokens() {
            const p = this.getParams();
            const [byDay, byTool, byAgent] = await Promise.all([
                api('tokens', { ...p, group_by: 'day' }),
                api('tokens', { ...p, group_by: 'tool', limit: '20' }),
                api('tokens', { ...p, group_by: 'agent' })
            ]);

            const days = byDay.data || [];
            renderChart('c-tokens-time', 'line', {
                labels: days.map(d => d.period),
                datasets: [
                    { label: 'New Input', data: days.map(d => d.input), borderColor: COLORS.input, backgroundColor: COLORS.input, fill: false, tension: 0.3, yAxisID: 'y' },
                    { label: 'Output', data: days.map(d => d.output), borderColor: COLORS.output, backgroundColor: COLORS.output, fill: false, tension: 0.3, yAxisID: 'y' },
                    { label: 'Cache Read', data: days.map(d => d.cache_read), borderColor: COLORS.cacheRead, backgroundColor: COLORS.cacheRead, borderDash: [5,3], fill: false, tension: 0.3, yAxisID: 'y1' },
                    { label: 'Cache Create', data: days.map(d => d.cache_creation), borderColor: COLORS.cacheCreate, backgroundColor: COLORS.cacheCreate, borderDash: [3,2], fill: false, tension: 0.3, yAxisID: 'y1' },
                ]
            }, { scales: {
                y: { type: 'linear', position: 'left', beginAtZero: true, title: { display: true, text: 'New Input / Output', color: '#999' }, ticks: { color: '#999' }, grid: { color: '#333' } },
                y1: { type: 'linear', position: 'right', beginAtZero: true, title: { display: true, text: 'Cache Tokens', color: '#999' }, ticks: { color: '#999' }, grid: { drawOnChartArea: false } },
                x: { ticks: { color: '#999' }, grid: { color: '#333' } }
            } });

            const tools = byTool.data || [];
            renderChart('c-tokens-tool', 'bar', {
                labels: tools.map(d => d.tool?.substring(0, 25)),
                datasets: [{ label: 'Total Tokens', data: tools.map(d => d.total_tokens), backgroundColor: COLORS.accent, borderColor: COLORS.accent, borderWidth: 1 }]
            }, { indexAxis: 'y' });

            // Cache efficiency
            renderChart('c-tokens-cache', 'line', {
                labels: days.map(d => d.period),
                datasets: [{
                    label: 'Cache Reuse %',
                    data: days.map(d => {
                        const total = (d.cache_read || 0) + (d.cache_creation || 0);
                        return total > 0 ? +((d.cache_read || 0) / total * 100).toFixed(1) : 0;
                    }),
                    borderColor: COLORS.cacheRead, backgroundColor: COLORS.cacheRead, fill: false, tension: 0.3
                }]
            });

            // Cache volume
            renderChart('c-tokens-cache-vol', 'line', {
                labels: days.map(d => d.period),
                datasets: [
                    { label: 'Cache Read', data: days.map(d => d.cache_read || 0), borderColor: COLORS.cacheRead, fill: true, backgroundColor: COLORS.cacheRead + '33', tension: 0.3 },
                    { label: 'Cache Create', data: days.map(d => d.cache_creation || 0), borderColor: COLORS.cacheCreate, fill: true, backgroundColor: COLORS.cacheCreate + '33', tension: 0.3 },
                ]
            });

            // By agent role (with agent_type breakdown)
            const roles = byAgent.data || [];
            renderChart('c-tokens-role', 'bar', {
                labels: roles.map(d => d.agent_role),
                datasets: [
                    { label: 'New Input', data: roles.map(d => d.input || 0), backgroundColor: COLORS.input, borderColor: COLORS.input, borderWidth: 1, yAxisID: 'y' },
                    { label: 'Output', data: roles.map(d => d.output || 0), backgroundColor: COLORS.output, borderColor: COLORS.output, borderWidth: 1, yAxisID: 'y' },
                    { label: 'Cache Read', data: roles.map(d => d.cache_read || 0), backgroundColor: COLORS.cacheRead, borderColor: COLORS.cacheRead, borderWidth: 1, yAxisID: 'y1' },
                    { label: 'Cache Create', data: roles.map(d => d.cache_creation || 0), backgroundColor: COLORS.cacheCreate, borderColor: COLORS.cacheCreate, borderWidth: 1, yAxisID: 'y1' },
                ]
            }, { scales: {
                y: { type: 'linear', position: 'left', beginAtZero: true, title: { display: true, text: 'New Input / Output', color: '#999' }, ticks: { color: '#999' }, grid: { color: '#333' } },
                y1: { type: 'linear', position: 'right', beginAtZero: true, title: { display: true, text: 'Cache Tokens', color: '#999' }, ticks: { color: '#999' }, grid: { drawOnChartArea: false } },
                x: { ticks: { color: '#999' }, grid: { color: '#333' } }
            } });
        },

        // -- Concurrency --
        async loadConcurrency() {
            const data = await api('concurrency', this.getParams());
            this.concData = data;
            this.concDrillSession = '';
            this.concDrillData = null;

            // Subagents spawned over time
            const ot = data.over_time || [];
            renderChart('c-conc-over-time', 'line', {
                labels: ot.map(d => d.period),
                datasets: [
                    { label: 'Subagents Spawned', data: ot.map(d => d.subagents_spawned), borderColor: COLORS.accent, backgroundColor: COLORS.accent, fill: false, tension: 0.3 },
                    { label: 'Sessions w/ Subagents', data: ot.map(d => d.sessions_with_subagents), borderColor: COLORS.output, backgroundColor: COLORS.output, fill: false, tension: 0.3 },
                ]
            });

            // Distribution histogram
            const dist = data.distribution || {};
            const bucketOrder = ['1','2','3','4','5','6','7','8','9','10','11-20','21-50','50+'];
            const buckets = bucketOrder.filter(b => dist[b]);
            renderChart('c-conc-dist', 'bar', {
                labels: buckets.map(b => b + ' subagents'),
                datasets: [{ label: 'Sessions', data: buckets.map(b => dist[b] || 0), backgroundColor: COLORS.accent, borderColor: COLORS.accent, borderWidth: 1 }]
            });

            // Agent type breakdown
            const types = data.by_type || [];
            if (types.length > 0) {
                renderChart('c-conc-types', 'doughnut', {
                    labels: types.map(d => d.agent_type),
                    datasets: [{ data: types.map(d => d.event_count), backgroundColor: COLORS.palette }]
                });
            }
        },
        async loadConcurrencyDrill(sessionId) {
            this.concDrillSession = sessionId;
            const data = await api('concurrency', { session: sessionId });
            this.concDrillData = data;
            const events = data.events || [];
            const step = Math.max(1, Math.floor(events.length / 60));
            const labels = [];
            const normalVals = [];
            const errorVals = [];
            for (let i = 0; i < events.length; i += step) {
                const chunk = events.slice(i, i + step);
                const maxConc = Math.max(...chunk.map(e => e.concurrent_count));
                const hasErr = chunk.some(e => e.status === 'error');
                const ts = chunk[0].timestamp || '';
                labels.push(ts.substring(11, 16) || String(i));
                if (hasErr) {
                    errorVals.push(maxConc);
                    normalVals.push(0);
                } else {
                    normalVals.push(maxConc);
                    errorVals.push(0);
                }
            }
            const datasets = [
                { label: 'Peak Concurrent', data: normalVals, backgroundColor: COLORS.accent, borderColor: COLORS.accent, borderWidth: 1 }
            ];
            if (errorVals.some(v => v > 0)) {
                datasets.push({ label: 'Peak Concurrent (errors)', data: errorVals, backgroundColor: COLORS.error, borderColor: COLORS.error, borderWidth: 1 });
            }
            renderChart('c-conc-drill', 'bar', { labels, datasets }, { scales: { x: { stacked: true, ticks: { color: '#999' }, grid: { color: '#333' } }, y: { stacked: true, beginAtZero: true, ticks: { color: '#999' }, grid: { color: '#333' } } } });
        },

        // -- Tools & Errors --
        async loadTools() {
            const p = this.getParams();
            const [toolsData, errType, latData] = await Promise.all([
                api('tools', { ...p, sort: 'count', limit: '20' }),
                api('errors', { ...p, group_by: 'type' }),
                api('latency', { ...p, limit: '15' })
            ]);

            const tools = toolsData.data || [];
            renderChart('c-tools-freq', 'bar', {
                labels: tools.map(d => d.tool?.substring(0, 25)),
                datasets: [{ label: 'Calls', data: tools.map(d => d.call_count), backgroundColor: COLORS.accent, borderColor: COLORS.accent, borderWidth: 1 }]
            }, { indexAxis: 'y' });

            renderChart('c-tools-errors', 'bar', {
                labels: tools.map(d => d.tool?.substring(0, 25)),
                datasets: [{ label: 'Error Rate', data: tools.map(d => +((d.error_rate || 0) * 100).toFixed(1)), backgroundColor: COLORS.error, borderColor: COLORS.error, borderWidth: 1 }]
            }, { indexAxis: 'y' });

            const errs = errType.data || [];
            renderChart('c-error-types', 'pie', {
                labels: errs.slice(0, 8).map(d => (d.error_type || 'unknown').substring(0, 30)),
                datasets: [{ data: errs.slice(0, 8).map(d => d.count), backgroundColor: COLORS.palette }]
            });

            const latItems = latData.data || [];
            renderChart('c-tools-latency', 'bar', {
                labels: latItems.map(d => d.tool?.substring(0, 20)),
                datasets: [
                    { label: 'Avg ms', data: latItems.map(d => d.avg_ms), backgroundColor: COLORS.accent, borderColor: COLORS.accent, borderWidth: 1 },
                    { label: 'Max ms', data: latItems.map(d => d.max_ms), backgroundColor: COLORS.error, borderColor: COLORS.error, borderWidth: 1 },
                ]
            }, { indexAxis: 'y' });
        },

        // -- Summarization --
        async loadSummarization() {
            const data = await api('summarization', this.getParams());
            this.summData = data;

            // Compression ratio + bytes saved over time
            const ot = data.over_time || [];
            renderChart('c-summ-compression', 'line', {
                labels: ot.map(d => d.period),
                datasets: [
                    { label: 'Compression Ratio', data: ot.map(d => d.compression_ratio ? +(d.compression_ratio * 100).toFixed(1) : 0), borderColor: COLORS.accent, backgroundColor: COLORS.accent, fill: false, tension: 0.3, yAxisID: 'y' },
                    { label: 'Bytes Saved', data: ot.map(d => (d.original_size || 0) - (d.summary_size || 0)), borderColor: COLORS.cacheRead, backgroundColor: COLORS.cacheRead, fill: false, tension: 0.3, yAxisID: 'y1' },
                ]
            }, { scales: {
                y: { type: 'linear', position: 'left', beginAtZero: true, title: { display: true, text: 'Compression %', color: '#999' }, ticks: { color: '#999' }, grid: { color: '#333' } },
                y1: { type: 'linear', position: 'right', beginAtZero: true, title: { display: true, text: 'Bytes Saved', color: '#999' }, ticks: { color: '#999' }, grid: { drawOnChartArea: false } },
                x: { ticks: { color: '#999' }, grid: { color: '#333' } }
            } });

            // Top tools by summarization with bytes saved
            const tools = data.by_tool || [];
            renderChart('c-summ-tools', 'bar', {
                labels: tools.map(d => d.tool?.substring(0, 25)),
                datasets: [
                    { label: 'Summarized Count', data: tools.map(d => d.summarized_count), backgroundColor: COLORS.accent, borderColor: COLORS.accent, borderWidth: 1 },
                ]
            }, { indexAxis: 'y' });

            // Tool compression efficiency
            renderChart('c-summ-tool-compression', 'bar', {
                labels: tools.map(d => d.tool?.substring(0, 25)),
                datasets: [
                    { label: 'Avg Compression %', data: tools.map(d => +((d.avg_compression || 0) * 100).toFixed(1)), backgroundColor: COLORS.cacheRead, borderColor: COLORS.cacheRead, borderWidth: 1 },
                ]
            }, { indexAxis: 'y' });

            // By agent role
            const roles = data.by_agent_role || [];
            renderChart('c-summ-role', 'bar', {
                labels: roles.map(d => d.agent_role),
                datasets: [
                    { label: 'Summarized', data: roles.map(d => d.summarized_count), backgroundColor: COLORS.accent, borderColor: COLORS.accent, borderWidth: 1 },
                    { label: 'Total', data: roles.map(d => d.total_events), backgroundColor: COLORS.palette[1], borderColor: COLORS.palette[1], borderWidth: 1 },
                ]
            });
        },

        // -- Sessions --
        async loadSessions() {
            this.sessData = await api('sessions', { ...this.getParams(), sort: this.sessSort, page: this.sessPage });
            if (!this.sessDetail) this.renderSessionsAggregate();
        },
        async renderSessionsAggregate() {
            const agg = await api('sessions/aggregate', this.getParams());
            this.sessAgg = agg;
            const b = agg.buckets || [];
            const labels = b.map(d => d.period);

            renderChart('c-sess-tokens', 'bar', {
                labels,
                datasets: [
                    { label: 'Avg Tokens/Session', data: b.map(d => Math.round(d.avg_tokens || 0)), backgroundColor: COLORS.accent, borderColor: COLORS.accent, borderWidth: 1 },
                    { label: 'Sessions', data: b.map(d => d.session_count), backgroundColor: COLORS.output, borderColor: COLORS.output, borderWidth: 1, yAxisID: 'y1' },
                ]
            }, { scales: {
                y: { beginAtZero: true, position: 'left', title: { display: true, text: 'Avg Tokens', color: '#999' }, ticks: { color: '#999' }, grid: { color: '#333' } },
                y1: { beginAtZero: true, position: 'right', title: { display: true, text: 'Sessions', color: '#999' }, ticks: { color: '#999' }, grid: { drawOnChartArea: false } },
                x: { ticks: { color: '#999' }, grid: { color: '#333' } }
            } });

            renderChart('c-sess-duration', 'bar', {
                labels,
                datasets: [{ label: 'Avg Duration (ms)', data: b.map(d => Math.round(d.avg_duration || 0)), backgroundColor: COLORS.output, borderColor: COLORS.output, borderWidth: 1 }]
            });

            renderChart('c-sess-events', 'bar', {
                labels,
                datasets: [{ label: 'Avg Events/Session', data: b.map(d => Math.round(d.avg_events || 0)), backgroundColor: COLORS.cacheRead, borderColor: COLORS.cacheRead, borderWidth: 1 }]
            });

            renderChart('c-sess-errors', 'bar', {
                labels,
                datasets: [{ label: 'Avg Errors/Session', data: b.map(d => +(d.avg_errors || 0).toFixed(1)), backgroundColor: COLORS.error, borderColor: COLORS.error, borderWidth: 1 }]
            });
        },
        async loadSessionDetail(sid) {
            this.sessDetail = await api(`session/${sid}`);
            this.replayData = null;
            const events = this.sessDetail.events || [];
            if (events.length > 0) {
                renderChart('c-session-timeline', 'bar', {
                    labels: events.map((e, i) => i),
                    datasets: [{
                        label: 'Duration ms',
                        data: events.map(e => e.duration_ms),
                        backgroundColor: events.map(e => e.status === 'error' ? COLORS.error : COLORS.accent)
                    }]
                }, { plugins: { legend: { display: false } } });
            }
        },
        async loadReplay(sid) {
            this.replayData = await api(`session/${sid}/replay`);
        },

        // -- Compare --
        async loadCompare() {
            this.cmpData = await api('compare', {
                from_a: this.cmpA.from, to_a: this.cmpA.to,
                from_b: this.cmpB.from, to_b: this.cmpB.to
            });
        },
    };
}

// Delegate chart-card clicks to expandChart
document.addEventListener('click', function(e) {
    const card = e.target.closest('.chart-card');
    if (!card) return;
    // Don't expand if clicking controls or buttons inside the card
    if (e.target.closest('.chart-controls') || e.target.closest('button') || e.target.closest('select') || e.target.closest('input')) return;
    const canvas = card.querySelector('canvas');
    if (canvas && canvas.id) expandChart(canvas.id);
});
