#!/usr/bin/env python3
"""
Workflow monitor - verbose output for debugging and tuning.

Usage:
    python3 monitor.py status         - Current state
    python3 monitor.py log            - Recent activity
    python3 monitor.py watch          - Live tail of log
    python3 monitor.py stats          - Usage statistics
"""

import json
import sys
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent.parent / ".state" / "session.json"
LOG_FILE = Path(__file__).resolve().parent.parent / ".state" / "activity.log"
STATS_FILE = Path(__file__).resolve().parent.parent / ".state" / "stats.json"


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def load_stats() -> dict:
    if STATS_FILE.exists():
        return json.loads(STATS_FILE.read_text())
    return {
        "tools_allowed": 0,
        "tools_blocked": 0,
        "subagents_spawned": 0,
        "phase_transitions": 0,
        "blocks_by_reason": {},
        "model_usage": {"haiku": 0, "sonnet": 0, "opus": 0},
    }


def save_stats(stats: dict):
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATS_FILE.write_text(json.dumps(stats, indent=2))


def log_event(event_type: str, details: str):
    """Append event to activity log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{timestamp}] {event_type}: {details}\n")


def show_status():
    state = load_state()
    stats = load_stats()

    print("=" * 50)
    print("AGENT-SWARM STATUS")
    print("=" * 50)

    print(f"\n📍 Phase: {state.get('phase', 'none') or 'none'}")
    print(f"🤖 Autopilot: {'ON' if state.get('autopilot_override') else 'OFF'}")
    print(f"📊 Search count: {state.get('search_count', 0)}")
    print(f"📖 Read count: {state.get('read_count', 0)}")

    checkpoints = state.get("checkpoints", {})
    active_checkpoints = [k for k, v in checkpoints.items() if v]
    print(f"⏸️  Checkpoints: {', '.join(active_checkpoints) or 'none'}")

    print("\n📈 Session Stats:")
    print(f"   Tools allowed: {stats.get('tools_allowed', 0)}")
    print(f"   Tools blocked: {stats.get('tools_blocked', 0)}")
    print(f"   Subagents spawned: {stats.get('subagents_spawned', 0)}")

    blocks = stats.get("blocks_by_reason", {})
    if blocks:
        print("\n🚫 Blocks by reason:")
        for reason, count in sorted(blocks.items(), key=lambda x: -x[1])[:5]:
            print(f"   {reason}: {count}")

    models = stats.get("model_usage", {})
    if any(models.values()):
        print("\n💰 Model usage:")
        for model, count in models.items():
            if count > 0:
                print(f"   {model}: {count}")


def show_log(lines: int = 20):
    if not LOG_FILE.exists():
        print("No activity log yet")
        return

    with open(LOG_FILE) as f:
        all_lines = f.readlines()

    print(f"Last {lines} events:")
    print("-" * 40)
    for line in all_lines[-lines:]:
        print(line.rstrip())


def watch_log():
    import time

    print("Watching activity log (Ctrl+C to stop)...")
    print("-" * 40)

    if not LOG_FILE.exists():
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOG_FILE.touch()

    with open(LOG_FILE) as f:
        f.seek(0, 2)  # Go to end
        try:
            while True:
                line = f.readline()
                if line:
                    print(line.rstrip())
                else:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nStopped watching")


def show_stats():
    stats = load_stats()

    print("=" * 50)
    print("USAGE STATISTICS")
    print("=" * 50)

    total_tools = stats.get("tools_allowed", 0) + stats.get("tools_blocked", 0)
    if total_tools > 0:
        block_rate = stats.get("tools_blocked", 0) / total_tools * 100
        print("\n🔧 Tool Usage:")
        print(f"   Total: {total_tools}")
        print(f"   Allowed: {stats.get('tools_allowed', 0)}")
        print(f"   Blocked: {stats.get('tools_blocked', 0)} ({block_rate:.1f}%)")

    print(f"\n🤖 Subagents: {stats.get('subagents_spawned', 0)}")
    print(f"🔄 Phase transitions: {stats.get('phase_transitions', 0)}")

    blocks = stats.get("blocks_by_reason", {})
    if blocks:
        print("\n🚫 Top block reasons:")
        for reason, count in sorted(blocks.items(), key=lambda x: -x[1]):
            print(f"   {reason}: {count}")

    models = stats.get("model_usage", {})
    total_model = sum(models.values())
    if total_model > 0:
        print("\n💰 Model distribution:")
        for model, count in sorted(models.items(), key=lambda x: -x[1]):
            pct = count / total_model * 100
            print(f"   {model}: {count} ({pct:.1f}%)")


def main():
    if len(sys.argv) < 2:
        show_status()
        return

    cmd = sys.argv[1]

    if cmd == "status":
        show_status()
    elif cmd == "log":
        lines = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        show_log(lines)
    elif cmd == "watch":
        watch_log()
    elif cmd == "stats":
        show_stats()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: monitor.py status|log|watch|stats")


if __name__ == "__main__":
    main()
