"""Tests for develop workflow state machine.

Covers: start/stop, phase queries, forward transitions, invalid
transitions, checkpoint enforcement, kickbacks, kickback counters,
and subtask scheduling.
"""
import pytest

from develop_workflow import (
    DevelopWorkflowError,
    start_develop,
    stop,
    get_phase,
    is_active,
    advance_phase,
    pass_checkpoint,
    record_kickback,
    add_subtask,
    get_eligible_subtasks,
    complete_subtask,
    _force_phase,
)


# ============================================================================
# TestStart
# ============================================================================
class TestStart:
    """Tests for start_develop()."""

    def test_start_returns_state_dict(self):
        state = start_develop("test task")
        assert isinstance(state, dict)

    def test_start_sets_active_true(self):
        state = start_develop("test task")
        assert state["active"] is True

    def test_start_sets_phase_intake(self):
        state = start_develop("test task")
        assert state["phase"] == "intake"

    def test_start_sets_task(self):
        state = start_develop("test task")
        assert state["task"] == "test task"

    def test_start_default_max_review_retries(self):
        state = start_develop("t")
        assert state["max_review_retries"] == 0

    def test_start_default_max_agent_respawns(self):
        state = start_develop("t")
        assert state["max_agent_respawns"] == 3

    def test_start_default_tickets_enabled(self):
        state = start_develop("t")
        assert state["tickets"]["enabled"] is True

    def test_start_override_max_review_retries(self):
        state = start_develop("t", max_review_retries=5)
        assert state["max_review_retries"] == 5

    def test_start_override_tickets_disabled(self):
        state = start_develop("t", tickets_enabled=False)
        assert state["tickets"]["enabled"] is False

    def test_start_empty_kickback_counters(self):
        state = start_develop("t")
        assert state["kickback_counters"] == {}

    def test_start_empty_subtasks(self):
        state = start_develop("t")
        assert state["subtasks"] == []

    def test_start_empty_user_stories(self):
        state = start_develop("t")
        assert state["user_stories"] == []

    def test_start_empty_agents(self):
        state = start_develop("t")
        assert state["agents"] == {}


# ============================================================================
# TestStop
# ============================================================================
class TestStop:
    """Tests for stop()."""

    def test_stop_sets_active_false(self):
        start_develop("t")
        stop("user_cancelled")
        assert is_active() is False

    def test_stop_sets_exit_reason(self):
        start_develop("t")
        stop("user_cancelled")
        # Verify via internal state - get_phase still works on inactive
        from develop_workflow import _get_state
        state = _get_state()
        assert state["exit_reason"] == "user_cancelled"

    def test_stop_on_inactive_does_nothing(self):
        # No workflow started -- should not raise
        stop("user_cancelled")


# ============================================================================
# TestPhaseQueries
# ============================================================================
class TestPhaseQueries:
    """Tests for get_phase() and is_active()."""

    def test_get_phase_returns_current(self):
        start_develop("t")
        assert get_phase() == "intake"

    def test_get_phase_none_when_no_workflow(self):
        assert get_phase() is None

    def test_is_active_true_when_started(self):
        start_develop("t")
        assert is_active() is True

    def test_is_active_false_when_not_started(self):
        assert is_active() is False

    def test_is_active_false_after_stop(self):
        start_develop("t")
        stop("done")
        assert is_active() is False


