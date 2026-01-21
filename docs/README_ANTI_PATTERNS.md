# Anti-Patterns Detection Framework - Documentation Index

**Complete guide to detecting and preventing agent behavioral anti-patterns during execution.**

---

## Quick Start

### For Operators/Debuggers
Start here if you're debugging a blocked agent or want to understand enforcement:

1. **[ANTI_PATTERNS_QUICK_REFERENCE.md](ANTI_PATTERNS_QUICK_REFERENCE.md)** (5 min read)
   - Detection quick map
   - Anti-pattern matrix
   - Common issues + fixes
   - Debugging commands

2. **[EXPLORATION_SUMMARY.md](EXPLORATION_SUMMARY.md)** (10 min read)
   - Executive summary
   - Current enforcement architecture
   - What's well-protected vs. needs work

### For Developers/Hook Authors
Start here if you're implementing new anti-pattern detection:

1. **[DETECTION_IMPLEMENTATION_GUIDE.md](DETECTION_IMPLEMENTATION_GUIDE.md)** (20 min read)
   - Implementation patterns with code examples
   - How to add new detection hooks
   - Testing framework
   - Integration checklist

2. **[ANTI_PATTERNS_DETECTION.md](ANTI_PATTERNS_DETECTION.md)** (30 min read)
   - Detailed 8 anti-patterns
   - Why each is wrong
   - Detection points
   - Correct vs. wrong examples

---

## Document Map

### Core Documentation (Ordered by Detail Level)

```
QUICK_REFERENCE.md
├─ For: Quick lookup, debugging
├─ Length: ~10 pages
├─ Includes: Matrix, examples, commands
└─ Time: 5-10 minutes

EXPLORATION_SUMMARY.md
├─ For: Architecture overview, recommendations
├─ Length: ~8 pages
├─ Includes: Findings, deployment checklist
└─ Time: 10-15 minutes

ANTI_PATTERNS_DETECTION.md
├─ For: Deep understanding of each pattern
├─ Length: ~20 pages
├─ Includes: Why patterns are wrong, detection logic
└─ Time: 20-30 minutes

DETECTION_IMPLEMENTATION_GUIDE.md
├─ For: Adding new hooks or patterns
├─ Length: ~15 pages
├─ Includes: Code examples, tests, integration
└─ Time: 15-25 minutes

README_ANTI_PATTERNS.md (this file)
├─ For: Navigation and reference
├─ Length: ~5 pages
└─ Time: 5 minutes
```

---

## Anti-Patterns Overview

### The 8 Patterns

| # | Pattern | Severity | Detection | Current |
|---|---------|----------|-----------|---------|
| 1 | Orchestrator editing directly | 🔴 Critical | PreToolUse block | ✓ Active |
| 2 | Subagent skipping test phases | 🔴 Critical | Phase model enforcement | ✓ Active |
| 3 | Subagent not registering | 🟠 High | Context injection | ✓ Active |
| 4 | Sequential task spawning | 🟠 High | 5-sec window tracking | ✓ Active |
| 5 | Missing run_in_background | 🟠 High | Flag check | ✓ Active |
| 6 | Classification mismatch | 🟠 High | Haiku API validation | ✓ Active |
| 7 | Calling workflow.start() | 🟡 Medium | Code review | ⚠️ Manual |
| 8 | Infinite loops (token overflow) | 🟡 Medium | Call count tracking | ⚪ Proposed |

**See:** [ANTI_PATTERNS_DETECTION.md](ANTI_PATTERNS_DETECTION.md) for full details

---

## Architecture at a Glance

### Detection Flow

```
User/Agent Request
        ↓
PreToolUse Hooks (check BEFORE execution)
├─ base-enforcement.py → Workflow active?
├─ iterate-enforcement.py → Phase restrictions?
├─ parallel-enforcement.py → Sequential spawns?
├─ background-enforcement.py → run_in_background flag?
└─ monitor_agent.py → Classification valid?
        ↓ (all pass)
Tool Executes
        ↓
PostToolUse Hooks (track AFTER execution)
├─ post-task-tracking.py → Extract metrics
├─ token-overflow-detection.py → Infinite loops?
└─ workspace-validation.py → File conflicts?
        ↓
Session Hooks (lifecycle)
├─ session-start.py → Initialize
└─ session-end.py → Cleanup
```

