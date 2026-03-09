# agent-swarm

Enforcement system for phase-gated, multi-agent workflows in Claude Code. Spawns specialized subagents (implementer, reviewer, architect, etc.) under a permission model that routes tool calls through a central MCP router, preventing code changes during planning and enforcing TDD discipline during implementation.

## Installation

```bash
claude plugin install agent-swarm
```

The plugin registers a `mcp-router` MCP server and installs `PreToolUse`, `SessionStart`, `SessionEnd`, and `PreCompact` hooks.

**Requirements:** Python 3.11+, `git`, `gh` CLI (for PR workflows)

---

## Workflows

### `/iterate` — TDD Loop

Use when you have a well-scoped task and want test-driven implementation with adversarial review gates.

```
test_writing → implement → test ── pass + confident ──→ review → done
                  ↑              └─ adversary fails ──→ implement
                  └─────────────── tests pass, weak suite → test_writing
```

| Phase | What happens | Tools |
|---|---|---|
| `test_writing` | Write tests first, cover edge cases | Read, Write, Edit, Glob, Grep, Bash |
| `implement` | Write minimal code to pass tests | Read, Write, Edit, Glob, Grep, Bash |
| `test` | Adversary runs tests, returns pass/fail + confidence verdict | Read, Glob, Grep, Bash (no Edit/Write) |
| `review` | Verify conventions, commit if clean | All |

**Gate logic:**
- All tests pass + high confidence → `review`
- Adversary-written tests fail → back to `implement`
- Tests pass but weak suite → back to `test_writing`
- Review clean → commit + done
- Review issues → back to `implement`

**Invoke:** `/iterate`

CLI: `python3 lib/iterate_workflow.py start "description" [max_iter]`

---

### Orchestrate — Parallel Task Dispatch

Use when a feature requires multiple independent subtasks that can be parallelized. The orchestrator breaks work into a task queue, spawns implementer subagents (each running their own iterate loop), and manages PRs per task group.

| Phase | What happens |
|---|---|
| `intake` | Gathers missing info (skipped if input is complete) |
| `design` | Plans architecture, documents decisions |
| `orchestrate` | Builds task queue, dispatches subagents, polls for completion |

Each `group` in the task queue maps to a PR. Stop condition: queue empty + no agents in flight + no unaddressed PR comments + clean working tree + all groups have PRs.

**Invoke:** Not directly user-invocable — triggered by the main agent when parallelism is warranted.

---

### `/develop` — Full SDLC Simulation

Use for significant features requiring full team simulation: requirements gathering, research, design review, TDD implementation, adversarial code review, and PM acceptance.

```
intake → research → design ─(checkpoint)→ branch
  → [test_writing → implement → test] → review ─(checkpoint)→ merge
  → acceptance ─(checkpoint)→ complete
```

| Role | Active phases |
|---|---|
| PM | intake, acceptance, complete |
| Researcher | research |
| Architect | design |
| Git-agent | branch, merge |
| Implementer | test_writing, implement, test |
| Reviewer | review |
| Debugger | on-demand during implement/test |

Checkpoints at `design`, `review`, and `acceptance` block phase advancement until the responsible agent passes them. Artifacts written to `.develop/`.

**Invoke:** `/develop`

---

## Permission System

Three layers enforce tool restrictions. Understanding this helps when debugging unexpected blocks.

**Layer 1 — `settings.json`:** Denies native `Read`, `Write`, `Edit`, `Glob`, `Grep`, `WebFetch`, `WebSearch` to the main agent, forcing file operations through the router.

**Layer 2 — PreToolUse hook (`hooks/native-tool-blocking.py`):** Runs on every tool call. Blocks everything except `mcp__router__*` / `mcp__plugin__*` tools, `Bash` calls prefixed with `mcp-call`, and system tools (`Task`, `SendMessage`, `AskUserQuestion`, `Skill`, etc.).

**Layer 3 — Router permissions (`config/permissions.yaml`):** Validates each tool call against a role × phase whitelist. A subagent in `test` phase cannot call `native__write_file`.

### Why subagents use `mcp-call`

Subagents spawned via `Task` can't reach MCP tools directly. They use a shell alias that routes through the router:

```bash
mcp-call native__read_file '{"file_path": "/path/to/file"}'
mcp-call native__bash '{"command": "pytest tests/"}'
```

MCP tool arguments are JSON; shell alias arguments are passed raw.

### Debugging

| Symptom | Likely cause | Fix |
|---|---|---|
| `[BLOCKED]` on native tool | Hook blocking | Use `mcp__router__native__*` equivalent |
| Permission denied from router | Wrong phase for that tool | Check `config/permissions.yaml` |
| Subagent can't write files | `native__write_file` globally restricted | Use `serena__create_text_file` or `serena__execute_shell_command` |

---

## Architecture Reference

```
Main Agent
    │
    ├─ mcp__router__* tools
    │       │
    │  MCP Router (lib/router.py)  ← TCP 127.0.0.1:7523
    │       │
    │  Controller / Daemon (lib/daemon.py)
    │  Manages: phase state, agent registry, task queue
    │
    └─ Task tool → Subagents
                       │
                  mcp-call alias → Router → Controller
```

| Path | Purpose |
|---|---|
| `lib/daemon.py` | Process entry point; owns Router and Controller |
| `lib/router.py` | MCP/JSON-RPC server; translates calls, enforces permissions |
| `lib/controller.py` | Workflow state, phase transitions, agent registry |
| `lib/orchestrate.py` | Task queue management, subagent dispatch, PR lifecycle |
| `lib/iterate_workflow.py` | TDD loop implementation |
| `lib/develop_workflow.py` | Full SDLC orchestration |
| `hooks/native-tool-blocking.py` | PreToolUse enforcement |
| `hooks/subagent-briefing.md` | Protocol injected into every subagent |
| `config/workflows/*.yaml` | Phase definitions, tool whitelists, transition rules |
| `config/permissions.yaml` | Role × phase permission matrix |

---

## Telemetry

Because every tool call — from both the main agent and subagents — routes through the MCP router, the router has full observability over everything that happens in a session. This is one of the core reasons the router exists.

What's captured per session and aggregated daily:

| Metric | Detail |
|---|---|
| Token usage | Input/output tokens per session and day |
| Call counts | Broken down by tool and backend |
| Timing | Response latency per backend |
| Summarization | Compaction events and performance |

Data is stored locally and processed by `lib/jsonl_extractor.py` into the schema defined in `lib/telemetry_schema_v2.py`. OpenTelemetry export is configured separately at `~/.claude/infra`.
