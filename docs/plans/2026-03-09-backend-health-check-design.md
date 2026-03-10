# Backend Health-Check Thread Design

**Date:** 2026-03-09  
**Status:** Approved

## Problem

The daemon's `BackendManager` uses lazy spawning — backends are only started when a tool is first called. If a backend (e.g. serena) crashes and no tool call follows for an extended period, it stays disconnected indefinitely. This caused a 3-day serena outage (2026-03-06 to 2026-03-09).

## Solution

Add a periodic health-check thread to `Controller` that proactively reconnects any disconnected external backend.

## Design

### Location

`lib/controller.py` — new private method `_run_health_checks()` started as a daemon thread in `__init__`.

### Behaviour

- Runs every **60 seconds** (configurable constant)
- Iterates `self.backends.list()` — all external backends (serena, context7, playwright)
- Calls `self.backends.list_tools(name)` for each:
  - If connection is live and tools are cached → returns instantly (no-op)
  - If connection is dead → triggers lazy-spawn + MCP handshake (existing `_get_connection` logic)
- Logs `WARNING` on failure, `INFO` on successful reconnect
- Swallows all exceptions — thread must never die

### Thread

- `daemon=True` so it doesn't block clean shutdown
- No new locks needed — `BackendManager` already has per-backend `RLock`

## Files Changed

| File | Change |
|------|--------|
| `lib/controller.py` | Add `_run_health_checks()` + thread start in `__init__` |

## Files Unchanged

`backends.py`, `daemon.py`, `router.py`, `config/backends.json`
