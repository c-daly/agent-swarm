---
name: implement
description: Auto-started default workflow. Overridden by iterate, debug, or orchestrate when invoked.
user_invocable: false
---

# Implement Workflow

**Auto-started** on every session. This is the default workflow for all implementation work.
You are already in the WORK phase. No initialization needed.

## Flow
WORK → VERIFY → DONE (you start in WORK)

## CLI (for manual control)
- `python3 lib/implementer_workflow.py status` — Check current phase
- `python3 lib/implementer_workflow.py advance` — Move to VERIFY when done
- `python3 lib/implementer_workflow.py verify 1 1` — Record test/lint results
- `python3 lib/implementer_workflow.py stop` — Stop workflow

## Exit Conditions

| Condition | Trigger |
|-----------|---------|
| `done` | Verification passed |
| `max_iterations` | 3 kickbacks |
| `user_stopped` | Manual stop |

