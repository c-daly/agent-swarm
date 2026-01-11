# Session Handoff - Iterate Workflow Development

**Date:** 2026-01-11
**Branch:** `feature/greptile-query-iterate-mode`
**PR:** #2 (c-daly/agent-swarm)

---

## What We Did

### 1. Fixed Critical Bugs from Greptile Review

**Problem:** `format_monitor_result()` in `hooks/monitor_agent.py` was updated to return proper hook format (`hookSpecificOutput`), but call sites still used old access pattern.

**Fixes applied:**
- `hooks/combined-enforcement.py:933-934` - Changed from `result.get("allowed")` to `result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"`
- `tests/test_monitor_agent.py:225-256` - Updated `TestFormatMonitorResult` to expect new hook format structure

**Commits:**
- `3fe530b` Fix monitor result access pattern at line 933 and update tests

### 2. Ran Adversary Agent for Coverage Analysis

**Before:** 16.1% coverage on `hooks/monitor_agent.py`
**After:** 88% coverage

**Tests added by adversary (10 new edge case tests):**
- `test_parse_decision_exception_during_parsing`
- `test_build_prompt_serena_tools`
- `test_build_prompt_none_inputs`
- `test_detect_batch_value_error_exception`
- `test_needs_monitoring_classification_none`
- `test_needs_monitoring_missing_classification`
- `test_needs_monitoring_complex_with_no_edits`
- `test_extract_commit_message_cat_heredoc_format`
- `test_detect_batch_iteration_pattern`
- `test_detect_batch_across_multiple`

**Finding:** Line 205 (`cat_match` regex) is dead code - the `heredoc_match` pattern catches all cases first. Should be removed in future cleanup.

**Commits:**
- `63f065e` Add edge case tests for monitor_agent, coverage 84% to 88%

### 3. Updated Iterate Workflow

Rewrote `skills/iterate/SKILL.md` to support:

**Parallel Implementation:**
```
┌─ Task(implementer): "Fix issue 1" ─┐
│─ Task(implementer): "Fix issue 2" ─│→ wait all → test → commit → push
└─ Task(adversary): "Coverage gaps" ─┘
```

**Greptile Pacing:**
- Push once per iteration
- Wait for review to complete before checking results
- Never push to same PR while Greptile is actively reviewing

**Multi-PR Interleaving:**
```
PR A: implement → push → [Greptile reviewing A]
                              ↓ switch to B
PR B: implement → push → [Greptile reviewing B]
                              ↓ switch to A
PR A: check review (complete) → address issues → push
```

**Commits:**
- `c6b757a` Update iterate workflow for parallel implementation and Greptile pacing
- `84ccd37` Add multi-PR interleaving pattern to iterate workflow

---

## What Worked

1. **Adversary agent** - Effectively found coverage gaps and wrote meaningful tests
2. **Greptile integration** - Found real bugs (the format_monitor_result access pattern)
3. **Parallel Task spawning** - Works well for independent issues

---

## What Didn't Work / Needs Improvement

### 1. I Didn't Stay on the Workflow

**Problem:** I kept dropping out of the iterate loop structure. Instead of following:
```
initialize → implement → adversary → review → checkpoint
```

I would:
- Do implementation directly without spawning agents
- Check Greptile reviews mid-implementation (getting stale results)
- Skip phases or do them out of order

**Root cause:** No enforcement mechanism. The workflow is documented but not enforced.

**Solution needed:** Add enforcement to `combined-enforcement.py` that:
- Tracks current iterate phase in session state
- Blocks tool calls that don't match current phase
- Forces phase transitions through explicit commands

### 2. Greptile Reviews Got Out of Sync

**Problem:** I pushed commits, then immediately checked Greptile reviews that were from *before* my changes. This caused confusion - reviews referenced bugs I'd already fixed.

**Root cause:** No tracking of which commit SHA a review corresponds to.

**Solution needed:**
- Track `last_pushed_sha` in session state
- Track `last_reviewed_sha` from Greptile response
- Block checking review results until `last_reviewed_sha >= last_pushed_sha`

### 3. No Automatic Issue Parsing

**Problem:** When Greptile returns multiple issues, I had to manually parse them into discrete tasks.

