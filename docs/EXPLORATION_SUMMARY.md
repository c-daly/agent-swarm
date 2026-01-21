# Agent Anti-Patterns Exploration Summary

**Date:** 2026-01-20  
**Scope:** Analysis of hooks, lib/, and enforcement mechanisms for anti-pattern detection

---

## Executive Summary

The codebase has **comprehensive enforcement infrastructure** detecting 8 distinct anti-patterns across orchestrator and subagent behaviors. Current implementation covers:

✓ **7 active detection hooks** (PreToolUse/PostToolUse)
✓ **Phase-based restrictions** (TDD workflow enforcement)
✓ **Parallel execution validation** (sequential spawn blocking)
✓ **Token budget tracking** (telemetry infrastructure)

**Recommendations:**
1. Add 3 new hooks for emerging anti-patterns (token overflow, file conflicts, phase transitions)
2. Enhance telemetry for better visibility into anti-pattern prevalence
3. Improve test coverage for edge cases

---

## Anti-Patterns Detected (Comprehensive List)

### Primary Detection Mechanisms

| # | Anti-Pattern | Current Hook | Status | Trigger |
|---|---|---|---|---|
| 1 | Orchestrator editing directly | `base-enforcement.py` + `iterate-enforcement.py` | ✓ Active | Edit/Write in orchestrate phase |
| 2 | Subagent skipping test phases | `iterate-enforcement.py` (phase model) | ✓ Active | Phase transition violations |
| 3 | Subagent not registering | `subagent-enforcement.py` (context injection) | ✓ Active | No agent_set_state call |
| 4 | Sequential task spawning | `parallel-enforcement.py` | ✓ Active | 3+ Task calls in 5 sec |
| 5 | Missing run_in_background | `background-enforcement.py` | ✓ Active | Task without flag |
| 6 | Classification mismatches | `monitor_agent.py` (Haiku validation) | ✓ Active | TRIVIAL + multi-file edits |
| 7 | Calling workflow.start() | Code review + logging | ⚠️ Manual | Subagent reinits state |
| 8 | Infinite loops (high token use) | **[NEW]** token-overflow detection | ⚪ Proposed | call_count > 100 |

---

## Enforcement Architecture

### Hook Locations & Responsibilities

```
/hooks/ (10 active + 3 enforcement)
├─ base-enforcement.py
│  └─ "No workflow = no editing" (foundational rule)
│
├─ iterate-enforcement.py
│  └─ Phase-based tool restrictions (test_writing/implement/test/review)
│
├─ subagent-enforcement.py
│  └─ Subagent context injection + TDD workflow messaging
│     • Injects agent_id, phase, mode to subagent
│     • Forces implementers to test_writing phase
│     • Blocks TDD phase skipping
│
├─ parallel-enforcement.py
│  └─ Sequential task detection
│     • Tracks spawns within 5-second window
│     • Allow: 0, Warn: 1, Block: 2+
│
├─ background-enforcement.py
│  └─ Enforces run_in_background=true on Task tool
│
├─ monitor_agent.py
│  └─ Contextual validation (Haiku API)
│     • Git commit message validation
│     • Classification appropriateness check
│     • 100-500ms latency (API call)
│
├─ post-task-tracking.py
│  └─ Telemetry collection (PostToolUse)
│     • Log subagent completion
│     • Extract metrics from output
│     • Periodic plugin autodiscovery
│
└─ [Additional hooks]
   ├─ session-start.py, session-end.py (lifecycle)
   ├─ verification_gates.py (review gate)
   ├─ state-protection.py (state race conditions)
   ├─ work_seeker.py (task dependency tracking)
   └─ max-agents-enforcement.py (resource limits)
```

### Phase Restriction Model

**File:** `/lib/phase_model.py`

Enforces TDD workflow with tool categories:

