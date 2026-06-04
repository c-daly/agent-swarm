# agent-swarm

Enforcement system for phase-gated, multi-agent workflows in Claude Code. Routes all tool calls through a central MCP router, enforces per-phase tool restrictions, and spawns specialized subagents under a role-based permission model.

## Installation

```bash
claude plugin install agent-swarm
```

Registers a `mcp-router` MCP server and installs `PreToolUse`, `SessionStart`, `SessionEnd`, and `PreCompact` hooks.

**Requirements:** Python 3.11+, `git`, `gh` CLI (for PR workflows)

---

## Workflows

Four workflow definitions live in `config/workflows/*.yaml`. Each defines phases, tool restrictions per phase, eligible agent roles, checkpoint gates, and transition rules.

### `/iterate` — TDD Loop

Well-scoped task with test-driven implementation and adversarial review gates.

```
test_writing → implement → test ─── pass + confident ──→ review → complete
                  ↑              ├── adversary fails ──→ implement
                  └──────────────┴── weak suite ───────→ test_writing
```

| Phase | What happens | Can write code? |
|---|---|---|
| `test_writing` | Write tests first, cover edge cases | Yes |
| `implement` | Write minimal code to pass tests | Yes |
| `test` | Run tests, adversary evaluates suite quality | No |
| `review` | Verify conventions, commit if clean | No |
| `complete` | Terminal | — |

**Gate logic:** Tests pass + high confidence → `review`. Adversary-written tests fail → `implement`. Tests pass but weak suite → `test_writing`. Review clean → `complete`. Review issues → `implement`.

**Invoke:** `/iterate`

---

### `/develop` — Full SDLC Simulation

Significant features requiring team simulation: requirements, research, design, TDD implementation, adversarial review, and PM acceptance.

```
intake → research → design ─(checkpoint)→ branch
  → test_writing → implement → test ─(checkpoint)→ review ─(checkpoint)→ merge
  → acceptance ─(checkpoint)→ complete
```

| Phase | Eligible agents | Can write code? |
|---|---|---|
| `intake` | PM | No |
| `research` | Researcher | No |
| `design` | Architect | No (checkpoint) |
| `branch` | Git-agent | No |
| `test_writing` | Implementer | Yes |
| `implement` | Implementer | Yes |
| `test` | Implementer, Debugger | No (checkpoint) |
| `review` | Reviewer | No (checkpoint) |
| `merge` | Git-agent | No |
| `acceptance` | PM | No (checkpoint) |
| `complete` | — | — |

Checkpoints at `design`, `test`, `review`, and `acceptance` block advancement until the responsible agent passes them. Max 8 concurrent agents, 3 agent respawns. Integrates with GitHub issues for feature tickets, subtasks, and followups.

**Invoke:** `/develop`

---

### `/experiment` — Autonomous Experiment Loop

Research experiments with eval gates, journal memory, and iteration limits.

```
read → plan → work → eval ─── pass ──→ journal → decide ─── done
                ↑      └── fail ──→ work          └── iterate → plan
```

| Phase | What happens | Can write code? |
|---|---|---|
| `read` | Read goal.yaml, understand experiment | No |
| `plan` | Design next iteration, research if needed | No |
| `work` | Implement the experiment (eval files protected) | Yes |
| `eval` | Run eval suite (eval files protected) | No |
| `journal` | Record results to journal/ | Journal only |
| `decide` | Continue iterating or stop | No |
| `done` | Terminal | — |

Max 10 iterations, 4 concurrent agents. Eval files are write-protected during both `work` and `eval` phases to prevent gaming.

**Invoke:** `/experiment`

---

### Orchestrate — Parallel Task Dispatch

Breaks a feature into independent subtasks, dispatches subagents (each running their own workflow), and manages PRs per task group.

| Phase | What happens |
|---|---|
| `intake` | Gather missing info (skipped if input is complete) |
| `design` | Plan architecture, document decisions |
| `orchestrate` | Build task queue, dispatch subagents, poll for completion |

Each `group` in the task queue maps to a PR. Stop condition: queue empty + no agents in flight + no unaddressed PR comments + clean working tree + all groups have PRs.

**Invoke:** `/orchestrate`

---

## Skills

Skills are invocable via `/skill_name`. They provide workflow entry points, utilities, and reference documentation.

### Workflow Skills

