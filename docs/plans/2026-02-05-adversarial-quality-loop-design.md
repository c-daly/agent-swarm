# Adversarial Quality Loop (AQL)

**Date:** 2026-02-05
**Status:** Design
**Related:** workflow engine, adversary gate, task tool, workflow config

---

## Feasibility Summary

- Fits current workflow engine model (phase definitions, transitions, gates) with a new
  workflow class, signal object, and configuration entry.
- Relies on existing subagent tooling and agent type templates; no new external services.
- Requires careful git worktree orchestration and cleanup to avoid repository corruption.
- Main risks are cost control (per-round budget) and calibration stability for critics.

---

## Overview

A GAN-inspired workflow where multiple agents compete and evaluate each other to produce
high-quality solutions. Three isolated roles create adversarial tension that drives
iterative improvement through classification, calibration, and accumulated learning.

**Deliverable:** Design document only (no implementation yet).

---

## Core Concept

Three roles with strict information isolation:

- **Actors (generators):** Configurable pool producing candidate solutions in parallel. Some
  genuine, some decoys at varying difficulty tiers. Decoys calibrate the critic.
- **Critic (discriminator):** Scores each candidate independently on a universal 0→1
  confidence spectrum. Blind to genuine vs. decoy. Does not suggest fixes — only classifies
  with evidence.
- **Judge (meta-evaluator):** Evaluates critic calibration (how well it distinguished real
  from decoy). Can disqualify candidates it deems dishonest/gaming (but does NOT select the
  winner — highest non-disqualified critic score wins). Updates the signal object. Produces
  synthesis guidance for next round. Decides convergence.

---

## Information Isolation

Each role is a separate subagent (Task tool) with scoped context:

**Role: Actor**
- Sees: Requirement spec, signal object (tracking scores), previous synthesis
- Does NOT see: Critic logic, judge calibration data, decoy types

**Role: Critic**
- Sees: Candidate code, signal object (tracking scores), evaluation criteria
- Does NOT see: Actor reasoning, genuine/decoy labels, judge data

**Role: Judge**
- Sees: All scores, genuine/decoy labels, full signal history
- Does NOT see: N/A — omniscient role with access to all data

---

## The Learning Mechanism

### Signal Object

A compact JSON object carries the quality signal between rounds:

```json
{
  "round": 3,
  "actors": {
    "actor_1": { "scores": [0.3, 0.45, 0.6] },
    "actor_2": { "scores": [0.1, 0.15] }
  },
  "critic_calibration": { "easy": 1.0, "medium": 0.8, "hard": 0.5 },
  "disqualified": ["actor_3"],
  "going_well": ["edge case handling improved", "no more mock abuse"],
  "going_poorly": ["test gaming pattern persists", "error paths untested"],
  "open_issues": ["test gaming pattern"]
}
```

Context stays trim: signal is compact JSON, actual work lives on the filesystem, and
prompt caching helps with repeated context across rounds.

### Parameter Adjustment Analog

In a GAN, gradient descent adjusts weights. In AQL, accumulated evidence context serves as
the analog:

- The signal object's tracking scores are passed to the critic as a Bayesian prior
- The critic factors historical performance trajectory into its confidence assessment
- Each round's evidence accumulates naturally — actors see their score trajectory, critic
  sees its calibration history
- No prompt rewriting needed — agents learn through in-context evidence

---

## Decoy Tiers (Calibration Mechanism)

Decoys keep the critic honest, like real samples keep a GAN discriminator honest:

| Tier   | Purpose              | What it produces                               |
|--------|----------------------|------------------------------------------------|
| Easy   | Baseline sanity      | Random/obviously wrong code                    |
| Medium | Defect detection     | Bugged but plausible solutions                 |
| Hard   | Sophistication test  | Subtly wrong, test-gaming solutions            |

Critic calibration per tier tells the judge how reliable the critic's scoring is.

---

## Loop Dynamics

### Round Sequence

1. **Generate phase:** Spawn N actor subagents in parallel (genuine + decoys per config)
2. **Evaluate phase:** Single critic scores each candidate sequentially (consistent scoring
   standard), 0→1 + evidence
3. **Judge phase:** Receives all scores + signal object. Updates signal. Decides: loop back
   or converge.

### Convergence

The loop terminates when ALL of:

- Best genuine candidate confidence ≥ configured threshold
- Critic calibration ≥ minimum reliability floor
- **OR** max iterations reached (hard stop)

### Stall Detection

If score trajectory delta < configured threshold across N rounds:

- **Escalate:** Surface state to user with judge's synthesis
- **Adjust:** Judge injects more dramatic guidance into signal object

---

## Configuration

Fits within the existing workflow YAML structure:

```yaml
name: aql
description: "GAN-inspired adversarial quality loop"
initial_phase: generate
terminal_phase: complete
max_agents: 8

# AQL-specific extensions
aql:
  pool:
    genuine_actors: 2
    decoys:
      easy: 1
      medium: 1
      hard: 0
  convergence:
    confidence_threshold: 0.8
    min_critic_calibration: 0.7
    max_iterations: 5
    stall_delta: 0.05
    stall_rounds: 2
  on_stall: escalate
  per_round_budget: 200000    # tokens per round
  verbosity: normal            # quiet | normal | verbose

phases:
  - name: generate
    allowed_tool_categories:
      - FILE_READ
      - FILE_WRITE
      - CODE_QUERY
      - CODE_EDIT
      - FILE_SEARCH
      - SHELL_SAFE
      - WEB_RESEARCH
      - SYMBOLIC        # Serena: find_symbol, find_referencing_symbols, etc.
      - CLAUDE_GUIDE    # Claude Code Guide for API/SDK/tool reference
    eligible_agents:
      - implementer
    checkpoint: false

  - name: evaluate
    allowed_tool_categories:
      - FILE_READ
      - CODE_QUERY
      - FILE_SEARCH
    blocked_tools:
      - native__write_file
      - native__bash
    eligible_agents:
      - adversary
    checkpoint: false

  - name: judge
    allowed_tool_categories:
      - FILE_READ
      - CODE_QUERY
    eligible_agents:
      - reviewer
    checkpoint: true
    gateway_conditions:
      - confidence_threshold_met

transitions:
  generate:
    - evaluate
  evaluate:
    - judge
  judge:
    - generate
    - complete
```

