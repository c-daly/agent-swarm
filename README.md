# Agent Swarm

Enforcement system for agent-based workflows in Claude Code.

## Features

- **Phase Enforcement**: During 'implement' phase, blocks direct Edit/Write tools - requires spawning subagents for code changes
- **Script Routing**: Tracks search tool usage, encourages batch scripts for MCP operations
- **Autopilot Mode**: Auto-approves all tools when enabled

## Installation

```bash
claude plugin install agent-swarm@<your-marketplace>
```

Or install from GitHub:

```bash
claude plugin add https://github.com/fearsidhe/agent-swarm
```

## Usage

### Session State

The plugin uses `~/.claude/plugins/agent-swarm/.state/session.json` to track:

```json
{
  "phase": "implement",
  "autopilot_override": false,
  "in_subagent": false,
  "search_count": 0
}
```

### Phases

- **intake**: Gathering requirements (no restrictions)
- **design**: Planning implementation (no restrictions)
- **implement**: Coding phase (Edit/Write blocked unless via subagent)
- **verify**: Testing (no restrictions)
- **review**: Final review (no restrictions)

### Autopilot Mode

Enable autopilot to auto-approve all tools:

```bash
python3 -c "
import json
from pathlib import Path
state_path = Path.home() / '.claude/plugins/agent-swarm/.state/session.json'
state = json.loads(state_path.read_text()) if state_path.exists() else {}
state['autopilot_override'] = True
state_path.write_text(json.dumps(state, indent=2))
print('Autopilot enabled')
"
```

## Files

- `hooks/combined-enforcement.py` - Main enforcement hook
- `.state/session.json` - Runtime state (gitignored)
- `.claude-plugin/manifest.json` - Plugin manifest
