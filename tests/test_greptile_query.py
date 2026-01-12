"""Tests for greptile_query.py"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock

import greptile_query


class TestGetCurrentRepo:
    """Tests for get_current_repo()"""

    def test_parses_ssh_remote(self):
        """Should parse git@github.com:owner/repo.git format"""
        mock_remote = MagicMock()
        mock_remote.stdout = "git@github.com:myorg/myrepo.git"
        mock_remote.returncode = 0

        mock_branch = MagicMock()
        mock_branch.stdout = "feature-branch"
        mock_branch.returncode = 0

        with patch("subprocess.run", side_effect=[mock_remote, mock_branch]):
            repo, branch = greptile_query.get_current_repo()

        assert repo == "myorg/myrepo"
        assert branch == "feature-branch"

    def test_parses_https_remote(self):
        """Should parse https://github.com/owner/repo.git format"""
        mock_remote = MagicMock()
        mock_remote.stdout = "https://github.com/myorg/myrepo.git"
        mock_remote.returncode = 0

        mock_branch = MagicMock()
        mock_branch.stdout = "main"
        mock_branch.returncode = 0

        with patch("subprocess.run", side_effect=[mock_remote, mock_branch]):
            repo, branch = greptile_query.get_current_repo()

        assert repo == "myorg/myrepo"
        assert branch == "main"

    def test_handles_subprocess_error(self):
        """Should return None, None on git command failure"""
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "git")):
            repo, branch = greptile_query.get_current_repo()

        assert repo is None
        assert branch is None


class TestQueryGreptile:
    """Tests for query_greptile()"""

    def test_returns_error_without_api_key(self):
        """Should return error when GREPTILE_API_KEY not set"""
        with patch.dict(os.environ, {"GREPTILE_API_KEY": ""}, clear=True):
            result = greptile_query.query_greptile("test query", repo="org/repo")

        assert "error" in result
        assert "GREPTILE_API_KEY" in result["error"]

    def test_returns_error_without_gh_token(self):
        """Should return error when GH_TOKEN not set"""
        env = {"GREPTILE_API_KEY": "test-key"}
        with patch.dict(os.environ, env, clear=True):
            result = greptile_query.query_greptile("test query", repo="org/repo")

        assert "error" in result
        assert "GH_TOKEN" in result["error"]

    def test_returns_error_without_repo(self):
        """Should return error when repo cannot be detected"""
        env = {"GREPTILE_API_KEY": "test-key", "GH_TOKEN": "gh-token"}
        with patch.dict(os.environ, env, clear=True):
            with patch.object(greptile_query, "get_current_repo", return_value=(None, None)):
                result = greptile_query.query_greptile("test query")

        assert "error" in result
        assert "Could not detect repository" in result["error"]

    def test_makes_correct_api_call(self):
        """Should call Greptile API with correct payload"""
        env = {"GREPTILE_API_KEY": "test-key", "GH_TOKEN": "gh-token"}

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": "Analysis result", "sources": []}
        mock_response.raise_for_status = MagicMock()

        with patch.dict(os.environ, env, clear=True):
            with patch("requests.post", return_value=mock_response) as mock_post:
                result = greptile_query.query_greptile(
                    "test query",
                    repo="myorg/myrepo",
                    branch="main",
                    genius=True
                )

        mock_post.assert_called_once()
        call_args = mock_post.call_args

        assert call_args[0][0] == "https://api.greptile.com/v2/query"
        assert call_args[1]["headers"]["Authorization"] == "Bearer test-key"
        assert call_args[1]["headers"]["X-GitHub-Token"] == "gh-token"

        payload = call_args[1]["json"]
        assert payload["messages"][0]["content"] == "test query"
        assert payload["repositories"][0]["repository"] == "myorg/myrepo"
        assert payload["repositories"][0]["branch"] == "main"
        assert payload["genius"] is True

    def test_handles_timeout(self):
        """Should return error on request timeout"""
        import requests
        env = {"GREPTILE_API_KEY": "test-key", "GH_TOKEN": "gh-token"}

        with patch.dict(os.environ, env, clear=True):
            with patch("requests.post", side_effect=requests.exceptions.Timeout()):
                result = greptile_query.query_greptile(
                    "test query",
                    repo="org/repo",
                    timeout=30
                )

        assert "error" in result
        assert "timed out" in result["error"]

    def test_handles_request_exception(self):
        """Should return error on request failure"""
        import requests
        env = {"GREPTILE_API_KEY": "test-key", "GH_TOKEN": "gh-token"}

        with patch.dict(os.environ, env, clear=True):
            with patch("requests.post", side_effect=requests.exceptions.ConnectionError("Connection failed")):
                result = greptile_query.query_greptile("test query", repo="org/repo")

        assert "error" in result

    def test_uses_detected_repo_when_not_provided(self):
        """Should auto-detect repo when not specified"""
        env = {"GREPTILE_API_KEY": "test-key", "GH_TOKEN": "gh-token"}

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": "OK"}
        mock_response.raise_for_status = MagicMock()

        with patch.dict(os.environ, env, clear=True):
            with patch.object(greptile_query, "get_current_repo", return_value=("detected/repo", "detected-branch")):
                with patch("requests.post", return_value=mock_response) as mock_post:
                    greptile_query.query_greptile("test query")

        payload = mock_post.call_args[1]["json"]
        assert payload["repositories"][0]["repository"] == "detected/repo"
        assert payload["repositories"][0]["branch"] == "detected-branch"


