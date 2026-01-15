"""Tests for exploration_helpers module.

Tests the explore-before-prompt pattern detection logic.
"""

import pytest
from exploration_helpers import (
    needs_exploration,
    detect_exploration_type,
    format_explorer_prompt,
    format_implementer_prompt,
    _is_vague_description,
    _extract_file_references,
    _has_vague_verb_without_specifics,
    _references_similarity_without_examples,
)


class TestNeedsExploration:
    """Test the main needs_exploration() function."""

    def test_vague_description_triggers_exploration(self):
        """Vague description (< 10 words, no files) should trigger exploration."""
        task = {"description": "Fix auth system"}
        context = {"files_read": [], "code_snippets": [], "patterns_known": []}

        assert needs_exploration(task, context) is True

    def test_detailed_description_no_exploration(self):
        """Detailed description with specifics should not trigger exploration."""
        task = {
            "description": "Fix token expiration bug in auth/tokens.py line 45 by updating expiry calculation"
        }
        context = {"files_read": ["auth/tokens.py"], "code_snippets": ["def generate_token()"], "patterns_known": []}

        assert needs_exploration(task, context) is False

    def test_unread_file_references_trigger_exploration(self):
        """Task referencing unread files should trigger exploration."""
        task = {"description": "Update auth logic in auth/middleware.py"}
        context = {"files_read": ["auth/tokens.py"], "code_snippets": [], "patterns_known": []}

        assert needs_exploration(task, context) is True

    def test_read_file_references_no_exploration(self):
        """Task referencing already-read files should not trigger exploration."""
        task = {"description": "Update auth logic in auth/tokens.py"}
        context = {"files_read": ["auth/tokens.py"], "code_snippets": [], "patterns_known": []}

        assert needs_exploration(task, context) is False

    def test_no_context_triggers_exploration(self):
        """Task with no available context should trigger exploration."""
        task = {"description": "Implement user authentication with JWT tokens"}
        context = {"files_read": [], "code_snippets": [], "patterns_known": []}

        assert needs_exploration(task, context) is True

    def test_rich_context_no_exploration(self):
        """Task with rich context should not trigger exploration."""
        task = {"description": "Implement JWT validation"}
        context = {
            "files_read": ["auth/jwt.py", "auth/middleware.py"],
            "code_snippets": ["def validate_token()", "def decode_jwt()"],
            "patterns_known": ["JWT validation pattern"],
        }

        assert needs_exploration(task, context) is False

    def test_vague_verb_without_specifics_triggers_exploration(self):
        """Vague verb without specifics should trigger exploration."""
        task = {"description": "Improve authentication performance"}
        context = {"files_read": ["auth/tokens.py"], "code_snippets": [], "patterns_known": []}

        assert needs_exploration(task, context) is True

    def test_vague_verb_with_specifics_no_exploration(self):
        """Vague verb with specifics should not trigger exploration."""
        task = {"description": "Fix authentication bug in auth/tokens.py:45 causing TypeError"}
        context = {"files_read": ["auth/tokens.py"], "code_snippets": [], "patterns_known": []}

        assert needs_exploration(task, context) is False

    def test_similarity_without_examples_triggers_exploration(self):
        """Task referencing similarity without examples should trigger exploration."""
        task = {"description": "Implement similar to the user auth pattern"}
        context = {"files_read": [], "code_snippets": [], "patterns_known": []}

        assert needs_exploration(task, context) is True

    def test_similarity_with_examples_no_exploration(self):
        """Task referencing similarity WITH examples should not trigger exploration."""
        task = {"description": "Implement similar to the user auth pattern"}
        context = {
            "files_read": [],
            "code_snippets": ["def authenticate_user()", "class UserAuth"],
            "patterns_known": [],
        }

        assert needs_exploration(task, context) is False


class TestDetectExplorationType:
    """Test exploration type detection."""

    def test_pattern_matching_for_similarity(self):
        """Task mentioning 'similar' should use pattern_matching."""
        task = {"description": "Implement similar to existing auth"}
        assert detect_exploration_type(task) == "pattern_matching"

    def test_pattern_matching_for_like(self):
        """Task mentioning 'like' should use pattern_matching."""
        task = {"description": "Create endpoint like in user module"}
        assert detect_exploration_type(task) == "pattern_matching"

    def test_dependency_mapping_for_refactor(self):
        """Task mentioning 'refactor' should use dependency_mapping."""
        task = {"description": "Refactor authentication module"}
        assert detect_exploration_type(task) == "dependency_mapping"

    def test_dependency_mapping_for_modify(self):
        """Task mentioning 'modify' should use dependency_mapping."""
        task = {"description": "Modify existing user validation"}
        assert detect_exploration_type(task) == "dependency_mapping"

    def test_file_discovery_for_file_references(self):
        """Task with file references should use file_discovery."""
        task = {"description": "Update auth/tokens.py module"}
        assert detect_exploration_type(task) == "file_discovery"

    def test_context_enrichment_default(self):
        """Vague task should default to context_enrichment."""
        task = {"description": "Fix auth issues"}
        assert detect_exploration_type(task) == "context_enrichment"


class TestIsVagueDescription:
    """Test vague description detection."""

    def test_short_without_files_is_vague(self):
        """Short description without files is vague."""
        assert _is_vague_description("Fix auth") is True

    def test_short_with_files_not_vague(self):
        """Short description WITH files is not vague."""
        assert _is_vague_description("Fix auth/tokens.py") is False

    def test_long_description_not_vague(self):
        """Long description is not vague."""
        desc = "Update the authentication token expiration logic to properly handle timezone conversions"
        assert _is_vague_description(desc) is False


