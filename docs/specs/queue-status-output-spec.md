# Queue Status Output Spec

## Overview

Add a compact task queue status display to the iterate workflow that shows at key moments.

## Output Format

```
[ITERATE] ═══════════════════════════════════════════════════════════════
  Phase: <PHASE> | Iteration: <N>/<MAX>
  Task: <description>

  Queue: <pending> pending | <active> active | <done> done
  ├─ [▶] task-id: description (worker-id)      # active
  ├─ [ ] task-id: description (blocked by: X)  # pending with deps
  ├─ [ ] task-id: description                  # pending
  └─ [✓] task-id: description                  # completed
═══════════════════════════════════════════════════════════════════════
```

## When to Show

- Workflow start
- Task completion
- Phase transitions
- Push/review events

## When NOT to Show

- Every spawn
- Every poll check
- Internal state updates

## Implementation

1. Add `format_queue_status()` function to iterate_workflow.py
2. Add `print_status_banner()` for the decorated output
3. Call from key points: start(), advance_phase(), handle_worker_completion()
4. Add config option to enable/disable (default: enabled)

## Files to Modify

- `lib/iterate_workflow.py` - main implementation
- `lib/orchestrate.py` - call on worker completion
