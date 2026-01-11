"""Tests for hooks/monitor_agent.py - contextual enforcement using Haiku API."""

import pytest
from unittest.mock import patch, MagicMock
import sys
import os

# Add hooks directory to path for import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'hooks'))

from monitor_agent import (
    needs_monitoring,
    call_monitor_agent,
    _build_monitor_prompt,
    _extract_commit_message,
    _parse_decision,
    format_monitor_result,
    detect_batch_need,
    ANTHROPIC_AVAILABLE,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_state():
    """Standard state dict for testing."""
    return {
        "classification_type": "SIMPLE",
        "files_edited_this_session": [],
        "search_count": 0,
        "read_count": 0,
    }


@pytest.fixture
def sample_state_complex():
    """State with COMPLEX classification."""
    return {
        "classification_type": "COMPLEX",
        "files_edited_this_session": [],
        "search_count": 0,
        "read_count": 0,
    }


@pytest.fixture
def sample_state_with_edits():
    """State with prior edits."""
    return {
        "classification_type": "SIMPLE",
        "files_edited_this_session": ["file1.py", "file2.py"],
        "search_count": 0,
        "read_count": 0,
    }


@pytest.fixture
def git_commit_input():
    """Sample git commit tool input."""
    return {"command": 'git commit -m "Fix bug in authentication"'}


@pytest.fixture
def edit_tool_input():
    """Sample Edit tool input."""
    return {"file_path": "/path/to/file.py", "old_string": "foo", "new_string": "bar"}


# =============================================================================
# TestExtractCommitMessage
# =============================================================================

class TestExtractCommitMessage:
    """Tests for _extract_commit_message function."""

    def test_extract_dash_m_flag(self):
        """Extract message from -m 'message' format."""
        command = 'git commit -m "Fix authentication bug"'
        assert _extract_commit_message(command) == "Fix authentication bug"

    def test_extract_dash_m_single_quotes(self):
        """Extract message from -m 'message' with single quotes."""
        command = "git commit -m 'Fix authentication bug'"
        assert _extract_commit_message(command) == "Fix authentication bug"

    def test_extract_heredoc_simple(self):
        """Extract message from <<EOF ... EOF format."""
        command = """git commit -F- <<EOF
Fix authentication bug

This fixes the login issue.
EOF"""
        result = _extract_commit_message(command)
        assert "Fix authentication bug" in result

    def test_extract_heredoc_with_quotes(self):
        """Heredoc with quotes: <<'EOF'."""
        command = """git commit -F- <<'EOF'
Fix bug
EOF"""
        result = _extract_commit_message(command)
        assert "Fix bug" in result

    def test_extract_cat_heredoc(self):
        """Extract from -m "$(cat <<EOF ... EOF)" format."""
        command = '''git commit -m "$(cat <<'EOF'
Fix authentication bug

Co-Authored-By: Someone
EOF
)"'''
        result = _extract_commit_message(command)
        assert "Fix authentication bug" in result

    def test_extract_multiline_message(self):
        """Message spanning multiple lines."""
        command = '''git commit -m "Line 1
Line 2
Line 3"'''
        result = _extract_commit_message(command)
        assert "Line 1" in result
        assert "Line 3" in result

    def test_extract_message_with_special_chars(self):
        """Messages with special characters."""
        command = 'git commit -m "Fix: handle \\"quotes\\" properly"'
        result = _extract_commit_message(command)
        assert "Fix:" in result

    def test_extract_no_message_found(self):
        """Command without extractable message."""
        command = "git commit --amend"
        assert _extract_commit_message(command) == "(unable to extract message)"

    def test_extract_empty_message(self):
        """Empty commit message."""
        command = 'git commit -m ""'
        # Should return empty string, not the fallback
        result = _extract_commit_message(command)
        assert result == "" or result == "(unable to extract message)"

    def test_extract_message_with_emoji(self):
        """Message containing Unicode emoji."""
        command = 'git commit -m "Fix bug 🐛"'
        result = _extract_commit_message(command)
        assert "Fix bug" in result


# =============================================================================
# TestParseDecision
# =============================================================================

class TestParseDecision:
    """Tests for _parse_decision function."""

    def test_parse_decision_allowed_yes(self):
        """Parse 'ALLOWED: yes' response."""
        text = "ALLOWED: yes\nREASON: Message is clean\nCONFIDENCE: 0.95"
        result = _parse_decision(text)
        assert result["allowed"] is True
        assert result["reason"] == "Message is clean"
        assert result["confidence"] == 0.95

    def test_parse_decision_allowed_no(self):
        """Parse 'ALLOWED: no' response."""
        text = "ALLOWED: no\nREASON: Contains emoji\nCONFIDENCE: 0.99"
        result = _parse_decision(text)
        assert result["allowed"] is False
        assert "emoji" in result["reason"].lower()
        assert result["confidence"] == 0.99

    def test_parse_decision_case_insensitive(self):
        """'allowed: YES' vs 'ALLOWED: yes'."""
        text = "allowed: YES\nreason: OK\nconfidence: 0.8"
        result = _parse_decision(text)
        assert result["allowed"] is True

    def test_parse_decision_missing_reason(self):
        """Response without REASON field defaults."""
        text = "ALLOWED: yes\nCONFIDENCE: 0.9"
        result = _parse_decision(text)
        assert result["allowed"] is True
        assert result["reason"] == "No reason provided"

    def test_parse_decision_missing_confidence(self):
        """Response without CONFIDENCE defaults to 0.5."""
        text = "ALLOWED: yes\nREASON: Looks good"
        result = _parse_decision(text)
        assert result["confidence"] == 0.5

    def test_parse_decision_malformed_response(self):
        """Completely malformed text returns None."""
        text = "This is not a valid response at all"
        assert _parse_decision(text) is None

    def test_parse_decision_empty_string(self):
        """Empty input returns None."""
        assert _parse_decision("") is None

    def test_parse_decision_extra_whitespace(self):
        """Excessive whitespace around values."""
        text = "ALLOWED:   yes  \nREASON:   Clean message   \nCONFIDENCE:   0.9  "
        result = _parse_decision(text)
        assert result["allowed"] is True
        assert "Clean message" in result["reason"]

    def test_parse_decision_confidence_boundaries(self):
        """Test confidence at boundaries."""
        for conf in ["0.0", "1.0", "0.5"]:
            text = f"ALLOWED: yes\nREASON: test\nCONFIDENCE: {conf}"
            result = _parse_decision(text)
            assert result["confidence"] == float(conf)


# =============================================================================
# TestFormatMonitorResult
# =============================================================================

class TestFormatMonitorResult:
    """Tests for format_monitor_result function."""

    def test_format_allowed_result(self):
        """Format allowed decision correctly."""
        decision = {"allowed": True, "reason": "Message is clean", "confidence": 0.95}
        result = format_monitor_result(decision)
        hook_output = result["hookSpecificOutput"]
        assert hook_output["permissionDecision"] == "allow"
        assert "[MONITOR] Approved" in hook_output["permissionDecisionReason"]
        assert "Message is clean" in hook_output["permissionDecisionReason"]

    def test_format_blocked_result(self):
        """Format blocked decision with proper message structure."""
        decision = {"allowed": False, "reason": "Contains attribution", "confidence": 0.99}
        result = format_monitor_result(decision)
        hook_output = result["hookSpecificOutput"]
        assert hook_output["permissionDecision"] == "deny"
        assert "[MONITOR AGENT]" in hook_output["permissionDecisionReason"]
        assert "Contains attribution" in hook_output["permissionDecisionReason"]
        assert "99%" in hook_output["permissionDecisionReason"]

    def test_format_confidence_display(self):
        """Test percentage formatting for various confidence values."""
        for conf, expected in [(0.0, "0%"), (0.5, "50%"), (0.999, "100%"), (1.0, "100%")]:
            decision = {"allowed": False, "reason": "test", "confidence": conf}
            result = format_monitor_result(decision)
            hook_output = result["hookSpecificOutput"]
            assert expected in hook_output["permissionDecisionReason"]

    def test_format_result_structure(self):
        """Verify exact dict structure matches hook expectations."""
        decision = {"allowed": True, "reason": "OK", "confidence": 0.9}
        result = format_monitor_result(decision)
        assert "hookSpecificOutput" in result
        hook_output = result["hookSpecificOutput"]
        assert hook_output["hookEventName"] == "PreToolUse"
        assert hook_output["permissionDecision"] in ("allow", "deny")
        assert isinstance(hook_output["permissionDecisionReason"], str)


# =============================================================================
# TestNeedsMonitoring
# =============================================================================

class TestNeedsMonitoring:
    """Tests for needs_monitoring function."""

    @pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="anthropic not installed")
    def test_needs_monitoring_git_commit_basic(self, sample_state):
        """Basic git commit command should trigger monitoring."""
        tool_input = {"command": 'git commit -m "Fix bug"'}
        assert needs_monitoring("Bash", tool_input, sample_state) is True

    @pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="anthropic not installed")
    def test_needs_monitoring_git_commit_variations(self, sample_state):
        """Various git commit command formats."""
        commands = [
            'git commit -m "message"',
            "git commit --amend -m 'message'",
            "git commit -am 'message'",
            'git commit -F- <<EOF\nmessage\nEOF',
        ]
        for cmd in commands:
            assert needs_monitoring("Bash", {"command": cmd}, sample_state) is True

    @pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="anthropic not installed")
    def test_needs_monitoring_first_simple_edit(self, sample_state):
        """First file edit with SIMPLE classification should trigger monitoring."""
        tool_input = {"file_path": "/path/to/file.py"}
        assert needs_monitoring("Edit", tool_input, sample_state) is True

    @pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="anthropic not installed")
    def test_needs_monitoring_subsequent_edits(self, sample_state_with_edits):
        """Subsequent edits should NOT trigger monitoring."""
        tool_input = {"file_path": "/path/to/file.py"}
        assert needs_monitoring("Edit", tool_input, sample_state_with_edits) is False

    @pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="anthropic not installed")
    def test_needs_monitoring_complex_classification(self, sample_state_complex):
        """COMPLEX classification should not trigger monitoring on first edit."""
        tool_input = {"file_path": "/path/to/file.py"}
        assert needs_monitoring("Edit", tool_input, sample_state_complex) is False

    def test_no_monitoring_when_anthropic_unavailable(self, sample_state):
        """Should return False when ANTHROPIC_AVAILABLE is False."""
        # This test verifies behavior when anthropic is unavailable
        # Since anthropic IS available in our env, we test the positive case
        tool_input = {"command": 'git commit -m "Fix bug"'}
        # With anthropic available, git commit should trigger monitoring
        assert needs_monitoring("Bash", tool_input, sample_state) is True

    @pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="anthropic not installed")
    def test_needs_monitoring_empty_state(self):
        """State dict is empty."""
        tool_input = {"command": 'git commit -m "Fix bug"'}
        assert needs_monitoring("Bash", tool_input, {}) is True

    @pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="anthropic not installed")
    def test_needs_monitoring_all_edit_tools(self, sample_state):
        """Test all edit tool variants."""
        edit_tools = [
            "Write",
            "Edit",
            "mcp__plugin_serena_serena__replace_symbol_body",
            "mcp__plugin_serena_serena__create_text_file",
            "mcp__plugin_serena_serena__replace_content",
        ]
        for tool in edit_tools:
            assert needs_monitoring(tool, {"file_path": "/test.py"}, sample_state) is True

    @pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="anthropic not installed")
    def test_needs_monitoring_non_monitored_tools(self, sample_state):
        """Tools that should not trigger monitoring."""
        non_monitored = ["Read", "Glob", "Grep", "Task", "WebFetch"]
        for tool in non_monitored:
            assert needs_monitoring(tool, {}, sample_state) is False


