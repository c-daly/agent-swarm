---
name: delegate
description: Fable decomposes work into a tiered task manifest; haiku/sonnet workers execute in parallel worktrees; Fable re-enters only for escalations and integration.
user_invocable: true
---

# Delegate

You (Fable) are the coherence-holder. You touch the work exactly three
times — **decompose**, **escalate**, **integrate**. Everything in between
runs on cheaper models through the parallel-orchestrate machinery.

## Phases

```
decompose → dispatch → monitor ⇄ dispatch (retries / tier bumps)
                          ↓
                      escalate → dispatch
                          ↓
                      integrate → done
```

| Phase | Driver | Purpose |
|-------|--------|---------|
| decompose | Fable | Read codebase, write tiered manifest, start orchestrator |
| dispatch | mechanical | Spawn pending tasks at their tier |
| monitor | mechanical | Record completions; orchestrator handles retries/bumps |
| escalate | Fable (checkpoint) | Re-spec / split / absorb top-tier failures |
| integrate | Fable (checkpoint) | Merge, full suite, one coherence review |

## Start

```
workflow__workflow_start(workflow_id="delegate", task="<description>")
mkdir -p .delegate/
```

## 1. decompose (Fable touchpoint 1)

Read the code you are decomposing. Then write the manifest to
`.delegate/<slug>.yaml`.

**Decomposition contract — every task you emit MUST be:**

- **Self-contained.** The description inlines everything the worker
  needs: exact file paths, interfaces to implement, types to use,
  acceptance criteria. The worker never re-explores the codebase and
  never makes an architectural judgment.
- **Verifiable.** Tests define done (`min_tests` enforced by the TDD
  worker prompt).
- **Bounded.** Explicit `target_dir`/`test_dir`; no cross-cutting edits.

**Inverse rule (load-bearing):** anything coherence-bound stays with
you. If you cannot spec a task tightly enough for a cheap model, split
it further or keep it for yourself in integrate. Delegation is for leaf
work, never the architectural core.

**Tier rubric:**

| Tier | Use for | escalation |
|------|---------|------------|
| `model: haiku` | Mechanical, well-templated work (CRUD, data classes, boilerplate tests, format conversions) | `sonnet` |
| `model: sonnet` | Local reasoning within one module (algorithms, refactors with clear contracts) | `fable` (default) |

`escalation: fable` means: no re-dispatch — the first top-tier failure
routes to you in the escalate phase.

**Manifest format** — parallel-orchestrate schema plus the two tier fields:

```yaml
project: <slug>
base_branch: main
max_retries: 2
tasks:
  - name: 1-todo-store
    description: |
      <fully self-contained spec: files, interfaces, acceptance criteria>
    target_dir: src/store
    test_dir: tests/store
    min_tests: 10
    model: haiku
    escalation: sonnet
    depends_on: []
```

Then initialize and advance:

```bash
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py load .delegate/<slug>.yaml
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py start .delegate/<slug>.yaml <cwd>
```

```
workflow__advance_phase(wf_id, "dispatch")
```

## 2. dispatch

```bash
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py pending .delegate/<slug>.yaml --json
```

For each entry, register the worker, then spawn it with the **Agent
tool** (the spawn protocol — see `skills/spawn/SKILL.md`):

1. `reg = router__register_agent(agent_id="<task_name>-w<n>", agent_type="implementer", roles=["editor", "shell_full"])`
2. Spawn:
   - `subagent_type: "implementer"` — never a native type
     (`general-purpose`/`Explore`/`Plan`): native types have no router
     access and will flail
   - `model: <entry.model>` — **this is the tiering lever; never omit it**
   - `prompt`: `reg["briefing"] + "\n\n" +` the entry's `prompt` field
     verbatim — the briefing carries the worker's identity/caller-id
   - Spawn all pending tasks **in parallel** — worktrees isolate them
Record each spawn, then advance:

```bash
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py spawned .delegate/<slug>.yaml <task_name> <worker_id>
```

```
workflow__advance_phase(wf_id, "monitor")
```

## 3. monitor

As workers complete, record results:

```bash
# success
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py complete .delegate/<slug>.yaml <task_name>
# failure
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py complete .delegate/<slug>.yaml <task_name> "<error>"
```

Route on the printed `Result:`:

- `retrying` → advance to dispatch, re-spawn at the same tier
- `escalated` → advance to dispatch, re-spawn (the pending entry now
  carries the bumped tier — spawn with the new `model`)
- `failed` → advance to escalate
- all tasks `completed` → advance to integrate

Do not investigate failures yourself in this phase — that is what the
tier bump is for. You read code again only in escalate/integrate.

## 4. escalate (Fable touchpoint 2 — checkpoint)

Entered only when a task failed at its top tier. For each failed task,
pick one:

1. **Re-spec** — the task spec was ambiguous or wrong. Rewrite its
   manifest description, reset it, return to dispatch.
2. **Split** — too big for one worker. Replace it with smaller manifest
   tasks, return to dispatch.
3. **Absorb** — it was coherence-bound after all. Mark it yours; do it
   personally during integrate.

Then `workflow__advance_phase(wf_id, "dispatch")` (cases 1–2) or
`workflow__advance_phase(wf_id, "integrate")` (case 3 or nothing left).

## 5. integrate (Fable touchpoint 3 — checkpoint)

```bash
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py merge .delegate/<slug>.yaml <cwd>
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py verify .delegate/<slug>.yaml <cwd>
```

Then do **one coherence review of the merged diff** (`git diff
<base_branch>...HEAD`): naming drift across tasks, duplicated helpers,
interface mismatches, violated invariants. Fix what you find — this is
also where absorbed tasks get done. Do not re-review individual tasks;
workers already passed their test gates.

On suite failure, offer the standard three options: fix and retry /
rollback / continue anyway.

Finish:

```bash
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py summary .delegate/<slug>.yaml
python3 ${AGENT_SWARM_ROOT}/lib/orchestrator.py stop .delegate/<slug>.yaml <cwd>
```

```
workflow__advance_phase(wf_id, "done")
workflow__workflow_stop(workflow_id="delegate")
```

## Cost discipline

- Your tokens are the expensive ones. If you notice yourself reading
  worker diffs during monitor, stop — that is integrate's job, once.
- Prefer more, smaller haiku tasks over fewer, bigger sonnet tasks
  **only when** the spec-writing overhead stays small; a task whose
  description takes longer to write than the work itself should be
  absorbed or batched.
- Every escalation is recorded in orchestrator state
  (`escalated_from`); check `summary` output to calibrate your tier
  rubric over time.
