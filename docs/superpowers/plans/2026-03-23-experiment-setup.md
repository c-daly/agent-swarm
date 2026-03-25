# `/experiment-setup` Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `/experiment-setup` skill that validates experiment directories and produces missing artifacts (constraints.yaml, eval scripts) before running `/experiment`.

**Architecture:** The skill is a single SKILL.md file containing the protocol for the LLM to follow. Two harness changes support it: widening `escalate_if` to accept dicts, and adding a `validate_goal()` function. No new Python modules — the skill instructs the LLM directly.

**Tech Stack:** Python (harness changes), YAML (skill definition), pytest (tests)

---

### Task 1: Widen `escalate_if` type in Constraints dataclass

**Files:**
- Modify: `lib/experiment_harness.py:83-108`
- Test: `tests/test_experiment_harness.py`

- [ ] **Step 1: Write failing test for dict escalate_if entries**

In `tests/test_experiment_harness.py`, add to the `TestLoadConstraints` class:

```python
def test_loads_dict_escalate_if(self, tmp_experiment):
    (tmp_experiment / "constraints.yaml").write_text(yaml.dump({
        "escalate_if": [
            {"condition": "Phase transition: plan → work", "reason": "routine_checkpoint"},
            "Cannot load weights",
        ],
    }))
    c = load_constraints(tmp_experiment)
    assert len(c.escalate_if) == 2
    assert c.escalate_if[0] == {"condition": "Phase transition: plan → work", "reason": "routine_checkpoint"}
    assert c.escalate_if[1] == "Cannot load weights"
```

- [ ] **Step 2: Run test to verify it passes (it should already pass)**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && python -m pytest tests/test_experiment_harness.py::TestLoadConstraints::test_loads_dict_escalate_if -v`

The current code uses `raw.get("escalate_if", [])` which passes through any list content. The type annotation is `list[str]` but Python doesn't enforce it at runtime. This test should pass — confirming that the data loading works already and we only need to update the type hint.

- [ ] **Step 3: Update type annotation**

In `lib/experiment_harness.py:89`, change:

```python
# Before
escalate_if: list[str] = field(default_factory=list)
# After
escalate_if: list = field(default_factory=list)
```

- [ ] **Step 4: Add helper to normalize escalate_if entries**

Add after the `Constraints` class (after line 91):

```python
def normalize_escalation(entry) -> dict:
    """Normalize an escalate_if entry to {condition, reason} dict."""
    if isinstance(entry, str):
        return {"condition": entry, "reason": "error"}
    if isinstance(entry, dict):
        return {"condition": entry.get("condition", ""), "reason": entry.get("reason", "error")}
    return {"condition": str(entry), "reason": "error"}
```

- [ ] **Step 5: Write test for normalize_escalation**

```python
class TestNormalizeEscalation:
    def test_string_entry(self):
        result = normalize_escalation("Cannot load weights")
        assert result == {"condition": "Cannot load weights", "reason": "error"}

    def test_dict_entry(self):
        result = normalize_escalation({"condition": "Phase transition", "reason": "routine_checkpoint"})
        assert result == {"condition": "Phase transition", "reason": "routine_checkpoint"}

    def test_dict_missing_reason_defaults_to_error(self):
        result = normalize_escalation({"condition": "Something bad"})
        assert result == {"condition": "Something bad", "reason": "error"}
```

- [ ] **Step 6: Run all tests to verify**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && python -m pytest tests/test_experiment_harness.py -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
cd /Users/cdaly/.claude/plugins/agent-swarm
git add lib/experiment_harness.py tests/test_experiment_harness.py
git commit -m "feat: widen escalate_if to accept dict entries with condition/reason

Backward-compatible: string entries still work, normalized to reason='error'.
Dict entries support {condition, reason} for routine checkpoints vs errors.
Closes #82 (partial — type widening only, escalation checking separate)"
```

---

### Task 2: Add `validate_goal()` function to harness