# ============================================================================
# TestForwardTransitions
# ============================================================================
class TestForwardTransitions:
    """Tests for the happy-path forward phase transitions."""

    def test_full_happy_path(self):
        """Complete the entire workflow through all phases."""
        start_develop("full run")
        advance_phase("research")
        advance_phase("design")
        pass_checkpoint()  # design checkpoint
        advance_phase("branch")
        advance_phase("test_writing")
        advance_phase("implement")
        advance_phase("test")
        pass_checkpoint()  # test checkpoint
        advance_phase("review")
        pass_checkpoint()  # review checkpoint
        advance_phase("merge")
        advance_phase("acceptance")
        pass_checkpoint()  # acceptance checkpoint
        advance_phase("complete")
        assert is_active() is False
        assert get_phase() == "complete"

    def test_intake_to_research(self):
        start_develop("t")
        state = advance_phase("research")
        assert state["phase"] == "research"

    def test_research_to_design(self):
        start_develop("t")
        _force_phase("research")
        state = advance_phase("design")
        assert state["phase"] == "design"

    def test_design_to_branch(self):
        start_develop("t")
        _force_phase("design")
        pass_checkpoint()
        state = advance_phase("branch")
        assert state["phase"] == "branch"

    def test_branch_to_test_writing(self):
        start_develop("t")
        _force_phase("branch")
        state = advance_phase("test_writing")
        assert state["phase"] == "test_writing"

    def test_test_writing_to_implement(self):
        start_develop("t")
        _force_phase("test_writing")
        state = advance_phase("implement")
        assert state["phase"] == "implement"

    def test_implement_to_test(self):
        start_develop("t")
        _force_phase("implement")
        state = advance_phase("test")
        assert state["phase"] == "test"

    def test_test_to_review(self):
        start_develop("t")
        _force_phase("test")
        pass_checkpoint()
        state = advance_phase("review")
        assert state["phase"] == "review"

    def test_review_to_merge(self):
        start_develop("t")
        _force_phase("review")
        pass_checkpoint()
        state = advance_phase("merge")
        assert state["phase"] == "merge"

    def test_merge_to_acceptance(self):
        start_develop("t")
        _force_phase("merge")
        state = advance_phase("acceptance")
        assert state["phase"] == "acceptance"

    def test_acceptance_to_complete(self):
        start_develop("t")
        _force_phase("acceptance")
        pass_checkpoint()
        state = advance_phase("complete")
        assert state["phase"] == "complete"
        assert state["active"] is False


# ============================================================================
# TestInvalidTransitions
# ============================================================================
class TestInvalidTransitions:
    """Tests for rejected transitions."""

    def test_intake_to_implement_raises(self):
        start_develop("t")
        with pytest.raises(DevelopWorkflowError, match="Invalid transition"):
            advance_phase("implement")

    def test_intake_to_nonexistent_raises(self):
        start_develop("t")
        with pytest.raises(DevelopWorkflowError, match="Unknown phase"):
            advance_phase("nonexistent")

    def test_advance_on_inactive_raises(self):
        start_develop("t")
        stop("cancelled")
        with pytest.raises(DevelopWorkflowError, match="not active"):
            advance_phase("research")

    def test_advance_without_start_raises(self):
        with pytest.raises(DevelopWorkflowError, match="not active"):
            advance_phase("research")


# ============================================================================
# TestCheckpoints
# ============================================================================
class TestCheckpoints:
    """Tests for checkpoint enforcement."""

    def test_design_requires_checkpoint(self):
        start_develop("t")
        _force_phase("design")
        with pytest.raises(DevelopWorkflowError, match="Checkpoint not passed"):
            advance_phase("branch")

    def test_test_requires_checkpoint(self):
        start_develop("t")
        _force_phase("test")
        with pytest.raises(DevelopWorkflowError, match="Checkpoint not passed"):
            advance_phase("review")

    def test_review_requires_checkpoint(self):
        start_develop("t")
        _force_phase("review")
        with pytest.raises(DevelopWorkflowError, match="Checkpoint not passed"):
            advance_phase("merge")

    def test_acceptance_requires_checkpoint(self):
        start_develop("t")
        _force_phase("acceptance")
        with pytest.raises(DevelopWorkflowError, match="Checkpoint not passed"):
            advance_phase("complete")

    def test_design_checkpoint_allows_advance(self):
        start_develop("t")
        _force_phase("design")
        pass_checkpoint()
        state = advance_phase("branch")
        assert state["phase"] == "branch"

    def test_test_checkpoint_allows_advance(self):
        start_develop("t")
        _force_phase("test")
        pass_checkpoint()
        state = advance_phase("review")
        assert state["phase"] == "review"

    def test_non_checkpoint_intake_advances_freely(self):
        start_develop("t")
        state = advance_phase("research")
        assert state["phase"] == "research"

    def test_non_checkpoint_branch_advances_freely(self):
        start_develop("t")
        _force_phase("branch")
        state = advance_phase("test_writing")
        assert state["phase"] == "test_writing"

    def test_non_checkpoint_test_writing_advances_freely(self):
        start_develop("t")
        _force_phase("test_writing")
        state = advance_phase("implement")
        assert state["phase"] == "implement"

    def test_non_checkpoint_implement_advances_freely(self):
        start_develop("t")
        _force_phase("implement")
        state = advance_phase("test")
        assert state["phase"] == "test"


