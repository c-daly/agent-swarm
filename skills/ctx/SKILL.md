---
name: ctx
description: View and manage hierarchical context for the current directory
user_invocable: true
---

## Usage
```
/ctx           # Show resolved context
/ctx tree      # Show hierarchy as tree
/ctx edit      # Edit context at current scope
```

## Hierarchy (walks up from cwd)
1. Component -- `.context/CONTEXT.md` in current/parent dirs
2. Repo -- `.claude/CONTEXT.md` at repo root
3. Project -- above repo
4. User -- `~/.claude/CONTEXT.md`

Sections can `@override` or `@ignore` parent values.

## CLI
```bash
python3 ~/.claude/plugins/agent-swarm/ctx/resolver.py resolve .
python3 ~/.claude/plugins/agent-swarm/ctx/resolver.py tree .
```

CONTEXT.md = static intentional knowledge. MEMORY.md = distilled session learnings.
