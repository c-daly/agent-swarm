#!/usr/bin/env python3
"""
Enhanced metrics tracking for agent-swarm performance.

Usage:
    python3 metrics.py report        - Show full report
    python3 metrics.py baseline      - Save current metrics as baseline
    python3 metrics.py compare       - Compare to baseline
    python3 metrics.py record <data> - Record custom metric
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"
METRICS_FILE = STATE_DIR / "metrics.json"
BASELINE_FILE = STATE_DIR / "baseline.json"
ACTIVITY_LOG = STATE_DIR / "activity.log"
SUBAGENT_METRICS = STATE_DIR / "subagent_metrics.json"

# Token cost estimates per tool type
TOKEN_ESTIMATES = {
    "Bash": 500,  # Small commands
    "Read": 2000,  # Average file size
    "Edit": 1500,  # Editing context
    "Write": 1000,  # Writing new files
    "Task": 5000,  # Subagent overhead
    "Grep": 1000,  # Search results
    "Glob": 500,  # File listings
    "WebSearch": 3000,  # Search results
    "WebFetch": 2500,  # Fetched content
}


def load_metrics():
    """Load current metrics."""
    if METRICS_FILE.exists():
        return json.loads(METRICS_FILE.read_text())

    return {
        "sessions": [],
        "current_session": {
            "started": datetime.now().isoformat(),
            "agents": {},
            "tool_calls": [],
            "cache_stats": {"hits": 0, "misses": 0},
            "quality_scores": [],
        },
    }


def save_metrics(metrics):
    """Save metrics to file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_FILE.write_text(json.dumps(metrics, indent=2))


def analyze_activity_log():
    """Extract metrics from activity log."""
    if not ACTIVITY_LOG.exists():
        return {}

    lines = ACTIVITY_LOG.read_text().split("\n")

    metrics = {
        "total_events": 0,
        "tools_by_type": defaultdict(int),
        "blocks_by_reason": defaultdict(int),
        "duplicate_reads": 0,
        "files_read": [],
        "search_patterns": [],
    }

    seen_reads = set()

    # Track script usage
    script_names = [
        "batch_search.py",
        "file_analyzer.py",
        "serena_batch.py",
        "gh_wrapper.py",
        "inventory.py",
        "context7_docs.py",
    ]

    for line in lines:
        if not line.strip():
            continue

        metrics["total_events"] += 1

        # Track script usage
        for script in script_names:
            if script in line:
                metrics["script_calls"] = metrics.get("script_calls", 0) + 1
                metrics["scripts_used"] = metrics.get("scripts_used", {})
                metrics["scripts_used"][script] = (
                    metrics["scripts_used"].get(script, 0) + 1
                )

        # Track tool usage
        if "TOOL:" in line or "ALLOWED:" in line:
            for tool in ["Read", "Write", "Edit", "Glob", "Grep", "Task", "Bash"]:
                if tool in line:
                    metrics["tools_by_type"][tool] += 1

        # Track blocks
        if "BLOCKED" in line:
            # Format: [timestamp] BLOCKED: Tool: [REASON] message
            # Extract the reason (second bracketed text)
            parts = line.split("BLOCKED:")
            if len(parts) > 1:
                blocked_part = parts[1]
                # Look for [REASON] in the blocked part
                if "[" in blocked_part and "]" in blocked_part:
                    reason = blocked_part.split("[")[1].split("]")[0]
                    metrics["blocks_by_reason"][reason] += 1
                else:
                    metrics["blocks_by_reason"]["unknown"] += 1

        # Track duplicate reads
        if "Read" in line and "file_path" in line:
            try:
                file = line.split("file_path")[1].split("}")[0].strip("\":' ")
                if file in seen_reads:
                    metrics["duplicate_reads"] += 1
                seen_reads.add(file)
                metrics["files_read"].append(file)
            except:
                pass

    metrics["unique_files"] = len(seen_reads)
    metrics["total_reads"] = len(metrics["files_read"])

    if metrics["total_reads"] > 0:
        metrics["duplicate_rate"] = (
            metrics["duplicate_reads"] / metrics["total_reads"] * 100
        )

    return metrics


def calculate_efficiency_score(metrics):
    """Calculate overall efficiency score (0-100)."""
    score = 100

    # Penalize high block rate
    if "tools_by_type" in metrics:
        total = sum(metrics["tools_by_type"].values())
        blocks = sum(metrics.get("blocks_by_reason", {}).values())
        if total > 0:
            block_rate = blocks / total * 100
            score -= min(block_rate, 30)  # Max 30 point penalty

    # Penalize duplicates
    dup_rate = metrics.get("duplicate_rate", 0)
    score -= min(dup_rate * 0.5, 20)  # Max 20 point penalty

    # Bonus for using batch operations
    tools = metrics.get("tools_by_type", {})
    individual = tools.get("Read", 0) + tools.get("Grep", 0) + tools.get("Glob", 0)
    batch = tools.get("Bash", 0)  # Assuming scripts via bash
    if individual + batch > 0:
        batch_ratio = batch / (individual + batch) * 100
        score += min(batch_ratio * 0.2, 10)  # Max 10 point bonus

    return max(0, min(100, score))


