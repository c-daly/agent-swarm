# tests/test_audit/test_cli.py
"""Tests for the test audit CLI."""
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from lib.test_audit.cli import interactive_review
from lib.test_audit.decision_engine import DecisionResult, HealthScore, Verdict


def test_cli_dry_run_outputs_summary(tmp_path: Path):
    """CLI should analyze test files and output summary."""
    # Create a test file
    test_file = tmp_path / "test_sample.py"
    test_file.write_text(
        """
from mymodule import process

def test_process_works():
    result = process("input")
    assert result == "output"

def test_no_assertions():
    process("x")  # No assert!
"""
    )

    # Run the CLI
    result = subprocess.run(
        [sys.executable, "-m", "lib.test_audit.cli", "--path", str(tmp_path)],
        capture_output=True,
        text=True,
    )

    # Check output contains summary
    assert result.returncode == 0
    output = result.stdout.lower()
    assert "keep" in output or "delete" in output or "review" in output


def test_interactive_review_processes_user_choices():
    """Interactive review prompts user and records decisions."""
    result = DecisionResult(
        needs_review={"test_ambiguous"},
        keeps=set(),
        deletes=set(),
        scores={
            "test_ambiguous": HealthScore(
                verdict=Verdict.REVIEW,
                confidence=0.6,
                reason="Needs human review",
            )
        },
    )

    # Simulate user typing 'k' (keep)
    with patch("builtins.input", return_value="k"):
        updated = interactive_review(result)

    assert "test_ambiguous" in updated.keeps
    assert "test_ambiguous" not in updated.needs_review
