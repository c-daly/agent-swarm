# Iterate Workflow

**User-Invocable:** Yes (`/iterate`)

A tight development loop for rapid iteration with adversarial testing. The adversary agent evaluates test quality, writes missing tests, and uses Greptile to validate coverage before final review.

## When to Use

- Small to medium feature work
- Bug fixes with test verification
- Refactoring with continuous validation
- Any task where you want robust test coverage

## Flow

```
[intake?] → [design?] → implement → ADVERSARY LOOP → Greptile review → [checkpoint] → done
                              ↑____________|fail
```

**Optional phases:** intake, design (skip if requirements are clear)
**Adversary loop:** Runs until Greptile confirms coverage is solid
**Exit conditions:** Greptile approves coverage, or max iterations reached

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

2. **ADVERSARY**: Evaluate and strengthen tests
   - Use `adversary` agent (sonnet)
   - Run `pytest --cov` to collect coverage
   - Query Greptile: "Should passing tests give confidence?"
   - If gaps exist:
     - Write tests targeting blind spots
     - Query Greptile: "Are these tests legitimate and fair?"
     - Run tests
     - If fail → back to IMPLEMENT
   - Loop until Greptile says coverage is solid

3. **REVIEW**: Final code review via Greptile
   - Query: "Tests are solid. Review implementation for bugs, security, maintainability."
   - Decision: APPROVED, NEEDS_WORK, or BLOCKED
   - If NEEDS_WORK → back to IMPLEMENT

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

## Adversary Agent

The adversary agent is the core differentiator of the iterate workflow. It acts as an adversarial tester that:

1. **Analyzes coverage** - Runs `pytest --cov` and parses results
2. **Questions confidence** - Asks Greptile if passing tests mean anything
3. **Finds blind spots** - Identifies untested code paths, weak assertions, missing edge cases
4. **Writes tests** - Creates tests targeting identified weaknesses
5. **Validates tests** - Submits new tests to Greptile for fairness check
6. **Routes failures** - Sends back to implementer if tests fail

### Scopes

| Scope | Trigger | What It Analyzes |
|-------|---------|------------------|
| `commit` | default | Files changed in HEAD commit |
| `pr` | `--scope pr` | Files changed vs base branch |
| `codebase` | `--scope codebase` | Full coverage analysis |

### Usage

```bash
# Default (commit scope)
/iterate "Fix the auth bug"

# PR scope
/iterate --scope pr "Add user validation"

# Full codebase analysis
/iterate --scope codebase "Improve test coverage"
```

### Coverage Analysis Script

```bash
# Get coverage for commit scope
python3 scripts/adversary_analyze.py --scope commit --run-coverage

# Format for Greptile query
python3 scripts/adversary_analyze.py --scope pr --greptile

# JSON output
python3 scripts/adversary_analyze.py --scope codebase --json
```

## Greptile Integration

Greptile is used at three points in the adversary loop:

### 1. Gap Discovery
```
Review tests for [files]. Coverage: [X]%. Uncovered: [lines].
Should passing tests give confidence this code is strong? What's missing?
```

### 2. Test Validation
```
Review these new tests. Are they:
1. Testing real behavior (not trivial)?
2. Fair (not gaming coverage)?
3. Following project test patterns?
```

### 3. Final Code Review
```
Tests are solid. Review the implementation for:
- Bugs and logic errors
- Security vulnerabilities
- Maintainability issues
```

## Example Session

```
User: /iterate "Fix the N+1 query in user list endpoint"

[ITERATE] Initialized - max 5 iterations
[ITERATE] Skipping intake/design (requirements clear)

--- Iteration 1 ---
[IMPLEMENT] Adding eager loading to user query
  Modified: src/api/users.py

[ADVERSARY] Analyzing coverage (commit scope)
  Coverage: 78% overall | 45% for changed files
  
  Greptile: "Should passing tests give confidence?"
  → No. Missing: error handling path, empty result case, pagination edge case
  
  Writing tests for gaps...
  Added: tests/test_users.py:45 - test_empty_user_list
  Added: tests/test_users.py:52 - test_user_list_pagination_boundary
  
  Greptile: "Are these tests fair?"
  → Yes. Tests cover real behavior and follow project patterns.
  
  Running tests...
  pytest: FAIL (test_user_list_pagination_boundary)
  
[ADVERSARY] → IMPLEMENTER (test failure)

--- Iteration 2 ---
[IMPLEMENT] Fixing pagination boundary condition
  Modified: src/api/users.py:34
  
[ADVERSARY] Analyzing coverage
  Coverage: 78% overall | 82% for changed files
  
  Greptile: "Should passing tests give confidence?"
  → Yes. Critical paths covered. Edge cases handled.
  
  Verdict: SOLID

[REVIEW] Final Greptile review
  "Tests are solid. Review implementation..."
  → No issues found. Code is clean and maintainable.
  Decision: APPROVED

[ITERATE] EXIT: review_approved
  Completed 2 iterations
  
[CHECKPOINT] Ready for user approval
  Files changed: src/api/users.py, tests/test_users.py
  Coverage: 45% → 82% for scope
  Tests added: 2
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
