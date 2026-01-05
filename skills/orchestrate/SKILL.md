---
name: orchestrate
description: Main workflow orchestrator for complex tasks. Coordinates phase transitions, enforces checkpoints based on config, manages subagent delegation. Invoke for [COMPLEX] tasks.
---

# Workflow Orchestrator

## Configuration

Load from `~/.claude/plugins/agent-swarm/config/workflow.json`:

```python
import json
from pathlib import Path
config = json.loads((Path.home() / ".claude/plugins/agent-swarm/config/workflow.json").read_text())
```

**Key settings:**
- `checkpoints.<phase>`: true/false - whether to pause for approval
- `autopilot.enabled`: bypass all prompts
- `phases.<phase>.enforce_subagents`: require Task tool for writes

## Phase Flow

```
intake → [checkpoint?] → research/explore → design → [checkpoint?]
→ implement → review → [checkpoint?] → debug (if needed) → git → [checkpoint?] → done
```

## Orchestrator Commands

### Initialize Session
```bash
python3 << 'EOF'
import json
from pathlib import Path

config_path = Path.home() / ".claude/plugins/agent-swarm/config/workflow.json"
state_path = Path.home() / ".claude/plugins/agent-swarm/.state/session.json"

config = json.loads(config_path.read_text()) if config_path.exists() else {}

state = {
    "phase": "intake",
    "autopilot_override": config.get("autopilot", {}).get("enabled", False),
    "in_subagent": False,
    "search_count": 0,
    "read_count": 0,
    "task_summary": "",
    "checkpoints": config.get("checkpoints", {})
}
state_path.parent.mkdir(parents=True, exist_ok=True)
state_path.write_text(json.dumps(state, indent=2))
print(f"[ORCHESTRATOR] Initialized")
print(f"  Phase: intake")
print(f"  Autopilot: {state['autopilot_override']}")
print(f"  Checkpoints: {[k for k,v in state['checkpoints'].items() if v]}")
EOF

# Run capability inventory
python3 ~/.claude/plugins/agent-swarm/scripts/inventory.py all
```

### Discover Available Tools
Before starting any task, know what's available:
```bash
# Full inventory
python3 ~/.claude/plugins/agent-swarm/scripts/inventory.py all

# Find right tool for a need
python3 ~/.claude/plugins/agent-swarm/scripts/inventory.py tools "find function definition"
```

**Tool Selection Priority:**
1. Serena → for code analysis (NOT Read)
2. Context7 → for docs (NOT WebSearch)
3. Batch scripts → for multiple operations
4. MCP tools → for single operations
5. Read/Bash → last resort only

### Transition Phase
```bash
python3 << 'EOF'
import json, sys
from pathlib import Path

new_phase = "PHASE_NAME"  # Replace with target phase

state_path = Path.home() / ".claude/plugins/agent-swarm/.state/session.json"
state = json.loads(state_path.read_text())

old_phase = state.get("phase", "")
state["phase"] = new_phase

# Reset counters on phase change
state["search_count"] = 0
state["read_count"] = 0

state_path.write_text(json.dumps(state, indent=2))

checkpoint_needed = state.get("checkpoints", {}).get(new_phase, False)
print(f"[ORCHESTRATOR] {old_phase} → {new_phase}")
if checkpoint_needed:
    print(f"  ⚠️  CHECKPOINT: Get user approval before proceeding")
EOF
```

### Check Checkpoint
```bash
python3 << 'EOF'
import json
from pathlib import Path

state_path = Path.home() / ".claude/plugins/agent-swarm/.state/session.json"
state = json.loads(state_path.read_text())

phase = state.get("phase", "")
needs_checkpoint = state.get("checkpoints", {}).get(phase, False)
autopilot = state.get("autopilot_override", False)

if autopilot:
    print(f"[CHECKPOINT] Skipped (autopilot mode)")
elif needs_checkpoint:
    print(f"[CHECKPOINT] Phase '{phase}' requires approval")
    print(f"  Present summary and wait for user confirmation")
else:
    print(f"[CHECKPOINT] Not required for phase '{phase}'")
EOF
```

