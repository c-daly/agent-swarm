# agent-swarm — project context

## Thesis

Claude Code plugin that enforces phase-gated workflows for AI-assisted development. Core idea: Claude is more effective when it cannot skip steps. The MCP router (`lib/mcp_router.py`) sits between Claude and all configured MCP servers, intercepting tool calls to enforce per-phase tool restrictions. Workflows defined in `config/workflows/*.yaml`; skills in `skills/<name>/SKILL.md`. GitHub: c-daly/agent-swarm.

## Canonical state files (read these for project recovery)

1. `<vault>/10-projects/agent-swarm/narrative.md` — project narrative, dated work entries
2. `<vault>/10-projects/agent-swarm/open-recommendations.md` — outstanding follow-ups with status flags
3. `<vault>/10-projects/agent-swarm/experiments/workflow-runs.md` — measured experiment record (append-only dated runs)
4. `<vault>/10-projects/agent-swarm/experiments/run-context/` — per-run context snapshots
5. `~/.claude/projects/-home-fearsidhe--claude-plugins-agent-swarm/memory/MEMORY.md` — auto-memory index

## Memory topics (use these in observation captures)

- `workflow-runs` — bench results, run-to-run comparisons
- `agent-swarm-architecture` — daemon, router, hooks, workflow engine
- `agent-swarm-bugs` — discovered defects + fixes
- `plugin-cache` — cache vs dev path divergence findings
- `bench-infra` — bench-start/end, benchmark.sh, related scripts

## Project-specific protocols

- **Plugin cache vs dev path**: skill files load from `~/.claude/plugins/cache/fearsidhe-plugins/agent-swarm/<version>/skills/<name>/SKILL.md`, not the dev path. Edit dev, then `cp` (or sync-plugin script when it exists) before testing in a new session. In-session edits don't propagate within the session either.
- **Bench scripts** live at `~/projects/iterate-test/assignments/`: `bench-start.sh`, `bench-end.sh`, `benchmark.sh` (full lifecycle wrapper), `nuke-and-recreate.sh` (needs `delete_repo` gh scope), `reset-assignments.sh` (lighter local reset).
- **Bench-end has a known bug**: hardcodes `assignments/<branch>/tests/` for pytest; breaks when subagents put tests at worktree root. Tracked in open-recommendations.md.
- **Orchestrate brief polling discipline**: orchestrator polls PR review threads once immediately after PR creation, exits before bot reviewers comment. Tracked as a recommendation; the resolveReviewThread mechanism itself is verified working when threads exist at poll time.
- **Daemon** at port 7523. In-memory state lost on restart. Restart after code changes (no hot-reload).
- **Subagent dispatch** via Task tool with iterate workflow; each subagent gets its own worktree at `~/projects/iterate-test-wt/<branch>/`. Worktree isolation works correctly — verified.
