# Anti-Patterns Quick Reference

**Compact reference for detecting and preventing agent anti-patterns.**

---

## Detection Quick Map

```
┌─────────────────────────────────────────────────────────────┐
│ ANTI-PATTERN DETECTION FLOW                                 │
└─────────────────────────────────────────────────────────────┘

Orchestrator Phase ("orchestrate")
├─ Edit/Write called?
│  ├─ YES → [BLOCK] base-enforcement.py + iterate-enforcement.py
│  │        Error: "Use Task(subagent_type=...)"
│  └─ NO → Continue
│
├─ Task tool called?
│  ├─ run_in_background=true?
│  │  ├─ NO → [BLOCK] background-enforcement.py
│  │  │       Error: "Must use run_in_background=true"
│  │  └─ YES → Continue
│  │
│  ├─ Sequential spawns detected (2+ in 5 sec)?
│  │  ├─ 1st → Allow (first is OK)
│  │  ├─ 2nd → [WARN] parallel-enforcement.py
│  │  │         Message: "Consider parallel spawning"
│  │  └─ 3rd+ → [BLOCK] parallel-enforcement.py
│  │           Error: "Must spawn in parallel block"
│  └─
└─

Subagent Phase ("test_writing" / "implement" / "test" / "review")
├─ File operation called?
│  └─ Check phase-based restrictions (iterate-enforcement.py)
│     ├─ test_writing: FILE_WRITE ✓, CODE_EDIT ✗
│     ├─ implement:   FILE_WRITE ✓, CODE_EDIT ✓
│     ├─ test:        FILE_WRITE ✗, SHELL_SAFE ✓ (pytest)
│     └─ review:      FILE_WRITE ✗, CODE_EDIT ✗
│
└─ All phases allow FILE_READ
```

---

## Anti-Pattern Detection Matrix

### Color Legend
- 🟢 **Allow** - Normal behavior
- 🟡 **Warn** - Antipattern detected, allow with message
- 🔴 **Block** - Violation, deny execution
- ⚪ **Info** - Tracked for telemetry only

| # | Anti-Pattern | When | Detection | Action | Fix |
|---|---|---|---|---|---|
| **1** | Orchestrator does Edit/Write | phase=orchestrate + Edit tool used | `iterate-enforcement.py` | 🔴 Block | Spawn Task(subagent_type="implementer") |
| **2** | Skips test_writing phase | implement phase used without tests | `iterate-enforcement.py` | 🔴 Block | Write tests first (phase=test_writing) |
| **3** | Sequential Task spawns | Task called 3+ times in 5 seconds | `parallel-enforcement.py` | 🟡 Warn on 2nd, 🔴 Block on 3rd | Task A() Task B() Task C() in one message |
| **4** | Missing run_in_background | Task called without flag | `background-enforcement.py` | 🔴 Block | Add run_in_background=true |
| **5** | Classification mismatch | [TRIVIAL] with multi-file edits | `monitor_agent.py` | 🔴 Block | Use [CONVERSATION] + /orchestrate |
| **6** | Infinite loops | Tool call count > 100 | `token-overflow-detection.py` (NEW) | ⚪ Info + Warn | Investigate agent logic |
| **7** | File conflicts | Multiple agents edit same file | `workspace-validation.py` (NEW) | ⚪ Info + Warn | Coordinate task assignments |
| **8** | Calls workflow.start() | Subagent reinits workflow | Code review | ⚪ Info | Use injected context instead |

---

## Phase Restriction Chart

```
TOOL CATEGORY          │ test_writing │ implement │   test   │  review
───────────────────────┼──────────────┼───────────┼──────────┼─────────
FILE_READ              │      ✓       │     ✓     │    ✓     │    ✓
FILE_WRITE (tests)     │      ✓       │     ✓     │    ✗     │    ✗
CODE_EDIT              │      ✗       │     ✓     │    ✗     │    ✗
SHELL_SAFE (pytest)    │      ✓       │     ✓     │    ✓     │    ✗
SUBAGENT              │      ✗       │     ✓     │    ✗     │    ✗
───────────────────────┴──────────────┴───────────┴──────────┴─────────

Legend: ✓ = Allowed | ✗ = Blocked
```