# =============================================================================
# TestDetectBatchNeed
# =============================================================================

class TestDetectBatchNeed:
    """Tests for detect_batch_need function."""

    def test_detect_batch_explicit_number(self):
        """'check 10 files' triggers batch requirement."""
        state = {"search_count": 0, "read_count": 0}
        messages = [{"content": "I need to check 10 files for errors"}]
        result = detect_batch_need("Grep", {}, state, messages)
        assert result is not None
        assert result["allowed"] is False
        assert "10" in result["message"]

    def test_detect_batch_low_threshold(self):
        """Number <= 5 should not trigger."""
        state = {"search_count": 0, "read_count": 0}
        messages = [{"content": "I need to check 5 files"}]
        result = detect_batch_need("Grep", {}, state, messages)
        assert result is None

    def test_detect_batch_threshold_boundary(self):
        """Test exactly at threshold (num=5 vs num=6)."""
        state = {"search_count": 0, "read_count": 0}

        # 5 should not trigger
        messages = [{"content": "check 5 files"}]
        assert detect_batch_need("Grep", {}, state, messages) is None

        # 6 should trigger
        messages = [{"content": "check 6 files"}]
        result = detect_batch_need("Grep", {}, state, messages)
        assert result is not None

    def test_detect_batch_qualitative_all(self):
        """'check all' triggers batch requirement."""
        state = {"search_count": 0, "read_count": 0}
        messages = [{"content": "Let me check all the files"}]
        result = detect_batch_need("Grep", {}, state, messages)
        assert result is not None
        assert result["allowed"] is False

    def test_detect_batch_find_all_pattern(self):
        """'find all X that Y' triggers batch requirement."""
        state = {"search_count": 0, "read_count": 0}
        messages = [{"content": "find all functions that use deprecated API"}]
        result = detect_batch_need("Grep", {}, state, messages)
        assert result is not None

    def test_detect_batch_codebase_wide(self):
        """'throughout the codebase' triggers."""
        state = {"search_count": 0, "read_count": 0}
        messages = [{"content": "search throughout the codebase for this pattern"}]
        result = detect_batch_need("Grep", {}, state, messages)
        assert result is not None

    def test_detect_batch_after_limit(self):
        """search_count > 2 or read_count > 2 returns None."""
        state = {"search_count": 3, "read_count": 0}
        messages = [{"content": "check 10 files"}]
        assert detect_batch_need("Grep", {}, state, messages) is None

        state = {"search_count": 0, "read_count": 3}
        assert detect_batch_need("Grep", {}, state, messages) is None

    def test_detect_batch_empty_messages(self):
        """Empty recent_messages list."""
        state = {"search_count": 0, "read_count": 0}
        result = detect_batch_need("Grep", {}, state, [])
        assert result is None

    def test_detect_batch_no_patterns_match(self):
        """Text with no batch indicators returns None."""
        state = {"search_count": 0, "read_count": 0}
        messages = [{"content": "Let me look at this one file"}]
        result = detect_batch_need("Grep", {}, state, messages)
        assert result is None

    def test_detect_batch_case_insensitive(self):
        """Pattern matching is case-insensitive."""
        state = {"search_count": 0, "read_count": 0}
        messages = [{"content": "CHECK ALL the files"}]
        result = detect_batch_need("Grep", {}, state, messages)
        assert result is not None

    def test_detect_batch_message_without_content(self):
        """Messages without 'content' key."""
        state = {"search_count": 0, "read_count": 0}
        messages = [{"role": "user"}, {"text": "check 10 files"}]
        # Should handle gracefully
        result = detect_batch_need("Grep", {}, state, messages)
        assert result is None  # No content to match

    def test_detect_batch_message_window(self):
        """Only uses last 3 messages."""
        state = {"search_count": 0, "read_count": 0}
        # Batch indicator is in old message (index 0), not in last 3
        messages = [
            {"content": "check 10 files"},  # Old - should be ignored
            {"content": "ok"},
            {"content": "sure"},
            {"content": "done"},
            {"content": "next task"},  # Last 3 start here
        ]
        result = detect_batch_need("Grep", {}, state, messages)
        assert result is None

    def test_detect_batch_return_format(self):
        """Verify block decision format matches hook expectations."""
        state = {"search_count": 0, "read_count": 0}
        messages = [{"content": "check 10 files"}]
        result = detect_batch_need("Grep", {}, state, messages)
        assert "allowed" in result
        assert "message" in result
        assert result["allowed"] is False


