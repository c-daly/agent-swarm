#!/usr/bin/env python3
"""
Session End Hook - Auto-generate metrics dashboard & prompt memory capture

Automatically generates the metrics dashboard at the end of each session
and prompts the agent to write important learnings to memory.
"""

import json
import sys
import subprocess
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
CHARTS_SCRIPT = SCRIPTS_DIR / "charts.py"
STATE_DIR = Path(__file__).parent.parent / ".state"
SESSION_FILE = STATE_DIR / "session.json"

def generate_dashboard():
    """Generate the metrics dashboard."""
    try:
        result = subprocess.run(
            ["python3", str(CHARTS_SCRIPT), "dashboard"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            # Extract dashboard path from output
            for line in result.stdout.split('\n'):
                if 'dashboard.html' in line and 'file://' in line:
                    return {
                        "success": True,
                        "path": line.strip(),
                        "message": "✅ Metrics dashboard generated automatically"
                    }

            return {
                "success": True,
                "message": "✅ Metrics dashboard generated"
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Dashboard generation timed out"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

def check_memory_write_needed(input_data):
    """Check if significant work was done that should be captured in memory."""

    # Check for file modifications in the input data
    messages = input_data.get("messages", [])

    # Look for indicators of significant work
    has_file_changes = False
    has_architecture_work = False
    has_problem_solving = False

    for msg in messages:
        if isinstance(msg, dict):
            content = str(msg.get("content", "")).lower()

            # Check for file edits/writes
            if any(word in content for word in ["edit", "write", "create", "modify", "refactor"]):
                has_file_changes = True

            # Check for architecture/design work
            if any(word in content for word in ["architecture", "design", "pattern", "structure"]):
                has_architecture_work = True

            # Check for problem-solving
            if any(word in content for word in ["bug", "fix", "issue", "error", "problem", "gotcha"]):
                has_problem_solving = True

    # If significant work was done, suggest memory write
    if has_file_changes or has_architecture_work or has_problem_solving:
        return {
            "needed": True,
            "message": (
                "\n\n📝 MEMORY CAPTURE RECOMMENDED\n"
                "   Significant work completed. Consider writing to project memory:\n"
                "   \n"
                "   Tool: mcp__plugin_serena_serena__write_memory\n"
                "   \n"
                "   What to capture:\n"
                "   - Key decisions made and rationale\n"
                "   - Gotchas/issues encountered and solutions\n"
                "   - Architecture changes or patterns introduced\n"
                "   - Important context for future sessions\n"
                "   \n"
                "   Example:\n"
                "   write_memory(\n"
                "       memory_file_name='workflow-consolidation-2026-01',\n"
                "       content='# Instruction Consolidation\\n\\n'\n"
                "               'Created CORE_PROTOCOL.md to reduce duplication.\\n'\n"
                "               'Gotcha: Phase enforcement blocks tools in wrong phase.\\n'\n"
                "               'Solution: Reset session.json or use correct phase.'\n"
                "   )"
            )
        }

    return {"needed": False}

def main():
    """Session end hook entry point."""

    # Read session data from stdin (if any)
    try:
        input_data = json.loads(sys.stdin.read())
    except:
        input_data = {}

    # Generate dashboard
    result = generate_dashboard()

    # Check if memory write is recommended
    memory_check = check_memory_write_needed(input_data)

    # Build output message
    message = result.get("message", "") or f"⚠️ Dashboard generation failed: {result.get('error', 'Unknown error')}"

    if result.get("path"):
        message += f"\n   {result['path']}"

    # Append memory suggestion if needed
    if memory_check.get("needed"):
        message += memory_check["message"]

    # Return result
    output = {
        "hookSpecificOutput": {
            "message": message
        }
    }

    print(json.dumps(output))

if __name__ == "__main__":
    main()
