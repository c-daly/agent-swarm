# Hook Consolidation Design

**Date:** 2026-01-30
**Goal:** Reduce hook count from 17 active → 12, delete ~24 dead files. No behavioral changes.
**Context:** Pre-work ahead of a larger router refactoring that will obviate most hooks.

---

## Phase 1: Orphan Cleanup

Delete 17 orphaned hook files (not wired in `hooks.json`) and their ~7 orphaned test files.

**Keep:** `hook_logging.py` — shared utility imported by 5 active hooks.

### Hook files to delete

```
hooks/auto-orchestrate-hook.sh
hooks/base-enforcement.py
hooks/combined_enforcement.py
hooks/context-injection.py
hooks/enforce-protocol.sh
hooks/iterate-enforcement.py
hooks/max-agents-enforcement.py
hooks/monitor_agent.py
hooks/nonblocking-enforcement.py
hooks/parallel-enforcement.py
hooks/state-protection.py
hooks/subagent-bash-lockdown.py
hooks/test-existence-enforcement.py
hooks/transcript-debug.py
hooks/verification_gates.py
hooks/workflow-enforcement.py
hooks/workflow-state-enforcement.py
```

### Test files to delete

```
tests/test_max_agents_hook.py
tests/test_test_existence_hook.py
tests/test_parallel_enforcement.py
tests/test_nonblocking_enforcement.py (if exists)
tests/test_monitor_agent.py
tests/test_base_enforcement.py
tests/test_orchestrator_blocking.py
```

---

## Phase 2: Task PreToolUse Consolidation (3→1)

**Current:** Three separate hooks on `PreToolUse:Task`:
1. `background-enforcement.py` — checks `run_in_background=true`
2. `implementer-only-enforcement.py` — checks subagent type during iterate workflow
3. `inject-subagent-briefing.sh` — checks prompt contains `SUBAGENT OPERATING PROTOCOL`

**Action:** Create `task-enforcement.py` combining all three checks. Check order (fail-fast on cheapest):
1. Background enforcement (pure parameter check, no I/O)
2. Briefing enforcement (string search in prompt, no I/O — replaces bash/jq with Python)
3. Implementer-only enforcement (requires `workflow_client` call)

**Delete after merge:**
- `hooks/background-enforcement.py`
- `hooks/implementer-only-enforcement.py`
- `hooks/inject-subagent-briefing.sh`

**Update `hooks.json`:** Replace three `PreToolUse:Task` hook entries with single `task-enforcement.py`.

---

## Phase 3: PostToolUse Tracking Consolidation (2→1)

**Current:** Two hooks on PostToolUse:
1. `post-tool-tracking.py` (166 lines, `PostToolUse:*`) — tracks subagent spawns + function signature changes
2. `post-task-tracking.py` (249 lines, `PostToolUse:Task`) — tracks subagent completion, token usage

Both share: `hook_logging` imports, same state directory, disabled metrics features, subagent tracking.

**Action:** Create `post-tool-hook.py` combining both. Use `tool_name == "Task"` to gate task-specific logic.

**Delete after merge:**
- `hooks/post-tool-tracking.py`
- `hooks/post-task-tracking.py`

**Update `hooks.json`:** Replace both PostToolUse entries with single `post-tool-hook.py` on `PostToolUse:*`.

---

## Phase 4: SessionStart Consolidation (3→1)

**Current:** Three hooks on SessionStart:
1. `session-start.py` (918 lines) — memory search, counter reset, capability injection
2. `session-init.py` (98 lines) — permission store query, injects workflow constraints
3. `telemetry-sessionstart.py` (79 lines) — batch processes historical JSONL files

**Action:** Absorb `session-init.py` and `telemetry-sessionstart.py` into `session-start.py`.
- Add permission query call (from `session-init.py`) as a new function in `session-start.py`
- Add JSONL batch processing call (from `telemetry-sessionstart.py`) as a new function in `session-start.py`
- Both are small, self-contained additions

**Delete after merge:**
- `hooks/session-init.py`
- `hooks/telemetry-sessionstart.py`

**Update `hooks.json`:** Remove `session-init.py` and `telemetry-sessionstart.py` entries from SessionStart.

---

## Result

### hooks.json after all changes

```
PreToolUse:
  mcp__router__router__*  → router-event-hook.py        (unchanged)
  mcp__*                  → subagent-mcp-bypass.py       (unchanged)
  *                       → native-tool-blocking.py      (unchanged)
                          → telemetry-pretool.py          (unchanged)
  Task                    → task-enforcement.py           (NEW: 3→1)

PostToolUse:
  *                       → telemetry-posttool.py         (unchanged)
                          → post-tool-hook.py             (NEW: 2→1)

PreCompact:
  *                       → pre-compacting.py             (unchanged)

SubagentStart:
  *                       → subagent-enforcement.py       (unchanged)

SubagentStop:
  *                       → subagent-complete.py          (unchanged)

SessionStart:
                          → session-start.py              (absorbs 2 others)

SessionEnd:
                          → session-end.py                (unchanged)
```

**Total: 12 hooks** (down from 17), **~24 dead files removed**.

### Risk Assessment

- **Phase 1 (orphan cleanup):** Zero risk — files are not wired in hooks.json.
- **Phase 2 (task enforcement):** Low risk — logic is simple conditional checks. Unit test the merged hook.
- **Phase 3 (post-tool tracking):** Low risk — both hooks have disabled features. The merge simplifies.
- **Phase 4 (session-start absorption):** Medium risk — session-start.py is already 918 lines. Adding more logic increases complexity. However, both absorbed pieces are small and self-contained.

### Implementation Order

1. Phase 1 first (safe, immediate cleanup)
2. Phase 2 (simplest consolidation, easy to test)
3. Phase 3 (moderate, disabled features can be removed during merge)
4. Phase 4 (most complex, touch the largest file last)
