# Iterate Workflow

**User-Invocable:** Yes (`/iterate`)

A tight development loop for rapid iteration on code changes. Unlike the full `orchestrate` workflow, this focuses on quick cycles of implement → test → review.

## When to Use

- Small to medium feature work
- Bug fixes with test verification
- Refactoring with continuous validation
- Any task where you want rapid feedback loops

## Flow

```
[intake?] → [design?] → (implement → test → review) × N → [checkpoint] → done
```

**Optional phases:** intake, design (skip if requirements are clear)
**Loop phases:** implement → test → review (repeat until exit condition)
**Exit conditions:** tests pass, review approved, or max iterations reached

## Configuration

Load from `~/.claude/plugins/agent-swarm/config/workflow.json`:

```json
{
  "iteration_modes": {
    "iterate": {
      "optional_phases": ["intake", "design"],
      "loop_phases": ["implement", "test", "review"],
      "max_iterations": 3,
      "checkpoint_after_loop": true,
      "exit_conditions": ["tests_pass", "review_approved", "max_reached"]
    }
  }
}
```

## Usage

### Quick Start (skip intake/design)
```bash
/iterate "Fix the bug in auth validation"
```

### With Design Phase
```bash
/iterate --design "Add caching to the API layer"
```

### Custom Iterations
```bash
/iterate --max-iter 5 "Optimize database queries"
```

## Loop Behavior

### Each Iteration

1. **IMPLEMENT**: Make code changes
   - Use `implementer` agent (sonnet)
   - Focused, incremental changes
   - Track what was modified

2. **TEST**: Run verification
   - Execute test suite
   - Check type errors
   - Run linter
   - Report: PASS or FAIL with details

3. **REVIEW**: Evaluate changes
   - Use `reviewer` agent (sonnet)
   - Check against requirements
   - Identify remaining issues
   - Decision: APPROVED, NEEDS_WORK, or BLOCKED

### Exit Conditions

| Condition | Trigger |
|-----------|---------|
| `tests_pass` | All tests green, no type/lint errors |
| `review_approved` | Reviewer approves with no blocking issues |
| `max_reached` | Hit `max_iterations` limit |

### On Exit

- Checkpoint for user approval
- Summary of all iterations
- List of files changed
- Test results
- Review findings

## Implementation Commands

### Initialize Iterate Session
```bash
python3 << 'EOF'
import json
from pathlib import Path

state_path = Path.home() / ".claude/plugins/agent-swarm/.state/session.json"
state = json.loads(state_path.read_text()) if state_path.exists() else {}

state["mode"] = "iterate"
state["iteration"] = 0
state["max_iterations"] = 3  # Override with --max-iter
state["loop_phase"] = "implement"
state["exit_reason"] = None

state_path.write_text(json.dumps(state, indent=2))
print(f"[ITERATE] Initialized - max {state['max_iterations']} iterations")
EOF
```

### Advance Loop Phase
```bash
python3 << 'EOF'
import json
from pathlib import Path

state_path = Path.home() / ".claude/plugins/agent-swarm/.state/session.json"
state = json.loads(state_path.read_text())

phases = ["implement", "test", "review"]
current = state.get("loop_phase", "implement")
current_idx = phases.index(current)

if current_idx == len(phases) - 1:
    # Completed review, start new iteration
    state["iteration"] = state.get("iteration", 0) + 1
    state["loop_phase"] = "implement"
    
    if state["iteration"] >= state.get("max_iterations", 3):
        state["exit_reason"] = "max_reached"
        print(f"[ITERATE] Max iterations reached - checkpoint required")
    else:
        print(f"[ITERATE] Starting iteration {state['iteration'] + 1}")
else:
    state["loop_phase"] = phases[current_idx + 1]
    print(f"[ITERATE] Phase: {state['loop_phase']}")

state_path.write_text(json.dumps(state, indent=2))
EOF
```

### Check Exit Condition
```bash
python3 << 'EOF'
import json
from pathlib import Path

state_path = Path.home() / ".claude/plugins/agent-swarm/.state/session.json"
state = json.loads(state_path.read_text())

exit_reason = state.get("exit_reason")
iteration = state.get("iteration", 0)
max_iter = state.get("max_iterations", 3)

if exit_reason:
    print(f"[ITERATE] EXIT: {exit_reason}")
    print(f"  Completed {iteration} iterations")
    print(f"  Ready for checkpoint")
else:
    print(f"[ITERATE] Iteration {iteration + 1}/{max_iter}")
    print(f"  Phase: {state.get('loop_phase', 'implement')}")
    print(f"  Continue loop...")
EOF
```

### Mark Exit Condition
```bash
python3 << 'EOF'
import json, sys
from pathlib import Path

# Set exit reason: tests_pass, review_approved, or max_reached
reason = "tests_pass"  # Change as needed

state_path = Path.home() / ".claude/plugins/agent-swarm/.state/session.json"
state = json.loads(state_path.read_text())

state["exit_reason"] = reason
state_path.write_text(json.dumps(state, indent=2))
print(f"[ITERATE] Marked exit: {reason}")
EOF
```

## Agent Usage

### Implement Phase
```json
{
  "subagent_type": "agent-swarm:implementer",
  "model": "sonnet",
  "prompt": "Implement: <specific change>. This is iteration N of iterate loop."
}
```

### Test Phase
Run directly (no subagent needed):
```bash
# Run test suite
pytest tests/ -v

# Type check
mypy src/

# Lint
ruff check src/
```

### Review Phase
```json
{
  "subagent_type": "agent-swarm:reviewer",
  "model": "sonnet", 
  "prompt": "Review iteration N changes. Check: <requirements>. Approve or identify issues."
}
```

## Greptile Integration

For AI-powered code review during the review phase:

```bash
# Quick review of current changes
python3 ~/.claude/plugins/agent-swarm/scripts/greptile_query.py \
  "Review the recent changes for bugs, security issues, and code quality" \
  --genius

# Targeted review
python3 ~/.claude/plugins/agent-swarm/scripts/greptile_query.py \
  "Check if these changes follow SOLID principles" \
  --repo owner/repo --branch feature-branch
```

## Example Session

```
User: /iterate "Fix the N+1 query in user list endpoint"

[ITERATE] Initialized - max 3 iterations
[ITERATE] Skipping intake/design (requirements clear)

--- Iteration 1 ---
[IMPLEMENT] Adding eager loading to user query
  Modified: src/api/users.py
  
[TEST] Running verification
  pytest: PASS (12 tests)
  mypy: PASS
  
[REVIEW] Checking changes
  ✓ N+1 query fixed
  ⚠ Could add query count assertion to tests
  Decision: NEEDS_WORK

--- Iteration 2 ---
[IMPLEMENT] Adding query count test
  Modified: tests/test_users.py
  
[TEST] Running verification
  pytest: PASS (13 tests)
  mypy: PASS
  
[REVIEW] Checking changes
  ✓ N+1 fixed with test coverage
  Decision: APPROVED

[ITERATE] EXIT: review_approved
  Completed 2 iterations
  
[CHECKPOINT] Ready for user approval
  Files changed: src/api/users.py, tests/test_users.py
  All tests passing
  Review: APPROVED
```

## Differences from Orchestrate

| Aspect | Orchestrate | Iterate |
|--------|-------------|---------|
| Phases | Full workflow (8 phases) | Tight loop (3 phases) |
| Checkpoints | Per-phase configurable | Single at end |
| Research | Included | Skip (requirements known) |
| Design | Full architecture | Optional quick plan |
| Focus | Complex/unknown tasks | Rapid iteration |
| Feedback | Per-phase summary | Per-iteration summary |
