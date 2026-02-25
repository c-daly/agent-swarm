---
name: pipeline
description: "Full pipeline from design doc through plan, manifest, parallel orchestration, to branch completion"
---

# Pipeline

Run the full implementation pipeline: design doc → plan → manifest → parallel orchestration → branch completion. Detects which stage to start from based on the input artifact, with checkpoints between each stage.

**Usage:** `/pipeline <path-to-artifact>`

---

## Stage Detection

Determine the starting stage from the input file:

| Pattern | Starting Stage |
|---------|---------------|
| `*-design.md` | Stage 1 (Planning) |
| `*-manifest.yaml` | Stage 3 (Orchestration) |
| `*.md` (other) | Stage 2 (Manifest Generation) |

If the file doesn't match any pattern, ask the user which stage to start from.

---

## Artifact Tracking

Maintain a tracking table throughout the pipeline. Print it at every checkpoint:

```
| Artifact     | Path                          | Status    |
|--------------|-------------------------------|-----------|
| Design doc   | docs/my-feature-design.md     | provided  |
| Plan         | docs/my-feature-plan.md       | pending   |
| Manifest     | docs/my-feature-manifest.yaml | pending   |
| Branches     | (per-task)                    | pending   |
```

Update status values as stages complete: `provided` → `generated` → `pending`.

---

## Stage 1: Planning

**Precondition:** Input is a design doc.

Invoke `superpowers:writing-plans` with the design doc path, adding these supplemental instructions to the prompt:

> When writing the plan, follow these conventions for parallel orchestration compatibility:
>
> 1. **Dependency markers**: For any task that must run after another, add a `**Depends on:** Task N` line immediately after the task description paragraph. Tasks without this marker are treated as independent and will run in parallel.
> 2. **Explicit file paths**: Every Do and Verify bullet must reference concrete file paths (e.g., `Create src/store.ts`, `Verify tests/store.test.ts passes`). The manifest generator infers directories from these paths.
> 3. **Independence by default**: Design tasks to be independent whenever possible. Only add dependencies when a task genuinely requires artifacts from another task.

**Output artifact:** `<design-basename>-plan.md` (produced by writing-plans)

### Checkpoint 1

Print the artifact tracking table with the plan marked as `generated`. Show a summary:

```
Plan generated: <path>
Tasks found: <count>
Dependencies: <count> task(s) have explicit dependencies
```

Ask the user: **Proceed to manifest generation / Edit the plan first / Stop**

---

## Stage 2: Manifest Generation

**Precondition:** Input is an implementation plan (`.md`).

Invoke `agent-swarm:plan-to-manifest` with the plan path.

**Output artifact:** `<plan-basename>-manifest.yaml` (produced by plan-to-manifest)

### Checkpoint 2

Print the artifact tracking table with the manifest marked as `generated`. Show a summary:

```
Manifest generated: <path>
Tasks: <count>
Dependencies: <dependency graph summary>
```

Ask the user: **Proceed to orchestration / Edit the manifest first / Stop**

---

## Stage 3: Orchestration

**Precondition:** Input is a manifest YAML (`.yaml`).

Invoke `agent-swarm:parallel-orchestrate` with the manifest path.

The orchestrator handles everything from here: spawning subagents, monitoring, merging, verification, and branch completion.

---

## Rules

1. **Always show checkpoints** between stages — never skip the user prompt.
2. **Never modify artifacts** produced by sub-skills — if edits are needed, tell the user and wait.
3. **Preserve the full artifact chain** — every artifact path must be tracked from start to finish.
4. **Resume from any stage** — if given a manifest directly, skip Stages 1 and 2.

## Required Sub-Skills

- `superpowers:writing-plans` (Stage 1)
- `agent-swarm:plan-to-manifest` (Stage 2)
- `agent-swarm:parallel-orchestrate` (Stage 3)