| Skill | Invoke | Purpose |
|---|---|---|
| `iterate` | `/iterate` | TDD loop with phase gates |
| `develop` | `/develop` | Full SDLC team simulation |
| `experiment` | `/experiment` | Autonomous experiment with eval gates |
| `orchestrate` | `/orchestrate` | Task queue dispatch with parallel subagents |
| `implement` | `/implement` | General implementation (default workflow, no TDD) |
| `debug` | `/debug` | Systematic debugging: triage → reproduce → hypothesize → prove → fix → verify |
| `teams-develop` | `/teams-develop` | Full PR lifecycle using native Claude Code teams |
| `agent-teams-workflow` | `/agent-teams-workflow` | Coordinate agent teams from a design doc or plan |

### Orchestration Skills

| Skill | Invoke | Purpose |
|---|---|---|
| `parallel-orchestrate` | `/parallel-orchestrate` | Dispatch N independent TDD subagents from a YAML manifest with worktree isolation |
| `plan-to-manifest` | `/plan-to-manifest` | Translate an implementation plan into a parallel orchestration YAML manifest |
| `pipeline` | `/pipeline` | End-to-end: design doc → plan → manifest → parallel orchestration → branch |
| `poll` | `/poll` | Controlled polling for async operations at specified intervals |

### Utility Skills

| Skill | Invoke | Purpose |
|---|---|---|
| `verify` | `/verify` | Run code quality checks (ruff, black, mypy, pytest) |
| `pr-comment` | `/pr-comment` | PR review comment workflow — understand the concern before fixing |
| `spawn` | `/spawn` | Reference for spawning subagents with correct prompt structure |
| `ctx` | `/ctx` | View and manage hierarchical context for the current directory |
| `remember` | `/remember` | Save a learning to persistent memory with automatic scope inference |
| `distill` | `/distill` | Distill session episodes into persistent memory patterns |

---

## Agent Roles

Nine specialized agent types, each with a defined toolset and model assignment. Agents are spawned as subagents by workflows or directly by the main agent.

| Agent | Model | Purpose | Can write? |
|---|---|---|---|
| `explorer` | haiku | Fast codebase exploration, file search, pattern mapping | No |
| `researcher` | haiku | Documentation lookup, library docs, API patterns | No |
| `architect` | sonnet | Architecture/design decisions, multi-file planning | No |
| `implementer` | sonnet/opus | Code implementation, modifications, side-effect safety | Yes |
| `reviewer` | sonnet | Code review, quality checking, test coverage, security | No |
| `debugger` | sonnet | Debug and fix: reproduce first, trace root cause, minimal fix | Yes |
| `adversary` | sonnet | Adversarial test quality evaluation, coverage gaps, legitimacy | Yes |
| `git-agent` | haiku | Staging, committing, PR creation, branch management | No (shell only) |
| `pm` | — | Intake, acceptance, decision-making | No |

---

## Permission System

Three layers enforce tool restrictions:

**Layer 1 — `settings.json`:** Denies native `Read`, `Write`, `Edit`, `Glob`, `Grep`, `WebFetch`, `WebSearch` to the main agent, forcing file operations through the router.

**Layer 2 — PreToolUse hook (`hooks/native-tool-blocking.py`):** Runs on every tool call. Blocks everything except `mcp__router__*` / `mcp__plugin__*` tools, `Bash` calls prefixed with `mcp-call`, and system tools (`Task`, `SendMessage`, `AskUserQuestion`, `Skill`, etc.).

**Layer 3 — Router permissions (`config/permissions.yaml`):** Multi-level whitelist:
- **Global** defaults (allowed/blocked/superblocked tools)
- **Roles** (read_only, editor, shell_safe, shell_full, workflow_control) — define tool category bundles
- **Agents** (per agent type) — inherit from roles, add agent-specific overrides
- **Workflows** (per workflow × phase) — override agent permissions within a specific phase

Tool categories: `FILE_READ`, `FILE_WRITE`, `FILE_SEARCH`, `CODE_QUERY`, `CODE_EDIT`, `SHELL_SAFE`, `SHELL_FULL`, `WEB_RESEARCH`, `USER_INTERACTION`, `SUBAGENT`, `WORKFLOW_CONTROL`.

**Superblocked tools** (never allowed regardless of role/phase): direct `Read`, `Write`, `Edit`, `Glob`, `Grep` — must use router equivalents.

### Subagent tool access

Subagents spawned via `Agent` or `Task` reach MCP tools through a shell alias:

