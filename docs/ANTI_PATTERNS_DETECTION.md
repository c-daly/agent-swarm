# Agent Anti-Patterns Detection Framework

**Purpose:** Detect and prevent subagent behavioral anti-patterns during execution to enforce workflow discipline and prevent silent failures.

---

## Anti-Patterns Identified

### 1. **Orchestrator Doing Implementation (Instead of Spawning)**

**Pattern:** Orchestrator agent uses Edit/Write tools directly instead of spawning Task agents for implementation work.

**Why it's wrong:**
- Violates separation of concerns (orchestrator ≠ implementer)
- Prevents parallel execution and subagent accountability
- Makes debugging failures harder (can't track which agent made changes)
- Subagents carry context about failures; orchestrator loses that

**Detection Points:**

| Location | Detection Method | Signal |
|----------|-----------------|--------|
| `/hooks/base-enforcement.py` | Pre-tool block | Edit/Write used in "orchestrate" phase without spawning first |
| `/hooks/iterate-enforcement.py` | Phase check | Phase="orchestrate" + tool="Edit" → deny |
| Telemetry | Sequence analysis | Edit seen before any Task spawns |

**Example (WRONG):**
```python
# Orchestrator doing work directly
Edit(file_path="src/feature.py", old_string="...", new_string="...")  # ❌ WRONG
```

**Correct approach:**
```python
# Orchestrator delegates to subagent
Task(
    subagent_type="implementer",
    prompt="Implement feature X in src/feature.py",
    run_in_background=True
)
```

---

### 2. **Subagent Skipping Test Phases**

**Pattern:** TDD subagent moves directly from test_writing → implement or skips test validation entirely.

**Why it's wrong:**
- Defeats purpose of TDD (tests define requirements)
- Breaks feedback loop (no confirmation that implementation works)
- Harder to debug failing implementations without test evidence
- Creates technical debt (untested code)

**Detection Points:**

| Location | Detection Method | Signal |
|----------|-----------------|--------|
| `/hooks/iterate-enforcement.py` | Phase transition | Phase="implement" but no test file edits detected |
| `/hooks/subagent-enforcement.py` | Context injection | Subagent context requires TDD order |
| Phase model | Phase blocking | test_writing has FILE_WRITE allowed, implement has CODE_EDIT allowed |

**Phase Sequence Enforcement** (`/lib/phase_model.py`):

```
test_writing     → implement        → test           → review
  ✓ FILE_WRITE      ✓ FILE_WRITE      ✓ SHELL_SAFE      ✓ FILE_READ
  ✓ SHELL_SAFE      ✓ CODE_EDIT       (pytest)          ✓ USER_INTERACTION
  ✓ FILE_READ       ✓ SUBAGENT        ✓ FILE_READ
  
  BLOCKED:          BLOCKED:          BLOCKED:          BLOCKED:
  - Edit            - (none - all     - Edit/Write      - Edit/Write
    (can't edit       implementation   (tests locked)    (no more changes)
     code)           tools allowed)
```

**Example (WRONG):**
```python
# Subagent in implement phase without writing tests first
@phase("implement")
def work():
    Edit(file_path="feature.py", ...)  # ❌ Should be in test_writing first
    Run(pytest)  # ❌ No tests written
```

**Correct flow:**
```python
@phase("test_writing")
def write_tests():
    Write(file_path="test_feature.py", content="def test_... assert False")

@phase("implement")
def implement():
    Edit(file_path="feature.py", ...)

@phase("test")
def run_tests():
    Run(pytest)  # ✓ Now tests exist and should pass
```

---

### 3. **Subagent Not Registering with Workflow**

**Pattern:** Subagent starts but never registers state, making orchestrator unable to track it or manage resource limits.

**Why it's wrong:**
- Orchestrator can't enforce max_agents limit
- Can't detect agent failures or hangs
- Resource exhaustion (agents spawn indefinitely)
- Workflow state becomes inconsistent

**Detection Points:**

| Location | Detection Method | Signal |
|----------|-----------------|--------|
| `/hooks/subagent-enforcement.py:agent_set_state()` | Workflow state | No agent state entry created for agent_id |
| `/lib/worker_pool.py` | Active worker tracking | Task spawned but no state registered |
| Telemetry | Agent count mismatch | Tasks spawned > active agents in tracking |

**Example (WRONG):**
```python
# Subagent spawned but never tells workflow it exists
import sys
sys.stdin.read()  # Start thinking
# ... does work ...
print("Done")  # Never registers with agent_set_state
```

**Correct pattern** (enforced by `/hooks/subagent-enforcement.py`):
```python
# Hook automatically injects:
# agent_id: sub-abc1234
# mode: iterate-tdd
# phase: test_writing (for implementers in orchestrate)
# parent_session: session-xyz

# Subagent loaded with this context
print("Agent ID:", agent_id)  # Can reference injected context
```

---

### 4. **Sequential Task Spawning (Instead of Parallel)**

**Pattern:** Orchestrator spawns multiple Task agents one-at-a-time instead of in parallel blocks.

**Why it's wrong:**
- Wastes execution time (tasks wait instead of running simultaneously)
- Loses efficiency gains from parallel agent execution
- Cumulative latency = N × task_duration instead of ~1 × task_duration

**Detection Points:**

| Location | Detection Method | Signal |
|----------|-----------------|--------|
| `/hooks/parallel-enforcement.py` | Sequential tracking | 2+ Task calls within 5-second window |
| Action | Response | 1st spawn: allow, 2nd: warn, 3rd: block |

**Example (WRONG):**
```python
# ❌ Sequential: wait for first to respond, then spawn second
Task(description="Task A")  # Response comes back
# ... handle response ...
Task(description="Task B")  # Then spawn next
```

**Correct pattern:**
```python
# ✅ Parallel: spawn all at once
Task(description="Task A", run_in_background=True)
Task(description="Task B", run_in_background=True)
Task(description="Task C", run_in_background=True)
# All three run simultaneously
```

---

### 5. **Task Missing `run_in_background=true`**

**Pattern:** Task spawned without `run_in_background=true`, blocking parallel execution.

**Why it's wrong:**
- Subagent runs synchronously, blocking orchestrator
- No parallel execution benefits
- Defeats purpose of background execution

**Detection Points:**

| Location | Detection Method | Signal |
|----------|-----------------|--------|
| `/hooks/background-enforcement.py` | Tool input check | task_input["run_in_background"] != True |
| Action | Response | Deny with message: "Must use run_in_background=true" |

**Example (WRONG):**
```python
Task(description="Implement feature")  # ❌ run_in_background missing
```

**Correct:**
```python
Task(description="Implement feature", run_in_background=True)  # ✓
```

---

### 6. **Subagent Calling Workflow Init (Instead of Using Injected State)**

**Pattern:** Subagent calls `iterate_workflow.start()` or `workflow_client.workflow_start()` instead of using injected context.

**Why it's wrong:**
- Overwrites orchestrator's workflow state
- Multiple agents competing for same state file
- Loses orchestrator's phase/mode information
- Race conditions and state corruption

**Detection Points:**

| Location | Detection Method | Signal |
|----------|-----------------|--------|
| `/hooks/subagent-enforcement.py` | Context injection warning | "DO NOT call start()" explicitly mentioned |
| Code review | Pattern search | grep "iterate_workflow.start()" in subagent code |
| Telemetry | State conflicts | Multiple agents writing to iterate.json simultaneously |

**Example (WRONG):**
```python
# Subagent (WRONG)
import iterate_workflow
iterate_workflow.start()  # ❌ Overwrites orchestrator's state
```

**Correct:**
```python
# Subagent uses injected context from SubagentStart hook
# Context already provides: agent_id, phase, mode, parent_session
# No need to call start() - state is already injected
```

---

### 7. **Classification Type Mismatch (TRIVIAL Without Workflow)**

**Pattern:** Agent classifies task as `[TRIVIAL]` but task actually requires multi-step work or orchestration.

**Why it's wrong:**
- Bypasses intended safeguards (Edit/Write allowed without workflow)
- Misapplies classification rules (Edit + multiple files ≠ trivial)
- Hides work that should be in /orchestrate

**Detection Points:**

| Location | Detection Method | Signal |
|----------|-----------------|--------|
| `/hooks/monitor_agent.py` | Contextual validation | First edit with SIMPLE classification → Haiku check |
| Validation | Rules | SIMPLE must be: 1 file, <50 lines, clear requirements |
| Telemetry | Pattern | Edit/Write before any Task spawn |

**Classification Rules:**

| Classification | Criteria | Tools Allowed |
|---|---|---|
| `[TRIVIAL]` | Single line fix, rename, clear intent | Edit/Write (no workflow needed) |
| `[CONVERSATION]` | General discussion, info request | Read, Grep, Glob, Web (no Edit) |
| `[RESEARCH]` | Exploration, understanding code | Read, Grep, Glob, Web (no Edit) |

**Example (WRONG):**
```python
# ❌ TRIVIAL classification but multi-step work
[TRIVIAL]
Edit(file_path="file1.py", ...)  # Step 1
Edit(file_path="file2.py", ...)  # Step 2
Edit(file_path="file3.py", ...)  # Step 3: This is NOT trivial!
```

**Correct:**
```python
# ✓ Use [CONVERSATION] + /orchestrate
[CONVERSATION]
# ... analysis ...
# Then invoke /orchestrate for actual implementation
```

---

### 8. **Content Embedding in Subagent Prompts**

**Pattern:** Orchestrator embeds literal file content, code blocks, or expected output in subagent prompts instead of giving intent + acceptance criteria.

**Why it's wrong:**
- Multiple agents get overlapping content, causing file stomping
- Agent has no room for judgment (becomes a copy-paste machine)
- Prompt bloat wastes context window
- No verification criteria — orchestrator can't check if agent did it right

**Detection Points:**

| Location | Detection Method | Signal |
|----------|-----------------|--------|
| Prompt analysis | Length + code block check | Prompt > 2000 chars with code blocks > 10 lines |
| Telemetry | File conflict detection | Two agents modifying same file simultaneously |

**Example (WRONG):**
```python
# ❌ Embedding file content in prompt
Task(prompt="Write this to briefing.md:\n# Subagent Operating Protocol\n[800 chars of content...]")
```

**Correct:**
```python
# ✅ Intent + acceptance criteria
Task(prompt="""Rewrite briefing.md following constraints-first template.

Acceptance criteria:
- Contains marker 'SUBAGENT OPERATING PROTOCOL'
- Size between 400-900 chars
- Constraints section appears before tool reference
- See agent_context.md for project patterns""")
```

**Related rule:** Each file may be modified by AT MOST one concurrent task. When decomposing into parallel tasks, assign non-overlapping file sets.

---

## Detection Logic Integration Points

### Current Enforcement Hooks

**File:** `/hooks/`

| Hook | Checks | Blocks |
|------|--------|--------|
| `base-enforcement.py` | Edit/Write called without active workflow | Deny if no workflow |
| `iterate-enforcement.py` | Phase-based tool restrictions (test_writing, implement, test, review) | Deny if tool blocked in phase |
| `subagent-enforcement.py` | Subagent context injection + TDD workflow messaging | (informational) |
| `parallel-enforcement.py` | Sequential Task spawning within 5-second window | Allow, Warn, Deny on 3rd spawn |
| `background-enforcement.py` | Task tool missing run_in_background=true | Deny if missing |
| `monitor_agent.py` | Contextual validation (Haiku API) for commits + classification | Deny if violations detected |

### Telemetry Collection Points

**File:** `/hooks/post-task-tracking.py` + `/scripts/charts.py`

- Task tool completion: logs agent_id, subagent_type, token usage
- Sequence analysis: detects anti-pattern timelines
- Failure attribution: identifies which agent caused issue

### State Management

**Files:**
- `/lib/workflow_client.py` - MCP state server client
- `/lib/iterate_workflow.py` - Phase state persistence
- `/lib/worker_pool.py` - Active agent tracking

**State Keys:**
- `workflow.iterate.phase` - Current TDD phase
- `workflow.iterate.mode` - Workflow mode (iterate-tdd, orchestrate)
- `agent.{agent_id}.phase` - Per-subagent phase
- `session.parallel_enforcement_state.recent_spawns` - Task spawn tracking

---

## Where to Add New Anti-Pattern Detection

### 1. **Phase Enforcement** (Existing Architecture)
**Where:** Modify `/hooks/iterate-enforcement.py`
**How:** Add rules to `is_tool_allowed()` for new phase transitions
**Example:** Detect implement→test_writing (backwards phase transition)

### 2. **Sequence Analysis** (New)
**Where:** Create `/hooks/sequence-analysis.py`
**Patterns to detect:**
- Edit after Task spawn without tests passing
- Multiple Edit calls in test_writing phase (should be one per test)
- Review phase with no test results

### 3. **Token Budget Violations** (New)
**Where:** Create `/hooks/token-budget-enforcement.py`
**Patterns to detect:**
- Single task consuming >80% of token budget
- Subagent making 50+ tool calls (likely infinite loop)

### 4. **Output Tracking** (Enhancement)
**Where:** Enhance `/hooks/post-task-tracking.py`
**Patterns to detect:**
- Task output shows failure but agent marked "complete"
- Agent claimed tests passed but no test files in output
- Modified files don't match claimed changes

### 5. **Workspace Consistency** (New)
**Where:** Create `/hooks/workspace-validation.py`
**Patterns to detect:**
- File conflicts (multiple agents editing same file simultaneously)
- Orphaned test files (tests exist but code doesn't)
- Uncommitted changes after "review" phase

---

## Integration with Existing Framework

### Hook Registration Pattern
All hooks follow this pattern in `/hooks/{name}.py`:

```python
#!/usr/bin/env python3
"""Hook description."""

import json
import sys

def main():
    input_data = json.loads(sys.stdin.read())
    
    # Extract tool info
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    
    # Detect anti-pattern
    if is_anti_pattern(tool_name, tool_input):
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "Clear explanation of violation"
            }
        }
    else:
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow"
            }
        }
    
    print(json.dumps(result))

if __name__ == "__main__":
    main()
```

### Hook Types

**PreToolUse hooks:** Block/allow tool execution
- Return `"permissionDecision": "allow" | "deny"`
- Can add `"additionalContext"` for warnings (allow with message)

**PostToolUse hooks:** Track after execution
- Used for telemetry, state updates
- Never block (informational only)

**Session hooks:** Session lifecycle events
- `session-start.py` - Initialize tracking
- `session-end.py` - Cleanup

---

## Testing Anti-Pattern Detection

**Test directory:** `/tests/`

Each hook should have corresponding test:
- `test_parallel_enforcement.py` - Tests for sequential spawn blocking
- `test_subagent_enforcement.py` - Tests for TDD phase enforcement
- `test_background_enforcement.py` - Tests for run_in_background requirement

**Test pattern:**
```python
def test_anti_pattern_detected(mock_workflow_state):
    """Verify anti-pattern is blocked."""
    result = run_hook(tool_name="Edit", tool_input=bad_input)
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "reason" in result["hookSpecificOutput"]["permissionDecisionReason"]
```

---

## Summary: Detection Matrix

| Anti-Pattern | Detection Hook | Signal | Block |
|---|---|---|---|
| Orchestrator edits directly | `base-enforcement.py` | phase=orchestrate + Edit | ✓ |
| Skips test_writing phase | `iterate-enforcement.py` | phase=implement with no prior tests | ✓ |
| Doesn't register state | `subagent-enforcement.py` | no agent_set_state call | ✗ (informational) |
| Sequential task spawns | `parallel-enforcement.py` | 3+ tasks in 5 sec | ✓ |
| Missing run_in_background | `background-enforcement.py` | Task without flag | ✓ |
| Classification mismatch | `monitor_agent.py` | TRIVIAL + multi-file | ✓ |
| Calls workflow.start() | (code review + logs) | init call in subagent | ✗ (message) |

---

## Files for Enhancement

**Priority 1 (Implement Now):**
1. `/hooks/sequence-analysis.py` - Detect workflow phase violations
2. `/hooks/token-budget-enforcement.py` - Prevent runaway tasks

**Priority 2 (Consider):**
3. `/hooks/workspace-validation.py` - File conflict detection
4. Enhanced telemetry in `/scripts/charts.py` - Visualize anti-patterns

**Priority 3 (Documentation):**
5. ANTI_PATTERNS.md (this file) in `/docs/`
6. Test coverage in `/tests/test_*_enforcement.py`