class TestExtractFileReferences:
    """Test file reference extraction."""

    def test_extracts_python_files(self):
        """Should extract .py file references."""
        text = "Update auth/tokens.py and utils/helpers.py"
        refs = _extract_file_references(text)
        assert "auth/tokens.py" in refs
        assert "utils/helpers.py" in refs

    def test_extracts_various_extensions(self):
        """Should extract multiple file types."""
        text = "Modify config.json, app.tsx, main.go, and README.md"
        refs = _extract_file_references(text)
        assert "config.json" in refs
        assert "app.tsx" in refs
        assert "main.go" in refs
        assert "README.md" in refs

    def test_no_files_returns_empty(self):
        """Should return empty set when no files found."""
        text = "Improve authentication performance"
        refs = _extract_file_references(text)
        assert len(refs) == 0


class TestHasVagueVerbWithoutSpecifics:
    """Test vague verb detection."""

    def test_improve_without_specifics_is_vague(self):
        """'Improve' without specifics is vague."""
        assert _has_vague_verb_without_specifics("Improve authentication") is True

    def test_fix_without_specifics_is_vague(self):
        """'Fix' without specifics is vague."""
        assert _has_vague_verb_without_specifics("Fix the bug") is True

    def test_fix_with_file_not_vague(self):
        """'Fix' with file reference is not vague."""
        assert _has_vague_verb_without_specifics("Fix auth/tokens.py") is False

    def test_fix_with_function_not_vague(self):
        """'Fix' with function reference is not vague."""
        assert _has_vague_verb_without_specifics("Fix generate_token() method") is False

    def test_fix_with_line_number_not_vague(self):
        """'Fix' with line number is not vague."""
        assert _has_vague_verb_without_specifics("Fix line 45") is False

    def test_fix_with_error_not_vague(self):
        """'Fix' with error message is not vague."""
        assert _has_vague_verb_without_specifics("Fix error: TypeError in auth") is False

    def test_no_vague_verb_not_vague(self):
        """Description without vague verbs is not vague."""
        assert _has_vague_verb_without_specifics("Implement JWT validation") is False


class TestReferencesSimilarityWithoutExamples:
    """Test similarity reference detection."""

    def test_similar_without_examples_is_true(self):
        """'Similar to' without code snippets returns True."""
        assert _references_similarity_without_examples("Implement similar to user auth", []) is True

    def test_similar_with_examples_is_false(self):
        """'Similar to' WITH code snippets returns False."""
        assert (
            _references_similarity_without_examples("Implement similar to user auth", ["def auth()"]) is False
        )

    def test_like_without_examples_is_true(self):
        """'Like in' without code snippets returns True."""
        assert _references_similarity_without_examples("Create like in module X", []) is True

    def test_no_similarity_reference_is_false(self):
        """No similarity reference returns False."""
        assert _references_similarity_without_examples("Implement authentication", []) is False


class TestFormatExplorerPrompt:
    """Test explorer prompt formatting."""

    def test_formats_file_discovery_prompt(self):
        """Should format file_discovery prompt."""
        task = {"description": "Update authentication system"}
        templates = {
            "file_discovery": "Find files for {topic}",
            "context_enrichment": "Explore {area}",
        }

        prompt = format_explorer_prompt("file_discovery", task, templates)
        assert "authentication system" in prompt

    def test_formats_pattern_matching_prompt(self):
        """Should format pattern_matching prompt."""
        task = {"description": "Implement similar to user validation"}
        templates = {
            "pattern_matching": "Find patterns for {feature}",
            "context_enrichment": "Explore {area}",
        }

        prompt = format_explorer_prompt("pattern_matching", task, templates)
        assert "user validation" in prompt

    def test_uses_default_template_for_unknown_type(self):
        """Should fall back to context_enrichment for unknown types."""
        task = {"description": "Fix auth"}
        templates = {
            "context_enrichment": "Explore {area}",
        }

        prompt = format_explorer_prompt("unknown_type", task, templates)
        assert "auth" in prompt


class TestFormatImplementerPrompt:
    """Test implementer prompt formatting."""

    def test_formats_without_exploration(self):
        """Should format prompt without exploration context."""
        task = {"description": "Implement JWT validation", "requirements": ["Must validate signature", "Check expiry"]}
        context = {"files_read": []}
        templates = {
            "without_exploration": "Task: {task_description}\n\nRequirements:\n{requirements}",
        }

        prompt = format_implementer_prompt(task, context, with_exploration=False, templates=templates)
        assert "Implement JWT validation" in prompt
        assert "Must validate signature" in prompt
        assert "Check expiry" in prompt

    def test_formats_with_exploration(self):
        """Should format prompt with exploration context."""
        task = {"description": "Implement JWT validation"}
        context = {
            "exploration": "Found auth/jwt.py with validate_token()",
            "requirements": ["Must validate signature"],
            "suggested_files": "auth/jwt.py",
        }
        templates = {
            "with_exploration": """Task: {task_description}

Exploration: {explorer_output}

Requirements: {requirements}

Files: {suggested_files}""",
        }

        prompt = format_implementer_prompt(task, context, with_exploration=True, templates=templates)
        assert "Implement JWT validation" in prompt
        assert "Found auth/jwt.py" in prompt
        assert "Must validate signature" in prompt
        assert "auth/jwt.py" in prompt

    def test_handles_list_requirements(self):
        """Should convert list requirements to bullet points."""
        task = {"description": "Fix auth", "requirements": ["Requirement 1", "Requirement 2"]}
        context = {}
        templates = {
            "without_exploration": "Requirements:\n{requirements}",
        }

        prompt = format_implementer_prompt(task, context, with_exploration=False, templates=templates)
        assert "- Requirement 1" in prompt
        assert "- Requirement 2" in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
