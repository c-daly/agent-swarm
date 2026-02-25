"""Builds prompts for TDD subagents."""

from lib.manifest import ManifestTask


def build_subagent_prompt(task: ManifestTask, base_branch: str) -> str:
    """Build the initial TDD prompt for a subagent."""
    return f"""You are a TDD subagent working on task: {task.name}

## Task Description
{task.description}

## Setup
1. Create and checkout branch `{task.branch_name}` from `{base_branch}`
2. Work in target directory: `{task.target_dir}`
3. Tests go in: `{task.test_dir}`

## TDD Workflow (strict order)
1. **Write tests first** — at least {task.min_tests} test functions in `{task.test_dir}`
2. **Run tests** — confirm they all fail (red phase)
3. **Implement** the code in `{task.target_dir}` to make tests pass
4. **Run tests again** — all {task.min_tests}+ tests must pass (green phase)
5. **Commit** all changes on branch `{task.branch_name}`

## Rules
- Do NOT modify files outside `{task.target_dir}` and `{task.test_dir}`
- Write at least {task.min_tests} test functions
- All tests must pass before committing
- Commit with a descriptive message summarizing what was implemented
"""


def build_retry_prompt(
    task: ManifestTask,
    base_branch: str,
    error: str,
    attempt: int,
    max_retries: int,
) -> str:
    """Build a retry prompt with error context."""
    return f"""You are a TDD subagent retrying task: {task.name}

## Retry Attempt {attempt} of {max_retries}

## Previous Error
```
{error}
```

## Task Description
{task.description}

## Context
- Branch: `{task.branch_name}` (already exists, checkout and continue)
- Target directory: `{task.target_dir}`
- Test directory: `{task.test_dir}`
- Minimum tests: {task.min_tests}

## Instructions
1. Review the error above and understand what went wrong
2. Check existing tests in `{task.test_dir}` — fix or add as needed
3. Fix the implementation in `{task.target_dir}`
4. Run tests — all must pass
5. Commit the fix on branch `{task.branch_name}`
"""
