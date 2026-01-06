# Enforcement System Fixes - 2026-01-06

## Executive Summary

**Problem:** Agents quit instead of adapting, Bash remains escape hatch, 0% script adoption.

**Root Cause:** "The system doesn't have a willpower problem; it has an incentive problem." (Explorer agent finding)

**Impact:** Fixed 3 critical bugs that made enforcement unworkable.

---

## What Was Broken

### 1. Bash Escape Hatch (64.6% usage, target 20%)
- **Problem:** No detection of cat/grep/find via Bash
- **Impact:** Agents routed around all enforcement via `bash: cat`, `bash: grep`
- **Evidence:** 1,902 Bash calls in one session, 44.5% of blocks led back to Bash

### 2. Unknown Block Reasons (87% of blocks)
- **Problem:** Field name mismatch - code looked for `message`, hook returned `permissionDecisionReason`
- **Impact:** 246 blocks showed as "unknown" instead of actual reason
- **Evidence:** Metrics showed 86.9% unknown, but reasons existed in wrong field

### 3. Non-Existent Infrastructure
- **Problem:** Briefing referenced `~/.claude/lib/mcp_bridge.py` which doesn't exist
- **Impact:** Script guidance was unusable, agents forced to use Bash
- **Evidence:** 0 script usage out of 2,944 operations

### 4. Missing rg/Ripgrep Guidance
- **Problem:** No documentation that Grep tool IS ripgrep
- **Impact:** Agents used `bash: rg` thinking it was different from Grep tool
- **Evidence:** User reported "nobody uses rg"

---

## Fixes Implemented

### Fix #1: Bash Abuse Detection
**File:** `hooks/combined-enforcement.py` (lines 334-371)

**What it does:** Detects and blocks specific Bash commands that have proper tool alternatives.

**Patterns blocked:**
```bash
# ❌ BLOCKED: bash: cat file.py
# ✅ SUGGEST: Read: {'file_path': 'file.py'}

# ❌ BLOCKED: bash: grep pattern .
# ✅ SUGGEST: Grep: {'pattern': 'pattern', 'path': '.'}

# ❌ BLOCKED: bash: rg pattern src/
# ✅ SUGGEST: Grep: {'pattern': 'pattern', 'path': 'src/'}

# ❌ BLOCKED: bash: find . -name "*.py"
# ✅ SUGGEST: Glob: {'pattern': '**/*.py'}

# ❌ BLOCKED: bash: sed 's/old/new/' file
# ✅ SUGGEST: Edit: {'file_path': 'file', 'old_string': 'old', 'new_string': 'new'}
```

**Block message format:**
```
[BASH ABUSE] Don't use 'cat' - use Read tool instead
❌ Bash: cat hooks/combined-enforcement.py
✅ Read: {'file_path': '<path>'}
Bash cat wastes tokens and bypasses tracking.
```

**Expected impact:**
- Bash usage: 64.6% → ~20%
- Agents learn proper tools through clear examples
- No more escape hatch for file operations

---

### Fix #2: Block Message Field Bug
**File:** `hooks/combined-enforcement.py` (line 450)

**What it does:** Extracts block reason from correct field

**Before:**
```python
msg = result.get("hookSpecificOutput", {}).get("message", "blocked")
# ↑ Field "message" doesn't exist, always defaulted to "blocked"
```

**After:**
```python
msg = result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "blocked")
# ↑ Correct field name - reasons now extracted properly
```

**Expected impact:**
- Unknown blocks: 87% → ~0%
- All blocks now properly categorized
- Better metrics and debugging

---

### Fix #3: Briefing Cleanup
**File:** `hooks/subagent-briefing.md` (lines 5-76)

**Removed:**
- All references to `mcp_bridge` (6 instances)
- All references to `native_grep`, `native_glob`, `MCPBridge`
- Non-existent infrastructure paths

**Added:**
- Clear table: "NEVER use Bash for file operations"
- Before/after examples for each tool
- Explicit statement: "Grep tool IS ripgrep (rg)"
- Why it matters: "Bash bypasses token tracking → runaway context"

