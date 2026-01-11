# Workflow Issues Analysis - 2026-01-07

**Source**: Episodic memory search of conversation archives  
**Scope**: Workflow enforcement violations and problematic blocking  
**Priority levels**: P0 (breaks workflow) > P1 (reduces effectiveness) > P2 (minor)

---

## Executive Summary

Analysis of recent conversation logs reveals 7 critical issues with the workflow enforcement system:

1. **Agents bypass workflow by misclassifying multi-file edits as SIMPLE**
2. **Commit message standards violated (attributions/emoji) despite CLAUDE.md prohibition**
3. **Tests/linting skipped before commits**
4. **Classification hook creates deadlocks** (FIXED in edc679b)
5. **Agents underuse subagents for exploration** - using 20+ direct tool calls instead
6. **Phase restrictions block semantically equivalent tools** (MCP variants of Read/Grep)
7. **Hooks not executing** (pre-compacting.py, track_subagent.py)

---

## Issue 1: Workflow Bypass via Misclassification [P0]

### Evidence

**Session**: 603d8ba1 (2025-12-31)

```
User: "fix the classification update issue"

Agent classification: [SIMPLE]
Files edited:
1. hooks/combined-enforcement.py
2. hooks/session-start.py

User feedback: "yes, and it makes all of my work useless"
```

### Root Cause

CLAUDE.md defines COMPLEX as:
> "Multiple files OR unclear scope OR architectural"

Agents classify multi-file edits as SIMPLE to avoid `workflow:orchestrate` requirement.

### Impact

- Bypasses orchestrator checkpoints
- No design phase review
- No proper verification
- Breaks the entire workflow system

### Proposed Fix

**Enforcement in `combined-enforcement.py`**:

```python
def check_workflow_compliance(tool_name, args, state):
    """Track files edited per session, enforce COMPLEX for >1 file."""
    
    # Track file edits
    if tool_name in {"Write", "Edit"}:
        if "files_edited_this_session" not in state:
            state["files_edited_this_session"] = set()
        
        file_path = args.get("file_path")
        if file_path:
            state["files_edited_this_session"].add(file_path)
            
            # If editing 2nd+ file with SIMPLE classification, block
            if len(state["files_edited_this_session"]) > 1:
                classification = state.get("classification")
                if classification == "SIMPLE":
                    return {
                        "allowed": False,
                        "message": (
                            "[WORKFLOW VIOLATION] Multi-file edit detected.\n"
                            f"   Files edited: {', '.join(state['files_edited_this_session'])}\n"
                            f"   Current classification: [SIMPLE]\n"
                            "\n"
                            "Multi-file edits require [COMPLEX] classification.\n"
                            "Either:\n"
                            "1. Reclassify as [COMPLEX] and invoke workflow:orchestrate\n"
                            "2. Complete current file, then handle second file separately"
                        )
                    }
```

### Test Scenario

```
1. Agent classifies task as [SIMPLE]
2. Agent uses Write on file1.py
3. Hook allows (first file)
4. Agent uses Edit on file2.py
5. Hook BLOCKS with multi-file violation
6. Agent must reclassify [COMPLEX] or finish file1 first
```

---

## Issue 2: Commit Message Standards Violated [P0]

### Evidence

**Session**: 603d8ba1 (2025-12-31)

