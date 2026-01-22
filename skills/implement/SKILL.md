---
name: implement
description: Use as default workflow when no specialized workflow (debug, iterate, pr-comment) applies. For general implementation tasks.
user_invocable: true
---

# Implement Workflow

Simple default workflow for general implementation. Use when specialized workflows don't apply.

## Initialize

```bash
python3 ~/.claude/plugins/agent-swarm/lib/implementer_workflow.py $ARGUMENTS
```

## Flow

```
WORK → VERIFY → DONE
     ↑    |
     +----+ (if tests/lint fail)
```

## Phases

| Phase | Purpose | Tools |
|-------|---------|-------|
| **work** | Do the task | All tools allowed |
| **verify** | Run tests and lint | All tools (can fix issues) |
| **done** | Complete | - |

## When to Use

- Subagent doing implementation work
- General task without specific workflow
- Default when no better workflow applies

## CLI

```bash
# Start
python3 lib/implementer_workflow.py start "Add feature X"

# With custom ID (for parallel agents)
python3 lib/implementer_workflow.py --id agent-123 start "Task"

# Check status
python3 lib/implementer_workflow.py status

# Record verification
python3 lib/implementer_workflow.py verify 1 1  # tests=pass, lint=pass

# Advance
python3 lib/implementer_workflow.py advance
```

## Exit Conditions

| Condition | Trigger |
|-----------|---------|
| `done` | Verification passed |
| `max_iterations` | 3 kickbacks |
| `user_stopped` | Manual stop |