```python
PHASES = {
    "test_writing": {
        allowed: [FILE_READ, FILE_WRITE, SHELL_SAFE],
        blocked: [CODE_EDIT]  # Can't edit implementation yet
    },
    "implement": {
        allowed: [FILE_READ, FILE_WRITE, CODE_EDIT, SHELL_SAFE],
        blocked: []  # All tools available for implementation
    },
    "test": {
        allowed: [FILE_READ, SHELL_SAFE],  # pytest only
        blocked: [FILE_WRITE, CODE_EDIT]  # No more changes
    },
    "review": {
        allowed: [FILE_READ, USER_INTERACTION],
        blocked: [FILE_WRITE, CODE_EDIT, SHELL_SAFE]  # Read-only
    }
}
```

---

## Key Findings from Code Analysis

### 1. Orchestrator Phase Enforcement (Most Restrictive)

**File:** `subagent-enforcement.py` (lines 80-100)

```python
# CRITICAL FIX: When spawning implementer in iterate-tdd from orchestrate phase,
# force the subagent to start in test_writing phase (not parent's orchestrate phase)
if mode == "iterate-tdd" and phase == "orchestrate" and agent_type == "implementer":
    phase = "test_writing"  # ← Subagent starts here, not parent's phase
```

**Why:** Prevents subagent from skipping TDD phases by inheriting orchestrator's phase.

### 2. Sequential Spawn Detection (Warn then Block)

**File:** `parallel-enforcement.py` (lines 45-95)

```python
recent_count = len(clean_old_spawns(state["recent_spawns"], current_time))

if recent_count == 0:
    # First spawn - always allow
    return "allow"
elif recent_count == 1:
    # Second spawn - WARN
    return "allow" + warning_message
else:
    # Third or more - BLOCK
    return "deny" with "Must spawn in parallel block"
```

**Impact:** Enforces efficient parallel execution of independent tasks.

### 3. TDD Workflow Injection (Context-Based)

**File:** `subagent-enforcement.py` (lines 110-150)

Injects this into subagent context:

```
## TDD Workflow (Follow This Order)

1. TEST_WRITING - Write failing tests first
   - These tests define what success looks like
   - Tests should fail initially (no implementation yet)

2. IMPLEMENT - Write code to make tests pass
   - Focus on making tests pass, nothing more
   - Keep implementation minimal

3. TEST - Run tests and verify
   - All tests must pass
   - Check linting/type checking if applicable

4. REVIEW - Self-review before completion
   - Check for obvious issues
   - Ensure code matches requirements
```

**Key:** Message explicitly forbids calling `start()` and writing to iterate.json.

### 4. Subagent State Registration

**File:** `subagent-enforcement.py` (lines 65-75)

```python
agent_state = {
    "phase": phase,           # Injected to subagent
    "mode": mode,
    "task": task_desc,
    "parent_session": session_id,
}
agent_set_state(agent_id, agent_state)  # Registers with orchestrator
```

**Impact:** Enables orchestrator to track max_agents and detect hung agents.

### 5. Workspace State Management

**Files:**
- `/lib/workflow_client.py` - State server client (MCP-based)
- `/lib/worker_pool.py` - Active agent tracking
- State keys: `workflow.iterate.{phase,mode}`, `agent.{id}.{state}`

---

## Detection Coverage

### Well-Protected Scenarios ✓

| Scenario | Detection | Enforcement |
|----------|-----------|-------------|
| Orchestrator uses Edit in orchestrate phase | `iterate-enforcement.py` | Block immediately |
| Subagent tries CODE_EDIT in test_writing | `iterate-enforcement.py` + phase model | Block (tool not allowed) |
| Task without run_in_background | `background-enforcement.py` | Block |
| 3rd sequential Task spawn | `parallel-enforcement.py` | Block after 5-second window |
| First edit classified as TRIVIAL but multi-file | `monitor_agent.py` | Block (Haiku validation) |

### Under-Protected Scenarios ⚠️