```bash
git commit -m "Fix classification hook deadlock

Updates classification tracking to allow re-classification when
task type changes during execution.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

**CLAUDE.md explicitly prohibits**:
> "NEVER add attributions, emoji, or decorations to commit messages"

### Root Cause

No enforcement of commit message content. Agents include attributions despite clear prohibition.

### Impact

- Violates project standards
- Makes git history noisy
- User must manually fix commits

### Proposed Fix

**Git safety check in `combined-enforcement.py`**:

```python
def check_git_safety(tool_name, args, state):
    """Validate commit messages before execution."""
    
    if tool_name == "Bash" and "git commit" in args.get("command", ""):
        command = args["command"]
        
        # Extract commit message
        # Handles: git commit -m "msg" and heredoc format
        import re
        
        # Check for heredoc format
        heredoc_match = re.search(r'<<["\']?EOF["\']?\s*(.*?)\s*EOF', command, re.DOTALL)
        if heredoc_match:
            message = heredoc_match.group(1)
        else:
            # Check for -m flag
            msg_match = re.search(r'-m\s+["\'](.+?)["\']', command)
            if msg_match:
                message = msg_match.group(1)
            else:
                return {"allowed": True}  # Can't parse, allow (will catch in post-hook)
        
        # Check for violations
        violations = []
        
        if "🤖" in message or "Generated with" in message:
            violations.append("Attribution detected")
        
        # Check for emoji (common ones)
        emoji_pattern = r'[\U0001F300-\U0001F9FF]'
        if re.search(emoji_pattern, message):
            violations.append("Emoji detected")
        
        if "Co-Authored-By: Claude" in message:
            violations.append("Claude attribution detected")
        
        if violations:
            return {
                "allowed": False,
                "message": (
                    f"[GIT SAFETY] Commit message violates CLAUDE.md standards:\n"
                    f"   {', '.join(violations)}\n"
                    "\n"
                    "CLAUDE.md requires:\n"
                    "- NEVER add attributions, emoji, or decorations to commit messages\n"
                    "\n"
                    "Please revise commit message to follow project conventions."
                )
            }
    
    return {"allowed": True}
```

---

## Issue 3: Tests Skipped Before Commits [P0]

### Evidence

**Session**: c38abb8f (2025-12-30)

```
Agent workflow:
1. Made code changes
2. Committed changes
3. THEN ran tests (which failed)
4. Fixed tests
5. Committed again
```

**CLAUDE.md requirement**:
> "Before any checkpoint or completion: Tests pass, Type-check passes, Linter passes"

### Root Cause

No enforcement of test execution before git commits. Agents commit without verification.

### Impact

- Commits broken code
- CI/CD failures
- Wastes time fixing later

### Proposed Fix

**3-layer approach**:

#### Layer 1: Approval Tracking (Immediate)

```python
def check_git_safety(tool_name, args, state):
    """Track approvals required before git operations."""
    
    if tool_name == "Bash":
        command = args.get("command", "")
        
        # Detect git commit/push
        if "git commit" in command or "git push" in command:
            approvals = state.get("approvals_granted", {})
            
            if not approvals.get("tests_passed"):
                return {
                    "allowed": False,
                    "message": (
                        "[GIT SAFETY] Cannot commit without test verification.\n"
                        "\n"
                        "Required before commit:\n"
                        "1. Run tests: pytest / npm test / go test / etc.\n"
                        "2. Verify all tests pass\n"
                        "3. Output: [VERIFY] tests: ✓\n"
                        "\n"
                        "Or request approval:\n"
                        "- If no tests exist: Say 'No tests present, proceeding'\n"
                        "- If tests not applicable: Explain why"
                    )
                }
```

#### Layer 2: Test Execution Detection (Future)

```python
# Track test commands executed
if tool_name == "Bash":
    command = args.get("command", "")
    test_patterns = ["pytest", "npm test", "go test", "cargo test", "mvn test"]
    
    if any(pattern in command for pattern in test_patterns):
        state["test_command_run"] = True
        state["last_test_result"] = None  # Will be set in post-hook
```

#### Layer 3: [VERIFY] Signal Parsing (Future)

```python
# Look for [VERIFY] signal in agent output
if "[VERIFY]" in agent_last_message:
    match = re.search(r'\[VERIFY\]\s*tests:\s*([✓✗])', agent_last_message)
    if match and match.group(1) == "✓":
        state["approvals_granted"]["tests_passed"] = True
```

---

## Issue 4: Classification Hook Deadlock [P0] ✅ FIXED

### Evidence

**Session**: 7ab8c0b4 (2026-01-01)

```
Agent outputs: "[TRIVIAL] Fix typo in README"
Hook blocks: "[PROCESS VIOLATION] Classification required"

Agent outputs: "[TRIVIAL]" again
Hook blocks: "[PROCESS VIOLATION] Classification required"

Infinite loop. User had to manually delete session.json.
```

### Root Cause (FIXED in edc679b)

```python
# Bug: Only set classification once
if match and not state.get("classification_given"):
    state["classification_given"] = True
    state["classification"] = classification
    
