# Delegate Workflow — Design

**Date:** 2026-06-10
**Status:** Approved (brainstorming dialogue, 2026-06-10)

A new agent-swarm workflow, `delegate`, that uses Fable 5 as the
coherence-holder — decomposition, escalation, integration — while discrete,
tightly-specified tasks execute on cheaper models (haiku/sonnet) through the
existing parallel-orchestrate machinery.

## Goals

- Fable 5 token spend is bounded to three touchpoints: **decompose**,
  **escalate**, **integrate**. Per-task work and per-task review never run
  on Fable.
- Each delegated task is specified tightly enough that a haiku/sonnet-tier
  model can complete it without re-exploring the codebase or making
  architectural judgments.
- Reuse, not rebuild: execution rides `lib/orchestrator.py` worktree-isolated
  TDD subagents; the manifest format is the existing parallel-orchestrate
  schema with two new per-task fields.

## Non-goals

- No per-phase model switching of the *main* session — the per-phase `model:`
  field in the workflow YAML is advisory metadata read by the skill, not
  enforced by the daemon (the loader ignores unknown keys).
- No replacement of iterate/orchestrate/pipeline; `delegate` is additive.

## Components

| Artifact | Status | Role |
|---|---|---|
| `config/workflows/delegate.yaml` | new | Phases, tool gating, transitions |
| `skills/delegate/SKILL.md` | new | Drives lifecycle; encodes decomposition contract and tiering rules |
| Manifest schema extension | new convention | Per-task `model:` and `escalation:` on the parallel-orchestrate manifest format |
| `lib/orchestrator.py` | patch | Pass per-task `model`/`escalation` through `pending --json` |

## Workflow YAML

```yaml
name: delegate
description: "Fable decomposes; cheap models execute; Fable escalates and integrates"
initial_phase: decompose
terminal_phase: done
max_agents: 8

phases:
  - name: decompose      # FABLE touchpoint 1: read codebase, write manifest
    model: fable         # advisory
    allowed_tool_categories: [FILE_READ, FILE_SEARCH, CODE_QUERY, FILE_WRITE, SHELL_SAFE]
    eligible_agents: [architect]
    checkpoint: false

  - name: dispatch       # spawn pending tasks at their manifest tier
    allowed_tool_categories: [SUBAGENT, SHELL_SAFE, FILE_READ]
    checkpoint: false

  - name: monitor        # poll orchestrator, record completions/failures
    allowed_tool_categories: [SHELL_SAFE, FILE_READ, SUBAGENT]
    checkpoint: false

  - name: escalate       # FABLE touchpoint 2: tasks that failed at top tier
    model: fable         # advisory
    allowed_tool_categories: [FILE_READ, FILE_SEARCH, CODE_QUERY, FILE_WRITE, SHELL_SAFE]
    checkpoint: true

  - name: integrate      # FABLE touchpoint 3: merge, full suite, coherence review
    model: fable         # advisory
    allowed_tool_categories: [FILE_READ, CODE_QUERY, SHELL_SAFE, FILE_WRITE]
    checkpoint: true

transitions:
  decompose: [dispatch]
  dispatch: [monitor]
  monitor: [dispatch, escalate, integrate]
  escalate: [dispatch, integrate]
  integrate: [done]
```

## Decomposition contract

The skill encodes hard rules for what Fable may emit as a delegable task.
Every manifest task must be:

- **Self-contained** — the description inlines everything the worker needs:
  file paths, interfaces to implement, types to use, acceptance criteria.
  The worker never re-explores the codebase and never makes an architectural
  judgment. This is what makes haiku-tier workers viable.
- **Verifiable** — tests define done (`min_tests`; existing TDD worker
  behavior unchanged).
- **Bounded** — explicit `target_dir`/`test_dir`; no cross-cutting edits.

**Inverse rule (load-bearing):** anything coherence-bound stays with Fable.
If a task cannot be specced tightly enough for a cheap model, Fable either
splits it further or keeps it for itself in `integrate`. Delegation is for
leaf work, never the architectural core.

### Tier assignment

During decompose, Fable tags each task:

```yaml
tasks:
  - name: 2-todo-store
    description: |
      <fully self-contained spec>
    target_dir: src/store
    test_dir: tests/store
    min_tests: 10
    model: haiku        # mechanical / well-templated work
    escalation: sonnet  # next tier on top-tier failure
```

- `model: haiku` — mechanical, well-templated work.
- `model: sonnet` — tasks needing local (not global) reasoning.
- `escalation` — the tier the task re-dispatches at after exhausting
  retries at its assigned tier. A task that also fails at its escalation
  tier routes to the escalate phase. `escalation: fable` skips the
  re-dispatch and routes the first top-tier failure straight to the
  escalate phase.

## Lifecycle

```
decompose (FABLE) → dispatch → monitor ⇄ dispatch (retries / tier bumps)
                                  ↓
                              escalate (FABLE, checkpoint) → dispatch
                                  ↓
                              integrate (FABLE, checkpoint) → done
```

1. **decompose** — Fable reads the codebase, writes the manifest, runs
   `orchestrator.py load` + `start` (worktree per task).
2. **dispatch** — for each pending task, spawn a worker via the Agent tool
   with `model: <task.model>`, passing the orchestrator-generated prompt
   verbatim; record with `orchestrator.py spawned`. Workers run in parallel.
3. **monitor** — record completions/failures via `orchestrator.py complete`.
   Failure at tier N: retry at tier N (manifest `max_retries`), then
   re-dispatch at the `escalation` tier. Every bump is recorded so the cost
   story is auditable.
4. **escalate** — entered only when a task fails at its top tier. Fable
   decides: re-spec, split, or absorb the task into its own integrate work.
   Checkpointed for user intervention.
5. **integrate** — `orchestrator.py merge` + `verify` (full suite), then one
   Fable coherence review of the merged diff. Not per-task review — workers
   already passed their own test gates.

## Error handling

- **Worker failure** — retry same tier → bump tier → escalate phase, as above.
- **Merge conflict** — lands in `integrate`; Fable resolves with the global
  view it already holds from decompose.
- **Post-merge suite failure** — the three existing parallel-orchestrate
  options (fix and retry / rollback / continue anyway), decided at the
  `integrate` checkpoint.

## Risks / verify at implementation

- **Worker spawn path.** `parallel-orchestrate` spawns native
  `general-purpose` agents, while `skills/spawn` warns native subagent types
  are router-blocked. Workers copy exactly what parallel-orchestrate does
  today; implementation step 1 verifies that path still works and accepts a
  `model` override.
- **Phase-gating reader.** `lib/daemon.py` only reads
  `name`/`checkpoint`/`transitions`; tool-category gating is enforced by the
  permission engine reading the same YAML. Confirm `delegate.yaml` is picked
  up by both (it was for the existing six workflows).

## Testing

- **Config test** — `delegate.yaml` loads via `load_workflow_configs`;
  initial/terminal phases exist; transitions reference defined phases
  (mirror existing workflow-config tests).
- **Orchestrator test** — fixture manifest with `model:`/`escalation:`
  fields round-trips through `pending --json`.
- **End-to-end smoke** — small demo manifest (pattern of
  `config/manifests/demo_data_structures.yaml`) against a throwaway project
  with haiku workers: confirms tier passthrough, one forced escalation, and
  a clean merge.
