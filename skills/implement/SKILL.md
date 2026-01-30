---
name: implement
description: Auto-started default workflow. Overridden by iterate, debug, or orchestrate when invoked.
user_invocable: false
---

Auto-started on every session. You are in the WORK phase.

## Flow
WORK -> VERIFY -> DONE

## CLI
```bash
python3 lib/implementer_workflow.py status    # Check phase
python3 lib/implementer_workflow.py advance   # Move to VERIFY
python3 lib/implementer_workflow.py verify 1 1  # Record test/lint (1=pass)
python3 lib/implementer_workflow.py stop      # Stop
```

Exit: verification passed, 3 kickbacks, or manual stop.
