---
name: experiment-setup
description: Validate experiment tickets and produce missing artifacts (constraints, eval scripts) for /experiment.
user_invocable: true
---

# Experiment Setup

Prepare an experiment directory so it is ready for `/experiment`. Validates the ticket (goal.yaml), produces missing artifacts (constraints.yaml, eval scripts), and cross-checks consistency.

## Entry Points

Check the experiment directory to determine starting state:

1. **goal.yaml exists** → proceed to Step 1
2. **goal.yaml missing but a GitHub issue URL/number is provided** → extract issue fields, write goal.yaml (only works with experiment-compatible templates where fields map 1:1 to goal.yaml). Then proceed to Step 1.
3. **Neither** → help create goal.yaml interactively (if human) or stop with error (if agent). Then proceed to Step 1.

## Step 1 — Validate goal.yaml

Load goal.yaml and check:
- `objective` is present and non-empty
- `success_criteria` is present and non-empty
- Each criterion has `metric` and `threshold`
- `eval` defaults to `eval/` if absent

Use the harness `validate_goal()` function if available, or check manually.

**On validation failure:**
- Human-driven: report issues, prompt for correction
- Agent-driven: report issues and STOP

## Step 1.5 — Spec coverage check (if spec exists)

If goal.yaml has a `spec:` field pointing to a spec document, or if a spec file exists at a conventional location (e.g., `docs/*-spec.md`):

1. Parse the spec's component inventory (adapters, analysis, visualizations, app shell, glossary)
2. For each spec component, check if there is a matching task in goal.yaml
3. For any spec component with no corresponding task, **file the missing issue automatically** (using the project's issue template and labeling conventions) and add it to the task list
4. Report what was filed

The spec is the source of truth. If a component is in the spec, it gets built. Missing issues are a data entry problem, not a design decision — fix them and move on.

## Step 2 — Read project context

Determine the **component type** from the `target` path:
- `adapters/` → Adapter
- `analysis/quant/` → Quant
- `analysis/` → Analysis
- `frontend/` or `components/` → Visualization
- Ambiguous → reason from objective text
- Unknown → use generic fallback

If `target` is set, inspect the target repo:
- Read schemas/models used by this component type
- Note existing modules and naming conventions
- Identify imports the eval will need

## Step 3 — Generate constraints.yaml (if missing or incomplete)

If constraints.yaml does not exist or is missing sections, generate it.

### Interface contracts

Derive from the objective and project context:
- Module path (from `target` field)
- Function names and signatures the eval will test

```yaml
interface_contracts:
  module: <derived from target path>
  functions:
    - name: <function_name>
      signature: "<full signature>"
```

### Interactivity level

Ask (human) or default (agent → autonomous):
- **Fully interactive** → add escalation for every phase transition:
  ```yaml
  escalate_if:
    - condition: "Phase transition: read → plan"
      reason: routine_checkpoint
    - condition: "Phase transition: plan → work"
      reason: routine_checkpoint
    - condition: "Phase transition: work → eval"
      reason: routine_checkpoint
    - condition: "Phase transition: eval → journal"
      reason: routine_checkpoint
    - condition: "Phase transition: journal → decide"
      reason: routine_checkpoint
  ```
- **Fully autonomous** → no checkpoint escalations
- **Selective** → specific transitions only

### Preserve existing content

If constraints.yaml already exists, read it and only add missing sections. Never overwrite existing `do_not_do`, `escalate_if`, or `known_findings`.

**Human-driven:** show the constraints.yaml content and ask for approval before writing.
**Agent-driven:** write directly.

## Step 4 — Generate eval scripts (if missing or incomplete)

### If eval/ directory is empty or missing

Generate eval scripts based on component type.

**Always generate `eval/conftest.py`:**

```python
import os
import pytest


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Emit [METRIC] test_pass_rate for the experiment harness."""
    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))
    total = passed + failed
    rate = passed / total if total > 0 else 0.0
    print(f"\n[METRIC] test_pass_rate={rate:.4f}")
```

Add environment variable fixtures based on goal.yaml `environment` section:

```python
@pytest.fixture
def <var_name_lower>():
    val = os.environ.get("<VAR_NAME>")
    if not val:
        pytest.skip("<VAR_NAME> not set")
    return val
```

**Generate test file** (`eval/test_<component>.py`) using the thoroughness checklist for the component type:

**Adapter checklist:**
- Returns correctly shaped data matching the relevant schema
- Metadata fields populated (source, unit, frequency)
- Handles errors gracefully (descriptive exceptions)
- Handles missing/malformed upstream data
- Date filtering works (start, end, range)
- Values are valid (finite, correct types)
- Chronological ordering of results
- Empty result handling

**Analysis checklist:**
- Expected output given known input fixtures
- Edge cases handled
- Deterministic given same inputs
- Degrades gracefully when data is stale/missing

**Quant checklist:**
- Numerical accuracy against reference calculations
- Degenerate cases (singular matrices, insufficient data)
- Numerical stability
- Correct dimensionality

**Visualization checklist:**
- Renders without error
- Accepts correct data shape
- Interactive elements function
- Glossary tooltips present

**Generic fallback checklist:**
- Schema compliance
- Error handling
- Edge cases
- Determinism

Tests MUST import from the interface specified in constraints.yaml `interface_contracts`.

### If eval/ already has tests

Validate existing tests against the component-type checklist:
- **Human-driven:** report gaps and offer to generate additional test files
- **Agent-driven:** auto-generate missing test cases in NEW files (never modify existing)

Also validate conftest.py:
- Has `[METRIC] test_pass_rate` emission
- Has fixtures for all environment variables in goal.yaml

## Step 5 — Cross-check consistency

Verify all artifacts are consistent:

1. **Eval imports match constraints:** If constraints.yaml has `interface_contracts.module = X` and `functions[].name = Y`, then eval must `from X import Y`
2. **Success criteria match eval:** If goal.yaml has `metric: test_pass_rate`, eval conftest must emit `[METRIC] test_pass_rate=...`
3. **Environment variables:** All env vars in goal.yaml `environment` must have corresponding conftest fixtures
4. **Constraints match objective:** Interface contracts should align with what the objective describes

Report any inconsistencies found.

**Human-driven:** show results, ask if corrections should be made.
**Agent-driven:** auto-fix what can be fixed, report what cannot.

## Output

After completing all steps, summarize:

```
Experiment directory: <path>
  goal.yaml:        ✓ valid
  constraints.yaml: ✓ generated / ✓ exists (validated)
  eval/conftest.py: ✓ generated / ✓ exists (validated)
  eval/test_*.py:   ✓ generated / ✓ exists (N gaps found)
  consistency:      ✓ all checks passed / ⚠ N issues

Ready for /experiment: YES / NO (fix issues above first)
```
