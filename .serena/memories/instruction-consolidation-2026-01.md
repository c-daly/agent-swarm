# Instruction Consolidation Session - 2026-01-06

## What We Built

### CORE_PROTOCOL.md (60 lines)
Single source of truth for universal agent rules. Consolidates:
- Tool selection hierarchy (Serena → Context7 → Scripts → MCP)
- Batch operations (3+ = use scripts)
- Parallel execution (independent calls in one message)
- Output standards (bullets, file:line refs, max lengths)
- Token efficiency (references not content)
- Side-effect checking (find_referencing_symbols before changes)
- Failure protocol (fail fast, 3 attempts max)

**Impact:** Eliminates 215 lines of duplication across 8 agent instruction files

### state.py CLI (249 lines)
Replaces 15-20 line Python snippets with single commands:
```bash
python3 scripts/state.py transition <phase>
python3 scripts/state.py checkpoint <phase> <on|off>
python3 scripts/state.py autopilot <on|off|toggle>
python3 scripts/state.py show [key]
python3 scripts/state.py config <get|set> <key> [value]
```

**Location:** `scripts/state.py`
**Testing:** Verified working in this session

### Memory Capture Hook
Enhanced `hooks/session-end.py` to detect significant work and prompt memory writing.

**Triggers:** File changes, architecture work, problem-solving
**Provides:** Tool name, what to capture, concrete example

## Results

**Instruction reduction:** 957 → 553 lines (42% reduction)
**Token savings:** ~6,000 tokens per agent spawn
**Files modified:** 9 (all agent instruction files)
**Files created:** 3 (CORE_PROTOCOL, state.py, COMMON_MISTAKES)

## Key Gotchas

### 1. Phase Enforcement Blocking
**Issue:** After state.py test transitioned to DESIGN phase, all Bash/Write operations blocked
**Symptom:** Can't commit, can't run verification scripts
**Solution:** 
- Phase restriction cleared naturally as conversation progressed
- Alternative: state.py can transition back to correct phase
- Last resort: Manual session.json reset

**Lesson:** Phase enforcement is effective but strict. Keep phase aligned with actual work.

### 2. Hook Code Loading
**Fact:** Hook code loads at session START, not during session
**Implication:** Can't test hook changes in same session they're developed
**Workaround:** Verify syntax, simulate logic, test next session

### 3. Script Discovery Decision
**Chose:** Simple `ls scripts/` approach over full registry.json
**Rationale:**
- Less infrastructure to maintain
- Self-documenting via filenames  
- Can add registry later if needed
**Status:** Working well, may revisit if discovery becomes problem

## Architecture Decisions

### Three-Tier Instruction Hierarchy
```
TIER 1: CORE_PROTOCOL.md (universal rules, 60 lines)
TIER 2: Agent files (role-specific, ~35-40 lines each)
TIER 3: Hook context (subagent-briefing, orchestrate)
```

Each agent now sees ~100 total lines vs previous ~200+ lines

### Enforcement Over Documentation
**Philosophy:** "If instructions haven't prevented mistakes, they won't"

**Applied to:**
- Debugging anti-patterns → Moved to human docs (COMMON_MISTAKES.md)
- Memory writing → Prompt at session-end, not just hope
- Tool selection → Enforce with hooks

**Result:** Leaner instructions, more automated compliance

### State Management Centralization
**Before:** Manual Python snippets scattered in instructions
**After:** Single CLI with validated inputs, testable, extendable

## Commands Reference

### Check instruction sizes
```bash
wc -l agents/*.md hooks/subagent-briefing.md skills/orchestrate/SKILL.md CORE_PROTOCOL.md
```

### Test state.py
```bash
cd ~/.claude/plugins/agent-swarm
python3 scripts/state.py show
python3 scripts/state.py transition VERIFY
```

### Write to memory (like this!)
```python
mcp__plugin_serena_serena__write_memory(
    memory_file_name='descriptive-name-YYYY-MM',
    content='# Title\n\n## Section\nContent here'
)
```

## Next Steps

1. **Merge branch:** `refactor/consolidate-instructions` → master
2. **Monitor effectiveness:** Does CORE_PROTOCOL reduce confusion? Is state.py easier?
3. **Consider MEDIUM priority:** Tool guide consolidation, output templates, spawn helper
4. **Test memory capture:** This session should trigger the prompt!

## Files to Know

- `CORE_PROTOCOL.md` - Universal rules, reference first
- `scripts/state.py` - State management CLI
- `hooks/session-end.py` - Memory capture prompt
- `docs/troubleshooting/COMMON_MISTAKES.md` - Debugging anti-patterns (human reference)
- `.state/session.json` - Current session state (reset if phase stuck)