**Example from new briefing:**
```markdown
| ❌ NEVER Do This | ✅ Use This Instead |
|------------------|---------------------|
| `bash: cat file.py` | `Read: {'file_path': 'file.py'}` |
| `bash: rg pattern` | `Grep: {'pattern': 'pattern'}` (Grep IS ripgrep) |
```

**Expected impact:**
- Agents know tools exist before being blocked
- No confusion about rg vs Grep
- Script guidance now references real tools (Path, glob from stdlib)

---

### Fix #4: Ripgrep Clarification
**File:** `hooks/subagent-briefing.md` (lines 22-38)

**Added section:** "The Grep Tool Uses Ripgrep (rg)"

**Content:**
```markdown
**IMPORTANT:** Don't invoke `rg` via Bash - use the Grep tool directly.

The Grep tool is powered by ripgrep internally, with better output formatting:

# ✅ Correct - use Grep tool
Grep: {
    'pattern': 'function.*export',
    'path': 'src/',
    'output_mode': 'files_with_matches',
    '-i': True  # case insensitive
}

# ❌ Wrong - don't use rg via Bash
bash: rg 'function.*export' src/
```

**Expected impact:**
- Agents use Grep tool instead of `bash: rg`
- User's preference (rg) is now the default via Grep tool
- Better output formatting than raw rg

---

## Expected Behavior Changes

### Before Fixes
```
Agent: *tries Read*
Hook: [TOKEN EFFICIENCY] 20 file reads
Agent: *tries Read again*
Hook: blocked
Agent: *uses bash: cat* ← ESCAPE HATCH
Hook: *allows it* ← NO DETECTION
Result: Bash becomes default
```

### After Fixes
```
Agent: *tries Read*
Hook: [TOKEN EFFICIENCY] Use Glob for batch operations
Agent: *tries bash: cat*
Hook: [BASH ABUSE] Don't use 'cat' - use Read tool instead
      ❌ Bash: cat file.py
      ✅ Read: {'file_path': 'file.py'}
Agent: *uses Read properly*
Result: Agent learns correct tool
```

---

## Testing the Fixes

**IMPORTANT:** Hooks are loaded at session start. To test these fixes, start a NEW session.

### Test 1: Verify Bash cat is blocked
```bash
# Should be blocked with helpful message
bash: cat hooks/combined-enforcement.py
```

**Expected output:**
```
[BASH ABUSE] Don't use 'cat' - use Read tool instead
❌ Bash: cat hooks/combined-enforcement.py
✅ Read: {'file_path': 'hooks/combined-enforcement.py'}
Bash cat wastes tokens and bypasses tracking.
```

### Test 2: Verify grep is blocked
```bash
# Should be blocked
bash: grep "def check" hooks/combined-enforcement.py
```

**Expected output:**
```
[BASH ABUSE] Don't use grep/rg via Bash - use Grep tool instead
❌ Bash: grep "def check" hooks/combined-enforcement.py
✅ Grep: {'pattern': '<regex>', 'path': '.', 'output_mode': 'files_with_matches'}
The Grep tool is powered by ripgrep (rg) and has proper output formatting.
```

### Test 3: Verify block reasons are categorized
```bash
# Check metrics after running some blocked commands
python3 scripts/metrics.py report | grep -A 10 "Block Reasons"
```

**Expected:** No more 87% "unknown", should see categories like:
- BASH ABUSE
- TOKEN EFFICIENCY
- SMART TOOLS
- etc.

---

## Metrics Predictions

### Current Metrics (Before Fixes)
```
Tool Usage:
  Bash: 1,902 (64.6%)     ← PRIMARY PROBLEM
  Read: 77 (2.6%)
  Task: 40 (1.4%)

Script Adoption: 0%       ← BRIEFING BUG

Block Reasons:
  unknown: 246 (87%)      ← FIELD BUG
  TOKEN EFFICIENCY: 13 (4.6%)
```

