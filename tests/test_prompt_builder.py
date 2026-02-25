"""Tests for prompt builder."""

from lib.manifest import ManifestTask
from lib.prompt_builder import build_retry_prompt, build_subagent_prompt


def _make_task(**overrides) -> ManifestTask:
    defaults = dict(
        name="stack",
        description="Implement a stack data structure with push, pop, peek, is_empty",
        target_dir="src/stack",
        test_dir="tests/test_stack",
        min_tests=10,
    )
    defaults.update(overrides)
    return ManifestTask(**defaults)


class TestBuildSubagentPrompt:
    def test_contains_branch_name(self):
        task = _make_task()
        prompt = build_subagent_prompt(task, base_branch="main")
        assert "task/stack" in prompt

    def test_contains_tdd_order(self):
        task = _make_task()
        prompt = build_subagent_prompt(task, base_branch="main")
        # TDD workflow steps: write tests is step 1, implement is step 3
        assert "Write tests first" in prompt
        # "Implement" step should come after the test-writing step
        write_tests_pos = prompt.find("Write tests first")
        implement_pos = prompt.find("Implement", write_tests_pos)
        assert implement_pos > write_tests_pos, "Tests should be mentioned before implementation"

    def test_contains_task_description(self):
        task = _make_task(description="Build a red-black tree")
        prompt = build_subagent_prompt(task, base_branch="main")
        assert "red-black tree" in prompt

    def test_contains_min_tests(self):
        task = _make_task(min_tests=15)
        prompt = build_subagent_prompt(task, base_branch="main")
        assert "15" in prompt


class TestBuildRetryPrompt:
    def test_contains_error_context(self):
        task = _make_task()
        prompt = build_retry_prompt(
            task, base_branch="main", error="AssertionError: expected 5 got 3",
            attempt=2, max_retries=3,
        )
        assert "AssertionError" in prompt

    def test_contains_attempt_info(self):
        task = _make_task()
        prompt = build_retry_prompt(
            task, base_branch="main", error="test failed",
            attempt=2, max_retries=3,
        )
        assert "2" in prompt
        assert "3" in prompt