**See:** [ANTI_PATTERNS_QUICK_REFERENCE.md](ANTI_PATTERNS_QUICK_REFERENCE.md#detection-quick-map)

---

## File Locations

### Documentation
```
/docs/
├─ README_ANTI_PATTERNS.md (this file)
├─ ANTI_PATTERNS_DETECTION.md (detailed patterns)
├─ DETECTION_IMPLEMENTATION_GUIDE.md (how to add hooks)
├─ ANTI_PATTERNS_QUICK_REFERENCE.md (quick lookup)
└─ EXPLORATION_SUMMARY.md (findings & recommendations)
```

### Enforcement Implementation
```
/hooks/
├─ base-enforcement.py (no workflow = no edit)
├─ iterate-enforcement.py (phase restrictions)
├─ subagent-enforcement.py (TDD workflow injection)
├─ parallel-enforcement.py (sequential spawn blocking)
├─ background-enforcement.py (run_in_background flag)
├─ monitor_agent.py (contextual validation)
├─ post-task-tracking.py (telemetry collection)
├─ session-start.py (lifecycle init)
├─ session-end.py (lifecycle cleanup)
└─ [3 more specialized hooks]

/lib/
├─ phase_model.py (TDD phase definitions)
├─ iterate_workflow.py (phase state persistence)
├─ workflow_client.py (state server client)
├─ worker_pool.py (agent tracking)
└─ orchestrate.py (orchestrator state machine)

/tests/
├─ test_base_enforcement.py
├─ test_iterate_enforcement.py
├─ test_subagent_enforcement.py
├─ test_parallel_enforcement.py
├─ test_background_enforcement.py
└─ [more enforcement tests]
```

---

## Common Scenarios

### Scenario 1: "Edit blocked - no workflow"
**Problem:** You got error "No workflow - Edit blocked"

**Solution:** You're in [CONVERSATION] mode (no /orchestrate or /iterate running)

**Fix:**
```bash
# Start a workflow first
/iterate --task "Your task"
# or
/orchestrate --max-agents 3
```

**Reference:** [QUICK_REFERENCE.md - Common Issues](ANTI_PATTERNS_QUICK_REFERENCE.md#common-issues)

---

### Scenario 2: "Task blocked - sequential spawn"
**Problem:** You got error "Cannot spawn Task agents sequentially"

**Solution:** You called Task 3+ times within 5 seconds

**Fix:**
```python
# ❌ Wrong: Sequential
Task(description="A")
# ... wait ...
Task(description="B")

# ✓ Right: Parallel
Task(description="A", run_in_background=True)
Task(description="B", run_in_background=True)
```

**Reference:** [QUICK_REFERENCE.md - Minimal Examples](ANTI_PATTERNS_QUICK_REFERENCE.md#minimal-examples)

---

### Scenario 3: "Code edit blocked - wrong phase"
**Problem:** Edit blocked with "Phase restrictions - test_writing"

**Solution:** You're in test_writing phase, can't edit code yet

**Fix:** Write tests first, then implementation:
```python
# Phase 1: test_writing
Write(file_path="test_feature.py", content="def test_... assert False")

# Phase 2: implement
Edit(file_path="feature.py", ...)

# Phase 3: test
Bash(command="pytest")
```

**Reference:** [ANTI_PATTERNS_DETECTION.md - Pattern 2](ANTI_PATTERNS_DETECTION.md#2-subagent-skipping-test-phases)

---

## Implementation Path

### For Adding New Anti-Pattern Detection

1. **Identify** the anti-pattern
   - Write description
   - List detection signals
   - Define correct behavior

2. **Create** hook file
   - Follow pattern from [DETECTION_IMPLEMENTATION_GUIDE.md](DETECTION_IMPLEMENTATION_GUIDE.md#step-2-create-hook-file)
   - Add to `/hooks/{name}.py`
   - Return `allow` or `deny` decision

3. **Test** the hook
   - Create `/tests/test_{name}.py`
   - Add 5+ test cases
   - Run: `pytest tests/test_{name}.py -v`

4. **Register** the hook
   - Add to `plugin.json` hooks array
   - Update documentation

5. **Deploy**
   - Run full test suite: `pytest tests/ -v`
   - Manual verification in workflow
   - Merge to main

**Detailed guide:** [DETECTION_IMPLEMENTATION_GUIDE.md](DETECTION_IMPLEMENTATION_GUIDE.md)

---

## Quick Commands

### Debug an Anti-Pattern Block

```bash
# Check what phase you're in
python3 << 'EOF'
from lib.workflow_client import workflow_get_state
state = workflow_get_state("iterate")
print(f"Phase: {state.get('phase')}, Mode: {state.get('mode')}")
EOF

# Check subagent state
python3 << 'EOF'
from lib.workflow_client import agent_get_state
agent = agent_get_state("sub-abc1234")
print(f"Subagent phase: {agent.get('phase')}")
EOF

# View recent hook logs
tail -50 ~/.claude/plugins/agent-swarm/.state/iterate.log

# Search logs for specific hook
grep "parallel-enforcement" ~/.claude/plugins/agent-swarm/.state/iterate.log
```

**More commands:** [QUICK_REFERENCE.md - Debugging Commands](ANTI_PATTERNS_QUICK_REFERENCE.md#debugging-commands)

---

## Testing Anti-Patterns

### Run All Tests
```bash
python3 -m pytest tests/test_*enforcement*.py -v
```

### Run Specific Test
```bash
# Test parallel enforcement
python3 -m pytest tests/test_parallel_enforcement.py::test_sequential_spawns_blocked -v

# Test all phase enforcement
python3 -m pytest tests/test_iterate_enforcement.py -v
```

### Add New Test
See [DETECTION_IMPLEMENTATION_GUIDE.md - Step 3](DETECTION_IMPLEMENTATION_GUIDE.md#step-3-add-test-file)

---

## Phase Restriction Reference

### What's Allowed in Each Phase

```
Phase           │ FILE_READ │ FILE_WRITE │ CODE_EDIT │ SHELL_SAFE │ SUBAGENT
────────────────┼───────────┼────────────┼───────────┼────────────┼──────────
test_writing    │    ✓      │     ✓      │     ✗     │     ✓      │    ✗
implement       │    ✓      │     ✓      │     ✓     │     ✓      │    ✓
test            │    ✓      │     ✗      │     ✗     │     ✓      │    ✗
review          │    ✓      │     ✗      │     ✗     │     ✗      │    ✗
```

**Full reference:** [QUICK_REFERENCE.md - Phase Restriction Chart](ANTI_PATTERNS_QUICK_REFERENCE.md#phase-restriction-chart)

---

## State Management Keys

### Workflow State
```python
workflow_get_state("session")
# Contains: phase, mode, active_agents, tokens_used, etc.

workflow_get_state("iterate")
# Contains: phase, mode, tasks_queue, active_workers, etc.
```

### Agent State
```python
agent_get_state("sub-abc1234")
# Contains: phase, mode, task, parent_session, status, etc.
```

**Full reference:** [QUICK_REFERENCE.md - State Keys for Detection](ANTI_PATTERNS_QUICK_REFERENCE.md#state-keys-for-detection)

---

## Recommended Reading Order

### For Quick Answers
1. [ANTI_PATTERNS_QUICK_REFERENCE.md](ANTI_PATTERNS_QUICK_REFERENCE.md)
2. Use Ctrl+F to find your issue

### For Understanding the System
1. [EXPLORATION_SUMMARY.md](EXPLORATION_SUMMARY.md) - Architecture overview
2. [ANTI_PATTERNS_DETECTION.md](ANTI_PATTERNS_DETECTION.md) - Each pattern explained
3. Relevant hook code in `/hooks/`

### For Implementation
1. [DETECTION_IMPLEMENTATION_GUIDE.md](DETECTION_IMPLEMENTATION_GUIDE.md) - Full examples
2. Review existing hooks in `/hooks/`
3. Follow integration checklist

---

## Performance Notes

| Hook | Latency | Overhead | Notes |
|------|---------|----------|-------|
| base-enforcement.py | <1ms | None | Direct state check |
| iterate-enforcement.py | <1ms | None | Phase lookup table |
| parallel-enforcement.py | <5ms | O(n) | 5-sec window cleanup |
| background-enforcement.py | <1ms | None | Flag check |
| monitor_agent.py | 100-500ms | **API call** | Haiku API validation |

**Total overhead:** 10-20ms (without Haiku), 100-500ms (with Haiku on first edit)

---

## FAQ

**Q: Why do I get "Edit blocked" errors?**
A: You're in a phase/mode that doesn't allow editing. See [QUICK_REFERENCE.md - Common Issues](ANTI_PATTERNS_QUICK_REFERENCE.md#common-issues).

**Q: How do I run tests in parallel?**
A: Spawn all Tasks in one message block:
```python
Task(...) Task(...) Task(...)  # All at once
```

**Q: Can I skip the test phase?**
A: No. TDD phases are enforced: test_writing → implement → test → review. Subagents cannot skip phases.

**Q: How do I debug a blocked agent?**
A: Use commands in [QUICK_REFERENCE.md - Debugging Commands](ANTI_PATTERNS_QUICK_REFERENCE.md#debugging-commands) to check phase, logs, and state.

**Q: Where do I report a hook bug?**
A: Create a test case in `/tests/test_{hook_name}.py` showing the issue, then file a PR.

---

## Contact & Support

- **Bug reports:** Add test case to `/tests/` → PR
- **Questions:** See FAQ above or search relevant `.md` file
- **Enhancement requests:** See [EXPLORATION_SUMMARY.md - Recommendations](EXPLORATION_SUMMARY.md#implementation-recommendations)

---

## Version History

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-20 | 1.0 | Initial framework documentation |

---

**Last Updated:** 2026-01-20  
**Scope:** Agent-swarm anti-patterns detection framework  
**Status:** ✓ Complete (7 active patterns + 3 proposed)