**Files:**
- Modify: `lib/experiment_harness.py`
- Test: `tests/test_experiment_harness.py`

- [ ] **Step 1: Write failing tests for goal validation**

Add to `tests/test_experiment_harness.py`:

```python
from experiment_harness import validate_goal

class TestValidateGoal:
    def test_valid_goal_returns_empty_list(self, tmp_experiment):
        write_goal(tmp_experiment, {
            "objective": "Build a thing",
            "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
        })
        goal = load_goal(tmp_experiment)
        errors = validate_goal(goal)
        assert errors == []

    def test_empty_objective(self, tmp_experiment):
        write_goal(tmp_experiment, {
            "objective": "",
            "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0}],
        })
        goal = load_goal(tmp_experiment)
        errors = validate_goal(goal)
        assert any("objective" in e.lower() for e in errors)

    def test_missing_success_criteria(self, tmp_experiment):
        write_goal(tmp_experiment, {
            "objective": "Build a thing",
            "success_criteria": [],
        })
        goal = load_goal(tmp_experiment)
        errors = validate_goal(goal)
        assert any("success_criteria" in e.lower() for e in errors)

    def test_criterion_missing_metric(self, tmp_experiment):
        write_goal(tmp_experiment, {
            "objective": "Build a thing",
            "success_criteria": [{"threshold": 1.0}],
        })
        goal = load_goal(tmp_experiment)
        errors = validate_goal(goal)
        assert any("metric" in e.lower() for e in errors)

    def test_criterion_missing_threshold(self, tmp_experiment):
        write_goal(tmp_experiment, {
            "objective": "Build a thing",
            "success_criteria": [{"metric": "test_pass_rate"}],
        })
        goal = load_goal(tmp_experiment)
        errors = validate_goal(goal)
        assert any("threshold" in e.lower() for e in errors)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && python -m pytest tests/test_experiment_harness.py::TestValidateGoal -v`
Expected: ImportError — `validate_goal` not found

- [ ] **Step 3: Implement validate_goal**

Add after `load_goal()` in `lib/experiment_harness.py`:

```python
def validate_goal(goal: Goal) -> list[str]:
    """Validate a Goal object. Returns list of error strings (empty = valid)."""
    errors = []
    if not goal.objective or not goal.objective.strip():
        errors.append("objective is empty or missing")
    if not goal.success_criteria:
        errors.append("success_criteria is empty or missing")
    for i, c in enumerate(goal.success_criteria):
        if "metric" not in c:
            errors.append(f"success_criteria[{i}] missing 'metric'")
        if "threshold" not in c:
            errors.append(f"success_criteria[{i}] missing 'threshold'")
    return errors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && python -m pytest tests/test_experiment_harness.py::TestValidateGoal -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
cd /Users/cdaly/.claude/plugins/agent-swarm
git add lib/experiment_harness.py tests/test_experiment_harness.py
git commit -m "feat: add validate_goal() for experiment setup validation"
```

---

### Task 3: Write the SKILL.md for `/experiment-setup`

**Files:**
- Create: `skills/experiment-setup/SKILL.md`

- [ ] **Step 1: Create the skill file**

```bash
mkdir -p /Users/cdaly/.claude/plugins/agent-swarm/skills/experiment-setup
```

Write `skills/experiment-setup/SKILL.md`:

```markdown
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

After completing all steps, summarize what was produced:

```
Experiment directory: <path>
  goal.yaml:        ✓ valid
  constraints.yaml: ✓ generated / ✓ exists (validated)
  eval/conftest.py: ✓ generated / ✓ exists (validated)
  eval/test_*.py:   ✓ generated / ✓ exists (N gaps found)
  consistency:      ✓ all checks passed / ⚠ N issues

Ready for /experiment: YES / NO (fix issues above first)
```
```

