#!/usr/bin/env python3
"""
Session End Hook - Auto-generate metrics dashboard

Automatically generates the metrics dashboard at the end of each session.
"""

import json
import sys
import subprocess
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
CHARTS_SCRIPT = SCRIPTS_DIR / "charts.py"

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

def main():
    """Session end hook entry point."""

    # Read session data from stdin (if any)
    try:
        input_data = json.loads(sys.stdin.read())
    except:
        input_data = {}

    # Generate dashboard
    result = generate_dashboard()

    # Return result
    output = {
        "hookSpecificOutput": {
            "message": result.get("message", "") or f"⚠️ Dashboard generation failed: {result.get('error', 'Unknown error')}"
        }
    }

    if result.get("path"):
        output["hookSpecificOutput"]["message"] += f"\n   {result['path']}"

    print(json.dumps(output))

if __name__ == "__main__":
    main()