def calculate_token_estimate(log_metrics):
    """Estimate tokens used based on tool calls."""
    total_tokens = 0
    token_by_tool = {}

    for tool, count in log_metrics.get("tools_by_type", {}).items():
        tokens = TOKEN_ESTIMATES.get(tool, 500) * count
        total_tokens += tokens
        token_by_tool[tool] = tokens

    # Add subagent token data if available
    subagent_tokens = 0
    if SUBAGENT_METRICS.exists():
        try:
            subagents = json.loads(SUBAGENT_METRICS.read_text())
            for agent_id, data in subagents.items():
                # Note: actual token usage would be tracked by TaskOutput
                # For now, estimate based on agent type
                agent_type = data.get("agent_type", "unknown")
                # Rough estimate: assume average completion
                if "explorer" in agent_type.lower():
                    subagent_tokens += 25000
                elif "implementer" in agent_type.lower():
                    subagent_tokens += 100000
                elif "reviewer" in agent_type.lower():
                    subagent_tokens += 40000
                else:
                    subagent_tokens += 50000
        except:
            pass

    total_tokens += subagent_tokens
    token_by_tool["Subagents"] = subagent_tokens

    # Calculate cost (Sonnet 4 pricing: $3 per million input tokens)
    cost = total_tokens * 0.000003

    return total_tokens, token_by_tool, cost


def show_report():
    """Show comprehensive metrics report."""
    print("=" * 60)
    print("AGENT-SWARM PERFORMANCE REPORT")
    print("=" * 60)

    log_metrics = analyze_activity_log()

    # Overall efficiency
    efficiency = calculate_efficiency_score(log_metrics)
    print(f"\n📊 Overall Efficiency Score: {efficiency:.1f}/100")

    # Token usage
    total_tokens, token_by_tool, cost = calculate_token_estimate(log_metrics)
    print("\n💰 Token Usage (estimated):")
    print(f"   Total: {total_tokens:,} tokens (${cost:.2f})")
    print("   Top consumers:")
    for tool, tokens in sorted(token_by_tool.items(), key=lambda x: -x[1])[:5]:
        if tokens > 0:
            pct = tokens / total_tokens * 100
            print(f"     {tool:15} {tokens:>10,} tokens ({pct:5.1f}%)")

    # Tool usage breakdown
    print("\n🔧 Tool Usage:")
    total_tools = sum(log_metrics["tools_by_type"].values())
    for tool, count in sorted(
        log_metrics["tools_by_type"].items(), key=lambda x: -x[1]
    ):
        pct = count / total_tools * 100 if total_tools > 0 else 0
        print(f"   {tool:15} {count:4} ({pct:5.1f}%)")

    # Script usage
    script_calls = log_metrics.get("script_calls", 0)
    direct_reads = log_metrics["tools_by_type"].get("Read", 0)
    total_data_ops = script_calls + direct_reads

    print("\n📜 Script Usage:")
    print(f"   Script calls: {script_calls}")
    print(f"   Direct reads: {direct_reads}")
    if total_data_ops > 0:
        adoption = script_calls / total_data_ops * 100
        print(
            f"   Adoption rate: {adoption:.1f}% {'✅' if adoption >= 60 else '⚠️' if adoption >= 30 else '❌'}"
        )
        print("   Target: 60%+")

    if log_metrics.get("scripts_used"):
        print("\n   Scripts used:")
        for script, count in sorted(
            log_metrics["scripts_used"].items(), key=lambda x: -x[1]
        ):
            print(f"      {script}: {count}")

    # Efficiency metrics
    print("\n⚡ Efficiency Metrics:")
    print(f"   Files read: {log_metrics['total_reads']}")
    print(f"   Unique files: {log_metrics['unique_files']}")
    print(
        f"   Duplicate reads: {log_metrics['duplicate_reads']} ({log_metrics.get('duplicate_rate', 0):.1f}%)"
    )

    # Block analysis
    print("\n🚫 Blocks:")
    total_blocks = sum(log_metrics["blocks_by_reason"].values())
    if total_blocks > 0:
        for reason, count in sorted(
            log_metrics["blocks_by_reason"].items(), key=lambda x: -x[1]
        ):
            pct = count / total_blocks * 100
            print(f"   {reason:25} {count:3} ({pct:.1f}%)")
    else:
        print("   None")

    # Recommendations
    print("\n💡 Recommendations:")

    # Script adoption recommendations
    if total_data_ops > 0:
        adoption = script_calls / total_data_ops * 100
        if adoption < 30 and direct_reads > 5:
            print(
                "   🔴 CRITICAL: Low script adoption - agents dumping data into context"
            )
            print("      Fix: Update subagent-briefing.md with correct script paths")
        elif adoption < 60 and direct_reads > 10:
            print("   ⚠️  Script adoption below target - review agent briefings")

    if log_metrics.get("duplicate_rate", 0) > 10:
        print("   ⚠️  HIGH: Duplicate reads detected - implement caching")

    tools = log_metrics["tools_by_type"]
    if tools.get("Read", 0) > 5 and script_calls == 0:
        print("   ⚠️  Multiple reads but NO scripts used - agents unaware of scripts")

    if tools.get("Grep", 0) + tools.get("Glob", 0) > 3:
        print("   ⚠️  Multiple searches - use batch_search.py")

    blocks = sum(log_metrics["blocks_by_reason"].values())
    if blocks > total_tools * 0.15:
        print("   ⚠️  High block rate - review enforcement rules")

    if efficiency >= 80:
        print("   ✅ Good efficiency - workflow is working well")
    elif efficiency >= 60:
        print("   ⚠️  Moderate efficiency - room for improvement")
    else:
        print("   ❌ Low efficiency - significant optimization needed")


