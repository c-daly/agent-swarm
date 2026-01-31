---
name: debug
description: Systematic debugging workflow with root cause verification before fixing
user_invocable: true
---

## Initialize (REQUIRED)
```bash
python3 ~/.claude/plugins/agent-swarm/lib/debug_workflow.py start "$ARGUMENTS"
```

## Flow
```
TRIAGE -> REPRODUCE -> HYPOTHESIZE -> [adversary] -> PROVE -> [adversary] -> FIX -> [adversary] -> VERIFY -> PUSH -> CHECK_STATUS -> DONE
```

## Phases

| Phase | Purpose | Allowed | Blocked |
|-------|---------|---------|---------|
| TRIAGE | Understand bug context | Read, Glob, Grep, Web | Edit, Write |
| REPRODUCE | Create failing test | Read, Glob, Grep, Edit, Write, Bash | (test files only) |
| HYPOTHESIZE | Form root cause theory | Read, Glob, Grep | Edit, Write |
| PROVE | Verify hypothesis | Read, Glob, Grep, Bash | Edit, Write |
| FIX | Implement fix | Read, Glob, Grep, Edit, Write, Bash | - |
| VERIFY | Run tests/lint | Read, Glob, Grep, Bash | Edit, Write |
| PUSH | Push changes | Bash | - |
| CHECK_STATUS | Verify CI/reviews | Read, Bash | Edit, Write |

## Adversary Gates
- HYPOTHESIZE: challenges alternative explanations
- PROVE: verifies prediction confirmed mechanism
- FIX: checks fix addresses proven root cause

## Kickback
| From | To | Trigger |
|------|-----|---------|
| REPRODUCE | TRIAGE | Can't reproduce |
| PROVE | HYPOTHESIZE | Prediction not confirmed |
| VERIFY | PROVE | Tests/lint fail |
| CHECK_STATUS | PROVE | CI fails or new comments |

## CLI
```bash
python3 lib/debug_workflow.py start "desc"                           # Start
python3 lib/debug_workflow.py status                                 # Status
python3 lib/debug_workflow.py phase                                  # Current phase
python3 lib/debug_workflow.py triage <sev> "<components>" "<artifacts>"  # Record triage
python3 lib/debug_workflow.py hypothesis "<hypothesis>" "<prediction>"   # Record hypothesis
python3 lib/debug_workflow.py verify <tests> <lint>                  # Record (1=pass)
python3 lib/debug_workflow.py advance                                # Next phase
python3 lib/debug_workflow.py stop                                   # Stop
```
