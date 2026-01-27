---
name: remember
description: Save a learning to persistent memory with automatic scope inference
user_invocable: true
---

# /remember - Save Learning

Saves a pattern, preference, or learning to persistent memory.

## Usage

```
/remember <thing to remember>
/remember --scope=global <thing>
/remember --scope=project <thing>
```

## How It Works

1. Analyzes the content to infer appropriate scope
2. Saves to the correct .context/MEMORY.md file
3. Confirms where it was saved

## Scope Inference

- Contains "always", "never", "I prefer" → user level (~/.claude/MEMORY.md)
- References specific file paths → component level
- General repo patterns → repo level

## Implementation

When invoked, the skill runs:
```bash
python3 ~/.claude/plugins/agent-swarm/context/remember.py "<content>" [--scope=<scope>]
```