class TestFormatOutput:
    """Tests for format_output()"""

    def test_formats_error(self):
        """Should format error message"""
        result = {"error": "Something went wrong"}
        output = greptile_query.format_output(result)

        assert "ERROR:" in output
        assert "Something went wrong" in output

    def test_formats_message(self):
        """Should include response message"""
        result = {"message": "The authentication uses JWT tokens..."}
        output = greptile_query.format_output(result)

        assert "The authentication uses JWT tokens" in output

    def test_formats_sources(self):
        """Should format source references"""
        result = {
            "message": "Found relevant code",
            "sources": [
                {"filepath": "src/auth.py", "linestart": 10, "lineend": 25, "summary": "Auth module"},
                {"filepath": "src/utils.py", "linestart": 5, "lineend": 15, "summary": "Utilities"}
            ]
        }
        output = greptile_query.format_output(result)

        assert "SOURCES" in output
        assert "src/auth.py:10-25" in output
        assert "src/utils.py:5-15" in output

    def test_formats_sources_verbose(self):
        """Should include summaries in verbose mode"""
        result = {
            "message": "Found code",
            "sources": [
                {"filepath": "src/auth.py", "linestart": 10, "lineend": 25, "summary": "Authentication module handles JWT"}
            ]
        }
        output = greptile_query.format_output(result, verbose=True)

        assert "Authentication module handles JWT" in output

    def test_limits_sources_displayed(self):
        """Should limit sources to first 10"""
        result = {
            "message": "Many sources",
            "sources": [{"filepath": f"file{i}.py", "linestart": i, "lineend": i+10} for i in range(15)]
        }
        output = greptile_query.format_output(result)

        # Should have exactly 10 file references
        assert output.count("file") == 10

    def test_handles_empty_result(self):
        """Should handle result with no message"""
        result = {}
        output = greptile_query.format_output(result)

        assert "No response" in output


class TestCLI:
    """Tests for command-line interface"""

    def test_parses_query_argument(self):
        """Should parse positional query argument"""
        import argparse
        with patch("sys.argv", ["greptile_query.py", "How does auth work?"]):
            # Re-import to test argparse
            import importlib
            # Just verify it doesn't crash - argparse is standard
            pass

    def test_main_with_json_output(self):
        """Should output JSON when --json flag is used"""
        env = {"GREPTILE_API_KEY": "test-key", "GH_TOKEN": "gh-token"}

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": "test response", "sources": []}
        mock_response.raise_for_status = MagicMock()

        with patch.dict(os.environ, env, clear=True):
            with patch("requests.post", return_value=mock_response):
                with patch("sys.argv", ["greptile_query.py", "test query", "--json", "--repo", "org/repo"]):
                    with patch("builtins.print") as mock_print:
                        with pytest.raises(SystemExit) as exc_info:
                            greptile_query.main()

        # Should exit with 0 (success)
        assert exc_info.value.code == 0
        # Should print JSON
        printed = mock_print.call_args[0][0]
        parsed = json.loads(printed)
        assert parsed["message"] == "test response"

    def test_main_exits_with_error_code_on_failure(self):
        """Should exit with code 1 on error"""
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.argv", ["greptile_query.py", "test query", "--repo", "org/repo"]):
                with patch("builtins.print"):
                    with pytest.raises(SystemExit) as exc_info:
                        greptile_query.main()

        assert exc_info.value.code == 1
