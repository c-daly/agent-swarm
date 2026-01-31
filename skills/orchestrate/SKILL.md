---
name: orchestrate
description: Main workflow orchestrator for complex tasks. Coordinates phase transitions, enforces checkpoints based on config, manages subagent delegation. Invoke for [COMPLEX] tasks.
user_invocable: false
---

# Workflow Orchestrator

**State CLI:** `python3 scripts/state.py <command>`
- `transition <phase>` - change phase
- `checkpoint <phase> <on|off>` - configure checkpoint
- `autopilot <on|off|toggle>` - bypass checkpoints

## Phase Machine

```
INTAKE -> [RESEARCH] -> [EXPLORE] -> DESIGN -> IMPLEMENT -> REVIEW -> [DEBUG] -> GIT -> DONE
```

Bracketed phases optional. Checkpoints per `config/workflow.json`.
At checkpoint: present summary, use AskUserQuestion, record approval in `.state/session.json`.

## Phase -> Skill Mapping

When entering a phase, invoke the corresponding skill for detailed instructions:

| Phase | Skill to invoke | Agent | Model |
|-------|----------------|-------|-------|
| INTAKE | `/ctx` | - | - |
| RESEARCH | `/spawn` researcher | researcher | haiku |
| EXPLORE | `/spawn` explorer | explorer | haiku |
| DESIGN | `/spawn` architect | architect | sonnet |
| IMPLEMENT | `/iterate` or `/implement` | implementer | opus |
| REVIEW | `/spawn` reviewer | reviewer | sonnet |
| DEBUG | `/debug` | debugger | sonnet |
| GIT | `/spawn` git-agent | git-agent | haiku |

Do NOT load all phase skills upfront. Invoke only when entering that phase.

## Subagent Spawning

Token budgets (prevent runaways):

| Agent | Budget |
|-------|--------|
| explorer | 50K |
| researcher | 150K |
| architect | 120K |
| implementer | 100K |
| reviewer | 80K |
| debugger | 150K |
| git-agent | 30K |

Always include `token_budget` in Task tool calls.

## Tool Priority
1. Serena -> code analysis
2. Context7 -> docs
3. Batch scripts -> >=3 ops
4. MCP tools -> single ops
5. Read/Bash -> last resort

## Enforcement
Hook `combined-enforcement.py` enforces phase restrictions, token limits, subagent requirements, git safety.
Violations blocked with guidance.
