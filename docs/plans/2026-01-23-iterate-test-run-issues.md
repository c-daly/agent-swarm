# Iterate Test Run Issues

**Date:** 2026-01-23
**Purpose:** Track issues found during dogfooding before LOGOS run

---

## Issues Found

### 1. No Automatic Task Queue Generation
**Problem:** Orchestrator started without a task queue. I jumped to spawning agents without first creating/loading tasks.

**Expected:** ORCHESTRATE phase should either:
- Load task queue from file (--json flag)
- Generate tasks from design doc/spec
- Prompt user if no input provided

**Fix needed:** Wire input adapters into iterate workflow startup, or add check that queue exists before spawning.

---

### 2. Hook Requires run_in_background=true
**Problem:** `background-enforcement.py` hook blocked Task calls without `run_in_background=true`.

**This is correct behavior** - enforces parallel execution pattern.

**Documentation needed:** Add this requirement to SKILL.md and agent prompts.

---

### 3. Manual Task Queue Creation
**Problem:** Had to manually create `.state/orchestrator-queue.json` with Python script.

**Expected:** Either:
- Input adapter loads from specified file
- Design doc parser generates tasks
- CLI prompts for task list

**Fix needed:** Implement JsonQueueAdapter to load from file specified via --json flag.

---

### 4. Task Queue Location Unclear
**Problem:** Created queue in `.state/orchestrator-queue.json` but iterate workflow may expect different location.

**Check:** Where does `load_queue()` in orchestrate.py look for the queue?

---

### 5. Task-to-Agent Mapping
**Problem:** No automatic mapping from task queue items to spawned agents. Manually copied task prompts.

**Expected:** Orchestrator should:
1. Read task from queue
2. Build prompt from task.prompt field
3. Spawn agent with that prompt
4. Track agent_id → task_id mapping

**Fix needed:** Add this logic to orchestrate.py spawn loop.

---

### 6. Subagents Use Wrong Tools (CRITICAL) - FIXED
**Problem:** Spawned subagents tried to use direct tools (Bash, Glob, Read, mcp__filesystem__*, mcp__plugin_serena_serena__*) which were auto-denied due to "prompts unavailable".

**Root Cause:** Subagents don't understand they have equivalent MCP router tools that ARE available:
- `mcp__plugin_agent-swarm_router__native__read_file` instead of `Read`
- `mcp__plugin_agent-swarm_router__native__glob` instead of `Glob`
- `mcp__plugin_agent-swarm_router__native__bash` instead of `Bash`
- `mcp__plugin_agent-swarm_router__serena__*` instead of `mcp__plugin_serena_serena__*`

**Fixes Applied:**
1. ✅ Created `hooks/subagent-tool-redirect.py` - PreToolUse hook that intercepts blocked tools for subagents and returns error message with correct router tool to use
2. ✅ Added hook to `hooks/hooks.json` (runs first in PreToolUse chain)
3. ✅ Updated `hooks/subagent-enforcement.py` - Added explicit tool table to `build_tdd_context()` showing which tools to use
4. ✅ Updated all phase-specific contexts (test_writing, implement, test, review) with tool reminders

**Severity:** CRITICAL - ~~subagents are completely non-functional without this fix~~ FIXED

---

### 7. Subagents Did Not Follow TDD Phases - FIXED
**Problem:** Subagents immediately tried to implement without writing tests first.

**Expected:** TDD workflow: test_writing → implement → test → review

**Fixes Applied:**
1. ✅ Strengthened `build_test_writing_context()` - explicit "DO NOT skip to implementation" warning
2. ✅ Each phase context now includes clear instructions and phase-specific restrictions
3. ✅ TEST phase explicitly states "DO NOT edit files in this phase"

---

## Pending Verification

- [ ] Do spawned agents receive phase context injection?
- [ ] Does retry_or_escalate work when agent fails?
- [ ] Is task marked complete when agent finishes?
- [ ] Are dependent tasks unblocked correctly?

---

## Notes for LOGOS Run

1. Create task queue JSON files in each repo first
2. Ensure all 75 tasks have `prompt` field populated
3. Test with 3-5 tasks before full run
4. Monitor for context explosion with many parallel agents
