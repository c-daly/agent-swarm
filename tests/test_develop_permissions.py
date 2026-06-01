"""Tests for pm agent type and develop workflow permissions."""
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).parent.parent
PERMISSIONS_YAML = PROJECT_ROOT / "config" / "permissions.yaml"


@pytest.fixture
def config():
    with open(PERMISSIONS_YAML) as f:
        return yaml.safe_load(f)


# ── PM Agent Type ──────────────────────────────────────────────────────

class TestPMAgentType:
    def test_pm_exists_in_agents(self, config):
        assert "pm" in config["agents"]

    def test_pm_allowed_includes_read_tools(self, config):
        allowed = config["agents"]["pm"]["allowed"]
        assert "native__read_file" in allowed
        assert "native__glob" in allowed
        assert "native__grep" in allowed

    def test_pm_allowed_includes_workflow_tools(self, config):
        allowed = config["agents"]["pm"]["allowed"]
        assert "workflow__*" in allowed

    def test_pm_allowed_includes_serena(self, config):
        allowed = config["agents"]["pm"]["allowed"]
        assert "serena__*" in allowed

    def test_pm_allowed_includes_context7(self, config):
        allowed = config["agents"]["pm"]["allowed"]
        assert "context7__*" in allowed

    def test_pm_blocked_includes_write_tools(self, config):
        blocked = config["agents"]["pm"]["blocked"]
        assert "native__write_file" in blocked
        assert "native__edit_file" in blocked
        assert "native__bash" in blocked


# ── Git-agent Agent Type ──────────────────────────────────────────────

class TestGitAgentType:
    def test_git_agent_exists_in_agents(self, config):
        assert "git-agent" in config["agents"]

    def test_git_agent_allowed_includes_read(self, config):
        allowed = config["agents"]["git-agent"]["allowed"]
        assert "native__read_file" in allowed
        assert "native__glob" in allowed
        assert "native__grep" in allowed

    def test_git_agent_allowed_includes_git_commands(self, config):
        allowed = config["agents"]["git-agent"]["allowed"]
        assert "native__bash(git*)" in allowed
        assert "native__bash(gh*)" in allowed

    def test_git_agent_blocked_includes_write_edit(self, config):
        blocked = config["agents"]["git-agent"]["blocked"]
        assert "native__write_file" in blocked
        assert "native__edit_file" in blocked


# ── Develop Workflow Section ──────────────────────────────────────────

class TestDevelopWorkflowSection:
    EXPECTED_PHASES = [
        "intake", "research", "design", "branch", "test_writing",
        "implement", "test", "review", "merge", "acceptance",
    ]

    def test_develop_exists_in_workflows(self, config):
        assert "develop" in config["workflows"]

    def test_all_phases_present(self, config):
        develop = config["workflows"]["develop"]
        for phase in self.EXPECTED_PHASES:
            assert phase in develop, f"Phase {phase} missing from develop workflow"

    def test_each_phase_has_allowed_and_blocked(self, config):
        develop = config["workflows"]["develop"]
        for phase in self.EXPECTED_PHASES:
            assert "allowed" in develop[phase], f"Phase {phase} missing allowed"
            assert "blocked" in develop[phase], f"Phase {phase} missing blocked"

    # ── Per-phase spot checks ─────────────────────────────────────────

    def test_intake_blocked(self, config):
        blocked = config["workflows"]["develop"]["intake"]["blocked"]
        assert "native__bash" in blocked
        assert "native__write_file" in blocked
        assert "native__edit_file" in blocked

    def test_research_allowed_web(self, config):
        allowed = config["workflows"]["develop"]["research"]["allowed"]
        assert "native__web_fetch" in allowed
        assert "native__web_search" in allowed

    def test_branch_allowed_git(self, config):
        allowed = config["workflows"]["develop"]["branch"]["allowed"]
        assert "native__bash(git*)" in allowed

    def test_test_writing_blocked_is_empty(self, config):
        blocked = config["workflows"]["develop"]["test_writing"]["blocked"]
        assert blocked == []

    def test_implement_allowed_tools(self, config):
        allowed = config["workflows"]["develop"]["implement"]["allowed"]
        assert "native__write_file" in allowed
        assert "native__edit_file" in allowed
        assert "native__bash(pytest*)" in allowed
        assert "native__bash(python*)" in allowed
        assert "native__bash(ruff*)" in allowed

    def test_test_phase_blocked_write(self, config):
        blocked = config["workflows"]["develop"]["test"]["blocked"]
        assert "native__write_file" in blocked
        assert "native__edit_file" in blocked

    def test_review_blocked(self, config):
        review = config["workflows"]["develop"]["review"]
        # Review blocks code changes...
        assert "native__write_file" in review["blocked"]
        assert "native__edit_file" in review["blocked"]
        # ...but must NOT wholesale-block bash: the reviewer needs read-only git
        # to inspect the PR diff (see test_review_binding_fix).
        assert "native__bash" not in review["blocked"]
        assert "native__bash(git diff*)" in review["allowed"]

    def test_merge_allowed_git_gh(self, config):
        allowed = config["workflows"]["develop"]["merge"]["allowed"]
        assert "native__bash(git*)" in allowed
        assert "native__bash(gh*)" in allowed

    def test_acceptance_blocked(self, config):
        blocked = config["workflows"]["develop"]["acceptance"]["blocked"]
        assert "native__bash" in blocked
        assert "native__write_file" in blocked
        assert "native__edit_file" in blocked
