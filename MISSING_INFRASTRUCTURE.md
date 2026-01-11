# Missing Infrastructure Report
Generated: 2026-01-10

## Summary
Critical infrastructure referenced throughout the codebase but missing from the filesystem. This occurred because `~/.claude` was cloned from git (github.com:c-daly/dotclaude.git), but the infrastructure was never committed to version control.

---

## 1. MCP Bridge (`~/.claude/lib/mcp_bridge.py`)

**Status:** ✗ MISSING (entire `~/.claude/lib/` directory doesn't exist)

**Referenced By:**
- `CLAUDE.md` - Listed as "verified working infrastructure"
- `agent-swarm/hooks/combined-enforcement.py` (2 references)
- `agent-swarm/hooks/subagent-briefing.md` (2 references)
- `agent-swarm/MCP_BRIDGE_COMPLETE.md` - Full documentation of what it should do
- `agent-swarm/MCP_TOOLS_REFERENCE.md` (4 references)
- `agent-swarm/SETUP.md` (4 references)
- `agent-swarm/ENFORCEMENT_FIXES.md` (1 reference)
- `agent-swarm/PARALLELISM.md` (1 reference)

**Expected Functionality:**
```python
from mcp_bridge import native_glob, native_grep, MCPBridge

# Programmatic glob without spawning tools
files = native_glob("**/*.py", "/path")

# Programmatic grep without spawning tools
results = native_grep("pattern", "/path", output_mode="content")

# Call any MCP tool from Python
bridge = MCPBridge()
result = bridge.call_tool("serena", "find_symbol", {"symbol": "MyClass"})
```

**Purpose:**
- Enable batch operations without token-heavy tool spawning
- Allow Python scripts to access MCP tools programmatically
- Support token-efficient search/analysis operations
- Referenced heavily in enforcement hooks as the "correct way" to do batch ops

**Documentation Available:**
- `MCP_BRIDGE_COMPLETE.md` - Complete specification of what was built
- `MCP_TOOLS_REFERENCE.md` - Reference guide
- `SETUP.md` - Installation instructions (expects it to exist)

---

## 2. Batch Scripts (`~/.claude/lib/scripts/`)

**Status:** ✗ MISSING (directory doesn't exist)

**Referenced By:**
- `CLAUDE.md` - Listed as "verified working infrastructure"
- Referenced in CLAUDE.md context efficiency rules

**Expected Contents:**
Per CLAUDE.md, this should contain "Reusable batch scripts" for common operations:
- Batch search scripts
- File analysis scripts
- Context aggregation scripts
- Any reusable utilities that use `mcp_bridge`

**Purpose:**
- Provide pre-built scripts for common batch operations
- Avoid recreating the same patterns repeatedly
- Standardize batch operation approaches

---

## 3. MCP Servers JSON (`~/.claude/lib/mcp_servers.json`)

**Status:** ✗ MISSING

**Referenced By:**
- `CLAUDE.md` infrastructure list

**Expected Functionality:**
- Configuration file listing available MCP servers
- Used by `inventory.py` to discover capabilities

**Note:** `inventory.py` currently reads from `~/.claude/settings.json` instead, but finds NO mcpServers configured there. MCP servers are currently coming from plugins, not global config.

---

## 4. Workflow Orchestrate Skill

**Status:** ⚠️ EXISTS BUT NOT ENABLED

**Location:** `~/.claude/plugins/agent-workflow/`

**Details:**
- Directory exists with complete skill structure
- Has `commands/orchestrate.md`
- Has 11 skills: context, design, escalation, implement, intake, mcp, research, review, spec-review, subagents, verify
- **BUT:** Not in `settings.json` enabledPlugins list
- **Result:** CLAUDE.md references `workflow:orchestrate` but it's not available to invoke

**Fix Required:** Enable the plugin in settings.json or via plugin manager

---

## 5. Session Start Hook Integration

**Status:** ⚠️ PARTIALLY IMPLEMENTED

**Issue:**
- `session-start.py` exists and is executable
- But it does NOT run `inventory.py` to inject capabilities
- Comment in `inventory.py` says "Run at session start" but this never happens
- Result: No automatic capability discovery at session start

**Expected Behavior:**
- On session start, run `inventory.py all`
- Inject output into session context via `hookSpecificOutput`
- Give Claude awareness of all MCP servers, skills, agents, scripts

---

## 6. Settings.json MCP Configuration

**Status:** ✗ EMPTY

**Finding:**
- `~/.claude/settings.json` exists
- Has `enabledPlugins` but NO `mcpServers` key
- `inventory.py` looks for `mcpServers` in settings
- MCP tools (serena, context7, playwright) are available via plugins, not global config

**Impact:**
- `inventory.py` won't find any MCP servers
- No centralized MCP configuration
- Capability discovery incomplete

---

## Impact Analysis

### High Impact (System Broken)
1. **mcp_bridge.py missing** → Enforcement hooks block bash but reference non-existent alternative
   - Scripts can't use `native_glob`/`native_grep`
   - Token efficiency instructions are unusable
   - Forced to violate enforcement or fail

2. **workflow:orchestrate unavailable** → CLAUDE.md CRITICAL section unenforceable
   - Can't invoke workflow for COMPLEX tasks
   - Classification system broken

### Medium Impact (Degraded Experience)
3. **No batch scripts** → Constant recreation of common patterns
4. **No session-start inventory** → No automatic capability awareness
5. **No MCP config in settings** → inventory.py incomplete

### Documentation Issues
6. Multiple docs describe infrastructure that doesn't exist
   - MCP_BRIDGE_COMPLETE.md describes completed work that's missing
   - SETUP.md has installation steps for non-existent files
   - Enforcement messages reference non-existent tools

---

## Root Cause

The `~/.claude` directory was cloned from GitHub (`github.com:c-daly/dotclaude.git`). The infrastructure was built locally but never committed to the git repository. When the directory was cloned to a new machine (or re-cloned), the uncommitted files were lost.

**Git Evidence:**
- Reflog shows: `HEAD@{0}: clone: from github.com:c-daly/dotclaude.git`
- No `lib/` directory in any commit history
- Remote repository has no `lib/` files

---

## Rebuild Priority

1. **Critical:** `mcp_bridge.py` with `native_glob`, `native_grep`, `MCPBridge`
2. **Critical:** Enable `agent-workflow` plugin
3. **High:** Update `session-start.py` to run `inventory.py`
4. **Medium:** Create basic batch scripts in `lib/scripts/`
5. **Low:** Add mcpServers to settings.json (or document that plugins provide this)

---

## Files Needing Updates After Rebuild

Once infrastructure is rebuilt, these may need adjustment:
- `SETUP.md` - Update installation instructions
- `MCP_BRIDGE_COMPLETE.md` - Verify it matches rebuilt version
- Agent-swarm enforcement hooks - Ensure they work with rebuilt infra
- CLAUDE.md - Verify infrastructure list is accurate
