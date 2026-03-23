# `/experiment-setup` Skill Design

## Purpose

Ensure an experiment directory is ready to run `/experiment`. Given a directory with a `goal.yaml`, the skill validates the ticket and produces any missing artifacts: `constraints.yaml` and eval scripts. It also cross-checks consistency across all artifacts.

## Entry Points

1. **goal.yaml exists:** Validate it, produce missing artifacts, check consistency.
2. **GitHub issue exists but no goal.yaml:** Extract issue fields and write goal.yaml. Only works with experiment-compatible issue templates (fields map 1:1 to goal.yaml). Templates with different field shapes (e.g., LOGOS templates using `acceptance` instead of `success_criteria`) are not supported — the skill reports the mismatch and stops.
3. **Neither exists:** Interactive (human) or autonomous (agent) creation of goal.yaml, then proceed as above.

## Artifacts Produced

### constraints.yaml

Complete example:

```yaml
interface_contracts:
  module: agora.adapters.fred_adapter
  functions:
    - name: fetch_series
      signature: "(series_id: str, api_key: str, *, start_date: date | None = None, end_date: date | None = None) -> list[TimeSeries]"

do_not_do:
  - "Do not hardcode API keys"

escalate_if:
  - condition: "Phase transition: plan → work"
    reason: routine_checkpoint
  - condition: "Cannot reach FRED API after retries"
    reason: error

known_findings: []
```

**Interface contracts** are a free-form YAML section read by the agent as context during the `read` phase. The harness does not parse or enforce them — they are documentation for the agent, telling it what interface the eval expects. No harness dataclass change is needed for this field.

**`escalate_if`** supports two formats (backward-compatible):
- **String:** `"Cannot load weights"` — treated as `reason: error`
- **Dict:** `{condition: str, reason: str}` — explicit reason

`reason` is an open string. Known values:
- `routine_checkpoint` — expected pause for human review, not an error
- `error` — something went wrong

Custom values are allowed; unknown reasons are displayed as-is to the user.

**Interactivity via escalation constraints:**
- **Fully interactive:** Escalation entries for every phase transition
- **Fully autonomous:** No checkpoint escalations
- **Selective:** Escalation entries for specific transitions only

### eval scripts

Pytest tests in `eval/` that verify the objective is met. The skill selects a thoroughness checklist based on component type:

**Adapters:**
- Returns correctly shaped data matching the relevant schema
- Metadata fields populated (source, unit, frequency where applicable)
- Handles API/data source errors gracefully (descriptive exceptions)
- Handles missing/malformed upstream data (skip or degrade, never crash)
- Date filtering works (start, end, range)
- Values are valid (finite, correct types)
- Chronological ordering of results
- Empty result handling (valid query, no data in range)

**Analysis modules:**
- Produces expected output given known input fixtures
- Edge cases handled
- Scores/outputs are deterministic given the same inputs
- Degrades gracefully when a data source is stale or missing

**Quantitative modules:**
- Numerical accuracy against known reference calculations
- Handles degenerate cases (singular matrices, insufficient data)
- Appropriate numerical stability techniques
- Correct dimensionality of outputs

**Visualizations:**
- Renders without error
- Accepts the data shape from its analysis module
- Interactive elements function
- Glossary tooltips present on all labeled metrics

**Fallback:** If component type cannot be determined from the target path or objective, use a generic checklist: schema compliance, error handling, edge cases, and determinism.

**Component type detection:** Inferred from the target path by substring matching (`adapters/` → Adapter, `analysis/quant/` → Quant, `analysis/` → Analysis, `frontend/` or `components/` → Visualization). If the path is ambiguous, fall back to LLM reasoning over the objective text. If still unclear, use the generic fallback.

### conftest.py

- Fixtures for environment variables (API keys, etc.) with `pytest.skip` when missing
- Fixtures for test data where applicable
- A pytest plugin or session-scoped fixture that emits `[METRIC] test_pass_rate=<passed/total>` at session end, so the harness can parse it via the standard `[METRIC]` format
- If `conftest.py` already exists, validate it covers needed fixtures and report gaps (same treatment as existing test scripts)