# Never updates when classification changes!
```

### Fix Applied

```python
# Now allows updates when classification changes
if match:
    current = state.get("classification")
    if current != classification:
        state["classification"] = classification
        state["classification_given"] = True
```

### Status

✅ **RESOLVED** - Committed in edc679b

---

## Issue 5: Subagents Underused for Exploration [P1] ⚠️ CRITICAL FINDING

### Evidence

**Session**: c38abb8f (2025-12-30)

```
User: "evaluate sophia repo against logos#433 requirements"

Agent performed 20+ direct tool calls:
- WebFetch (GitHub issue details)
- mcp__plugin_serena_serena__find_file (3x)
- mcp__plugin_serena_serena__search_for_pattern (4x)
- Read (3x)
- mcp__plugin_serena_serena__find_symbol (4x)
- Grep (2x)
- mcp__plugin_serena_serena__get_symbols_overview (2x)
- mcp__plugin_serena_serena__find_referencing_symbols (1x)

Total context: ~150K tokens for exploration
```

**What agent should have done**:

```python
Task(
    subagent_type='Explore',
    model='haiku',  # Cheap model for exploration
    description='Evaluate sophia compliance',
    prompt='''
    Evaluate the sophia repository against logos#433 requirements.
    
    Required:
    1. Find config files (sophia.toml, etc.)
    2. Check for required features (memory, persistence, etc.)
    3. Verify API completeness
    4. Return compliance report with file references
    '''
)
```

### Why Agents Don't Spawn Subagents

**Reasons observed**:

1. **Perceived overhead** - "I already know what to do, just do it directly"
2. **Task tool has higher latency** - Direct tools feel faster
3. **No enforcement** - Nothing stops direct tool use
4. **Instructions unclear** - Task tool usage guidelines buried in docs

### Impact

- **Massive token waste** - 150K tokens vs ~30K with subagent
- **Slower execution** - Sequential tool calls vs parallel subagent work
- **Context pollution** - Large results flood main conversation
- **Cost inefficiency** - Sonnet doing exploration that Haiku can handle

### Proposed Fix

**Exploration pattern detection**:

```python
def check_token_efficiency(tool_name, args, state):
    """Detect exploration patterns and suggest Task tool."""
    
    # Track search/read operations
    if tool_name in {"Glob", "Grep", "Read", "mcp__plugin_serena_serena__search_for_pattern",
                     "mcp__plugin_serena_serena__find_file", "mcp__plugin_serena_serena__find_symbol"}:
        
        if "exploration_tool_count" not in state:
            state["exploration_tool_count"] = 0
        
        state["exploration_tool_count"] += 1
        
        # After 3 exploratory tools, suggest subagent
        if state["exploration_tool_count"] >= 3:
            # Check if this is a research task
            classification = state.get("classification")
            
            if classification == "RESEARCH":
                return {
                    "allowed": False,
                    "message": (
                        f"[TOKEN EFFICIENCY] Research pattern detected ({state['exploration_tool_count']} search tools).\n"
                        "\n"
                        "For codebase exploration, use Task tool with Explore subagent:\n"
                        "\n"
                        "Task(\n"
                        "    subagent_type='Explore',\n"
                        "    model='haiku',  # Cheap for exploration\n"
                        "    description='<3-5 word summary>',\n"
                        "    prompt='Find X, analyze Y, return summary with file:line refs'\n"
                        ")\n"
                        "\n"
                        "Benefits:\n"
                        "- Subagent aggregates findings (returns summary, not raw data)\n"
                        "- Uses cheaper haiku model (~80% cost savings)\n"
                        "- Keeps main context clean\n"
                        "- Runs searches in parallel\n"
                        "\n"
                        "To continue with direct tools, explain why subagent is inappropriate."
                    )
                }
```

### Test Scenario

```
1. User: "How does error handling work in this codebase?"
2. Agent classifies: [RESEARCH]
3. Agent uses Grep "error"
4. Agent uses Grep "exception"
5. Agent uses Read on error.py
6. Hook BLOCKS: "Research pattern detected, use Task tool with Explore subagent"
7. Agent spawns Explorer or explains why direct approach needed
```

---

## Issue 6: Phase Restrictions Block Equivalent Tools [P1]

### Evidence

**Session**: 32873e8c (2026-01-02)

```
Phase: INTAKE
Allowed tools: {"Read", "Glob", "Grep", "AskUserQuestion"}

