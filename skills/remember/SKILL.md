---
name: remember
description: Save a learning to persistent memory with automatic scope inference
user_invocable: true
---

## Usage
```
/remember <thing to remember>
/remember --scope=global|project <thing>
```

## Scope Inference
- "always", "never", "I prefer" -> user level (~/.claude/MEMORY.md)
- Specific file paths -> component level
- General repo patterns -> repo level

## CLI
```bash
python3 ~/.claude/plugins/agent-swarm/context/remember.py "<content>" [--scope=<scope>]
```