### Toggle Autopilot
```bash
python3 << 'EOF'
import json
from pathlib import Path

state_path = Path.home() / ".claude/plugins/agent-swarm/.state/session.json"
state = json.loads(state_path.read_text()) if state_path.exists() else {}

current = state.get("autopilot_override", False)
state["autopilot_override"] = not current
state_path.write_text(json.dumps(state, indent=2))

print(f"[AUTOPILOT] {'Enabled' if state['autopilot_override'] else 'Disabled'}")
EOF
```

### Configure Checkpoint
```bash
python3 << 'EOF'
import json
from pathlib import Path

# Edit these values
phase = "implement"  # Phase to configure
enabled = True       # True = checkpoint required, False = skip

config_path = Path.home() / ".claude/plugins/agent-swarm/config/workflow.json"
config = json.loads(config_path.read_text())

config["checkpoints"][phase] = enabled
config_path.write_text(json.dumps(config, indent=2))

print(f"[CONFIG] Checkpoint for '{phase}': {'enabled' if enabled else 'disabled'}")
EOF
```

## Phase Responsibilities

### INTAKE
- Classify: trivial/simple/complex
- Gather requirements
- **Checkpoint if enabled**: Present understanding, get approval

### RESEARCH (complex/unfamiliar only)
- Deep web research
- Use `researcher` agent (haiku model)
- Return summarized findings only

### EXPLORE
- Codebase navigation
- Use `explorer` agent (haiku model)
- Return file:line references, not content

### DESIGN
- Architecture planning
- Use `architect` agent (sonnet model)
- **Checkpoint if enabled**: Present plan, get approval

### IMPLEMENT
- **ENFORCED**: Must use Task tool with `implementer` agent
- Direct Edit/Write BLOCKED
- Each subagent: focused scope, sonnet model

### REVIEW
- Use `reviewer` agent (sonnet model)
- Run tests, verify against design
- **Checkpoint if enabled**: Present review results

### DEBUG (if needed)
- Use `debugger` agent (sonnet model)
- Fix issues from review
- Loop until review passes

### GIT
- Use `git-agent` (haiku model)
- Stage, commit, push
- **Checkpoint if enabled**: Confirm before push
- **Auto-snapshot after completion**:
  ```bash
  python3 ~/.claude/plugins/agent-swarm/scripts/charts.py snapshot
  ```
  This automatically captures metrics for historical tracking and trend analysis.

## Subagent Spawning

When spawning subagents, specify model AND token budget:

```python
# Token budgets by agent type (prevent runaways)
AGENT_TOKEN_BUDGETS = {
    "agent-swarm:explorer": 50000,      # Quick exploration
    "agent-swarm:researcher": 150000,   # Deep research allowed
    "agent-swarm:architect": 120000,    # Design needs space
    "agent-swarm:implementer": 100000,  # Focused implementation
    "agent-swarm:reviewer": 80000,      # Review existing code
    "agent-swarm:debugger": 150000,     # Debugging can be complex
    "agent-swarm:git-agent": 30000      # Simple git operations
}
```

```json
{
  "description": "Explore auth system",
  "prompt": "Find all authentication-related files...",
  "subagent_type": "agent-swarm:explorer",
  "model": "haiku",
  "token_budget": 50000
}
```

**CRITICAL:** Always include `token_budget` parameter to prevent runaway agents

Models by agent:
- researcher, explorer, git-agent: **haiku** (cheap, parallelizable)
- architect, implementer, reviewer, debugger: **sonnet** (needs reasoning)
- orchestrator only: **opus** (complex coordination)

## Enforcement Active

The hook `combined-enforcement.py` enforces:
- Phase tool restrictions
- Token efficiency limits
- Subagent requirements
- Git safety

Violations are blocked with guidance message.
