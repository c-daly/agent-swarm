# SUBAGENT OPERATING PROTOCOL

## Tools — Calling Convention

All tools are called via Bash with `mcp-call` prefix. You only have `Bash` — use it like this:

```bash
mcp-call <tool_name> '<json_args>'
```

### Available Tools

| Op | Command |
|----|---------|
| Read files | `mcp-call --caller-id=<your-agent-id> native__read_file '{"file_path": "/absolute/path"}'` |
| Write files | `mcp-call --caller-id=<your-agent-id> native__write_file '{"file_path": "/absolute/path", "content": "..."}'` |
| Edit files | `mcp-call --caller-id=<your-agent-id> native__edit_file '{"file_path": "/absolute/path", "old_string": "...", "new_string": "..."}'` |
| Find files | `mcp-call --caller-id=<your-agent-id> native__glob '{"pattern": "**/*.py", "path": "/dir"}'` |
| Search code | `mcp-call --caller-id=<your-agent-id> native__grep '{"pattern": "regex", "path": "/dir"}'` |
| Run commands | `mcp-call --caller-id=<your-agent-id> native__bash '{"command": "pytest tests/"}'` |

**`--caller-id` is required for all MCP tool calls.** Without it, the router cannot identify your agent for permission checks and the call fails at registration. Your agent ID was assigned at registration; use it as the value.

### Examples

```bash
# Read a file
mcp-call --caller-id=01a native__read_file '{"file_path": "/home/fearsidhe/projects/myproject/src/main.py"}'

# Write a file
mcp-call --caller-id=01a native__write_file '{"file_path": "/home/fearsidhe/projects/myproject/src/new.py", "content": "class Foo:\n    pass\n"}'

# Run tests
mcp-call --caller-id=01a native__bash '{"command": "cd /home/fearsidhe/projects/myproject && pytest tests/ -v"}'

# Git operations
mcp-call --caller-id=01a native__bash '{"command": "cd /home/fearsidhe/projects/myproject && git add -A && git commit -m \"feat: add feature\""}'
```

(Replace `01a` with your actual agent ID from registration.)

**IMPORTANT:** Do NOT use bare `Bash` commands like `cat`, `echo`, `python3`. Always use `mcp-call`.

## Long-Running Commands (pytest, builds)
MCP tool calls timeout at ~30s. For commands that take longer (e.g. full test suite):
```bash
mcp-call --caller-id=01a native__bash '{"command": "nohup pytest tests/ > /tmp/output.txt 2>&1 &"}'
# then later:
mcp-call --caller-id=01a native__bash '{"command": "cat /tmp/output.txt"}'
```

## Efficiency
- Track what you've read — no duplicate reads
- Output summaries only, not raw data

## Git (REVIEW phase only)
1. Verify branch (never create branches — orchestrator's job)
2. Commit -> push -> create PR via `gh`
