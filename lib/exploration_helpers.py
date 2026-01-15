"""Helpers for detecting when orchestrator needs exploration before prompting.

The explore-before-prompt pattern helps orchestrators write better prompts by:
1. Detecting when context is insufficient
2. Spawning explorer to gather context
3. Using explorer output to enrich implementer prompts
"""

import re
from typing import Dict, List, Optional


def needs_exploration(task: Dict, available_context: Dict) -> bool:
    """Determine if task needs exploration before implementation.

    Args:
        task: Task dict with 'description', optionally 'type', 'metadata'
        available_context: Dict with 'files_read', 'code_snippets', 'patterns_known'

    Returns:
        True if exploration is recommended before spawning implementer.

    Detection criteria (returns True if ANY match):
    - Task references files/modules not yet read
    - Task description is vague (< 10 words, no file paths)
    - No code snippets or file references in context
    - Task uses vague verbs without specifics
    - Task mentions "similar to" or "like in" without examples
    """
    description = task.get("description", "")
    files_read = set(available_context.get("files_read", []))
    code_snippets = available_context.get("code_snippets", [])
    patterns_known = available_context.get("patterns_known", [])

    # Criterion 1: References unread files
    referenced_files = _extract_file_references(description)
    if referenced_files and not referenced_files.issubset(files_read):
        return True

    # Criterion 2: Vague verb without specifics
    if _has_vague_verb_without_specifics(description):
        return True

    # Criterion 3: References similarity without examples
    if _references_similarity_without_examples(description, code_snippets):
        return True

    # Criterion 4: No context available AND vague description
    has_context = code_snippets or patterns_known or files_read
    if not has_context:
        if _is_vague_description(description):
            return True

    return False


def detect_exploration_type(task: Dict) -> str:
    """Detect which type of exploration is needed.

    Args:
        task: Task dict with 'description'

    Returns:
        One of: 'file_discovery', 'pattern_matching', 'dependency_mapping', 'context_enrichment'
    """
    description = task.get("description", "").lower()

    # Pattern matching: mentions "similar", "like", "following"
    if any(word in description for word in ["similar", "like", "following", "match"]):
        return "pattern_matching"

    # Dependency mapping: mentions "refactor", "modify", "change existing"
    if any(word in description for word in ["refactor", "modify", "change", "update existing"]):
        return "dependency_mapping"

    # File discovery: mentions specific file/module names
    if _extract_file_references(description):
        return "file_discovery"

    # Default: context enrichment for vague tasks
    return "context_enrichment"


def _is_vague_description(description: str) -> bool:
    """Check if description is too vague (< 10 words, no file paths).

    Args:
        description: Task description text

    Returns:
        True if description is vague
    """
    words = description.split()
    word_count = len(words)

    # Short and no file references = vague
    has_file_ref = bool(_extract_file_references(description))

    return word_count < 10 and not has_file_ref


def _extract_file_references(text: str) -> set:
    """Extract file/module references from text.

    Matches patterns like:
    - path/to/file.py
    - file.ts
    - module.go
    - component.tsx

    Args:
        text: Text to search for file references

    Returns:
        Set of file path strings found
    """
    # Pattern: word characters + / or . + file extension
    file_pattern = r'\b[\w/]+\.(py|js|ts|tsx|go|rs|java|cpp|h|json|yaml|yml|md|txt)\b'
    matches = re.findall(file_pattern, text, re.IGNORECASE)

    # Return full matches (with extension), not just the extension group
    full_matches = re.findall(r'\b[\w/]+\.\w+\b', text)
    return set(m for m in full_matches if any(m.endswith(ext) for ext in ['.py', '.js', '.ts', '.tsx', '.go', '.rs', '.java', '.cpp', '.h', '.json', '.yaml', '.yml', '.md', '.txt']))


