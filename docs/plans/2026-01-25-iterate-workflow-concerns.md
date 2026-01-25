# Iterate Workflow Concerns

**Date:** 2026-01-25
**Updated:** 2026-01-25
**Status:** Most issues resolved or have clear path forward

---

## 1. Chicken-and-Egg in Orchestrate Phase

**Problem:** Orchestrate phase is meant for spawning agents, but it blocks too many tools. Can't easily fix the workflow itself when problems arise.

**Status:** ✅ Resolved

**Resolution:** `/implement` command provides an escape hatch. When iterate workflow is broken or stuck, use `/implement` to bypass it entirely. This is documented in the command itself.

---

## 2. Error Message Quality

**Problem:**
- "Unknown error" masks real issues
- "Run tests first" appears even when it doesn't apply
- Hook errors don't always explain what to do instead

**Status:** ✅ Partially Fixed

**What's fixed:**
- "Unknown error" → now shows actual stderr (mcp_native.py:661)
- "Run tests first" → changed to "Complete current phase before using this tool" (iterate_workflow.py:329)

**Still aspirational:**
- Context-aware error messages per phase (nice-to-have, not blocking)

---

## 3. Multi-Repo Support Incomplete

**Problem:**
- `repo_path` exists but the plumbing is fragile
- Race conditions with shared state when spawning parallel agents
- `mcp-call` lacks --cwd flag

**Status:** ✅ Resolved

**What's fixed:**
- `--cwd` flag added to mcp-call (bin/mcp-call)
- Race condition fixed - repo_path passed directly to on_spawn (orchestrate.py:269-272)
- Briefing docs updated with multi-repo git examples (hooks/subagent-briefing.md)

**Verified:** 2026-01-25 - git operations with --cwd work correctly across LOGOS repos.

---

## 4. mcp-call Ergonomics

**Problem:**
- JSON escaping in mcp-call is error-prone for complex args
- No tab completion or discoverability for available tools

**Status:** Low priority - ergonomic annoyance, not a blocker

**Notes:** Subagents *should* be limited. The mcp-call approach is functional. Shell aliases (git, gh, pytest) cover the common cases without JSON. Complex JSON args are rare in practice.

**Potential improvements (if needed later):**
- `mcp-call --list` to show available tools
- `mcp-call --help <tool>` to show tool schema
- Better error messages for malformed JSON

---

## 5. Phase Transitions Are Manual

**Problem:**
- No automatic phase advancement
- Tests pass → still need manual `advance` command
- Easy to get stuck in wrong phase

**Status:** Open - has design proposal

**Proposal:** Opt-in auto-advance triggers in workflow config:
```python
auto_advance = {
    "verify": {
        "conditions": ["tests_pass", "no_lint_errors"],
        "target": "review"
    }
}
```
- Keep manual advancement as default
- Let users opt into auto-advance per phase
- Conditions are composable (all must pass)

**Priority:** Medium - reduces friction but manual works fine

---

## 6. Debugging Is Hard

**Problem:**
- Subagent output is in temp files
- Errors get swallowed or masked
- No clear way to see what subagents tried

**Status:** Open - has design proposal

**Proposal:**
1. **`--verbose` flag** for workflows - tails subagent output files in real-time
2. **Failure dump** - on subagent failure, automatically include last N lines of output in main context
3. **`/iterate debug` command** - shows recent subagent activity, output file locations, last errors

**Priority:** Medium - would significantly improve debugging experience

---

## 7. Hook Layering Complexity

**Problem:**
- Multiple enforcement hooks with overlapping rules
- Hard to know which hook blocked what
- No centralized "what can I do here?" command

**Status:** Migration debt - will be resolved by centralized router

**Notes:** The router-based approach being developed will centralize tool access control. Once that's in place, most hooks can be removed. This concern is tracking debt to clean up, not a design flaw to fix in the current system.

**Interim mitigation:** `/iterate status` shows current phase and basic info. A `--tools` flag could list allowed tools, but may not be worth implementing if hooks are going away.

---

## Summary

| # | Concern | Status | Action |
|---|---------|--------|--------|
| 1 | Orchestrate chicken-and-egg | ✅ Resolved | /implement is the escape hatch |
| 2 | Error message quality | ✅ Mostly fixed | Specific issues addressed |
| 3 | Multi-repo support | ✅ Resolved | --cwd and race fix verified |
| 4 | mcp-call ergonomics | Low priority | Functional, not blocking |
| 5 | Manual phase transitions | Open | Opt-in auto-advance proposal |
| 6 | Debugging is hard | Open | --verbose / debug command proposal |
| 7 | Hook layering | Migration debt | Router will obsolete hooks |

---

## Next Steps

If we want to improve iterate workflow further:
1. Implement `/iterate debug` command (most bang for buck)
2. Add `--verbose` to workflow init
3. Consider auto-advance if manual transitions become painful

Otherwise, the major blockers are resolved and iterate is functional.
