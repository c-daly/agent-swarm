---
name: pr-comment
description: PR review comment workflow - understand the concern before fixing
user_invocable: true
---

## Initialize (REQUIRED)
```bash
python3 ~/.claude/plugins/agent-swarm/lib/pr_comment_workflow.py start "<comment>" <pr_number>
```

## Flow
```
UNDERSTAND -> [adversary] -> FIX -> [adversary] -> VERIFY -> PUSH -> CHECK_REVIEWS -> DONE
```

## Phases

| Phase | Purpose | Allowed | Blocked |
|-------|---------|---------|---------|
| UNDERSTAND | Grasp reviewer's concern | Read, Glob, Grep | Edit, Write, Bash |
| FIX | Implement changes | Read, Glob, Grep, Edit, Write, Bash | - |
| VERIFY | Run tests/lint | Read, Glob, Grep, Bash | Edit, Write |
| PUSH | Push changes | Bash | - |
| CHECK_REVIEWS | Check for new comments | Read, Bash | Edit, Write |

## Required Before Leaving UNDERSTAND
- Articulate reviewer's concern in your own words
- Identify specific problem in current code

## Adversary Gates
- UNDERSTAND: validates your articulation of the concern
- FIX: checks fix matches articulated understanding

## Kickback
| From | To | Trigger |
|------|-----|---------|
| VERIFY | FIX | Tests/lint fail |
| CHECK_REVIEWS | UNDERSTAND | New review comments |

## CLI
```bash
python3 lib/pr_comment_workflow.py start "comment" <pr>              # Start
python3 lib/pr_comment_workflow.py understand "<articulation>" "<problem>"  # Record
python3 lib/pr_comment_workflow.py verify <tests> <lint>             # Record (1=pass)
python3 lib/pr_comment_workflow.py advance                           # Next phase
python3 lib/pr_comment_workflow.py stop                              # Stop
```
