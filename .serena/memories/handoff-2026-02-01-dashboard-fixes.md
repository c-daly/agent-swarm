# Handoff: Dashboard Fixes & Import Pipeline

## Date: 2026-02-01
## Branch: feature/dashboard

## What Was Done

### 1. Fixed HTML/JS Mismatches in index.html
The HTML was out of sync with the refactored app.js. An Alpine error (`concurrencySession is not defined`) was breaking reactivity across the entire page, killing chart click-to-expand.

**Concurrency section** (root cause of Alpine crash):
- `concurrencySession` → `concDrillSession`
- `concurrencySessions` → `concData.top_sessions`
- `concurrencyData` → `concDrillData`
- `loadConcurrencyDetail()` → `loadConcurrencyDrill(concDrillSession)`
- Added canvas IDs: `c-conc-over-time`, `c-conc-dist`, `c-conc-types`, `c-conc-drill`

**Summarization section**:
- Replaced `c-summ-time` (no match in app.js) with `c-summ-compression`
- Added `c-summ-tools`, `c-summ-tool-compression`

**Tokens section**: Added missing `c-tokens-cache-vol` canvas

**Sessions section**: Added 4 aggregate charts: `c-sess-tokens`, `c-sess-duration`, `c-sess-events`, `c-sess-errors`

**Chart modal**: Added missing overlay HTML (CSS existed in style.css already)

**Chart click handlers**: Added delegated click listener on `.chart-card` → `expandChart(canvasId)`

### 2. Dashboard Import Pipeline in Controller
Added `Controller.run_dashboard_import()` in `lib/controller.py`:
- Uses `importlib` to load `dashboard/import.py` (reserved keyword filename)
- Calls `init_db()` + `import_claude_transcripts()` against `dashboard/data/dashboard.db`
- Runs automatically on daemon startup (background thread)
- Exposed as `router__import_dashboard` tool for on-demand calls
- CLI command: `python3 lib/daemon.py --import-dashboard`

### 3. Real get_full Test
Did a real `router__get_full` tool call through Claude (not manual socket):
- `mcp__router__native__read_file` on controller.py → summarized with content_id
- `mcp__router__router__get_full` with content_id → full 679-line content
- Both calls recorded in router telemetry (`data/datastore.db`)
- Will appear in JSONL transcript on next import → dashboard Full Requests counter

## Outstanding Issues

### Token Numbers Need Work
- Dashboard `input + output` = 8.2M vs Anthropic's reported 6.7M all-time
- `cache_read_tokens` sums to 3.5 BILLION — it's the same ~80K context re-read every API call
- Cache tokens displayed on separate chart axes (good) but could still confuse
- Need to decide: show raw API numbers, or normalize to billing-equivalent?
- Possible sources of 8.2M vs 6.7M gap: DuckDB legacy data, subagent attribution

### Not Yet Verified
- The HTML fixes haven't been browser-tested yet
- The `--import-dashboard` CLI command hasn't been tested against running daemon
- `run_dashboard_import()` startup thread hasn't been tested (daemon needs restart)

## Files Modified
- `dashboard/static/index.html` — HTML/JS alignment, chart modal, click handlers
- `dashboard/static/app.js` — chart-card click delegation listener
- `lib/controller.py` — `run_dashboard_import()` method, router tool, startup thread
- `lib/daemon.py` — `--import-dashboard` CLI subcommand

## Next Steps
1. Restart daemon, verify import runs on startup (check `logs/daemon.log`)
2. Browser-test all dashboard tabs, especially concurrency and chart expand
3. Run `python3 lib/daemon.py --import-dashboard` to verify CLI
4. Decide on token display strategy (billing-equivalent vs raw)
5. Consider renaming `dashboard/import.py` → `dashboard/importer.py` to avoid keyword issue
