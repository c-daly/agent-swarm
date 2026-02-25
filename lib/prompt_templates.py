"""Prompt templates for explore-before-prompt pattern.

Provides reusable prompt templates for:
- Explorer agents (gather context)
- Implementer agents (with/without exploration context)
"""

# Explorer prompt templates
EXPLORATION_PROMPTS = {
    "file_discovery": """Find all files related to {topic}.

Return:
- File paths with brief descriptions
- Key functions/classes in each file
- Usage patterns or examples
- Entry points for modification

Limit: 20 files max, 2000 chars total.""",

    "pattern_matching": """Find implementations of {feature}.

Return:
- Files where pattern is used
- Common approaches or styles
- Helper functions typically involved
- Examples of correct usage

Limit: 15 patterns max, 2000 chars total.""",

    "dependency_mapping": """Map dependencies for {component}.

Return:
- Files that import/use this component
- Functions that call these methods
- Potential side effects of changes
- Test files covering this code

Limit: 20 references max, 2000 chars total.""",

    "context_enrichment": """Explore {area} to understand current implementation.

Return:
- Directory structure
- Key files and their purposes
- Existing patterns in use
- Suggested starting points

Limit: 20 files max, 2000 chars total."""
}


# Implementer prompt templates
IMPLEMENTER_PROMPTS = {
    "with_exploration": """Implement: {task_description}

**Context from Exploration:**
{explorer_output}

**Requirements:**
{requirements}

**Files to Modify:**
{suggested_files}

Follow the patterns shown above. Use EditFile/WriteFile to make changes, then RunShell to run tests.""",

    "without_exploration": """Implement: {task_description}

**Requirements:**
{requirements}

Use ReadFile and SearchContent to explore the codebase first. Verify side effects before changes.
Use EditFile/WriteFile to make changes, then RunShell to run tests."""
}


def get_exploration_prompt(exploration_type: str) -> str:
    """Get exploration prompt template by type.

    Args:
        exploration_type: One of 'file_discovery', 'pattern_matching',
                          'dependency_mapping', 'context_enrichment'

    Returns:
        Prompt template string with placeholders

    Raises:
        KeyError: If exploration_type is invalid
    """
    return EXPLORATION_PROMPTS[exploration_type]


def get_implementer_prompt(with_exploration: bool = False) -> str:
    """Get implementer prompt template.

    Args:
        with_exploration: Whether to use template with exploration context

    Returns:
        Prompt template string with placeholders
    """
    key = "with_exploration" if with_exploration else "without_exploration"
    return IMPLEMENTER_PROMPTS[key]


def list_exploration_types() -> list:
    """List available exploration types.

    Returns:
        List of exploration type keys
    """
    return list(EXPLORATION_PROMPTS.keys())
