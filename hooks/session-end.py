#!/usr/bin/env python3
"""
Session End Hook - Learning capture and session cleanup

Captures learnings from conversation, compresses old sessions,
and triggers memory distillation at session end.
"""

import json
import re
import sys
import signal
import glob
from datetime import datetime
from pathlib import Path

# Add plugin root and lib to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent.parent / "context"))
from lib.stores.compression import compress_old_sessions  # noqa: E402
from memory import EpisodeStore, trigger_distillation  # noqa: E402

STATE_DIR = Path(__file__).parent.parent / ".state"
SESSION_FILE = STATE_DIR / "session.json"


def get_projects_dir() -> Path:
    """Return the Claude projects directory path."""
    return Path.home() / ".claude" / "projects"


def get_context_dir() -> Path:
    """Return the .context directory for the plugin."""
    return Path(__file__).parent.parent / ".context"


def extract_learnings_from_conversation(jsonl_lines: list[str]) -> list[str]:
    """Extract LEARNING: tags from assistant messages in conversation JSONL.

    Args:
        jsonl_lines: List of JSONL strings, each representing a conversation message

    Returns:
        List of learning descriptions extracted from assistant messages
    """
    learnings = []
    pattern = r"LEARNING:\s*(.+?)(?:\n|$)"

    for line in jsonl_lines:
        try:
            data = json.loads(line)
            # Only process assistant messages
            if data.get("type") != "assistant":
                continue

            # Get content from message
            message = data.get("message", {})
            content = message.get("content", "")
            if not content:
                continue

            # Extract LEARNING: tags (case insensitive)
            matches = re.findall(pattern, content, re.IGNORECASE)
            learnings.extend(matches)
        except (json.JSONDecodeError, AttributeError, KeyError):
            continue

    return learnings


def find_conversation_file(session_id: str) -> Path | None:
    """Find the conversation JSONL file for a given session ID.

    Searches in ~/.claude/projects/*/{session_id}.jsonl

    Args:
        session_id: The session ID to search for

    Returns:
        Path to the JSONL file if found, None otherwise
    """
    projects_dir = get_projects_dir()
    if not projects_dir.exists():
        return None

    # Search for session file in any project directory
    pattern = str(projects_dir / "*" / f"{session_id}.jsonl")
    matches = glob.glob(pattern)

    if matches:
        return Path(matches[0])
    return None


def log_main_agent_learnings(learnings: list[str], source: str) -> None:
    """Append learnings from main agent to EPISODES.md.

    Creates .context directory and EPISODES.md if they don't exist.

    Args:
        learnings: List of learning descriptions
        source: Source identifier (e.g., "main-agent")
    """
    if not learnings:
        return

    context_dir = get_context_dir()
    context_dir.mkdir(parents=True, exist_ok=True)

    episodes_file = context_dir / "EPISODES.md"

    # Build episode entry
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry_lines = [
        f"\n## Session: {timestamp} - Main Agent Learning Capture",
        f"- **Source**: {source}",
        "- **Outcome**: success",
        "- **Learnings**:",
    ]
    for learning in learnings:
        entry_lines.append(f"  - {learning}")
    entry_lines.append("")

    # Append to file
    with open(episodes_file, "a") as f:
        f.write("\n".join(entry_lines))


def capture_main_agent_learnings(session_id: str) -> int:
    """Capture LEARNING: tags from main agent conversation and log to EPISODES.md.

    Args:
        session_id: The session ID to process

    Returns:
        Number of learnings captured
    """
    try:
        # Find the conversation file
        conv_file = find_conversation_file(session_id)
        if not conv_file or not conv_file.exists():
            return 0

        # Read JSONL lines
        jsonl_lines = conv_file.read_text().strip().split("\n")

        # Extract learnings
        learnings = extract_learnings_from_conversation(jsonl_lines)

        if learnings:
            log_main_agent_learnings(learnings, f"main-agent:{session_id[:8]}")

        return len(learnings)
    except Exception:
        return 0  # Don't fail hook on learning capture errors


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
            ),
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
        use_alarm = hasattr(signal, "SIGALRM")
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
                "pattern_count": len(memory.patterns),
            }
        except TimeoutError as e:
            return {"distilled": False, "episode_count": episode_count, "error": str(e)}
        finally:
            if use_alarm and old_handler is not None:
                signal.signal(signal.SIGALRM, old_handler)
                signal.alarm(0)

    except Exception as e:
        return {"distilled": False, "episode_count": 0, "error": str(e)}


def main():
    """Session end hook entry point."""

    # Read session data from stdin (if any)
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        input_data = {}

    # Check if memory write is recommended
    memory_check = check_memory_write_needed(input_data)

    # Build output message
    messages = []

    # Capture LEARNING: tags from main agent conversation
    session_id = input_data.get("sessionId", "")
    if session_id:
        learnings_captured = capture_main_agent_learnings(session_id)
        if learnings_captured > 0:
            messages.append(f"\ud83d\udcdd Captured {learnings_captured} learning(s) from main agent")

    # Compress old session files
    compression_result = compress_old_session_files()
    if compression_result.get("compressed", 0) > 0:
        messages.append(f"\ud83d\udce6 Compressed {compression_result['compressed']} old session file(s)")

    # Auto-distillation check
    distill_result = check_and_distill(Path.cwd())
    if distill_result.get("distilled"):
        messages.append(f"\ud83d\udcdd Distilled {distill_result['episode_count']} episodes into {distill_result['pattern_count']} patterns")
    elif distill_result.get("error"):
        messages.append(f"\u26a0\ufe0f Auto-distillation failed: {distill_result['error']}")

    # Append memory suggestion if needed
    if memory_check.get("needed"):
        messages.append(memory_check["message"])

    # Return result
    message = "\n".join(messages) if messages else "Session ended"
    output = {"systemMessage": message}

    print(json.dumps(output))


if __name__ == "__main__":
    main()
