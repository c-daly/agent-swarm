# agent-swarm — project context

## Thesis

Claude Code plugin that enforces phase-gated workflows for AI-assisted development. Core idea: Claude is more effective when it cannot skip steps. The MCP router (`lib/mcp_router.py`) sits between Claude and all configured MCP servers, intercepting tool calls to enforce per-phase tool restrictions. Workflows defined in `config/workflows/*.yaml`; skills in `skills/<name>/SKILL.md`. GitHub: c-daly/agent-swarm.

## Canonical state files (read these for project recovery)

1. `<vault>/10-projects/agent-swarm/narrative.md` — project narrative, dated work entries
2. `<vault>/10-projects/agent-swarm/open-recommendations.md` — outstanding follow-ups with status flags
3. `<vault>/10-projects/agent-swarm/experiments/workflow-runs.md` — measured experiment record (append-only dated runs)
4. `<vault>/10-projects/agent-swarm/experiments/run-context/` — per-run context snapshots
5. `~/.claude/projects/-Users-cdaly-projects-agent-swarm/memory/MEMORY.md` — auto-memory index *(machine-specific path; encodes this dev tree's cwd)*

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

## Session start protocol

> *Stopgap until continuity's resume-brief is installed and provides this automatically — see `hooks/session-start.py:discover_resume_brief`. Remove this section when that path returns non-empty.*

Trigger: every session, before responding to the first user message.

1. `tail -120 <vault>/10-projects/agent-swarm/narrative.md` — read the latest 1-2 dated entries.
2. Skim `<vault>/10-projects/agent-swarm/open-recommendations.md` for `[~]` (in progress) and `[ ]` (open) items related to the cwd / area the user is asking about.
3. Read `~/.claude/projects/-Users-cdaly-projects-agent-swarm/memory/MEMORY.md` — the auto-memory index, not bodies. Pull a body only when the index entry is relevant. *(Path encodes the cwd of this dev tree — `-Users-cdaly-projects-agent-swarm` for this machine. If you're on a different machine, derive the equivalent: `~/.claude/projects/<encoded-cwd>/memory/MEMORY.md`.)*
4. Briefly acknowledge what state is being picked up from in the first response (e.g., "picking up from the simple-workflow PR93 merge; bin/ infra follow-ups still open").

## Task completion protocol

> *Stopgap until continuity provides a write-on-end mechanism. Pare back when continuity covers narrative + open-rec updates automatically; keep only what continuity does not.*

Trigger: when the user signals stopping ("this is done", "good for now", "wrapping up") or before a clean session end.

1. Append a dated narrative entry to `<vault>/10-projects/agent-swarm/narrative.md` summarizing what shipped — commits, PRs, decisions, validation steps.
2. Update `<vault>/10-projects/agent-swarm/open-recommendations.md`: mark resolved items with `[x] *Done <date>*`; append new follow-ups discovered.
3. Save feedback / project memories per the auto-memory rules already in the system prompt (don't duplicate vault entries — memories are for *cross-conversation* signals like preferences and decisions; vault entries are project narrative).
4. **Sync the vault.** `cd <vault> && git add 10-projects/agent-swarm/{narrative,open-recommendations}.md && git commit -m "agent-swarm: <one-line summary of what shipped>" && git push`. Always provide `-m` (Claude's shell is non-interactive — no `-m` will hang at the editor). Don't skip the sync — the vault is the durable record across sessions and machines.

## Local CLAUDE.md files

These live in subdirectories and load when cwd is at or below them. Each one captures area-specific context that's non-obvious from reading the code.

- `bin/CLAUDE.md` — dev/cache discipline, known infra bugs in shell scripts.
- `config/workflows/CLAUDE.md` — what `load_workflow_configs` actually consumes vs what's aspirational; the `_KNOWN_WORKFLOWS` gotcha when adding a new workflow.
- `lib/CLAUDE.md` — daemon/router/controller/permissions orientation; pointer to `protocol_assembly.py` as the seam for future briefing changes.
