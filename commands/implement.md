---
description: Start implementer workflow for general tasks (use when iterate is broken or unnecessary)
argument-hint: [task description]
---

Start the implementer workflow for general implementation tasks.

**Use this when:**
- Iterate workflow is broken or unavailable
- You need to make quick fixes without TDD ceremony
- General implementation without specialized workflow

## Initialize

```bash
python3 ~/.claude/plugins/agent-swarm/lib/implementer_workflow.py $ARGUMENTS
```

## Workflow

Simple: WORK → VERIFY → DONE

All tools allowed in WORK phase. This is the escape hatch when iterate has issues.

## Commands

- `python3 lib/implementer_workflow.py status` - Check status
- `python3 lib/implementer_workflow.py advance` - Move to next phase
- `python3 lib/implementer_workflow.py stop` - Stop workflow