---

## Hook Execution Timeline

```
Pre-Tool Check                 Tool Execution             Post-Tool Check
─────────────────              ──────────────             ────────────────
1. base-enforcement.py         Tool runs                  post-task-tracking.py
   └─ Workflow active?         └─ (may spawn              └─ Extract metrics
                                  subagents)              └─ Log completion
2. iterate-enforcement.py                                 └─ Check for new
   └─ Phase allowed?                                         plugins

3. parallel-enforcement.py
   └─ Sequential spawns?

4. background-enforcement.py
   └─ run_in_background=true?

5. monitor_agent.py
   └─ Contextual validation

↓ (All passed)

Tool runs successfully
```

---

## Minimal Examples

### ✓ CORRECT: TDD Flow in Subagent

```python
# Phase 1: test_writing
Write(file_path="tests/test_feature.py", content="""
def test_adds_numbers():
    from src.feature import add
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
""")

# Phase 2: implement
Edit(file_path="src/feature.py", old_string="...", new_string="""
def add(a, b):
    return a + b
""")

# Phase 3: test
Bash(command="pytest tests/test_feature.py -v")
```

### ❌ WRONG: Skips Tests

```python
# Phase 1: implement (NO TEST WRITING PHASE!)
Edit(file_path="src/feature.py", old_string="...", new_string="""
def add(a, b):
    return a + b
""")

# This violates TDD: tests should come first!
```

### ✓ CORRECT: Parallel Task Spawning

```python
# Orchestrator in "orchestrate" phase
Task(
    subagent_type="implementer",
    task="Implement feature A",
    run_in_background=True
)
Task(
    subagent_type="implementer",
    task="Implement feature B",
    run_in_background=True
)
Task(
    subagent_type="explorer",
    task="Research architecture",
    run_in_background=True
)
# All three run in parallel
```

### ❌ WRONG: Sequential Spawning

```python
# First Task (blocks here)
Task(subagent_type="implementer", task="A", run_in_background=True)

# ... wait for response ...

# Second Task (after first completes)
Task(subagent_type="implementer", task="B", run_in_background=True)  # [WARN]

# Third Task (after second completes)
Task(subagent_type="implementer", task="C", run_in_background=True)  # [BLOCK]
```

---

## State Keys for Detection

### Session State
```python
workflow_get_state("session")
├─ phase: str                          # Current phase
├─ mode: str                           # "iterate-tdd", "orchestrate"
├─ active_agents: int                  # Tracked subagents
├─ parallel_enforcement_state: dict    # Sequential task tracking
│  └─ recent_spawns: list             # Task spawns in last 5 sec
├─ tokens_used: dict                   # Per-agent token usage
└─ workspace_modifications: dict       # File modification tracking
```

### Agent State (Subagent)
```python
agent_get_state("sub-abc1234")
├─ phase: str                          # test_writing/implement/test/review
├─ mode: str                           # Inherited from parent
├─ task: str                           # Assigned task description
├─ parent_session: str                 # Parent orchestrator session
├─ tool_calls_sequence: list          # Recent tool calls [for telemetry]
└─ status: str                         # running/completed/failed
```

---

## Telemetry Points

### What Gets Tracked
- ✓ Tool calls with timestamps and agent_id
- ✓ Phase transitions
- ✓ File modifications (by which agent)
- ✓ Token usage per agent
- ✓ Subagent completion status
- ✓ Test results (passed/failed)

### Telemetry Files
```
~/.claude/plugins/agent-swarm/.state/
├─ iterate.log              # Workflow logs (per-phase)
├─ subagent_metrics.json    # Agent completion tracking
├─ workspace_conflicts.json # File modification conflicts
└─ token_usage.json         # Token consumption per agent
```

---

## Testing Anti-Patterns

### Run All Tests
```bash
python3 -m pytest tests/test_*enforcement*.py -v
```

### Run Specific Anti-Pattern Test
```bash
# Test parallel enforcement
python3 -m pytest tests/test_parallel_enforcement.py::test_sequential_spawns_blocked -v

# Test phase enforcement
python3 -m pytest tests/test_subagent_enforcement.py::test_implementer_gets_test_writing_phase -v
```

