---
name: orchestrate
description: Main workflow orchestrator for complex tasks. Coordinates phase transitions, enforces checkpoints, manages subagent delegation. Invoke this skill when starting a [COMPLEX] classified task.
---

# Workflow Orchestrator

## Purpose
Coordinate multi-phase development workflow with enforcement, checkpoints, and subagent delegation.

## Phases

| Phase | Purpose | Enforcement |
|-------|---------|-------------|
| intake | Understand request, classify complexity | None |
| design | Plan implementation approach | None |
| implement | Write code via subagents | Edit/Write blocked except via subagents |
| verify | Run tests, type-check, lint | None |
| review | Final quality check | None |

## Process

### 1. Initialize Session State

```bash
python3 -c "
import json
from pathlib import Path
state_path = Path.home() / '.claude/plugins/agent-swarm/.state/session.json'
state = {
    'phase': 'intake',
    'autopilot_override': False,
    'in_subagent': False,
    'search_count': 0,
    'task_summary': ''
}
state_path.parent.mkdir(parents=True, exist_ok=True)
state_path.write_text(json.dumps(state, indent=2))
print('[ORCHESTRATOR] Session initialized - Phase: intake')
"
```

### 2. Intake Phase
- Classify the task complexity
- Gather requirements
- Document in scratch file
- **Checkpoint**: Get user approval on understanding

### 3. Design Phase
Update state:
```bash
python3 -c "
import json
from pathlib import Path
state_path = Path.home() / '.claude/plugins/agent-swarm/.state/session.json'
state = json.loads(state_path.read_text())
state['phase'] = 'design'
state_path.write_text(json.dumps(state, indent=2))
print('[ORCHESTRATOR] Phase: design')
"
```
- Create implementation plan
- Identify files to modify
- **Checkpoint**: Get user approval on approach

### 4. Implement Phase
Update state:
```bash
python3 -c "
import json
from pathlib import Path
state_path = Path.home() / '.claude/plugins/agent-swarm/.state/session.json'
state = json.loads(state_path.read_text())
state['phase'] = 'implement'
state_path.write_text(json.dumps(state, indent=2))
print('[ORCHESTRATOR] Phase: implement - Edit/Write now require subagents')
"
```

**IMPORTANT**: During implement phase:
- Direct Edit/Write tools are BLOCKED
- Must use Task tool to spawn subagents for code changes
- Each subagent should handle a focused piece of work

### 5. Verify Phase
```bash
python3 -c "
import json
from pathlib import Path
state_path = Path.home() / '.claude/plugins/agent-swarm/.state/session.json'
state = json.loads(state_path.read_text())
state['phase'] = 'verify'
state_path.write_text(json.dumps(state, indent=2))
print('[ORCHESTRATOR] Phase: verify')
"
```
- Run tests
- Run type-checker (if applicable)
- Run linter (if applicable)
- **Checkpoint**: All checks must pass

### 6. Review Phase
```bash
python3 -c "
import json
from pathlib import Path
state_path = Path.home() / '.claude/plugins/agent-swarm/.state/session.json'
state = json.loads(state_path.read_text())
state['phase'] = 'review'
state_path.write_text(json.dumps(state, indent=2))
print('[ORCHESTRATOR] Phase: review')
"
```
- Final quality check
- Summary of changes
- **Checkpoint**: User approval to complete

### 7. Complete
```bash
python3 -c "
import json
from pathlib import Path
state_path = Path.home() / '.claude/plugins/agent-swarm/.state/session.json'
state = json.loads(state_path.read_text())
state['phase'] = ''
state_path.write_text(json.dumps(state, indent=2))
print('[ORCHESTRATOR] Workflow complete')
"
```

## Autopilot Mode

To enable autopilot (auto-approve all tool calls):
```bash
python3 -c "
import json
from pathlib import Path
state_path = Path.home() / '.claude/plugins/agent-swarm/.state/session.json'
state = json.loads(state_path.read_text()) if state_path.exists() else {}
state['autopilot_override'] = True
state_path.write_text(json.dumps(state, indent=2))
print('[ORCHESTRATOR] Autopilot enabled')
"
```

## Escalation Triggers
- Requirements unclear after 2-3 questions
- Architectural decision needed
- External dependency required
- Multiple valid approaches exist