# ============================================================================
# TestKickbacks
# ============================================================================
class TestKickbacks:
    """Tests for valid kickback transitions (going backward)."""

    def test_test_to_implement(self):
        start_develop("t")
        _force_phase("test")
        pass_checkpoint()
        state = advance_phase("implement")
        assert state["phase"] == "implement"

    def test_review_to_implement(self):
        start_develop("t")
        _force_phase("review")
        pass_checkpoint()
        state = advance_phase("implement")
        assert state["phase"] == "implement"

    def test_review_to_test_writing(self):
        start_develop("t")
        _force_phase("review")
        pass_checkpoint()
        state = advance_phase("test_writing")
        assert state["phase"] == "test_writing"

    def test_merge_to_implement(self):
        start_develop("t")
        _force_phase("merge")
        state = advance_phase("implement")
        assert state["phase"] == "implement"

    def test_acceptance_to_implement(self):
        start_develop("t")
        _force_phase("acceptance")
        pass_checkpoint()  # acceptance needs checkpoint
        state = advance_phase("implement")
        assert state["phase"] == "implement"

    def test_acceptance_to_test_writing(self):
        start_develop("t")
        _force_phase("acceptance")
        pass_checkpoint()  # acceptance needs checkpoint
        state = advance_phase("test_writing")
        assert state["phase"] == "test_writing"

    def test_record_kickback_increments_counter(self):
        start_develop("t")
        record_kickback("review")
        from develop_workflow import _get_state
        state = _get_state()
        assert state["kickback_counters"]["review"] == 1


# ============================================================================
# TestKickbackCounters
# ============================================================================
class TestKickbackCounters:
    """Tests for kickback counter tracking and limits."""

    def test_first_kickback_sets_counter_to_one(self):
        start_develop("t")
        record_kickback("review")
        from develop_workflow import _get_state
        state = _get_state()
        assert state["kickback_counters"]["review"] == 1

    def test_multiple_kickbacks_increment(self):
        start_develop("t")
        record_kickback("review")
        record_kickback("review")
        record_kickback("review")
        from develop_workflow import _get_state
        state = _get_state()
        assert state["kickback_counters"]["review"] == 3

    def test_separate_sources_separate_counters(self):
        start_develop("t")
        record_kickback("review")
        record_kickback("review")
        record_kickback("acceptance")
        from develop_workflow import _get_state
        state = _get_state()
        assert state["kickback_counters"]["review"] == 2
        assert state["kickback_counters"]["acceptance"] == 1

    def test_max_retries_zero_means_unlimited(self):
        """max_review_retries=0 means no limit."""
        start_develop("t", max_review_retries=0)
        # Should not raise even after many kickbacks
        for _ in range(100):
            record_kickback("review")
        from develop_workflow import _get_state
        state = _get_state()
        assert state["kickback_counters"]["review"] == 100

    def test_max_retries_allows_up_to_limit(self):
        start_develop("t", max_review_retries=2)
        record_kickback("review")  # 1 ok
        record_kickback("review")  # 2 ok
        from develop_workflow import _get_state
        state = _get_state()
        assert state["kickback_counters"]["review"] == 2

    def test_max_retries_exceeded_raises(self):
        start_develop("t", max_review_retries=2)
        record_kickback("review")  # 1
        record_kickback("review")  # 2
        with pytest.raises(DevelopWorkflowError, match="Max retries"):
            record_kickback("review")  # 3 -- exceeds


