# Iterate Workflow Enhancement Spec

## Overview

Enhance `/iterate` to support discovery phases (INTAKE → DESIGN → ORCHESTRATE) when input is vague, then spawn autonomous subagents for TDD implementation.

---

## Phase Definitions

### Phase 1: INTAKE (optional)
- **Trigger:** Vague input requiring discovery
- **Purpose:** Understand requirements, gather context
- **Output:** Clarified requirements, scope definition
- **Advances to:** DESIGN

### Phase 2: DESIGN (optional)
- **Trigger:** Advancement from INTAKE only
- **Purpose:** Plan architecture, define tasks, write spec
- **Output:** Spec file saved, task queue populated
- **Advances to:** ORCHESTRATE

### Phase 3: ORCHESTRATE (automatic event loop)
- **Purpose:** Task manager for subagents
- **Responsibilities:**
  - Track active subagent count (respect `max_agents` config)
  - Manage task queue with dependencies
  - Spawn subagents as needed (each starts at `test_writing`)
  - Collect output from subagents on completion
  - After batch push: read external review comments
  - Convert review comments → new tasks
  - Add review tasks to queue
- **Exit condition:** Queue empty AND no active subagents AND external review clean

---

## Subagent Lifecycle (autonomous)

```
test_writing → implement → test → review → [commit] → DONE
      ↑           ↑         │       │
      │           │         │       │
      │           └─────────┤       │
      │        (test/lint)  │       │
      │                     │       │
      └─────────────────────┘       │
         (coverage fail)            │
                                    │
      implement ◄───────────────────┘
         (pre-push check fail)
```

### Phase: test_writing
- Write failing tests (TDD red)
- Advances to: implement

### Phase: implement
- Write code to make tests pass (TDD green)
- Advances to: test

### Phase: test
- Run tests, lint, coverage
- **test/lint fail** → kickback to implement
- **coverage fail** → kickback to test_writing
- **all pass** → advances to review

### Phase: review
- Optional: pre-push code examination
- **pre-push issues** → kickback to implement
- **clean** → commit, call push (gated), subagent terminates

---

## Task Lifecycle

```
pending → in_progress → committed → [batch push] → in_review → done
                                                       │
                                          (issues) ────┘
                                               ↓
                                     new tasks (pending)
```

---

## Push Batching (Gated Push)

Commits held until ALL tasks for a PR are committed. Push is a gated action:

```python
def push():
    pr_group = get_current_pr_group()
    tasks = get_tasks_for_pr_group(pr_group)

    if all(t.status == "committed" for t in tasks):
        git_push()  # Actually push
        mark_tasks_in_review(tasks)
        log(f"Pushed PR group: {pr_group}")
    else:
        log(f"Push deferred - waiting on {len(pending)} tasks")
        # Return silently, subagent completes normally
```

- Last subagent to commit triggers actual push
- Subagent doesn't know whether push actually happened
- Avoids triggering multiple review cycles

---

## Task Dependencies

Tasks can depend on other tasks. ORCHESTRATE only spawns tasks whose dependencies are complete.

```json
{
  "queue": [
    {"id": "task-001", "pr_group": "feature-auth", "depends_on": [], "status": "pending"},
    {"id": "task-002", "pr_group": "feature-auth", "depends_on": ["task-001"], "status": "pending"},
    {"id": "task-003", "pr_group": "feature-auth", "depends_on": ["task-001", "task-002"], "status": "pending"}
  ]
}
```

### Spawn Logic

```
FOR each pending task:
    IF dependencies all "committed" or "done":
        IF active_subagents < max_agents:
            spawn subagent for task
            mark task "in_progress"
```

---

## ORCHESTRATE Event Loop (Automatic)

```
ORCHESTRATE:
    LOOP (automatic):
        - Check for spawnable tasks (deps met, under max_agents)
        - Spawn eligible tasks
        - Listen for subagent completions
        - Update task status on completion
        - When all tasks committed → batch push (gated)
        - Poll for review (every N minutes)
        - Convert review comments → tasks
        - EXIT when: queue empty + no active + review clean
```

