# Iterate Workflow

**User-Invocable:** Yes (`/iterate`)

TDD development loop with phase gates. Works autonomously until exit conditions met.

## Flow

```
test_writing → implement → test → review → done
      ↑            ↑         |       |
      |            |         v       v
      +-- coverage +-- fail -+  issues
```

## Phases

| Phase | Purpose | Allowed Tools |
|-------|---------|---------------|
| **test_writing** | Write tests first (spec) | Read, Glob, Grep, Edit, Write, Bash, Task |
| **implement** | Make tests pass | Read, Glob, Grep, Edit, Write, Bash, Task |
| **test** | Run pytest, lint, coverage | Read, Glob, Grep, Bash (no editing!) |
| **review** | Fix Greptile issues | Read, Glob, Grep, Edit, Write, Bash, Task |

## Kick-back Logic

After `test` phase, results determine next phase:

| Result | Next Phase | Why |
|--------|------------|-----|
| All pass | review | Ready for code review |
| Coverage low | test_writing | Need more tests |
| Tests fail | implement | Fix code |
| Lint fail | implement | Fix code |

After `review` phase:

| Result | Next Phase | Why |
|--------|------------|-----|
| Clean | done | Workflow complete |
| Issues | implement | Fix review comments |

## Usage

```bash
# Start iterate workflow
/iterate "Add user validation feature"

# With custom max iterations
/iterate --max 10 "Refactor auth module"
```

## CLI Commands

```bash
# Start workflow
python3 lib/iterate_workflow.py start "task description" [max_iterations]

# Check status
python3 lib/iterate_workflow.py status

# Get current phase
python3 lib/iterate_workflow.py phase

# Advance to next phase
python3 lib/iterate_workflow.py advance

# Record test results (after running pytest, lint, coverage)
python3 lib/iterate_workflow.py test <tests> <lint> <coverage>
# Use 1=pass, 0=fail. Example: test 1 1 0 (tests pass, lint pass, coverage fail)

# Record review status
python3 lib/iterate_workflow.py review <clean>
# Use 1=clean, 0=issues

# Stop workflow
python3 lib/iterate_workflow.py stop
```

## Test Phase Verification

In the `test` phase, run these checks:

```bash
# 1. Run tests
pytest tests/ -v

# 2. Run lint
ruff check .

# 3. Run coverage
pytest --cov=. --cov-report=term-missing

# 4. Record results
python3 lib/iterate_workflow.py test 1 1 1  # if all pass
python3 lib/iterate_workflow.py test 1 0 1  # if lint failed
python3 lib/iterate_workflow.py test 0 1 1  # if tests failed

# 5. Advance phase (kick-back or proceed based on results)
python3 lib/iterate_workflow.py advance
```

## Review Phase

1. Push changes to trigger Greptile review
2. Check for review comments
3. If issues found: `python3 lib/iterate_workflow.py review 0` then `advance`
4. If clean: `python3 lib/iterate_workflow.py review 1` then `advance`

## Exit Conditions

| Condition | Trigger |
|-----------|---------|
| `review_approved` | Review clean, workflow complete |
| `max_iterations` | Hit iteration limit (default: 5) |
| `user_stopped` | Manual `/iterate stop` |

## DO NOT

- Skip phases (workflow enforces order)
- Use Edit/Write in test phase (blocked by hook)
- Ignore kick-back (follow the loop)
- Bypass test verification