**Solution needed:** Helper function that:
- Parses Greptile review body
- Extracts discrete issues with file:line references
- Returns structured list ready for parallel Task spawning

---

## Implementation Details for Future Work

### Phase Enforcement Hook

Add to `combined-enforcement.py`:

```python
def check_iterate_phase(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """Enforce iterate workflow phase discipline."""
    if state.get("mode") != "iterate":
        return None

    current_phase = state.get("loop_phase", "implement")

    # Define allowed tools per phase
    phase_tools = {
        "implement": {"Task", "Edit", "Write", "Bash"},  # implementation tools
        "test": {"Bash"},  # only pytest/mypy/ruff
        "push": {"Bash"},  # only git push
        "wait": set(),  # no tools - must wait for Greptile
        "review": {"mcp__plugin_greptile_greptile__*"},  # only Greptile tools
    }

    allowed = phase_tools.get(current_phase, set())

    # Check if tool matches any allowed pattern
    if not any(tool_name.startswith(t.rstrip("*")) for t in allowed):
        return block(
            f"[ITERATE] Phase '{current_phase}' doesn't allow {tool_name}.\n"
            f"Allowed tools: {allowed}\n"
            f"Use /iterate advance to move to next phase."
        )

    return None
```

### Greptile SHA Tracking

Add to session state:

```python
def track_greptile_review(state: dict, review_data: dict) -> None:
    """Track which SHA Greptile reviewed."""
    state["greptile_reviews"] = state.get("greptile_reviews", [])
    state["greptile_reviews"].append({
        "review_id": review_data["id"],
        "sha": get_current_sha(),
        "timestamp": datetime.now().isoformat(),
        "status": review_data["status"]
    })

def can_check_review(state: dict) -> bool:
    """Check if latest push has been reviewed."""
    last_push_sha = state.get("last_pushed_sha")
    reviews = state.get("greptile_reviews", [])

    if not reviews:
        return False

    latest_review = reviews[-1]
    return latest_review["sha"] == last_push_sha and latest_review["status"] == "COMPLETED"
```

### Issue Parser for Parallel Spawning

```python
def parse_greptile_issues(review_body: str) -> list[dict]:
    """Parse Greptile review into discrete issues for parallel fixing."""
    issues = []

    # Look for patterns like:
    # **[P0] Issue title** at file.py:123
    # **Critical:** description

    import re
    pattern = r'\*\*\[(P\d)\]\s*([^*]+)\*\*.*?(?:at|in)\s+([^:\s]+):(\d+)'

    for match in re.finditer(pattern, review_body, re.DOTALL):
        priority, title, file, line = match.groups()
        issues.append({
            "priority": priority,
            "title": title.strip(),
            "file": file,
            "line": int(line),
            "prompt": f"Fix {priority} issue: {title.strip()} at {file}:{line}"
        })

    return sorted(issues, key=lambda x: x["priority"])

def spawn_parallel_fixes(issues: list[dict]) -> list[str]:
    """Generate Task tool calls for parallel issue fixing."""
    return [
        {
            "subagent_type": "agent-swarm:implementer",
            "prompt": issue["prompt"],
            "model": "sonnet"
        }
        for issue in issues
    ]
```

### Cross-Repo State Management

For LOGOS-scale work with multiple repos:

```python
# ~/.claude/state/multi-repo.json
{
    "active_work": [
        {
            "repo": "logos-core",
            "branch": "feature/auth-refactor",
            "pr": 42,
            "status": "awaiting_review",
            "last_push_sha": "abc123",
            "greptile_review_id": "2241500"
        },
        {
            "repo": "logos-api",
            "branch": "feature/auth-endpoints",
            "pr": 17,
            "status": "implementing",
            "issues_remaining": 2
        },
        {
            "repo": "logos-ui",
            "branch": "feature/auth-components",
            "pr": 8,
            "status": "review_complete",
            "issues": []
        }
    ],
    "work_queue": [
        {"repo": "logos-ui", "action": "address_review"},
        {"repo": "logos-core", "action": "check_review"},
        {"repo": "logos-api", "action": "continue_impl"}
    ]
}
```

### Workflow Orchestrator

