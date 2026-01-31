# SUBAGENT OPERATING PROTOCOL

## Tools
| Op | Tool |
|----|------|
| Search code | `serena__search_for_pattern` |
| Read files | `serena__read_file`, `native__read_file` |
| Find symbols | `serena__find_symbol`, `serena__get_symbols_overview` |
| Find files | `native__glob`, `serena__find_file` |
| Run commands | `native__bash` (git, pytest, ruff, gh) |
| Edit code | `serena__replace_content`, `serena__replace_symbol_body` |

Multi-repo: `native__bash 'git -C /path/to/repo status'`

## Long-Running Commands (pytest, builds)
MCP tool calls timeout at ~30s. For commands that take longer (e.g. full test suite):
```bash
nohup <command> > /tmp/output.txt 2>&1 &
# then later:
cat /tmp/output.txt
```

## Efficiency
- >=3 reads or searches -> batch script with `mcp_bridge`
- Track what you've read -- no duplicate reads
- Output summaries only, not raw data

## Git (REVIEW phase only)
1. Verify branch (never create branches -- orchestrator's job)
2. Commit -> push -> create PR via `gh`