### Predicted Metrics (After Fixes)
```
Tool Usage:
  Read: ~30%              ← Was 2.6%
  Grep: ~15%              ← New usage
  Bash: ~20%              ← Was 64.6%
  Task: ~15%              ← Was 1.4%

Script Adoption: ~40%     ← Briefing now usable

Block Reasons:
  BASH ABUSE: ~40%        ← New category
  TOKEN EFFICIENCY: ~30%
  SMART TOOLS: ~20%
  unknown: <5%            ← Was 87%
```

---

## What's Still Missing

These fixes address the immediate "agents quit" problem, but longer-term improvements needed:

1. **Progressive enforcement** - Warn → Guide → Block (not instant block)
2. **Recovery tracking** - Verify agents actually use suggested alternative
3. **Context budget** - Hard limit on tokens per agent (prevent runaway)
4. **Phase enforcement** - Most agents run with `phase=""`, bypassing restrictions
5. **MAX_BASH_CALLS** - Currently undefined in token efficiency check

These can be addressed in follow-up work once the core fixes prove effective.

---

## Files Changed

1. `hooks/combined-enforcement.py` - Added Bash abuse detection + field fix
2. `hooks/subagent-briefing.md` - Removed mcp_bridge, added tool guidance
3. `hooks/inject-subagent-briefing.sh` - **CRITICAL FIX** - Actually injects briefing into subagent prompts
4. `scripts/charts.py` - Fixed subagent token calculation (earlier in session)

### Fix #5: Briefing Injection (CRITICAL)

**Problem:** The injection hook read the briefing but didn't modify the prompt
- Hook returned "allow" without modifying tool_input
- Subagents never saw the briefing content
- Explains why 0% followed briefing guidance

**Fix:** Modified `hooks/inject-subagent-briefing.sh` to:
1. Read from correct path (`$PLUGIN_ROOT/hooks/subagent-briefing.md`)
2. Prepend briefing to the original prompt
3. Return `modifiedToolInput` with updated prompt

**Before:**
```bash
BRIEFING=$(cat ~/.claude/hooks/subagent-briefing.md)
# ... just returns "allow", briefing discarded
echo '{"permissionDecision": "allow"}'
```

**After:**
```bash
BRIEFING=$(cat "$PLUGIN_ROOT/hooks/subagent-briefing.md")
MODIFIED_PROMPT="# SUBAGENT OPERATING PROTOCOL\n\n$BRIEFING\n\n---\n\n# YOUR TASK\n\n$ORIGINAL_PROMPT"
# Returns modified prompt so subagent actually sees briefing
echo '{"permissionDecision": "allow", "modifiedToolInput": {...}}'
```

**Expected impact:** Subagents will finally see the updated briefing with Bash restrictions and tool guidance

---

## Commit Message

```
Fix enforcement system - close Bash escape hatch and enable briefing injection

Problems:
- 64.6% Bash usage via cat/grep/find escape hatch
- 87% blocks showed "unknown" (field name bug)
- Briefing referenced non-existent mcp_bridge
- No rg/ripgrep guidance
- CRITICAL: Briefing injection hook didn't actually inject (0% guidance followed)

Fixes:
- Detect and block Bash cat/grep/rg/find/sed with helpful messages
- Extract block reasons from correct field (permissionDecisionReason)
- Remove all mcp_bridge references from briefing
- Add "Grep tool IS ripgrep" documentation with examples
- Fix injection hook to actually prepend briefing to subagent prompts

Expected impact:
- Bash usage: 64.6% → 20%
- Unknown blocks: 87% → <5%
- Script adoption: 0% → 40%
- Agents adapt instead of quit (now they see the briefing!)

Ref: Session analysis by Explorer agent a8189bc

Files changed:
- hooks/combined-enforcement.py (Bash abuse detection + field fix)
- hooks/subagent-briefing.md (remove mcp_bridge, add tool guidance)
- hooks/inject-subagent-briefing.sh (actually inject briefing into prompts)
```

---

**Status:** ✅ All fixes implemented and ready for testing in new session.