def _has_vague_verb_without_specifics(description: str) -> bool:
    """Check if description uses vague verbs without specifics.

    Vague verbs: improve, fix, refactor, enhance, optimize
    Specifics: file paths, function names, line numbers, error messages

    Args:
        description: Task description text

    Returns:
        True if has vague verb without specifics
    """
    vague_verbs = ["improve", "fix", "refactor", "enhance", "optimize", "update"]
    description_lower = description.lower()

    # Check for vague verbs
    has_vague_verb = any(verb in description_lower for verb in vague_verbs)

    if not has_vague_verb:
        return False

    # Check for specifics
    has_file_ref = bool(_extract_file_references(description))
    has_function_ref = bool(re.search(r'\b[a-z_][a-z0-9_]*\(\)', description, re.IGNORECASE))
    has_line_number = bool(re.search(r':\d+|line \d+', description, re.IGNORECASE))
    has_error_msg = bool(re.search(r'error:|exception:|failed:', description, re.IGNORECASE))

    has_specifics = has_file_ref or has_function_ref or has_line_number or has_error_msg

    return has_vague_verb and not has_specifics


def _references_similarity_without_examples(description: str, code_snippets: List[str]) -> bool:
    """Check if description references similarity without providing examples.

    Looks for phrases like "similar to", "like in", "following the pattern of"
    but no code snippets are available in context.

    Args:
        description: Task description text
        code_snippets: List of code snippet strings in available context

    Returns:
        True if mentions similarity but no examples in context
    """
    similarity_phrases = ["similar to", "like in", "following", "match the", "same as"]
    description_lower = description.lower()

    has_similarity_ref = any(phrase in description_lower for phrase in similarity_phrases)

    return has_similarity_ref and not code_snippets


def format_explorer_prompt(exploration_type: str, task: Dict, templates: Optional[Dict] = None) -> str:
    """Format an explorer prompt based on exploration type.

    Args:
        exploration_type: One of the exploration types from detect_exploration_type()
        task: Task dict with 'description' and optional metadata
        templates: Optional custom templates dict (defaults to EXPLORATION_PROMPTS)

    Returns:
        Formatted prompt string for explorer agent
    """
    if templates is None:
        from prompt_templates import EXPLORATION_PROMPTS
        templates = EXPLORATION_PROMPTS

    description = task.get("description", "")

    # Extract topic/feature/component from description
    # Simple heuristic: first noun phrase or last 3 words
    words = description.split()
    topic = " ".join(words[-3:]) if len(words) >= 3 else description

    template = templates.get(exploration_type, templates["context_enrichment"])

    # Format with extracted topic
    if "{topic}" in template:
        return template.format(topic=topic)
    elif "{feature}" in template:
        return template.format(feature=topic)
    elif "{component}" in template:
        return template.format(component=topic)
    elif "{area}" in template:
        return template.format(area=topic)

    return template


def format_implementer_prompt(
    task: Dict,
    context: Dict,
    with_exploration: bool = False,
    templates: Optional[Dict] = None
) -> str:
    """Format an implementer prompt with or without exploration context.

    Args:
        task: Task dict with 'description' and optional 'requirements'
        context: Dict with available context, optionally including 'exploration' key
        with_exploration: Whether exploration output is included in context
        templates: Optional custom templates dict (defaults to IMPLEMENTER_PROMPTS)

    Returns:
        Formatted prompt string for implementer agent
    """
    if templates is None:
        from prompt_templates import IMPLEMENTER_PROMPTS
        templates = IMPLEMENTER_PROMPTS

    description = task.get("description", "")
    requirements = task.get("requirements", context.get("requirements", []))

    if isinstance(requirements, list):
        requirements = "\n".join(f"- {r}" for r in requirements)

    if with_exploration:
        explorer_output = context.get("exploration", "No exploration output available")
        suggested_files = context.get("suggested_files", "See exploration output above")

        template = templates["with_exploration"]
        return template.format(
            task_description=description,
            explorer_output=explorer_output,
            requirements=requirements,
            suggested_files=suggested_files
        )
    else:
        template = templates["without_exploration"]
        return template.format(
            task_description=description,
            requirements=requirements
        )