All parameters configurable: pool size (genuine + decoys independently), confidence
threshold, critic calibration floor, max iterations, stall detection, role instructions.

---

## Architecture & Integration

### New Files

| File                         | Purpose                                        |
|-----------------------------|------------------------------------------------|
| `lib/aql_workflow.py`       | AQL workflow engine extending WorkflowEngine   |
| `config/workflows/aql.yaml` | Default AQL configuration                       |
| `skills/aql/SKILL.md`       | Skill file for invoking the workflow            |
| `lib/aql_signal.py`         | Signal object data structure and management     |

### Reused Infrastructure

| Component           | How used                                           |
|--------------------|----------------------------------------------------|
| WorkflowEngine     | Base class for phase management, transitions       |
| workflow_client    | Signal object stored as workflow value             |
| gateway_conditions | Standard conditions + new confidence_threshold_met |
| controller         | Checkpoint enforcement                             |
| Task tool          | Spawn actor/critic/judge subagents                 |
| Agent types        | implementer (actors), adversary (critic), reviewer (judge) |

---

## Signal Object Lifecycle

1. Judge creates initial signal at round 0 (empty tracking scores)
2. Stored via `workflow_set_value("aql_signal", json)`
3. Passed to critic as context during evaluate phase
4. Judge reads scores, updates signal, writes back after each round
5. Available for post-mortem analysis after completion

---

## Subagent Mapping

**AQL Role: Genuine actor**
- Agent Type: implementer
- Modified Instructions: Standard implementation prompt

**AQL Role: Easy decoy**
- Agent Type: implementer
- Modified Instructions: "Produce random/unrelated code"

**AQL Role: Medium decoy**
- Agent Type: implementer
- Modified Instructions: "Produce solution with deliberate bugs"

**AQL Role: Hard decoy**
- Agent Type: implementer
- Modified Instructions: "Produce subtly wrong / test-gaming solution"

**AQL Role: Critic**
- Agent Type: adversary
- Modified Instructions: "Score 0-1 with evidence, consider tracking history"

**AQL Role: Judge**
- Agent Type: reviewer
- Modified Instructions: "Evaluate calibration, update signal, decide convergence"

---

## Resolved Design Decisions

- **Context compression:** Signal stays compact JSON; work lives on filesystem; prompt
  caching helps
- **Critic parallelism:** One critic, sequential scoring (consistent standard)
- **Decoy realism:** Creative freedom + real failure pattern templates (combination approach)
- **Cost management:** Per-round token budget (max cost = per_round * max_iterations)
- **Result selection:** Highest non-disqualified critic score wins; judge can disqualify but
  not select
- **Observability:** Configurable verbosity levels
  - Quiet = final result only
  - Normal = round summaries
  - Verbose = full signal + evidence each round
- **Multi-file solutions:** Git worktrees per actor. Full isolation. Winning worktree becomes
  the result. Temporary worktrees cleaned up after.
- **Decoy generation:** Dynamic, not from a catalog. Tier instructions guide the LLM:
  easy = unrelated, medium = subtle mutations, hard = creative deception. No static files
  to maintain.
- **Git integration:** AQL creates its own `aql/<task>` branch, runs the loop there. Winning
  result committed on that branch, ready to merge.

---

## Git Worktree Strategy

Each genuine actor and each decoy actor gets its own temporary git worktree branched from
the AQL branch:

```
main
└── aql/add-auth          # AQL branch (created at start)
    ├── aql/add-auth-actor-1   # genuine actor worktree
    ├── aql/add-auth-actor-2   # genuine actor worktree
    ├── aql/add-auth-decoy-1   # decoy worktree
    └── aql/add-auth-decoy-2   # decoy worktree
```

- Genuine actor worktrees persist across rounds — each actor iterates on their own
  solution
- Decoy worktrees are created fresh each round (calibration tools, not persistent)
- Critic evaluates code in each worktree (read-only)
- Judge updates signal object; all genuine actors continue in next round with their own
  code
- At convergence: highest non-disqualified genuine actor's worktree merged to AQL branch
- All worktrees cleaned up after loop completes
- Orphaned worktrees handled via explicit AQL cleanup command
- Final result lives on the `aql/<task>` branch

---

## Decoy Tier Instructions

No static catalog. Decoys are dynamically generated per tier:

**Tier: Easy**
- Instruction to decoy actor: "Produce something unrelated to the requirement"

**Tier: Medium**
- Instruction to decoy actor: "Take the genuine approach and introduce random subtle
  mutations (off-by-one, wrong comparison, missing null check)"

**Tier: Hard**
- Instruction to decoy actor: "Creatively produce a solution that appears correct but
  subtly misses the requirement or games the tests"

---

## Actor Diversity

Same prompt, natural LLM variance provides diversity. No forced strategy hints.

---

## Cross-round Continuity

Each genuine actor persists with their own worktree across rounds, iterating on their own
solution. Decoys are fresh each round.
