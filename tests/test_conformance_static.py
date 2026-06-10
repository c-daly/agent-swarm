"""Static workflow-governance conformance gate (#106).

Runs lib.conformance.analyze() across ALL workflow configs and asserts the
per-workflow governance matrix against a documented baseline. This is the
config-derived, no-LLM CI entrypoint: a workflow newly losing governance
(fail-open) fails CI, and a known gap getting fixed also fails -- forcing a
deliberate baseline update either way. Complements the live driver
(test_conformance_live.py), which exercises one workflow end-to-end.

Current known gaps are tracked in #106 (and surfaced by `python3 -m lib.conformance`):
  - pr_comment: no workflows['pr_comment'] block in permissions.yaml -> L1 skipped.
  - develop:    phase 'complete' declared in YAML but absent at L1.
  - experiment: phase 'done' declared in YAML but absent at L1.
  - debug:      in _KNOWN_WORKFLOWS but has no workflow YAML (phantom).
"""

import pytest

from lib.conformance import analyze

# Workflows whose declared phases are NOT fully governed at L1 today. Each is a
# known, tracked gap (#106). A workflow entering or leaving this set should fail
# the matrix test below, so the baseline is updated deliberately.
KNOWN_FAIL_OPEN = {"develop", "experiment", "pr_comment"}

# _KNOWN_WORKFLOWS entries that have no workflow YAML.
KNOWN_PHANTOM = {"debug"}

# Workflows that must stay fully governed -- a regression here is a real defect.
CORE_GOVERNED = {"simple", "iterate", "orchestrate", "delegate"}


@pytest.fixture(scope="module")
def conformance():
    """analyze() reads + regex-parses several config files; compute it once and
    share across the module's tests rather than re-running per test."""
    return analyze()


def test_fail_open_matrix_matches_baseline(conformance):
    """The set of fail-open workflows must equal the documented baseline."""
    fail_open = {r.name for r in conformance["workflows"] if r.fail_open}
    assert fail_open == KNOWN_FAIL_OPEN, (
        "workflow governance conformance changed -- "
        f"newly fail-open: {sorted(fail_open - KNOWN_FAIL_OPEN)}; "
        f"newly fixed (update KNOWN_FAIL_OPEN): {sorted(KNOWN_FAIL_OPEN - fail_open)}"
    )


def test_phantom_known_matches_baseline(conformance):
    """_KNOWN_WORKFLOWS entries without a YAML must equal the documented baseline."""
    phantom = set(conformance["phantom_known"])
    assert phantom == KNOWN_PHANTOM, (
        "phantom _KNOWN_WORKFLOWS changed -- "
        f"new: {sorted(phantom - KNOWN_PHANTOM)}; "
        f"gone (update KNOWN_PHANTOM): {sorted(KNOWN_PHANTOM - phantom)}"
    )


def test_core_workflows_stay_governed(conformance):
    """simple, iterate, orchestrate must remain fully governed (not fail-open)."""
    by_name = {r.name: r for r in conformance["workflows"]}
    for wf in CORE_GOVERNED:
        assert wf in by_name, f"{wf} workflow config is missing"
        assert not by_name[wf].fail_open, (
            f"{wf} regressed to fail-open: {by_name[wf].notes}"
        )