### Add New Test
```python
# tests/test_my_pattern.py
def test_my_anti_pattern(mock_workflow_state):
    """Verify my anti-pattern is detected."""
    result = run_hook(tool_name="MyTool", tool_input=bad_input)
    
    # Assert it was blocked
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "reason" in result["hookSpecificOutput"]["permissionDecisionReason"]
```

---

## Debugging Commands

### Check What Phase Subagent Is In
```bash
python3 << 'EOF'
from lib.workflow_client import agent_get_state
agent = agent_get_state("sub-abc1234")
print(f"Phase: {agent.get('phase')}, Mode: {agent.get('mode')}")
EOF
```

### List Active Agents
```bash
python3 << 'EOF'
from lib.workflow_client import workflow_get_state
session = workflow_get_state("session")
print(f"Active agents: {session.get('active_agents', 0)}")
EOF
```

### View Last N Tool Calls
```bash
tail -100 ~/.claude/plugins/agent-swarm/.state/iterate.log | grep "Tool"
```

### Check for File Conflicts
```bash
python3 << 'EOF'
from lib.workflow_client import workflow_get_state
state = workflow_get_state("iterate")
mods = state.get("workspace_modifications", {})
for file, changes in mods.items():
    if len(set(c["agent_id"] for c in changes)) > 1:
        print(f"CONFLICT: {file} modified by {len(changes)} agents")
EOF
```

---

## Hook Performance Notes

| Hook | Max Latency | Overhead | Notes |
|------|-------------|----------|-------|
| `base-enforcement.py` | <1ms | None | Direct state check |
| `iterate-enforcement.py` | <1ms | None | Phase lookup table |
| `parallel-enforcement.py` | <5ms | O(n) where n=recent tasks | 5-sec window cleanup |
| `background-enforcement.py` | <1ms | None | Flag check |
| `monitor_agent.py` | 100-500ms | API call to Haiku | Only on classification change |
| `token-overflow-detection.py` | <1ms | None | Regex pattern match |

**Total PreToolUse overhead:** ~10-20ms without monitor_agent, ~100-500ms with monitor_agent

---

## Common Issues

### Issue: "Task blocked - sequential spawn"
**Cause:** Called Task 3+ times within 5 seconds
**Fix:** Spawn all Tasks in one message block:
```python
Task(...) Task(...) Task(...)  # All at once
```

### Issue: "Phase restrictions - Edit blocked in test_writing"
**Cause:** Tried to edit code during test phase
**Fix:** Edit is only allowed in "implement" phase. Current flow must be:
1. test_writing → 2. implement → 3. test → 4. review

### Issue: "No workflow active - Edit blocked"
**Cause:** Called Edit outside of /iterate or /orchestrate
**Fix:** Start a workflow first:
```
/iterate --task "Your task"
# or
/orchestrate --max-agents 3
```

### Issue: "Excessive tool calls (156 calls)"
**Cause:** Subagent made >100 tool calls (likely infinite loop)
**Fix:** Check subagent for:
- Infinite retry logic
- Circular dependency in task definitions
- Stuck recursion

---

## Enforcement Summary by Role

### Orchestrator Responsibilities
- ✓ Spawn subagents (don't edit directly)
- ✓ Use Task with run_in_background=true
- ✓ Spawn independent tasks in parallel
- ✗ Never use Edit/Write in "orchestrate" phase
- ✗ Never call workflow.start()

### Subagent Responsibilities
- ✓ Follow TDD phases: test_writing → implement → test → review
- ✓ Use injected workflow context
- ✗ Never skip phases
- ✗ Never call workflow.start() or workflow_client functions
- ✗ Never edit files outside your assigned phase

---

## References

| Document | Purpose |
|----------|---------|
| `ANTI_PATTERNS_DETECTION.md` | Detailed patterns with examples |
| `DETECTION_IMPLEMENTATION_GUIDE.md` | How to add new detection hooks |
| `/hooks/*.py` | Actual hook implementations |
| `/lib/phase_model.py` | Phase definitions and tool categories |
| `/tests/test_*enforcement.py` | Test cases for detection |