---

## Configuration

```json
{
  "max_agents": 3,
  "review_poll_interval_minutes": 5
}
```

---

## Input Detection

**Start at INTAKE when:**
- No clear file targets
- Requirements are vague/ambiguous
- "Create", "build", "design" without specifics
- Cannot immediately write a failing test

**Start at test_writing when:**
- Specific file(s) identified
- Clear expected behavior
- Can write a test immediately

---

## Iterate Input Types

```
1. Vague input     → INTAKE → DESIGN → [spec file] + [task queue] → ORCHESTRATE
2. Spec file       → decompose → [task queue] → ORCHESTRATE
3. Task queue file → load → ORCHESTRATE
```

---

## Spec and Task Queue Handling

**Specs:**
- Saved to file (e.g., `docs/specs/<feature>-spec.md`)
- Persistent artifact from DESIGN phase

**Task Queue:**
- In-memory during execution
- Can be saved on session end for resumption
- Saved format is valid input to restart iterate

---

## DESIGN Phase Outputs

1. **Spec file** (saved to `docs/specs/`)
2. **Task queue** (in-memory, decomposed from spec)

---

## Session Persistence

On session end (before completion):
```json
// .state/task_queue.json
{
  "spec_file": "docs/specs/feature-spec.md",
  "tasks": [
    {"id": "task-001", "status": "committed", ...},
    {"id": "task-002", "status": "in_progress", ...},
    {"id": "task-003", "status": "pending", ...}
  ]
}
```

Resume with:
```bash
python3 lib/iterate_workflow.py start --queue=.state/task_queue.json
```

---

## State Schema

```json
{
  "phase": "ORCHESTRATE",
  "iteration": 1,
  "max_iterations": 5,
  "task": "description",
  "spec_file": "docs/specs/feature-spec.md",
  "queue": [
    {
      "id": "task-001",
      "description": "...",
      "status": "pending|in_progress|committed|in_review|done",
      "depends_on": [],
      "subagent_id": null,
      "pr_group": "feature-name"
    }
  ],
  "active_subagents": ["agent-id-1", "agent-id-2"],
  "pr_groups": {
    "feature-name": {
      "tasks": ["task-001", "task-002"],
      "pushed": false,
      "review_clean": false
    }
  }
}
```

---

## CLI Interface

```bash
# Start with auto-detection
python3 lib/iterate_workflow.py start "<task>" [max_iterations]

# Start with spec file
python3 lib/iterate_workflow.py start --spec=docs/specs/feature-spec.md

# Start with saved queue (resume)
python3 lib/iterate_workflow.py start --queue=.state/task_queue.json

# Force start phase
python3 lib/iterate_workflow.py start "<task>" --phase=INTAKE
python3 lib/iterate_workflow.py start "<task>" --phase=test_writing

# Advance phase
python3 lib/iterate_workflow.py advance

# Record test results (subagent)
python3 lib/iterate_workflow.py test <tests:0|1> <lint:0|1> <coverage:0|1>

# Record review result (subagent)
python3 lib/iterate_workflow.py review <clean:0|1>

# Queue management (ORCHESTRATE)
python3 lib/iterate_workflow.py queue add "<task description>" [--depends=task-id,task-id]
python3 lib/iterate_workflow.py queue list
python3 lib/iterate_workflow.py queue status <task_id> <status>

# Subagent management (ORCHESTRATE)
python3 lib/iterate_workflow.py subagent spawn <task_id>
python3 lib/iterate_workflow.py subagent complete <subagent_id> <output>
python3 lib/iterate_workflow.py subagent list

# Push (gated)
python3 lib/iterate_workflow.py push [--pr-group=name]

# Save queue for resumption
python3 lib/iterate_workflow.py save

# Status
python3 lib/iterate_workflow.py status
```

---

## Subagent Spawning

Use Task tool with `subagent_type`:

```python
Task(
    description=f"Implement: {task['description']}",
    prompt=f"...",
    subagent_type="agent-swarm:implementer",
    model="sonnet",
    run_in_background=True
)
```
