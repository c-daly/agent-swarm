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
        # First capture a snapshot of current metrics
        snapshot_result = subprocess.run(
            ["python3", str(CHARTS_SCRIPT), "snapshot"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # Log snapshot result (don't fail if it errors)
        if snapshot_result.returncode != 0:
            print(f"⚠️ Snapshot capture failed: {snapshot_result.stderr}", file=sys.stderr)
        
        # Then generate the full dashboard
        result = subprocess.run(
            ["python3", str(CHARTS_SCRIPT), "all"],
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
    """Memory write is ALWAYS required at session end."""

    # Memory write is mandatory for all sessions
    # Even if no code was changed, conversations have context worth preserving
    if True:  # Always true - memory write always required
        return {
            "needed": True,
            "message": (
                "\n\n============================================================\n"
                "📝 MEMORY CAPTURE REQUIRED\n"
                "============================================================\n"
                "Before ending this session, you MUST write learnings to memory.\n"
                "Even brief conversations contain valuable context.\n"
                "\n"
                "Tool: mcp__plugin_serena_serena__write_memory\n"
                "\n"
                "What to capture:\n"
                "  • Key decisions made and rationale\n"
                "  • Gotchas/issues encountered and solutions\n"
                "  • Architecture changes or patterns introduced\n"
                "  • Important context for future sessions\n"
                "  • Even simple Q&A if it reveals codebase details\n"
                "\n"
                "Example:\n"
                "  write_memory(\n"
                "      memory_file_name='<feature>-<date>',\n"
                "      content='# Session Summary\\n\\n'\n"
                "              '<what was done>\\n'\n"
                "              '<key decisions>\\n'\n"
                "              '<gotchas and solutions>'\n"
                "  )\n"
                "============================================================"
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