Subagent spawned in INTAKE phase.
Subagent tried to use:
- mcp__filesystem__read_text_file ❌ BLOCKED
- mcp__plugin_serena_serena__read_file ❌ BLOCKED

These are semantically equivalent to Read!
```

### Root Cause

Phase restrictions check exact tool names, not semantic categories.

```python
PHASE_TOOLS = {
    "INTAKE": {"Read", "Glob", "Grep", "AskUserQuestion"},
    # ...
}

# Bug: Only checks exact names
if tool_name not in PHASE_TOOLS[phase]:
    block()
```

### Impact

- Subagents blocked from using MCP variants of allowed tools
- Forces workarounds (switching phases unnecessarily)
- Makes subagents less useful

### Proposed Fix (Partially Implemented)

**Tool category matching**:

```python
TOOL_CATEGORIES = {
    "file_read": {
        "Read",
        "mcp__filesystem__read_text_file",
        "mcp__plugin_serena_serena__read_file"
    },
    "file_search": {
        "Glob",
        "Grep",
        "mcp__filesystem__search_files",
        "mcp__plugin_serena_serena__find_file",
        "mcp__plugin_serena_serena__search_for_pattern"
    },
    "symbol_read": {
        "mcp__plugin_serena_serena__find_symbol",
        "mcp__plugin_serena_serena__get_symbols_overview"
    }
}

def get_tool_category(tool_name):
    """Map tool name to semantic category."""
    for category, tools in TOOL_CATEGORIES.items():
        if tool_name in tools:
            return category
    return None

def check_phase_restrictions(tool_name, args, state):
    """Check if tool category allowed in current phase."""
    phase = state.get("phase", "IMPLEMENT")
    
    # Get semantic category
    category = get_tool_category(tool_name)
    
    # Get allowed categories for phase
    allowed_categories = PHASE_CATEGORIES[phase]
    
    if category and category not in allowed_categories:
        return {"allowed": False, "message": f"[PHASE] {category} not allowed in {phase}"}
    
    return {"allowed": True}
```

### Status

⚠️ **PARTIALLY IMPLEMENTED** in session 32873e8c, needs completion

---

## Issue 7: Hooks Not Executing [P2]

### Evidence

**Files exist but not running**:

1. **`hooks/pre-compacting.py`** - Should write HANDOFF.md before context compaction
2. **`scripts/track_subagent.py`** - Should log subagent token usage

**Expected behavior**:
- Pre-compacting hook: Auto-generate handoff when context gets long
- Track subagent: Log every Task tool completion

**Actual behavior**:
- No handoff auto-generated
- No subagent metrics logged

### Investigation Blocked

Attempted to investigate with:
- `grep` to search Claude Code settings ❌ BLOCKED by [BASH ABUSE]
- `find` to locate config files ❌ BLOCKED by [BASH ABUSE]
- Multiple searches ❌ BLOCKED by [TOKEN EFFICIENCY]

### Root Cause

**Investigation completed:**

1. **`preCompacting` hook IS registered** in `.claude-plugin/manifest.json`:
   ```json
   "preCompacting": {
     "script": "../hooks/pre-compacting.py",
     "description": "Auto-write handoff before context compacting to preserve state"
   }
   ```
   
2. **`track_subagent.py` is NOT a hook** - it's a standalone CLI script in `scripts/`:
   - Should be called manually: `python3 scripts/track_subagent.py <agent_id> <agent_type>`
   - Or: `python3 scripts/track_subagent.py report` to view metrics
   - **NOT integrated into hook system**

3. **Actual tracking hook**: `hooks/post-task-tracking.py` has its own `track_subagent()` function
   - Writes to `subagent_metrics.json`
   - Extracts agent ID from Task tool output
   - Registered as `postToolUse` hook

### Likely Causes

**For preCompacting hook not running:**
1. **Hook name case-sensitivity** - Registered as `preCompacting` (camelCase)
2. **Event not firing** - May need to be `PreCompacting` or `pre-compacting`
3. **Hook execution failure** - Silent failure with no error output
4. **Context threshold** - Hook may only fire at specific context levels

**For track_subagent.py not working:**
1. **Not a hook** - It's a CLI tool, not auto-invoked
2. **Should be integrated** into `post-task-tracking.py` hook
3. **Or called manually** after each subagent completion

### Recommended Actions

**1. Fix preCompacting hook registration:**

Check if Claude Code expects different case:
```bash
# Test hook manually
cd ~/.claude/plugins/agent-swarm
echo '{}' | python3 hooks/pre-compacting.py