```python
def get_next_work_item(state: dict) -> dict:
    """Determine what to work on next across all repos."""

    # Priority order:
    # 1. Reviews that are complete and need addressing
    # 2. Implementation work in progress
    # 3. Repos awaiting review (switch away from these)

    for item in state["active_work"]:
        if item["status"] == "review_complete":
            return {"repo": item["repo"], "action": "address_issues"}

    for item in state["active_work"]:
        if item["status"] == "implementing":
            return {"repo": item["repo"], "action": "continue_impl"}

    # All repos awaiting review - check if any completed
    for item in state["active_work"]:
        if item["status"] == "awaiting_review":
            if check_review_complete(item["greptile_review_id"]):
                return {"repo": item["repo"], "action": "check_review"}

    return {"action": "wait", "message": "All repos awaiting review"}
```

---

## Vision: Rapid Codebase Refactor

With this workflow fully implemented, a large refactor could proceed:

```
1. Greptile analyzes codebase, identifies 50 issues across 3 repos
2. Parse into discrete tasks, prioritize by dependency order
3. Spawn 5 parallel implementers per repo (15 total agents)
4. As each completes: test locally, commit
5. When repo batch done: push, trigger Greptile review
6. While reviewing: switch to next repo batch
7. When review complete: parse new issues, spawn fixes
8. Repeat until all repos clean

Timeline compression:
- Sequential: 50 issues × 10 min each = 8+ hours
- Parallel (5 agents, 3 repos): 50 issues ÷ 15 = ~3 batches × 15 min = 45 min
```

The key is:
- Never idle waiting for reviews
- Maximum parallelism within each repo
- Clean handoffs between repos
- Enforcement to stay on workflow

### Design Principle: Autonomous Loop with Visibility

**The workflow should run autonomously until the user decides to stop it.**

Not:
- Constant approval seeking ("Here's what I found, want me to continue?")
- Silent operation with big dumps at the end

But:
- **Clear state at all times** - what phase, what's pending, what's blocked
- **Progress indicators** - issues fixed, coverage %, PRs in flight, agents running
- **Keeps running** - no stopping to ask permission for each step
- **User can check in anytime** - see status, redirect if needed, or let it continue

The user kicks it off and can walk away. When they come back, they see:
```
[ITERATE] Running - Iteration 3/5
  PR #42 (logos-core): awaiting review
  PR #17 (logos-api): 2 agents implementing
  PR #8 (logos-ui): review complete, 0 issues remaining

  Progress: 47/50 issues resolved
  Coverage: 78% → 91%
  Time elapsed: 32 min
```

They can:
- Let it continue (`/iterate continue`)
- Pause and review (`/iterate pause`)
- Stop and checkpoint (`/iterate stop`)
- Redirect focus (`/iterate focus logos-api`)

---

## Files Changed This Session

| File | Changes |
|------|---------|
| `hooks/combined-enforcement.py` | Fixed monitor result access pattern (line 933-934) |
| `hooks/monitor_agent.py` | Already had correct format (verified) |
| `tests/test_monitor_agent.py` | Updated TestFormatMonitorResult + 10 new edge case tests |
| `skills/iterate/SKILL.md` | Rewrote for parallel impl, Greptile pacing, multi-PR interleaving |
| `HANDOFF.md` | This document |

---

## Next Session

1. **Implement phase enforcement** - Add `check_iterate_phase()` to combined-enforcement.py
2. **Add Greptile SHA tracking** - Track which commit each review corresponds to
3. **Build issue parser** - Auto-parse Greptile reviews into Task spawn parameters
4. **Test on larger refactor** - Try the parallel workflow on a real multi-file change
5. **Fix dead code** - Remove unreachable `cat_match` at monitor_agent.py:205

---

## Commands

```bash
# Current branch
git log --oneline -5
# 84ccd37 Add multi-PR interleaving pattern to iterate workflow
# c6b757a Update iterate workflow for parallel implementation and Greptile pacing
# 63f065e Add edge case tests for monitor_agent, coverage 84% to 88%
# 3fe530b Fix monitor result access pattern at line 933 and update tests

# Run tests
/home/fearsidhe/.local/bin/pytest tests/ --ignore=tests/test_git_approval_layers.py -v

# Check coverage
/home/fearsidhe/.local/bin/pytest --cov=hooks tests/test_monitor_agent.py

# View iterate workflow
cat ~/.claude/plugins/agent-swarm/skills/iterate/SKILL.md
```