# ============================================================================
# TestSubtasks
# ============================================================================
class TestSubtasks:
    """Tests for subtask management and dependency-based scheduling."""

    def test_add_subtask_appends(self):
        start_develop("t")
        add_subtask({"id": 1, "name": "sub1"})
        from develop_workflow import _get_state
        state = _get_state()
        assert len(state["subtasks"]) == 1
        assert state["subtasks"][0]["id"] == 1

    def test_add_subtask_defaults_status_pending(self):
        start_develop("t")
        add_subtask({"id": 1, "name": "sub1"})
        from develop_workflow import _get_state
        state = _get_state()
        assert state["subtasks"][0]["status"] == "pending"

    def test_get_eligible_no_deps(self):
        """Tasks with no dependencies are immediately eligible."""
        start_develop("t")
        add_subtask({"id": 1, "name": "sub1", "depends_on": []})
        eligible = get_eligible_subtasks()
        assert len(eligible) == 1
        assert eligible[0]["id"] == 1

    def test_get_eligible_excludes_pending_deps(self):
        """Tasks with unmet dependencies are NOT eligible."""
        start_develop("t")
        add_subtask({"id": 1, "name": "sub1", "depends_on": []})
        add_subtask({"id": 2, "name": "sub2", "depends_on": [1]})
        eligible = get_eligible_subtasks()
        ids = [s["id"] for s in eligible]
        assert 1 in ids
        assert 2 not in ids

    def test_complete_subtask_sets_completed(self):
        start_develop("t")
        add_subtask({"id": 1, "name": "sub1", "depends_on": []})
        complete_subtask(1)
        from develop_workflow import _get_state
        state = _get_state()
        assert state["subtasks"][0]["status"] == "completed"

    def test_completing_dep_makes_dependent_eligible(self):
        start_develop("t")
        add_subtask({"id": 1, "name": "A", "depends_on": []})
        add_subtask({"id": 2, "name": "B", "depends_on": [1]})
        # Before completing dep
        eligible = get_eligible_subtasks()
        assert [s["id"] for s in eligible] == [1]
        # Complete dep
        complete_subtask(1)
        eligible = get_eligible_subtasks()
        ids = [s["id"] for s in eligible]
        assert 2 in ids

    def test_chain_only_first_eligible(self):
        """Chain A -> B -> C: only A eligible initially."""
        start_develop("t")
        add_subtask({"id": 1, "name": "A", "depends_on": []})
        add_subtask({"id": 2, "name": "B", "depends_on": [1]})
        add_subtask({"id": 3, "name": "C", "depends_on": [2]})
        eligible = get_eligible_subtasks()
        assert [s["id"] for s in eligible] == [1]

    def test_chain_complete_first_second_eligible(self):
        """Chain A -> B -> C: after completing A, only B eligible."""
        start_develop("t")
        add_subtask({"id": 1, "name": "A", "depends_on": []})
        add_subtask({"id": 2, "name": "B", "depends_on": [1]})
        add_subtask({"id": 3, "name": "C", "depends_on": [2]})
        complete_subtask(1)
        eligible = get_eligible_subtasks()
        assert [s["id"] for s in eligible] == [2]

    def test_chain_complete_both_third_eligible(self):
        """Chain A -> B -> C: after completing A and B, C eligible."""
        start_develop("t")
        add_subtask({"id": 1, "name": "A", "depends_on": []})
        add_subtask({"id": 2, "name": "B", "depends_on": [1]})
        add_subtask({"id": 3, "name": "C", "depends_on": [2]})
        complete_subtask(1)
        complete_subtask(2)
        eligible = get_eligible_subtasks()
        assert [s["id"] for s in eligible] == [3]