def save_baseline():
    """Save current metrics as baseline for comparison."""
    log_metrics = analyze_activity_log()

    baseline = {
        "timestamp": datetime.now().isoformat(),
        "metrics": log_metrics,
        "efficiency_score": calculate_efficiency_score(log_metrics),
    }

    BASELINE_FILE.write_text(json.dumps(baseline, indent=2))
    print(f"✅ Baseline saved: {baseline['efficiency_score']:.1f}/100 efficiency")


def compare_to_baseline():
    """Compare current metrics to baseline."""
    if not BASELINE_FILE.exists():
        print("❌ No baseline found. Run 'metrics.py baseline' first.")
        return

    baseline = json.loads(BASELINE_FILE.read_text())
    current = analyze_activity_log()

    print("=" * 60)
    print("BASELINE COMPARISON")
    print("=" * 60)

    baseline_score = baseline["efficiency_score"]
    current_score = calculate_efficiency_score(current)

    print("\n📊 Efficiency Score:")
    print(f"   Baseline: {baseline_score:.1f}")
    print(f"   Current:  {current_score:.1f}")

    diff = current_score - baseline_score
    if diff > 0:
        print(f"   Change:   +{diff:.1f} ✅ IMPROVED")
    elif diff < 0:
        print(f"   Change:   {diff:.1f} ❌ DEGRADED")
    else:
        print(f"   Change:   {diff:.1f} → Same")

    # Compare key metrics
    print("\n📈 Key Metrics:")

    metrics_compare = [
        ("Total reads", "total_reads"),
        ("Unique files", "unique_files"),
        ("Duplicate rate", "duplicate_rate"),
        ("Total blocks", lambda m: sum(m.get("blocks_by_reason", {}).values())),
    ]

    for label, key in metrics_compare:
        if callable(key):
            base_val = key(baseline["metrics"])
            curr_val = key(current)
        else:
            base_val = baseline["metrics"].get(key, 0)
            curr_val = current.get(key, 0)

        diff = curr_val - base_val
        symbol = "✅" if diff <= 0 else "⚠️"

        if isinstance(curr_val, float):
            print(
                f"   {label:20} {base_val:6.1f} → {curr_val:6.1f} ({diff:+.1f}) {symbol}"
            )
        else:
            print(f"   {label:20} {base_val:6} → {curr_val:6} ({diff:+}) {symbol}")

    # Tool usage changes
    print("\n🔧 Tool Usage Changes:")
    base_tools = baseline["metrics"].get("tools_by_type", {})
    curr_tools = current.get("tools_by_type", {})

    all_tools = set(base_tools.keys()) | set(curr_tools.keys())
    for tool in sorted(all_tools):
        base = base_tools.get(tool, 0)
        curr = curr_tools.get(tool, 0)
        if base != curr:
            diff = curr - base
            symbol = "📈" if diff > 0 else "📉"
            print(f"   {tool:15} {base:4} → {curr:4} ({diff:+3}) {symbol}")


def record_agent_metrics(agent_type, tokens_used, output_size, task_description):
    """Record metrics for a specific agent execution."""
    metrics = load_metrics()

    agent_record = {
        "timestamp": datetime.now().isoformat(),
        "type": agent_type,
        "tokens": tokens_used,
        "output_size": output_size,
        "task": task_description[:100],
    }

    if agent_type not in metrics["current_session"]["agents"]:
        metrics["current_session"]["agents"][agent_type] = []

    metrics["current_session"]["agents"][agent_type].append(agent_record)
    save_metrics(metrics)

    print(f"✅ Recorded: {agent_type} used {tokens_used} tokens")


def main():
    if len(sys.argv) < 2:
        show_report()
        return

    cmd = sys.argv[1]

    if cmd == "report":
        show_report()
    elif cmd == "baseline":
        save_baseline()
    elif cmd == "compare":
        compare_to_baseline()
    elif cmd == "record":
        if len(sys.argv) < 5:
            print("Usage: metrics.py record <agent_type> <tokens> <output_size>")
            return
        record_agent_metrics(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), "manual")
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: metrics.py report|baseline|compare|record")


if __name__ == "__main__":
    main()