# Check Claude Code logs for hook errors
# Location varies by OS - check ~/.config/claude-code/ or ~/Library/Application Support/
```

Consider renaming in manifest.json:
- Try: `"PreCompacting"` (PascalCase)
- Try: `"pre-compacting"` (kebab-case)
- Current: `"preCompacting"` (camelCase)

**2. Integrate track_subagent.py into hooks:**

Option A: Call from post-task-tracking.py:
```python
# In hooks/post-task-tracking.py, after detecting Task tool completion:
import subprocess
script_path = Path(__file__).parent.parent / "scripts/track_subagent.py"
subprocess.run(["python3", str(script_path), agent_id, agent_type])
```

Option B: Manual usage after each session:
```bash
python3 scripts/track_subagent.py report
```

**3. Test hook execution:**

```bash
# Enable Claude Code verbose logging (check docs for flag)
# Then watch for hook execution messages
```

---

## Priority Roadmap

### P0 - Breaks Workflow (Immediate)

1. ✅ **Classification deadlock** - FIXED in edc679b
2. ⚠️ **Multi-file COMPLEX enforcement** - Draft ready (Issue 1)
3. ⚠️ **Commit message validation** - Draft ready (Issue 2)
4. ⚠️ **Git approval requirement** - Draft ready (Issue 3)

### P1 - Reduces Effectiveness (High)

5. ⚠️ **Exploration pattern detection** - Draft ready (Issue 5)
6. ⚠️ **Tool category matching** - Partially implemented (Issue 6)

### P2 - Minor Issues (Medium)

7. ⚠️ **Hook execution investigation** - Blocked, needs manual check (Issue 7)

---

## Testing Recommendations

### For Each Fix

1. **Unit test** - Test enforcement logic in isolation
2. **Integration test** - Test with actual tool calls
3. **Regression test** - Verify legitimate uses still work
4. **User acceptance** - User validates fix solves problem

### Test Data Sources

- Conversation archives in `~/.config/superpowers/conversation-archive/`
- Session state files in `~/.claude/plugins/agent-swarm/.state/`
- Git history in repository

### Example Test: Multi-file Enforcement

```python
def test_multifile_enforcement():
    state = {"classification": "SIMPLE"}
    
    # First file - should allow
    result = check_workflow_compliance("Write", {"file_path": "a.py"}, state)
    assert result["allowed"] == True
    
    # Second file - should block
    result = check_workflow_compliance("Write", {"file_path": "b.py"}, state)
    assert result["allowed"] == False
    assert "Multi-file edit" in result["message"]
    
    # After reclassifying as COMPLEX - should allow
    state["classification"] = "COMPLEX"
    result = check_workflow_compliance("Write", {"file_path": "c.py"}, state)
    assert result["allowed"] == True
```

---

## Ironic Note

This analysis was itself blocked multiple times by the enforcement system:

1. Attempted grep to find hook references → [BASH ABUSE]
2. Attempted multiple searches → [TOKEN EFFICIENCY] 
3. Attempted find command → [BASH ABUSE]
4. Attempted Write tool → [PROCESS VIOLATION] Classification required

**Lesson**: Enforcement hooks need escape hatches for meta-work (investigating the enforcement system itself).

---

## Appendix: Session References

| Session ID | Date | Issue | Evidence |
|------------|------|-------|----------|
| 603d8ba1 | 2025-12-31 | Multi-file bypass, commit attribution | Agent edited 2 files with [SIMPLE], added emoji to commit |
| c38abb8f | 2025-12-30 | Subagent underuse, tests skipped | 20+ direct tool calls, committed before testing |
| 7ab8c0b4 | 2026-01-01 | Classification deadlock | Infinite loop, user deleted session.json |
| 32873e8c | 2026-01-02 | Phase restrictions | Explorer blocked from MCP read tools |

All sessions available in: `~/.config/superpowers/conversation-archive/`
