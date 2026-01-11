# Agent Swarm Setup

## Prerequisites

### 1. MCP Bridge Infrastructure

Agent-swarm relies on `/home/fearsidhe/.claude/plugins/agent-swarm/lib/mcp_bridge.py` for token-efficient batch operations.

**Installation:**
```bash
# The mcp_bridge.py file should already exist at:
ls -la /home/fearsidhe/.claude/plugins/agent-swarm/lib/mcp_bridge.py

# If missing, copy from this repo's reference:
# (Note: mcp_bridge.py is maintained separately in /home/fearsidhe/.claude/plugins/agent-swarm/lib/)
```

**Verify installation:**
```bash
python3 -c "import sys; sys.path.insert(0, '/home/fearsidhe/.claude/plugins/agent-swarm/lib'); from mcp_bridge import native_glob; print('✅ mcp_bridge installed')"
```

### 2. Dependencies

- Python 3.8+
- `rg` (ripgrep) - for native_grep batching
- Git - for version control

### 3. Environment Setup

The agent-swarm plugin uses enforcement hooks that require:
- Claude Code CLI
- Active MCP servers: Serena, Context7, Filesystem, Memory

## Configuration

### Workflow Checkpoints

Edit `config/workflow.json` to control checkpoint behavior:

```json
{
  "checkpoints": {
    "intake": true,      // Always verify requirements
    "research": true,    // Gather info before designing
    "explore": true,     // Understand codebase
    "design": true,      // Get approval before implementing
    "implement": true,   // Review after implementation
    "review": true,      // Final quality check
    "git": true          // Commit review
  }
}
```

### Autopilot Mode

Disable checkpoints for fully autonomous operation:

```json
{
  "autopilot": {
    "enabled": true,
    "suppress_non_workflow_prompts": true,
    "auto_approve_tools": true
  }
}
```

**Warning:** Autopilot skips all human approval gates!

## Token Efficiency Features

### Enforcement Hook

`hooks/combined-enforcement.py` blocks inefficient tool usage:

- ❌ `cat file` → Use Read tool instead
- ❌ `cat > file << EOF` → Use Write tool instead
- ❌ `grep pattern` → Use Grep tool instead
- ✅ Allows legitimate pipes: `grep | cat`

### Batch Operations

When you need to perform 3+ similar operations, use a script with mcp_bridge:

**Good Example:**
```python
import sys
sys.path.insert(0, '/home/fearsidhe/.claude/plugins/agent-swarm/lib')
from mcp_bridge import native_glob

# Batch 5 patterns into one script
patterns = ['**/*.py', '**/*.js', '**/*.ts', '**/*.md', '**/*.json']
counts = {p: len(native_glob(p, '/project')) for p in patterns}
print(f"Summary: {counts}")
# Returns: {'**/*.py': 45, '**/*.js': 23, ...}
```

**Bad Example:**
```python
# ❌ Don't use native commands for single operations
from mcp_bridge import native_read
content = native_read('file.txt')  # Just use Read tool!
```

## Agent Instructions

Agent behavior is defined in `agents/`:

- `explorer.md` - Codebase exploration with strict output limits (2000 chars max)
- `implementer.md` - Code implementation with file change limits (10 files max)
- `architect.md` - System design and planning
- `reviewer.md` - Code quality review

## Diagnostic Tools

### Track Subagent Performance

```bash
python3 scripts/track_subagent.py <agent_id> <agent_type>

# Or view report:
python3 scripts/track_subagent.py report
```

### Diagnose Efficiency Issues

```bash
python3 scripts/diagnose.py

# Or analyze recent activity:
python3 scripts/diagnose.py --recent 100
```

## Troubleshooting

### "ModuleNotFoundError: No module named 'mcp_bridge'"

Ensure `/home/fearsidhe/.claude/plugins/agent-swarm/lib/` is in your Python path:

```python
import sys
sys.path.insert(0, '/home/fearsidhe/.claude/plugins/agent-swarm/lib')
from mcp_bridge import native_glob
```

### Hook Not Blocking Cat/Grep

Verify hook is active:

```bash
cat hooks/combined-enforcement.py | grep "cat abuse"
```

The hook is called automatically by Claude Code on every tool use.

### Checkpoints Not Triggering

Check `config/workflow.json` - checkpoints must be enabled (`true`).

## See Also

- `~/.claude/CLAUDE.md` - Global agent operating protocol
- `/home/fearsidhe/.claude/plugins/agent-swarm/lib/README.md` - MCP bridge documentation
- `ENFORCEMENT_FIXES.md` - Enforcement system changelog