```bash
mcp-call native__read_file '{"file_path": "/path/to/file"}'
mcp-call native__bash '{"command": "pytest tests/"}'
```

### Debugging

| Symptom | Likely cause | Fix |
|---|---|---|
| `[BLOCKED]` on native tool | Hook blocking | Use `mcp__router__native__*` equivalent |
| Permission denied from router | Wrong phase for that tool | Check `config/permissions.yaml` |
| Subagent can't write files | Phase restriction | Check workflow YAML for current phase |

---

## Hooks

| Hook | File | Purpose |
|---|---|---|
| `PreToolUse` (Task/Agent) | `agent-dispatch.py` | Intercept agent/task spawning for registration and briefing |
| `PreToolUse` (*) | `native-tool-blocking.py` | Block native tools, force router usage |
| `SessionStart` | `session-start.py` | Initialize daemon, load state |
| `SessionEnd` | `session-end.py` | Persist state, cleanup |
| `PreCompact` | `pre-compacting.py` | Save context before compaction |

Additional hook support files: `hook_logging.py`, `subagent-briefing.md` (protocol injected into every subagent), `subagent-mcp-bypass.py`.

---

## MCP Backends

The router proxies tool calls to five backends, configured in `config/backends.json`:

| Backend | Prefix | Purpose |
|---|---|---|
| `native` | `native__*` | File I/O, search, bash, web — core tools |
| `serena` | `serena__*` | Language-server-powered code intelligence (symbols, references, rename) |
| `context7` | `context7__*` | Library documentation lookup |
| `playwright` | `playwright__*` | Browser automation |
| `workflow` | `workflow__*` | Workflow state, phase transitions, agent registry |

---

## Architecture

```
Main Agent
    │
    ├─ mcp__router__* tools
    │       │
    │  MCP Router (lib/router.py)  ← TCP 127.0.0.1:7523
    │       │
    │  Controller (lib/controller.py)
    │  Manages: phase state, agent registry, permissions
    │       │
    │  Daemon (lib/daemon.py)
    │  Process lifecycle, backend management
    │
    └─ Agent/Task tool → Subagents
                       │
                  mcp-call alias → Router → Controller
```

### Key modules

| Path | Purpose |
|---|---|
| `lib/daemon.py` | Process entry point; owns Router and Controller |
| `lib/router.py` | MCP/JSON-RPC server; translates calls, enforces permissions |
| `lib/controller.py` | Workflow state, phase transitions, agent registry |
| `lib/iterate_workflow.py` | TDD loop implementation |
| `lib/experiment_workflow.py` | Experiment loop with eval gates |
| `lib/debug_workflow.py` | Systematic debugging workflow |
| `lib/orchestrate.py` | Task queue management, subagent dispatch |
| `lib/orchestrator.py` | Higher-level orchestration coordination |
| `lib/workflow_server.py` | MCP server for workflow state tools |
| `lib/workflow_base.py` | Base classes for workflow engines |
| `lib/permissions.py` | Permission evaluation logic |
| `lib/backends.py` | Backend process management |
| `lib/adversary_gate.py` | Adversarial test quality evaluation |
| `lib/review_gate.py` | Code review gate logic |
| `lib/prompt_builder.py` | Subagent prompt assembly |
| `lib/summarization_service.py` | Context summarization for compaction |
| `hooks/native-tool-blocking.py` | PreToolUse enforcement |
| `hooks/agent-dispatch.py` | Agent/Task interception and registration |
| `hooks/subagent-briefing.md` | Protocol injected into every subagent |
| `config/workflows/*.yaml` | Phase definitions, tool whitelists, transition rules |
| `config/permissions.yaml` | Role × phase permission matrix |
| `config/backends.json` | Backend process configuration |
| `skills/` | Invocable skill definitions (18 skills) |
| `agents/` | Agent role definitions (9 roles) |
| `commands/` | Command definitions (implement, spawn) |

---

## Telemetry

Every tool call routes through the MCP router, giving full observability over sessions.

| Metric | Detail |
|---|---|
| Token usage | Input/output tokens per session and day |
| Call counts | Broken down by tool and backend |
| Timing | Response latency per backend |
| Summarization | Compaction events and performance |

Data is stored locally and processed by `lib/jsonl_extractor.py` into the schema defined in `lib/telemetry_schema_v2.py`. Storage managed by `lib/stores/` (JSONL writer, compression, events). OpenTelemetry export is configured separately at `~/.claude/infra`.
