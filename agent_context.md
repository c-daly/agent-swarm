# Subagent Operating Context

**INJECTION**: This file is included in subagent prompts for environment context.

---

## Tool Access

Subagents access tools via `mcp-call`. Native Claude Code tools (Bash, Read, Write, Edit, Glob, Grep) are NOT available.

### Shell Commands
```bash
mcp-call git status
mcp-call gh pr list
mcp-call pytest tests/ -v
mcp-call ruff check .
```

### Code Operations
```bash
mcp-call serena__read_file '{"relative_path": "src/foo.py"}'
mcp-call serena__find_symbol '{"name_path_pattern": "MyClass"}'
mcp-call serena__search_for_pattern '{"substring_pattern": "pattern"}'
```

## Key Paths
- Plugin root: ~/.claude/plugins/agent-swarm/
- Hooks: ~/.claude/plugins/agent-swarm/hooks/
- This context file: ~/.claude/plugins/agent-swarm/agent_context.md

## Hierarchical Context

Context is injected based on directory. Check CONTEXT.md files in the working directory and parents for project-specific guidance.
