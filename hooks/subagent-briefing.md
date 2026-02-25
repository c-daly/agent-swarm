# SUBAGENT OPERATING PROTOCOL

## Tools — Calling Convention

All tools are called via Bash with `mcp-call` prefix. You only have `Bash` — use it like this:

```bash
mcp-call <tool_name> '<json_args>'
```

### Available Tools

| Op | Command |
|----|---------|
| Read files | `mcp-call native__read_file '{"file_path": "/absolute/path"}'` |
| Write files | `mcp-call native__write_file '{"file_path": "/absolute/path", "content": "..."}'` |
| Edit files | `mcp-call native__edit_file '{"file_path": "/absolute/path", "old_string": "...", "new_string": "..."}'` |
| Find files | `mcp-call native__glob '{"pattern": "**/*.py", "path": "/dir"}'` |
| Search code | `mcp-call native__grep '{"pattern": "regex", "path": "/dir"}'` |
| Run commands | `mcp-call native__bash '{"command": "pytest tests/"}'` |

### Examples

```bash
# Read a file
mcp-call native__read_file '{"file_path": "/home/fearsidhe/projects/myproject/src/main.py"}'

# Write a file
mcp-call native__write_file '{"file_path": "/home/fearsidhe/projects/myproject/src/new.py", "content": "class Foo:\n    pass\n"}'

# Run tests
mcp-call native__bash '{"command": "cd /home/fearsidhe/projects/myproject && pytest tests/ -v"}'

# Git operations
mcp-call native__bash '{"command": "cd /home/fearsidhe/projects/myproject && git add -A && git commit -m \"feat: add feature\""}'
```

**IMPORTANT:** Do NOT use bare `Bash` commands like `cat`, `echo`, `python3`. Always use `mcp-call`.

## Long-Running Commands (pytest, builds)
MCP tool calls timeout at ~30s. For commands that take longer (e.g. full test suite):
```bash
mcp-call native__bash '{"command": "nohup pytest tests/ > /tmp/output.txt 2>&1 &"}'
# then later:
mcp-call native__bash '{"command": "cat /tmp/output.txt"}'
```

## Efficiency
- Track what you've read — no duplicate reads
- Output summaries only, not raw data

## Git (REVIEW phase only)
1. Verify branch (never create branches — orchestrator's job)
2. Commit -> push -> create PR via `gh`
