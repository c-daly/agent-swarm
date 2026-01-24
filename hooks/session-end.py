#!/usr/bin/env python3
"""
Session End Hook - Auto-generate metrics dashboard & prompt memory capture

Automatically generates the metrics dashboard at the end of each session
and prompts the agent to write important learnings to memory.
"""

import json
import sys
import subprocess
import signal
from pathlib import Path

# Add plugin root and lib to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent.parent / "context"))
from lib.stores.compression import compress_old_sessions  # noqa: E402
from memory import EpisodeStore, trigger_distillation  # noqa: E402

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
CHARTS_SCRIPT = SCRIPTS_DIR / "charts.py"
STATE_DIR = Path(__file__).parent.parent / ".state"
SESSION_FILE = STATE_DIR / "session.json"


def generate_dashboard():
    """Generate the metrics dashboard."""
    try:
        # First capture a snapshot of current metrics
        snapshot_result = subprocess.run(
            ["poetry", "run", "python", str(CHARTS_SCRIPT), "snapshot"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # Log snapshot result (don't fail if it errors)
        if snapshot_result.returncode != 0:
            print(f"\u26a0\ufe0f Snapshot capture failed: {snapshot_result.stderr}", file=sys.stderr)
        
        # Then generate the full dashboard
        result = subprocess.run(
            ["poetry", "run", "python", str(CHARTS_SCRIPT), "all"],
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
                        "message": "\u2705 Metrics dashboard generated automatically"
                    }

            return {
                "success": True,
                "message": "\u2705 Metrics dashboard generated"
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
                "\ud83d\udcdd MEMORY CAPTURE REQUIRED\n"
                "============================================================\n"
                "Before ending this session, you MUST write learnings to memory.\n"
                "Even brief conversations contain valuable context.\n"
                "\n"
                "Tool: mcp__plugin_serena_serena__write_memory\n"
                "\n"
                "What to capture:\n"
                "  \u2022 Key decisions made and rationale\n"
                "  \u2022 Gotchas/issues encountered and solutions\n"
                "  \u2022 Architecture changes or patterns introduced\n"
                "  \u2022 Important context for future sessions\n"
                "  \u2022 Even simple Q&A if it reveals codebase details\n"
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


def compress_old_session_files():
    """Compress session JSONL files older than 24 hours."""
    sessions_dir = STATE_DIR / "sessions"
    if not sessions_dir.exists():
        return {"compressed": 0}

    try:
        count = compress_old_sessions(sessions_dir, max_age_hours=24)
        return {"compressed": count}
    except Exception as e:
        return {"error": str(e)}


def check_and_distill(scope_path: Path, threshold: int = 10, timeout_seconds: int = 5) -> dict:
    """
    Check episode count and trigger distillation if threshold exceeded.
    
    Args:
        scope_path: Path to the project/scope directory
        threshold: Minimum episode count to trigger distillation (default: 10)
        timeout_seconds: Maximum time to wait for distillation (default: 5)
    
    Returns:
        dict with keys:
            - distilled: bool - whether distillation was performed
            - episode_count: int - number of episodes found
            - pattern_count: int - number of patterns after distillation (if distilled)
            - error: str - error message if failed (optional)
    """
    try:
        store = EpisodeStore(scope_path)
        episodes = store.get_episodes()
        episode_count = len(episodes)
        
        if episode_count < threshold:
            return {"distilled": False, "episode_count": episode_count}
        
        # Set timeout for distillation (Unix only - SIGALRM not available on Windows)
        use_alarm = hasattr(signal, 'SIGALRM')
        old_handler = None

        if use_alarm:
            def timeout_handler(signum, frame):
                raise TimeoutError("Distillation timed out")

            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout_seconds)

        try:
            memory = trigger_distillation(scope_path)
            if use_alarm:
                signal.alarm(0)  # Cancel alarm
            return {
                "distilled": True,
                "episode_count": episode_count,
                "pattern_count": len(memory.patterns)
            }
        except TimeoutError as e:
            return {
                "distilled": False,
                "episode_count": episode_count,
                "error": str(e)
            }
        finally:
            if use_alarm and old_handler is not None:
                signal.signal(signal.SIGALRM, old_handler)
                signal.alarm(0)
            
    except Exception as e:
        return {
            "distilled": False,
            "episode_count": 0,
            "error": str(e)
        }


def main():
    """Session end hook entry point."""

    # Read session data from stdin (if any)
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        input_data = {}

    # Generate dashboard
    result = generate_dashboard()

    # Check if memory write is recommended
    memory_check = check_memory_write_needed(input_data)

    # Build output message
    message = result.get("message", "") or f"\u26a0\ufe0f Dashboard generation failed: {result.get('error', 'Unknown error')}"

    if result.get("path"):
        message += f"\n   {result['path']}"

    # Compress old session files
    compression_result = compress_old_session_files()
    if compression_result.get("compressed", 0) > 0:
        message += f"\n\ud83d\udce6 Compressed {compression_result['compressed']} old session file(s)"

    # Auto-distillation check
    distill_result = check_and_distill(Path.cwd())
    if distill_result.get("distilled"):
        message += f"\n\ud83d\udcdd Distilled {distill_result['episode_count']} episodes into {distill_result['pattern_count']} patterns"
    elif distill_result.get("error"):
        message += f"\n\u26a0\ufe0f Auto-distillation failed: {distill_result['error']}"

    # Append memory suggestion if needed
    if memory_check.get("needed"):
        message += memory_check["message"]

    # Return result
    output = {
        "systemMessage": message
    }

    print(json.dumps(output))


if __name__ == "__main__":
    main()