## goal.yaml Validation

Step 1 validates that goal.yaml is well-formed:
- `objective` is present and non-empty
- `success_criteria` is present and non-empty
- Each criterion has `metric` and `threshold`
- `eval` defaults to `eval/` if absent (consistent with harness behavior)

On failure: **human-driven** — report issues and prompt for correction. **Agent-driven** — report issues and stop (do not guess at corrections).

## Process

### Step 1 — Read and validate goal.yaml
Parse objective, target, context, success_criteria, environment. Validate per the rules above. Determine component type from target path or objective.

### Step 2 — Read project context
Inspect the target repo: schemas, existing modules, naming conventions. The eval must import from real paths and use real types.

### Step 3 — Generate constraints.yaml (if missing or incomplete)
- Derive interface contracts from the objective and project context — module path, function names, signature
- Determine interactivity level:
  - **Human-driven:** Ask whether fully autonomous, fully interactive, or specific checkpoints
  - **Agent-driven:** Default to autonomous (no checkpoint escalations)
- Preserve existing constraints; only add what's missing

### Step 4 — Generate eval scripts (if missing or incomplete)
- Select thoroughness checklist based on component type
- Write tests that import from the interface specified in constraints
- Tests verify the behaviors described in the objective
- **If `eval/` already has tests:**
  - Validate against the checklist and identify gaps
  - **Human-driven:** Report gaps and offer to fill them
  - **Agent-driven:** Auto-generate missing test cases in new test files (never modify existing files)
- Generate or validate `conftest.py` with appropriate fixtures

### Step 5 — Cross-check consistency
Verify and report:
- Eval imports match constraint interface contracts
- Success criteria in goal.yaml correspond to what the eval actually measures
- Environment variables in goal.yaml are handled in conftest.py
- Constraints interface matches what the objective describes

**Human-driven mode:** Show planned output at each step, ask for approval before writing.
**Agent-driven mode:** Run straight through, report results at the end.

## Harness Changes

### 1. `escalate_if` type widening

`escalate_if` in the `Constraints` dataclass changes from `list[str]` to `list[str | dict]`:

```python
escalate_if: list[str | dict] = field(default_factory=list)
```

Dict entries: `{"condition": str, "reason": str}`. String entries remain valid (backward-compatible, treated as `reason: "error"`).

### 2. Escalation checking in decide phase

**Prerequisite:** The decide phase in `experiment_workflow.py` does not currently check `escalate_if` conditions. This must be implemented before or alongside this skill. The escalation check should:
- Read `Constraints.escalate_if` entries
- Match conditions against the current experiment state (the agent self-reports whether a condition is met)
- On match: stop the workflow, surface the condition and reason to the user
- `routine_checkpoint` entries surface as informational pauses, not errors

### 3. test_pass_rate synthesis

The harness's `run_eval()` parses `[METRIC] key=value` from eval output and pytest pass/fail counts, but does not synthesize `test_pass_rate` from the counts. Two options:
- **Option A (eval-side):** The setup skill generates a conftest.py pytest plugin that emits `[METRIC] test_pass_rate=<ratio>` at session end. No harness change needed.
- **Option B (harness-side):** The harness synthesizes `test_pass_rate` from parsed pytest counts automatically.

**Recommendation:** Option A — keep the harness simple, let the eval be explicit about what it reports.

## Skill Metadata

```yaml
---
name: experiment-setup
description: Validate experiment tickets and produce missing artifacts (constraints, eval scripts) for /experiment.
user_invocable: true
---
```

Single-shot skill (no phases, no workflow config). Lives at `skills/experiment-setup/SKILL.md`.

## Interaction with Other Skills

- **`/ticket-gen`** (future): Produces goal.yaml. `/experiment-setup` runs after.
- **`/experiment`**: Consumes the experiment directory. `/experiment-setup` runs before.
- Compose: `/ticket-gen` → `/experiment-setup` → `/experiment`
