# Iterate Workflow

**User-Invocable:** Yes (`/iterate`)

TDD development loop with phase gates. Works autonomously until exit conditions met.

## Flow

**With ORCHESTRATE (main agent coordinates workers):**
```
ORCHESTRATE ──┬──→ [spawn subagents] ──→ queue empty? ──→ done
              │                              ↓
              └──────────── no ←─────────────┘
```

**Subagents (TDD loop):**
```
test_writing → implement → test → review → done
      ↑            ↑         |       |
      |            |         v       v
      +-- coverage +-- fail -+  issues
```

## Phases

| Phase | Purpose | Allowed Tools |
|-------|---------|---------------|
| **orchestrate** | Main agent coordinates workers | Read, Task, TaskOutput, TodoWrite (NO Edit/Write/Bash!) |
| **test_writing** | Write tests first (spec) | Read, Glob, Grep, Edit, Write, Bash |
| **implement** | Make tests pass | Read, Glob, Grep, Edit, Write, Bash |
| **test** | Run pytest, lint, coverage | Read, Glob, Grep, Bash (no editing!) |
| **review** | Fix Greptile issues | Read, Glob, Grep, Edit, Write, Bash |

## Orchestrator Role

**When in ORCHESTRATE phase, you NEVER do implementation tasks. Edit/Write/Bash are BLOCKED.**

The ORCHESTRATE phase enforces the orchestrator role through tool restrictions:
- ✅ Read, Task, TaskOutput, TodoWrite - coordination tools
- ❌ Edit, Write, NotebookEdit, Bash - blocked, spawn agents instead

### Rules
- 1 task → spawn 1 agent
- 5 tasks → spawn 5 agents in parallel
- No exceptions - you cannot edit code yourself

### Orchestrator responsibilities (ORCHESTRATE phase)
- Read specs/queue files
- Spawn subagents via Task tool
- Monitor completions via TaskOutput
- Track progress via TodoWrite
- Check completion: `is_orchestration_complete()` → queue empty AND no workers

### What the orchestrator does NOT do
- **Does NOT evaluate agent work quality** - agents are responsible for their own verification
- **Does NOT run tests** - test/review agents handle that
- **Does NOT review code** - reviewer agents handle that
- Just spawns agents, takes output, updates queue

Future: Autokill feature may terminate long-running or failing agents.

### Insufficient context → Go back to INTAKE
If the orchestrator cannot write quality prompts because it lacks context:

**Orchestrator does NOT explore in ORCHESTRATE.** Go back to INTAKE phase.

INTAKE is where orchestrator context gathering happens:
- Explore codebase
- Read relevant files
- Understand scope and patterns
- Gather requirements

**If you're in ORCHESTRATE and can't write good prompts:**
```bash
python3 lib/iterate_workflow.py set-phase intake
```

Then complete intake properly before returning to orchestrate.

**Signs you rushed intake:**
- Writing vague prompts like "implement spec.md"
- Not knowing which files to reference
- Unclear on existing patterns
- Missing acceptance criteria

### Subagents explore current code
Subagents are close to the code - they explore their specific area of the **current codebase**:
- Read related files to understand patterns
- Grep for similar implementations
- Check for side effects before changes
- Find existing code to follow

**NOT web searches.** Subagents understand the code they're changing, not researching external topics.
Web/external research happens in RESEARCH phase (orchestrator responsibility).

### Subagent responsibilities (TDD loop phases)
- Write tests (test_writing phase)
- Write/modify code (implement phase)
- Fix review issues (review phase)

## Task Queue (Fundamental)

**ALL work flows through the task queue.** This is not optional infrastructure - it's the enforcement mechanism that ensures subagents are spawned.

### Queue Flow

```
IMPLEMENT phase:
  Identify work → Add to queue → Spawn agents → Mark done → Push when queue empty

REVIEW phase:
  Get comments → Add to queue → Spawn agents → Mark done → Push when queue empty
```

### Queue Operations

| Operation | When | API |
|-----------|------|-----|
| Add task | After decomposing work | `workflow_queue.add_task(task)` |
| Spawn agents | After populating queue | `Task(...)` for each item (up to max parallel) |
| Mark done | After agent completes | `workflow_queue.mark_done(task_id)` |
| Check empty | Before push | `workflow_queue.all_complete(pr_id)` |

### Push Triggers

Push happens when:
- Implementation batch is complete (queue empty after implement phase)
- Review comments are all addressed (queue empty after review fixes)

**Do NOT push after each task.** Wait for the batch.

### Dynamic Queue Updates

The queue can grow during execution:
- New implementation tasks discovered during work
- New review comments after push
- Dependencies identified by subagents

The orchestrator monitors and repopulates as needed.

## Parallel Execution

Spawn agents in ONE message block (up to max configured) to run simultaneously:

```
Task(description="Implement module A", subagent_type="agent-swarm:implementer", prompt="...")
Task(description="Implement module B", subagent_type="agent-swarm:implementer", prompt="...")
Task(description="Implement module C", subagent_type="agent-swarm:implementer", prompt="...")
```

Even for a single task:
```
Task(description="Implement module A", subagent_type="agent-swarm:implementer", prompt="...")
```

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

## PR Completion Tracking

Work is grouped by logical PRs. The orchestrator MUST track completion properly:

After each agent completes:
1. Update task status: `workflow_queue.mark_done(task_id)`
2. Check if PR ready: `workflow_queue.all_complete(pr_id)`
3. Only push when ALL tasks for PR are done
4. Triggers ONE Greptile review per PR, not per task

**Do NOT:**
- Push after each individual task completes
- Trigger multiple reviews for the same PR

## Review Phase

1. Verify all PR tasks complete (see PR Completion Tracking)
2. Push changes to trigger Greptile review (ONE push per PR)
3. Check for review comments
4. If issues found: `python3 lib/iterate_workflow.py review 0` then `advance`
5. If clean: `python3 lib/iterate_workflow.py review 1` then `advance`

## Exit Conditions

| Condition | Trigger |
|-----------|---------|
| `orchestration_complete` | Queue empty AND no active workers (ORCHESTRATE mode) |
| `review_approved` | Review clean, workflow complete (TDD loop) |
| `max_iterations` | Hit iteration limit (default: 5) |
| `user_stopped` | Manual `/iterate stop` |

## DO NOT

- Skip phases (workflow enforces order)
- Use Edit/Write in test phase (blocked by hook)
- Use Edit/Write/Bash in ORCHESTRATE phase (blocked - spawn agents instead)
- Ignore kick-back (follow the loop)
- Bypass test verification
- Do implementation work yourself (ALWAYS spawn agents)
- Spawn agents sequentially (use ONE message block for parallel execution)
