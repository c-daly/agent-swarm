# Handoff: Hooks Refactor (2026-02-01, Session 2)

## Branch
`feature/hooks-refactor` based off `dev` (post PR #66 merge)

## Commits (7 total)
- `9d78c09` — removed `router-event-hook.py` (dead code, old async API)
- `3be6e6a` — removed `subagent-mcp-bypass.py` (overridden by native-tool-blocking.py)
- `fe57952` — simplified `native-tool-blocking.py`, moved native tool deny list to settings.json
- `b3ba833` — moved task enforcement logic into router controller (`_check_task_enforcement`)
- `401fae3` — removed `post-tool-hook.py`, moved active_agents tracking to SubagentStart
- `e279a1c` — simplified telemetry pair: 1-file state, dropped poetry run from pretool, stripped dead code from posttool
- `2e63f25` — aggressively simplified session-start.py (550→200 lines), removed 6 subsystems

## Current Hook Inventory

### hooks.json (7 hooks across 7 events)

| Event | Hook | Status |
|-------|------|--------|
| PreToolUse:* | native-tool-blocking.py | REFACTORED (bash filter + subagent sandbox) |
| PreToolUse:* | telemetry-pretool.py | SIMPLIFIED (1-file state, no poetry run) |
| PreToolUse:Task | task-enforcement.py | REFACTORED (thin client to router) |
| PostToolUse:* | telemetry-posttool.py | SIMPLIFIED (stripped token estimates, transcript parsing) |
| PreCompact:* | pre-compacting.py | UNCHANGED (handoff + flag persistence) |
| SubagentStart:* | subagent-enforcement.py | UPDATED (added active_agents tracking) |
| SubagentStop:* | subagent-complete.py | UNCHANGED (completion + learning capture) |
| SessionStart | session-start.py | SIMPLIFIED (removed inventory, episodic search, context hierarchy, memory patterns, JSONL processing) |
| SessionEnd | session-end.py | UNCHANGED (dashboard, compression, distillation) |

### Removed Hooks
- `router-event-hook.py` — dead code
- `subagent-mcp-bypass.py` — redundant with native-tool-blocking
- `post-tool-hook.py` — redundant with subagent lifecycle hooks

## Known Issues
- **Ghost post-tool-hook error**: Cached hooks.json still references deleted file until restart
- **Stale port file**: `.state/router.port` — `workflow_client.py` reads it but `mcp-router` uses DAEMON_PORT env var
- **telemetry-posttool still uses `poetry run`**: Needs duckdb which is a poetry dependency

## Remaining Work
- `pre-compacting.py` — could simplify by querying router for state instead of reading session.json directly
- `subagent-enforcement.py` — large (300 lines) but functional, TDD context injection works
- `subagent-complete.py` — could move workflow state update to router
- `session-end.py` — multiple responsibilities but session-end is the right place for cleanup
- Migrate `workflow_client.py` from port file to DAEMON_PORT env var
- Restart and verify all hooks work correctly with the new slimmed set