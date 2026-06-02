"""The iterate worker briefing must accurately describe the engine instance it
is bound to: real phases, correct call syntax, and the worker's own instance id.

A worker can only drive its engine-backed `iterate:<agent_id>` instance if the
briefing names that instance and uses the router's real param names -- otherwise
every transition is rejected and the worker stalls in test_writing.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from protocol_assembly import (
    WORKFLOW_PROTOCOLS,
    assemble_subagent_briefing,
)


class TestIterateProtocolText:
    def test_lists_real_engine_phases(self):
        text = WORKFLOW_PROTOCOLS["iterate"]
        for phase in ("test_writing", "implement", "test", "review", "complete"):
            assert phase in text

    def test_uses_router_param_names(self):
        text = WORKFLOW_PROTOCOLS["iterate"]
        # advance_phase takes workflow_id + target_phase (not the stale
        # "workflow"/"phase"); pass_checkpoint legitimately takes a "phase".
        assert "workflow_id" in text
        assert "target_phase" in text
        # the stale advance syntax keyed on bare "workflow" -- must be gone
        assert '"workflow":' not in text

    def test_mentions_checkpoint_before_review(self):
        text = WORKFLOW_PROTOCOLS["iterate"]
        assert "workflow_pass_checkpoint" in text

    def test_carries_instance_placeholder(self):
        # The raw protocol text is a template; the assembler fills __WF_ID__.
        assert "__WF_ID__" in WORKFLOW_PROTOCOLS["iterate"]


class TestIterateBriefingInterpolation:
    def test_interpolates_instance_id(self):
        briefing = assemble_subagent_briefing(
            "implementer",
            workflow_override="iterate",
            workflow_instance_id="iterate:sub-abc123",
        )
        assert "iterate:sub-abc123" in briefing
        assert "__WF_ID__" not in briefing

    def test_falls_back_to_workflow_name_without_instance(self):
        briefing = assemble_subagent_briefing(
            "implementer", workflow_override="iterate"
        )
        # No raw placeholder should survive even when no instance id is supplied.
        assert "__WF_ID__" not in briefing
        assert "iterate" in briefing