| Scenario | Current Detection | Gap |
|----------|---|---|
| Subagent makes 150+ tool calls | None (PostToolUse only) | **[NEW]** token-overflow-detection |
| Multiple agents edit same file | None | **[NEW]** workspace-validation |
| Subagent transitions backwards (implement → test_writing) | None (phase model only checks forward) | **[NEW]** phase-transition-validation |
| Subagent returns false completion status | post-task-tracking only logs | Enhancement needed |
| Test file orphaned (written but no code) | None | Enhancement to phase-exit validation |

---

## Current Telemetry Infrastructure

### Collection Points

**File:** `/hooks/post-task-tracking.py`

```python
def track_subagent(agent_id, agent_type, prompt):
    metrics[agent_id] = {
        "spawned_at": datetime.now().isoformat(),
        "agent_type": agent_type,
        "status": "completed",
        "prompt": prompt[:100]
    }
    # Saved to ~/.claude/plugins/agent-swarm/.state/subagent_metrics.json
```

### Telemetry Files

```
~/.claude/plugins/agent-swarm/.state/
├─ iterate.log                    # All workflow events
├─ subagent_metrics.json          # Per-agent completion
├─ plugin_check_count.txt         # Auto-plugin discovery trigger
└─ post_task_debug.log            # Hook debug output (DISABLED)
```

### Visualization

**File:** `/scripts/charts.py`

- Loads telemetry from disk
- Generates daily summaries
- Shows token trends per agent
- Supports v1 and v2 schema

---

## Implementation Recommendations

### Priority 1: Add New Detection Hooks (High Value)

**1. Token Overflow Detection**
- **Location:** `/hooks/token-overflow-detection.py` (NEW)
- **Trigger:** PostToolUse after Task completes
- **Detection:** call_count > 100 (infinite loop indicator)
- **Action:** Log warning + suggest investigation
- **Effort:** Low (1-2 hours)

**2. Phase Transition Validation**
- **Location:** `/hooks/phase-transition-validation.py` (NEW)
- **Trigger:** PreToolUse or session hook
- **Detection:** Invalid transitions (e.g., implement → test_writing)
- **Action:** Log pattern + telemetry
- **Effort:** Low-Medium (2-3 hours)

**3. Workspace Conflict Detection**
- **Location:** `/hooks/workspace-validation.py` (NEW)
- **Trigger:** PostToolUse after file modifications
- **Detection:** Multiple agents editing same file
- **Action:** Warn about conflicts + save to tracking
- **Effort:** Medium (3-4 hours)

### Priority 2: Enhance Existing Infrastructure

**1. Improve Token Budget Tracking**
- Add per-phase token breakdown
- Alert when single task >80% of budget
- Track cumulative token usage by agent type

**2. Add Test Pair Validation**
- When exiting test phase, verify test files exist
- When implement phase exits, verify code files changed
- Track orphaned test/code files

**3. Enhanced Failure Attribution**
- Log which agent made which changes
- Track failures to specific commits
- Enable easier debugging

### Priority 3: Documentation & Testing

**1. Add test coverage for edge cases**
   - Backwards phase transitions
   - Concurrent file modifications
   - Token overflow scenarios

**2. Create runbook for anti-pattern debugging**
   - Decision tree for "which hook blocked me?"
   - Common causes and fixes
   - Debug command reference

---

## Files Reviewed

### Hooks (10 files analyzed)
✓ base-enforcement.py
✓ iterate-enforcement.py
✓ subagent-enforcement.py
✓ parallel-enforcement.py
✓ background-enforcement.py
✓ monitor_agent.py
✓ post-task-tracking.py
✓ session-start.py, session-end.py
✓ verification_gates.py

### Lib (Key files)
✓ /lib/phase_model.py (Phase definitions + restrictions)
✓ /lib/iterate_workflow.py (State persistence + logging)
✓ /lib/workflow_client.py (MCP state server client)
✓ /lib/worker_pool.py (Agent tracking)
✓ /lib/orchestrate.py (Orchestrator state machine)

### Tests (Sample review)
✓ test_subagent_enforcement.py
✓ test_parallel_enforcement.py
✓ test_background_enforcement.py

### Scripts
✓ charts.py (Telemetry visualization)
✓ gh_wrapper.py (Safe git operations)