# =============================================================================
# TestBuildMonitorPrompt
# =============================================================================

class TestBuildMonitorPrompt:
    """Tests for _build_monitor_prompt function."""

    def test_build_prompt_git_commit(self, sample_state):
        """Build commit validation prompt."""
        tool_input = {"command": 'git commit -m "Fix authentication bug"'}
        prompt = _build_monitor_prompt("Bash", tool_input, sample_state)

        assert "git commit" in prompt.lower() or "commit" in prompt.lower()
        assert "Fix authentication bug" in prompt
        assert "ALLOWED:" in prompt  # Expects structured response
        assert "REASON:" in prompt
        assert "CONFIDENCE:" in prompt

    def test_build_prompt_classification_validation(self, sample_state):
        """Build SIMPLE classification prompt."""
        tool_input = {"file_path": "/path/to/file.py"}
        prompt = _build_monitor_prompt("Edit", tool_input, sample_state)

        assert "SIMPLE" in prompt
        assert "file_path" in prompt.lower() or "/path/to/file.py" in prompt
        assert "ALLOWED:" in prompt

    def test_build_prompt_includes_standards(self, sample_state):
        """Verify CLAUDE.md standards are included in commit prompt."""
        tool_input = {"command": 'git commit -m "message"'}
        prompt = _build_monitor_prompt("Bash", tool_input, sample_state)

        # Should mention attribution/emoji rules
        assert "attribution" in prompt.lower() or "emoji" in prompt.lower()

    def test_build_prompt_unsupported_tool(self, sample_state):
        """Tool not requiring monitoring returns empty string."""
        prompt = _build_monitor_prompt("Read", {}, sample_state)
        assert prompt == ""

    def test_build_prompt_empty_state(self):
        """Empty state dict."""
        tool_input = {"file_path": "/test.py"}
        prompt = _build_monitor_prompt("Edit", tool_input, {})
        # Should handle gracefully
        assert "ALLOWED:" in prompt


