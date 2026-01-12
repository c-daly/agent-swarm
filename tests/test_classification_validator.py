"""Tests for classification validator."""

import pytest
from lib.classification_validator import validate_classification, ARCHITECTURAL_KEYWORDS


class TestValidateClassification:
    """Test suite for validate_classification function."""

    def test_simple_single_file_valid(self):
        """SIMPLE classification with single file should be valid."""
        valid, reason = validate_classification(
            claimed="SIMPLE",
            task="Fix typo in config file",
            state={"files_edited_this_session": ["config.py"]}
        )
        assert valid is True
        assert reason == "OK"

    def test_simple_multiple_files_invalid(self):
        """SIMPLE classification with multiple files should be invalid."""
        valid, reason = validate_classification(
            claimed="SIMPLE",
            task="Update configuration",
            state={"files_edited_this_session": ["config.py", "utils.py", "main.py"]}
        )
        assert valid is False
        assert "SIMPLE allows 1 file, edited 3" in reason
        assert "/iterate or /orchestrate" in reason

    def test_simple_no_files_valid(self):
        """SIMPLE classification with no files edited should be valid."""
        valid, reason = validate_classification(
            claimed="SIMPLE",
            task="Research issue",
            state={"files_edited_this_session": []}
        )
        assert valid is True
        assert reason == "OK"

    def test_simple_missing_files_key_valid(self):
        """SIMPLE classification with missing files_edited_this_session key should be valid."""
        valid, reason = validate_classification(
            claimed="SIMPLE",
            task="Read code",
            state={}
        )
        assert valid is True
        assert reason == "OK"

    @pytest.mark.parametrize("keyword", ARCHITECTURAL_KEYWORDS)
    def test_trivial_architectural_keywords_invalid(self, keyword):
        """TRIVIAL classification with architectural keywords should be invalid."""
        valid, reason = validate_classification(
            claimed="TRIVIAL",
            task=f"We need to {keyword} the system",
            state={}
        )
        assert valid is False
        assert f"'{keyword}' requires COMPLEX classification" in reason

    @pytest.mark.parametrize("keyword", ARCHITECTURAL_KEYWORDS)
    def test_simple_architectural_keywords_invalid(self, keyword):
        """SIMPLE classification with architectural keywords should be invalid."""
        valid, reason = validate_classification(
            claimed="SIMPLE",
            task=f"Let's {keyword} the module",
            state={"files_edited_this_session": ["module.py"]}
        )
        assert valid is False
        assert f"'{keyword}' requires COMPLEX classification" in reason

    def test_architectural_keyword_case_insensitive(self):
        """Architectural keyword detection should be case-insensitive."""
        valid, reason = validate_classification(
            claimed="SIMPLE",
            task="REFACTOR the utility functions",
            state={"files_edited_this_session": ["utils.py"]}
        )
        assert valid is False
        assert "'refactor' requires COMPLEX classification" in reason

    def test_complex_multiple_files_valid(self):
        """COMPLEX classification with multiple files should be valid."""
        valid, reason = validate_classification(
            claimed="COMPLEX",
            task="Refactor authentication system",
            state={"files_edited_this_session": ["auth.py", "user.py", "session.py"]}
        )
        assert valid is True
        assert reason == "OK"

    def test_complex_architectural_keywords_valid(self):
        """COMPLEX classification with architectural keywords should be valid."""
        valid, reason = validate_classification(
            claimed="COMPLEX",
            task="Migrate from REST to GraphQL",
            state={}
        )
        assert valid is True
        assert reason == "OK"

    def test_research_classification_valid(self):
        """RESEARCH classification should always be valid."""
        valid, reason = validate_classification(
            claimed="RESEARCH",
            task="Explore codebase architecture",
            state={}
        )
        assert valid is True
        assert reason == "OK"

    def test_conversation_classification_valid(self):
        """CONVERSATION classification should always be valid."""
        valid, reason = validate_classification(
            claimed="CONVERSATION",
            task="Discuss design options",
            state={}
        )
        assert valid is True
        assert reason == "OK"

    def test_empty_task_valid(self):
        """Empty task should be valid (no architectural keywords)."""
        valid, reason = validate_classification(
            claimed="SIMPLE",
            task="",
            state={"files_edited_this_session": ["file.py"]}
        )
        assert valid is True
        assert reason == "OK"

    def test_architectural_keyword_in_word(self):
        """Architectural keywords should match within words."""
        valid, reason = validate_classification(
            claimed="SIMPLE",
            task="Refactoring utility module",
            state={"files_edited_this_session": ["utils.py"]}
        )
        assert valid is False
        assert "'refactor' requires COMPLEX classification" in reason

    def test_trivial_no_files_no_keywords_valid(self):
        """TRIVIAL with no files and no keywords should be valid."""
        valid, reason = validate_classification(
            claimed="TRIVIAL",
            task="Fix comment typo",
            state={}
        )
        assert valid is True
        assert reason == "OK"