---

## Deployment Checklist

To integrate anti-pattern detection enhancements:

- [ ] Implement 3 new hooks (token-overflow, phase-transition, workspace-validation)
- [ ] Add tests for each new hook (minimum 3-5 test cases each)
- [ ] Update hook registry in plugin.json
- [ ] Enhance telemetry collection in post-task-tracking.py
- [ ] Add visualization to charts.py
- [ ] Document in ANTI_PATTERNS_DETECTION.md (✓ Done)
- [ ] Create DETECTION_IMPLEMENTATION_GUIDE.md (✓ Done)
- [ ] Create ANTI_PATTERNS_QUICK_REFERENCE.md (✓ Done)
- [ ] Run full test suite: `pytest tests/ -v`
- [ ] Manual testing in iterate workflow
- [ ] Deploy to main branch

---

## Summary: Where Detection Happens

| Phase | Detection Point | Hook/Mechanism |
|-------|---|---|
| **PreToolUse** (before execution) | Edit in orchestrate? | base-enforcement.py ← **Fastest** |
| **PreToolUse** | Tool allowed in phase? | iterate-enforcement.py |
| **PreToolUse** | Sequential spawns? | parallel-enforcement.py |
| **PreToolUse** | Task has bg flag? | background-enforcement.py |
| **PreToolUse** | Classification valid? | monitor_agent.py ← **Slowest (API)** |
| **PostToolUse** (after execution) | Extract metrics | post-task-tracking.py |
| **PostToolUse** | Detect runaway loops | token-overflow-detection.py (NEW) |
| **PostToolUse** | Check file conflicts | workspace-validation.py (NEW) |
| **Session** (lifecycle) | Track agent state | session-start.py, session-end.py |

---

## References

**Documentation Created:**
1. `ANTI_PATTERNS_DETECTION.md` - Detailed 8 anti-patterns with examples
2. `DETECTION_IMPLEMENTATION_GUIDE.md` - How to add new hooks + code examples
3. `ANTI_PATTERNS_QUICK_REFERENCE.md` - Compact reference + debugging
4. `EXPLORATION_SUMMARY.md` - This document

**Code Artifacts:**
- `/hooks/` - 10 enforcement hooks
- `/lib/phase_model.py` - TDD phase restrictions
- `/scripts/charts.py` - Telemetry visualization
- `/tests/test_*enforcement.py` - Test coverage

---

## Questions Answered

**Q1: What anti-patterns subagents might exhibit?**
- Skipping TDD phases (tests → implement → test)
- Not registering with workflow (can't track resources)
- Calling workflow.start() instead of using injected state
- Making excessive tool calls (infinite loops)

**Q2: How does current telemetry/enforcement track behavior?**
- PreToolUse hooks: Block at execution time
- PostToolUse hooks: Log completion + metrics
- Phase model: Restrict tools per workflow phase
- Sequence analysis: Track task spawning patterns

**Q3: What patterns to detect?**
- Orchestrator editing instead of spawning (✓ detected)
- Subagent skipping test phases (✓ detected)
- Agent not registering with workflow (✓ via context injection)
- Sequential task spawning (✓ detected)
- Missing run_in_background (✓ detected)
- Token overflow/infinite loops (⚠️ proposed)
- File conflicts (⚠️ proposed)
- Phase transition violations (⚠️ proposed)

**Q4: Where should detection logic be added?**
- New hooks: `/hooks/{pattern}-detection.py`
- Telemetry: Enhance `/scripts/charts.py`
- Tests: Add `/tests/test_{pattern}.py`
- State: Use workflow state keys
- Integration: Register in `plugin.json`

---

## Conclusion

The agent-swarm framework has **mature enforcement infrastructure** for detecting most critical anti-patterns. The recommendations focus on:

1. **Emerging patterns** (token overflow, file conflicts, phase transitions)
2. **Enhanced telemetry** for visibility into anti-pattern prevalence
3. **Improved testing** for edge cases

All documentation has been created for implementation teams to add new hooks with confidence.