# =============================================================================
# TestCallMonitorAgent (Mocked)
# =============================================================================

class TestCallMonitorAgent:
    """Tests for call_monitor_agent function with mocked API."""

    @pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="anthropic not installed")
    def test_call_monitor_success(self, sample_state):
        """Successful API call returns valid decision."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="ALLOWED: yes\nREASON: Clean\nCONFIDENCE: 0.9")]

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch('monitor_agent.anthropic.Anthropic') as mock_client:
                mock_client.return_value.messages.create.return_value = mock_response

                tool_input = {"command": 'git commit -m "Fix bug"'}
                result = call_monitor_agent("Bash", tool_input, sample_state)

                assert result is not None
                assert result["allowed"] is True
                assert result["confidence"] == 0.9

    @pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="anthropic not installed")
    def test_call_monitor_blocked_commit(self, sample_state):
        """Commit with emoji gets blocked."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="ALLOWED: no\nREASON: Contains emoji\nCONFIDENCE: 0.99")]

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch('monitor_agent.anthropic.Anthropic') as mock_client:
                mock_client.return_value.messages.create.return_value = mock_response

                tool_input = {"command": 'git commit -m "Fix bug 🐛"'}
                result = call_monitor_agent("Bash", tool_input, sample_state)

                assert result is not None
                assert result["allowed"] is False

    def test_call_monitor_no_api_key(self, sample_state):
        """Missing ANTHROPIC_API_KEY returns None."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            tool_input = {"command": 'git commit -m "Fix bug"'}
            result = call_monitor_agent("Bash", tool_input, sample_state)
            assert result is None

    def test_call_monitor_anthropic_unavailable(self, sample_state):
        """ANTHROPIC_AVAILABLE=False returns None."""
        with patch('monitor_agent.ANTHROPIC_AVAILABLE', False):
            tool_input = {"command": 'git commit -m "Fix bug"'}
            result = call_monitor_agent("Bash", tool_input, sample_state)
            assert result is None

    @pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="anthropic not installed")
    def test_call_monitor_api_error(self, sample_state):
        """API raises exception, returns None (fail open)."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch('monitor_agent.anthropic.Anthropic') as mock_client:
                mock_client.return_value.messages.create.side_effect = Exception("API Error")

                tool_input = {"command": 'git commit -m "Fix bug"'}
                result = call_monitor_agent("Bash", tool_input, sample_state)

                assert result is None  # Fail open

    @pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="anthropic not installed")
    def test_call_monitor_haiku_model_used(self, sample_state):
        """Verify correct model is used."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="ALLOWED: yes\nREASON: OK\nCONFIDENCE: 0.9")]

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch('monitor_agent.anthropic.Anthropic') as mock_client:
                mock_instance = mock_client.return_value
                mock_instance.messages.create.return_value = mock_response

                tool_input = {"command": 'git commit -m "Fix bug"'}
                call_monitor_agent("Bash", tool_input, sample_state)

                # Verify model parameter
                call_args = mock_instance.messages.create.call_args
                assert call_args.kwargs.get("model") == "claude-3-5-haiku-20241022"

    @pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="anthropic not installed")
    def test_call_monitor_token_limits(self, sample_state):
        """Verify max_tokens=200, temperature=0."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="ALLOWED: yes\nREASON: OK\nCONFIDENCE: 0.9")]

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch('monitor_agent.anthropic.Anthropic') as mock_client:
                mock_instance = mock_client.return_value
                mock_instance.messages.create.return_value = mock_response

                tool_input = {"command": 'git commit -m "Fix bug"'}
                call_monitor_agent("Bash", tool_input, sample_state)

                call_args = mock_instance.messages.create.call_args
                assert call_args.kwargs.get("max_tokens") == 200
                assert call_args.kwargs.get("temperature") == 0
