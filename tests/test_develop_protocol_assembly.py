"""Tests for PM role, develop workflow, and new phase protocols."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import pytest
from protocol_assembly import (
    ROLE_PROTOCOLS,
    WORKFLOW_PROTOCOLS,
    PHASE_PROTOCOLS,
    get_role_protocol,
    get_workflow_protocol,
    assemble_subagent_briefing,
)


# =============================================================================
# PM Role
# =============================================================================

class TestPMRole:
    def test_pm_key_exists_in_role_protocols(self):
        assert "pm" in ROLE_PROTOCOLS

    def test_pm_protocol_mentions_stakeholder(self):
        text = ROLE_PROTOCOLS["pm"]
        assert "stakeholder" in text.lower()

    def test_pm_protocol_mentions_stories(self):
        text = ROLE_PROTOCOLS["pm"]
        assert "stories" in text.lower()

    def test_pm_protocol_mentions_acceptance(self):
        text = ROLE_PROTOCOLS["pm"]
        assert "acceptance" in text.lower()

    def test_get_role_protocol_pm_returns_nonempty(self):
        result = get_role_protocol("pm")
        assert isinstance(result, str)
        assert len(result) > 0


# =============================================================================
# Develop Workflow
# =============================================================================

class TestDevelopWorkflow:
    def test_develop_key_exists_in_workflow_protocols(self):
        assert "develop" in WORKFLOW_PROTOCOLS

    def test_develop_protocol_mentions_intake(self):
        text = WORKFLOW_PROTOCOLS["develop"]
        assert "intake" in text.lower()

    def test_develop_protocol_mentions_kickback(self):
        text = WORKFLOW_PROTOCOLS["develop"]
        assert "kickback" in text.lower()

    def test_develop_protocol_mentions_team_coordination(self):
        text = WORKFLOW_PROTOCOLS["develop"]
        # Must mention at least one of TeamCreate or SendMessage
        assert "teamcreate" in text.lower() or "sendmessage" in text.lower()

    def test_get_workflow_protocol_develop_returns_nonempty(self):
        result = get_workflow_protocol("develop")
        assert isinstance(result, str)
        assert len(result) > 0


# =============================================================================
# New Phases for Develop Workflow
# =============================================================================

class TestDevelopPhases:
    def test_research_key_exists(self):
        assert "research" in PHASE_PROTOCOLS

    def test_research_mentions_context_or_investigate(self):
        text = PHASE_PROTOCOLS["research"]
        assert "context" in text.lower() or "investigate" in text.lower()

    def test_branch_key_exists(self):
        assert "branch" in PHASE_PROTOCOLS

    def test_branch_mentions_feature_branch(self):
        text = PHASE_PROTOCOLS["branch"]
        assert "feature branch" in text.lower() or "branch" in text.lower()

    def test_merge_key_exists(self):
        assert "merge" in PHASE_PROTOCOLS

    def test_merge_mentions_pr_or_merge_conflicts(self):
        text = PHASE_PROTOCOLS["merge"]
        assert "pr" in text.lower() or "merge conflict" in text.lower()

    def test_acceptance_key_exists(self):
        assert "acceptance" in PHASE_PROTOCOLS

    def test_acceptance_mentions_user_stories(self):
        text = PHASE_PROTOCOLS["acceptance"]
        assert "user stories" in text.lower() or "acceptance criteria" in text.lower()

    # Existing phases still present
    @pytest.mark.parametrize("phase", ["intake", "design", "test", "review", "implement"])
    def test_existing_phases_still_present(self, phase):
        assert phase in PHASE_PROTOCOLS


# =============================================================================
# Briefing Assembly Integration
# =============================================================================

class TestBriefingAssembly:
    def test_pm_develop_intake_briefing_contains_pm_role(self):
        briefing = assemble_subagent_briefing(
            "pm", workflow_override="develop", phase_override="intake"
        )
        pm_text = ROLE_PROTOCOLS["pm"]
        assert pm_text in briefing

    def test_pm_develop_intake_briefing_contains_develop_workflow(self):
        briefing = assemble_subagent_briefing(
            "pm", workflow_override="develop", phase_override="intake"
        )
        develop_text = WORKFLOW_PROTOCOLS["develop"]
        assert develop_text in briefing

    def test_pm_develop_intake_briefing_contains_intake_phase(self):
        briefing = assemble_subagent_briefing(
            "pm", workflow_override="develop", phase_override="intake"
        )
        intake_text = PHASE_PROTOCOLS["intake"]
        assert intake_text in briefing

    def test_reviewer_develop_review_briefing_contains_reviewer_role(self):
        briefing = assemble_subagent_briefing(
            "reviewer", workflow_override="develop", phase_override="review"
        )
        reviewer_text = ROLE_PROTOCOLS["reviewer"]
        assert reviewer_text in briefing

    def test_reviewer_develop_review_briefing_contains_develop_workflow(self):
        briefing = assemble_subagent_briefing(
            "reviewer", workflow_override="develop", phase_override="review"
        )
        develop_text = WORKFLOW_PROTOCOLS["develop"]
        assert develop_text in briefing

    def test_implementer_develop_implement_contains_implementer_role(self):
        briefing = assemble_subagent_briefing(
            "implementer", workflow_override="develop", phase_override="implement"
        )
        impl_text = ROLE_PROTOCOLS["implementer"]
        assert impl_text in briefing