- [ ] **Step 2: Verify skill frontmatter is valid**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && python -c "import yaml; d = list(yaml.safe_load_all(open('skills/experiment-setup/SKILL.md').read().split('---')[1])); print(d)"`

- [ ] **Step 3: Commit**

```bash
cd /Users/cdaly/.claude/plugins/agent-swarm
git add skills/experiment-setup/SKILL.md
git commit -m "feat: add /experiment-setup skill for experiment directory preparation"
```

---

### Task 4: Register the skill in the plugin manifest

**Files:**
- Modify: `skills.yaml` or plugin config (wherever skills are registered)

- [ ] **Step 1: Find the skill registration mechanism**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && grep -r "experiment" skills.yaml manifest.yaml plugin.yaml package.json 2>/dev/null || find . -name "*.yaml" -path "*/config/*" | head -10`

Skills in agent-swarm are auto-discovered from `skills/*/SKILL.md` via the plugin system. Verify the new skill appears.

- [ ] **Step 2: Verify skill is discoverable**

Run: `ls /Users/cdaly/.claude/plugins/agent-swarm/skills/experiment-setup/SKILL.md`

If the plugin auto-discovers from the skills directory, no registration is needed.

- [ ] **Step 3: Commit (if registration file was modified)**

Only if a manifest or config file needed updating.

---

### Task 5: Fix the fred_adapter experiment using the new skill

This is the integration test — run `/experiment-setup` against the existing fred_adapter experiment to verify it works end-to-end.

**Files:**
- Modify: `~/projects/agora/experiments/fred_adapter/eval/conftest.py`
- Modify: `~/projects/agora/experiments/fred_adapter/eval/test_fred_adapter.py`
- Create: `~/projects/agora/experiments/fred_adapter/constraints.yaml`

- [ ] **Step 1: Create constraints.yaml for fred_adapter**

Write `~/projects/agora/experiments/fred_adapter/constraints.yaml`:

```yaml
interface_contracts:
  module: agora.adapters.fred_adapter
  functions:
    - name: fetch_series
      signature: "(series_id: str, api_key: str, *, start_date: date | None = None, end_date: date | None = None) -> list[TimeSeries]"

do_not_do:
  - "Do not hardcode API keys"

escalate_if: []

known_findings: []
```

- [ ] **Step 2: Update conftest.py with test_pass_rate emission**

Write `~/projects/agora/experiments/fred_adapter/eval/conftest.py`:

```python
import os
import pytest


@pytest.fixture
def fred_api_key():
    key = os.environ.get("FRED_API_KEY")
    if not key:
        pytest.skip("FRED_API_KEY not set")
    return key


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Emit [METRIC] test_pass_rate for the experiment harness."""
    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))
    total = passed + failed
    rate = passed / total if total > 0 else 0.0
    print(f"\n[METRIC] test_pass_rate={rate:.4f}")
```

- [ ] **Step 3: Strengthen the eval tests**

Rewrite `~/projects/agora/experiments/fred_adapter/eval/test_fred_adapter.py` addressing the gaps we identified:

```python
"""Eval tests for the FRED adapter."""

import math
from datetime import date

import pytest

from agora.adapters.fred_adapter import fetch_series
from agora.schemas import TimeSeries, TimeSeriesMetadata


class TestSchemaCompliance:
    """Returns correctly shaped TimeSeries objects."""

    def test_returns_list_of_timeseries(self, fred_api_key):
        result = fetch_series("GDP", fred_api_key)
        assert isinstance(result, list)
        assert len(result) > 0
        for item in result:
            assert isinstance(item, TimeSeries)

    def test_timeseries_fields(self, fred_api_key):
        result = fetch_series("GDP", fred_api_key)
        item = result[0]
        assert isinstance(item.date, date)
        assert isinstance(item.value, float)
        assert isinstance(item.metadata, TimeSeriesMetadata)

    def test_metadata_source_is_fred(self, fred_api_key):
        result = fetch_series("GDP", fred_api_key)
        for item in result:
            assert item.metadata.source == "FRED"

    def test_metadata_fields_populated(self, fred_api_key):
        """Metadata should include unit and frequency when available."""
        result = fetch_series("GDP", fred_api_key)
        item = result[0]
        assert item.metadata.unit is not None or item.metadata.frequency is not None

    def test_values_are_finite(self, fred_api_key):
        result = fetch_series("GDP", fred_api_key)
        for item in result:
            assert math.isfinite(item.value)

    def test_results_in_chronological_order(self, fred_api_key):
        result = fetch_series("GDP", fred_api_key)
        dates = [item.date for item in result]
        assert dates == sorted(dates)


class TestDateFiltering:
    """Date range filtering."""

    def test_start_date_filter(self, fred_api_key):
        start = date(2020, 1, 1)
        result = fetch_series("GDP", fred_api_key, start_date=start)
        assert len(result) > 0
        for item in result:
            assert item.date >= start

    def test_end_date_filter(self, fred_api_key):
        end = date(2020, 12, 31)
        result = fetch_series("GDP", fred_api_key, end_date=end)
        assert len(result) > 0
        for item in result:
            assert item.date <= end

    def test_date_range(self, fred_api_key):
        start = date(2019, 1, 1)
        end = date(2020, 12, 31)
        result = fetch_series("GDP", fred_api_key, start_date=start, end_date=end)
        assert len(result) > 0
        for item in result:
            assert start <= item.date <= end

    def test_empty_date_range(self, fred_api_key):
        """Valid series but no data in range — should return empty list, not error."""
        result = fetch_series("GDP", fred_api_key, start_date=date(1800, 1, 1), end_date=date(1800, 12, 31))
        assert isinstance(result, list)
        assert len(result) == 0


class TestErrorHandling:
    """Graceful handling of bad inputs."""

    def test_invalid_series_raises_with_message(self, fred_api_key):
        with pytest.raises(Exception, match=r".+"):
            fetch_series("DEFINITELY_NOT_A_REAL_SERIES_XYZ123", fred_api_key)

    def test_invalid_api_key_raises_with_message(self):
        with pytest.raises(Exception, match=r".+"):
            fetch_series("GDP", "not_a_valid_key")


class TestMissingValues:
    """FRED missing observations must be skipped."""

    def test_no_missing_values_in_output(self, fred_api_key):
        result = fetch_series("DFF", fred_api_key, start_date=date(2020, 1, 1), end_date=date(2020, 3, 31))
        for item in result:
            assert isinstance(item.value, float)
            assert math.isfinite(item.value)
```

- [ ] **Step 4: Commit the agora changes**

```bash
cd ~/projects/agora
git add experiments/fred_adapter/
git commit -m "feat: strengthen fred_adapter eval with constraints and test_pass_rate metric

- Add constraints.yaml with interface contracts
- Add test_pass_rate emission in conftest.py
- Strengthen tests: metadata population, chronological order, empty range, stricter error matching"
```

---

### Task 6: Run verification

- [ ] **Step 1: Run harness tests**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && python -m pytest tests/test_experiment_harness.py -v`
Expected: All pass

- [ ] **Step 2: Run full agent-swarm test suite**

Run: `cd /Users/cdaly/.claude/plugins/agent-swarm && python -m pytest tests/ -v --timeout=30`
Expected: All pass (or only pre-existing failures)

- [ ] **Step 3: Verify skill file is well-formed**

Run: `head -5 /Users/cdaly/.claude/plugins/agent-swarm/skills/experiment-setup/SKILL.md`
Expected: Shows valid YAML frontmatter with name, description, user_invocable

- [ ] **Step 4: Verify agora experiment directory is complete**

```bash
ls -la ~/projects/agora/experiments/fred_adapter/
ls -la ~/projects/agora/experiments/fred_adapter/eval/
```

Expected: goal.yaml, constraints.yaml, eval/conftest.py, eval/test_fred_adapter.py all present.
