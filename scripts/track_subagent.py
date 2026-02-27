#!/usr/bin/env python3
"""
Track subagent performance - call this after a subagent completes.

Usage:
    python3 track_subagent.py <agent_id> <agent_type>

Extracts token usage from task output and logs to metrics.
"""

import os
import sys
import json
import re
from pathlib import Path
from datetime import datetime

STATE_DIR = Path(__file__).resolve().parent.parent / ".state"
SUBAGENT_METRICS = STATE_DIR / "subagent_metrics.json"
TASK_OUTPUT_DIR = Path(os.environ.get(
    "CLAUDE_TASK_OUTPUT_DIR",
    f"/tmp/claude/{str(Path.home()).replace('/', '-').lstrip('-')}/tasks"
))


def load_subagent_metrics():
    """Load existing subagent metrics."""
    if SUBAGENT_METRICS.exists():
        return json.loads(SUBAGENT_METRICS.read_text())

    return {
        "agents": [],
        "summary": {
            "total_agents": 0,
            "total_tokens": 0,
            "avg_tokens": 0,
            "by_type": {},
        },
    }


def extract_token_usage(agent_id):
    """Extract token usage from agent output."""
    # Check task output file
    output_file = TASK_OUTPUT_DIR / f"{agent_id}.output"

    if not output_file.exists():
        return None

    try:
        content = output_file.read_text()

        # Look for token usage in system reminders
        # Pattern: "Agent <id> progress: X new tools used, Y new tokens"
        matches = re.findall(r"(\d+) new tokens", content)

        if matches:
            # Sum all token increments
            total = sum(int(m) for m in matches)
            return total

        return None
    except Exception:
        return None


def track_agent(agent_id, agent_type):
    """Track a completed subagent."""
    metrics = load_subagent_metrics()

    tokens = extract_token_usage(agent_id)

    agent_record = {
        "id": agent_id,
        "type": agent_type,
        "timestamp": datetime.now().isoformat(),
        "tokens": tokens if tokens else "unknown",
        "status": "timeout" if tokens and tokens > 3000000 else "completed",
    }

    metrics["agents"].append(agent_record)

    # Update summary
    metrics["summary"]["total_agents"] += 1

    if tokens:
        metrics["summary"]["total_tokens"] += tokens

        # By type
        if agent_type not in metrics["summary"]["by_type"]:
            metrics["summary"]["by_type"][agent_type] = {
                "count": 0,
                "total_tokens": 0,
                "avg_tokens": 0,
                "max_tokens": 0,
            }

        type_stats = metrics["summary"]["by_type"][agent_type]
        type_stats["count"] += 1
        type_stats["total_tokens"] += tokens
        type_stats["avg_tokens"] = type_stats["total_tokens"] / type_stats["count"]
        type_stats["max_tokens"] = max(type_stats["max_tokens"], tokens)

    # Overall average
    completed_with_tokens = [
        a for a in metrics["agents"] if isinstance(a.get("tokens"), int)
    ]
    if completed_with_tokens:
        metrics["summary"]["avg_tokens"] = sum(
            a["tokens"] for a in completed_with_tokens
        ) / len(completed_with_tokens)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SUBAGENT_METRICS.write_text(json.dumps(metrics, indent=2))

    # Print alert if excessive
    if tokens and tokens > 500000:
        print(
            f"⚠️  HIGH TOKEN USAGE: {agent_type} used {tokens:,} tokens", file=sys.stderr
        )

    return agent_record


def show_subagent_report():
    """Show subagent performance report."""
    if not SUBAGENT_METRICS.exists():
        print("No subagent metrics yet. Agents will be tracked automatically.")
        return

    metrics = load_subagent_metrics()
    summary = metrics["summary"]

    print("=" * 60)
    print("SUBAGENT PERFORMANCE REPORT")
    print("=" * 60)

    print("\n📊 Overall:")
    print(f"   Total agents: {summary['total_agents']}")
    print(f"   Total tokens: {summary['total_tokens']:,}")
    print(f"   Average per agent: {summary['avg_tokens']:,.0f}")

    print("\n🤖 By Agent Type:")
    for agent_type, stats in sorted(summary["by_type"].items()):
        print(f"\n   {agent_type}:")
        print(f"      Count: {stats['count']}")
        print(f"      Avg tokens: {stats['avg_tokens']:,.0f}")
        print(f"      Max tokens: {stats['max_tokens']:,}")

        # Alert on high usage
        if stats["avg_tokens"] > 200000:
            print("      ⚠️  HIGH: Avg exceeds 200K")
        elif stats["avg_tokens"] > 100000:
            print("      ⚠️  Moderate: Consider optimization")

    # Recent agents
    print("\n📋 Recent Agents (last 10):")
    for agent in metrics["agents"][-10:]:
        tokens_str = (
            f"{agent['tokens']:,}" if isinstance(agent["tokens"], int) else "unknown"
        )
        status_emoji = "⚠️ " if agent.get("status") == "timeout" else "✅"
        print(f"   {status_emoji} {agent['type']:20} {tokens_str:>12} tokens")


def main():
    if len(sys.argv) == 1:
        # No args = show report
        show_subagent_report()
        return

    if sys.argv[1] == "report":
        show_subagent_report()
        return

    if len(sys.argv) < 3:
        print("Usage: track_subagent.py <agent_id> <agent_type>")
        print("   or: track_subagent.py report")
        sys.exit(1)

    agent_id = sys.argv[1]
    agent_type = sys.argv[2]

    record = track_agent(agent_id, agent_type)
    if record["tokens"] != "unknown":
        print(f"✅ Tracked: {agent_type} used {record['tokens']:,} tokens")


if __name__ == "__main__":
    main()
