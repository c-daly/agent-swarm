# Iterate Workflow Development - 2026-01-11

## Key Learnings

### What Worked
1. **Adversary agent** - Effectively found coverage gaps (16% → 88%) and wrote meaningful tests
2. **Greptile integration** - Found real bugs (format_monitor_result access pattern mismatch)
3. **Parallel Task spawning** - Works well for independent implementation tasks

### What Didn't Work
1. **No workflow enforcement** - I kept dropping out of the iterate loop, doing implementation directly instead of spawning agents
2. **Greptile reviews got out of sync** - Checked stale reviews that referenced already-fixed bugs
3. **Manual issue parsing** - Had to manually extract discrete tasks from Greptile reviews

## Solutions Needed

### 1. Phase Enforcement
Add `check_iterate_phase()` to combined-enforcement.py that:
- Tracks current phase in session state
- Blocks tool calls that don't match current phase
- Forces explicit phase transitions

### 2. Greptile SHA Tracking
- Track `last_pushed_sha` in session state
- Track `last_reviewed_sha` from Greptile response
- Block checking reviews until reviewed SHA matches pushed SHA

### 3. Issue Parser
Function to parse Greptile review body → discrete tasks for parallel spawning

## Parallel Workflow Pattern

```
┌─ Task(implementer): "Fix issue 1" ─┐
│─ Task(implementer): "Fix issue 2" ─│→ wait all → test → commit → push → WAIT → review
└─ Task(adversary): "Coverage gaps" ─┘
```

## Multi-PR Interleaving (for LOGOS-scale work)

```
PR A: implement → push → [Greptile reviewing A]
                              ↓ switch to B
PR B: implement → push → [Greptile reviewing B]
                              ↓ switch to A
PR A: check review (complete) → address issues → push
```

## Timeline Compression Vision

Sequential: 50 issues × 10 min = 8+ hours
Parallel (15 agents across 3 repos): ~45 min

## Core Design Principle

**Autonomous loop with visibility, running until user says stop.**

- Clear state at all times (phase, pending, blocked)
- Progress indicators (issues fixed, coverage %, agents running)
- Keeps running without approval seeking
- User can check in, see status, redirect or let it continue

User commands: `/iterate continue`, `/iterate pause`, `/iterate stop`, `/iterate focus <repo>`

## Implementation Files
- `skills/iterate/SKILL.md` - Updated with parallel patterns
- `HANDOFF.md` - Full implementation details and code snippets
- `hooks/combined-enforcement.py` - Needs phase enforcement added
