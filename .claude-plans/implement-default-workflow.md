# Auto-Start Implementer Workflow as Default

## Problem

The main agent starts in CONVERSATION mode with all editing tools blocked behind workflow invocation. To do any implementation work, the user must invoke `/orchestrate` or `/iterate`, which adds ceremony and friction. Without an active workflow, various hooks have no workflow context, causing inconsistent behavior.

## Solution

Auto-start the implementer workflow (WORK → VERIFY → DONE) on every session start. The main agent is always in the WORK phase by default. `/iterate` and `/orchestrate` override when needed.

## Changes

### 1. `hooks/session-start.py` — Auto-start implementer workflow

In `main()`, after `reset_enforcement_counters()`, for main agent only (not subagents):

```python
if not agent_id:
    try:
        from permission_query import get_active_workflow_id
        active_wf = get_active_workflow_id()
        if active_wf is None:
            from implementer_workflow import ImplementerWorkflow
            wf = ImplementerWorkflow()
            wf.start("Default session workflow")
    except Exception:
        pass  # Don't fail session start
```

Logic:
- Only for main agent (`not agent_id`)
- Only if no workflow already active (iterate/debug/pr_comment take precedence)
- Uses existing `ImplementerWorkflow.start()` which creates proper state via router socket
- Fail-safe: exception doesn't break session start

### 2. `~/.claude/CLAUDE.md` — Remove classification gating

**Remove:**
- The entire classification system (TRIVIAL/CONVERSATION/RESEARCH)
- "CONVERSATION mode restrictions" (Edit/Write/Bash blocked)
- "To do implementation work: Invoke /orchestrate or /iterate"
- "Invoking a workflow unlocks: Edit, Write, NotebookEdit, Bash"

**Replace with:**
```
## 1. Default Workflow

You start every session in the **implementer workflow** (WORK → VERIFY → DONE).
All router tools are available immediately. No workflow invocation needed for implementation work.

**Workflow override:**
| Workflow | When to use |
|----------|-------------|
| `/iterate` | TDD discipline: test → implement → test → review loop |
| `/orchestrate` | Complex tasks needing discovery, design, user checkpoints |

When iterate or orchestrate activates, it takes precedence over the default implementer workflow.

**Before completing work:**
- Run tests (`pytest`)
- Run lint (`ruff check .`)
- Advance to VERIFY: `python3 lib/implementer_workflow.py advance`
```

**Keep:** All other sections (scope discipline, security, subagent usage, state persistence, quality checks).

### 3. `skills/implement/SKILL.md` — Update to reflect auto-start

Change the description and flow to indicate it's auto-started:

```
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
```

Remove the Initialize section that tells agents to run `python3 lib/implementer_workflow.py $ARGUMENTS`.

### 4. `hooks/subagent-briefing.md` — Mention default workflow

Add one line under the tool table to tell subagents they're in the implementer workflow by default and should advance through WORK → VERIFY → DONE.

## Files Modified

| File | Change |
|------|--------|
| `hooks/session-start.py` | Add auto-start after `reset_enforcement_counters()` |
| `~/.claude/CLAUDE.md` | Remove classification gating, add default workflow section |
| `skills/implement/SKILL.md` | Update to reflect auto-start, remove init section |
| `hooks/subagent-briefing.md` | Add default workflow mention |

## What Doesn't Change

- `lib/implementer_workflow.py` — No code changes needed, existing `start()` method works
- `hooks/native-tool-blocking.py` — Already allows mcp__router__* for main agent
- `lib/permission_query.py` — Already has "implementer" in `_KNOWN_WORKFLOWS`
- Iterate/orchestrate workflows — They use different workflow IDs, coexist cleanly
- `get_active_workflow_id()` checks iterate first, so iterate takes precedence automatically

## Verification

1. `python3 -c "from permission_query import get_active_workflow_id; print(get_active_workflow_id())"` → should return "implementer" after session start
2. Start a new session → no classification prompt, can edit immediately
3. Invoke `/iterate` → iterate takes over, implementer stays but is deprioritized
4. Session-start hook completes without errors in `.state/workflow_client.log`
