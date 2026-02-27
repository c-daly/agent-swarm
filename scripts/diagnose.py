#!/usr/bin/env python3
"""
Diagnostic analysis - explains WHY efficiency is high or low.

Usage:
    python3 diagnose.py              - Full diagnostic
    python3 diagnose.py --recent N   - Analyze last N events
    python3 diagnose.py --agent TYPE - Focus on specific agent
"""

import sys
import json
import re
from pathlib import Path
from collections import defaultdict, Counter

STATE_DIR = Path(__file__).resolve().parent.parent / ".state"
ACTIVITY_LOG = STATE_DIR / "activity.log"
SUBAGENT_METRICS = STATE_DIR / "subagent_metrics.json"


class EfficiencyAnalyzer:
    def __init__(self):
        self.events = []
        self.patterns = defaultdict(list)
        self.issues = []
        self.wins = []

    def load_activity_log(self, recent=None):
        """Load and parse activity log."""
        if not ACTIVITY_LOG.exists():
            return

        lines = ACTIVITY_LOG.read_text().split("\n")
        if recent:
            lines = lines[-recent:]

        for line in lines:
            if not line.strip():
                continue

            event = self.parse_event(line)
            if event:
                self.events.append(event)

    def parse_event(self, line):
        """Parse a log line into structured event."""
        try:
            # Extract timestamp
            time_match = re.search(r"\[(\d{2}:\d{2}:\d{2})\]", line)
            timestamp = time_match.group(1) if time_match else None

            # Extract event type
            if "ALLOWED:" in line:
                event_type = "allowed"
                tool = line.split("ALLOWED:")[1].split()[0].strip()
            elif "BLOCKED" in line:
                event_type = "blocked"
                tool = (
                    line.split("BLOCKED:")[1].split()[0].strip()
                    if ":" in line.split("BLOCKED")[1]
                    else "unknown"
                )
                reason = (
                    line.split("[")[-1].split("]")[0]
                    if "[" in line.split("BLOCKED")[-1]
                    else "unknown"
                )
            else:
                return None

            return {
                "timestamp": timestamp,
                "type": event_type,
                "tool": tool,
                "reason": reason if event_type == "blocked" else None,
                "raw": line,
            }
        except Exception:
            return None

    def analyze_patterns(self):
        """Identify efficiency patterns."""

        # Group events by time windows (5 min)
        windows = defaultdict(list)
        for event in self.events:
            if event["timestamp"]:
                # Group by hour:minute (ignore seconds)
                window = event["timestamp"][:5]
                windows[window].append(event)

        # Analyze each window
        for window, events in windows.items():
            self.analyze_window(window, events)

    def analyze_window(self, window, events):
        """Analyze a 5-minute window of activity."""
        tools = [e["tool"] for e in events]
        tool_counts = Counter(tools)

        # Pattern: Repeated same tool
        for tool, count in tool_counts.items():
            if count >= 5:
                self.patterns["repeated_tool"].append(
                    {
                        "window": window,
                        "tool": tool,
                        "count": count,
                        "issue": f"Used {tool} {count} times in short period - consider batching",
                    }
                )

        # Pattern: Read after Read after Read
        read_sequence = 0
        for event in events:
            if event["tool"] == "Read":
                read_sequence += 1
            else:
                if read_sequence >= 3:
                    self.patterns["read_sequence"].append(
                        {
                            "window": window,
                            "count": read_sequence,
                            "issue": f"{read_sequence} consecutive Reads - use batch script",
                        }
                    )
                read_sequence = 0

        # Pattern: Blocked then same tool allowed
        for i in range(len(events) - 1):
            if events[i]["type"] == "blocked" and events[i + 1]["type"] == "allowed":
                if events[i]["tool"] == events[i + 1]["tool"]:
                    self.patterns["block_retry"].append(
                        {
                            "window": window,
                            "tool": events[i]["tool"],
                            "issue": "Tool blocked then immediately retried - may indicate confusion",
                        }
                    )

    def identify_issues(self):
        """Identify specific inefficiency issues."""

        # Issue: High repeat tool usage
        if self.patterns["repeated_tool"]:
            worst = max(self.patterns["repeated_tool"], key=lambda x: x["count"])
            self.issues.append(
                {
                    "severity": "high" if worst["count"] > 10 else "medium",
                    "category": "batching",
                    "description": f"{worst['tool']} used {worst['count']} times rapidly",
                    "recommendation": "Use batch script: batch_search.py or file_analyzer.py",
                    "impact": "High token waste on redundant operations",
                }
            )

        # Issue: Long read sequences
        if self.patterns["read_sequence"]:
            worst = max(self.patterns["read_sequence"], key=lambda x: x["count"])
            self.issues.append(
                {
                    "severity": "high",
                    "category": "sequential_reads",
                    "description": f"{worst['count']} consecutive file reads",
                    "recommendation": "Use mcp__plugin_serena_serena__find_symbol instead of reading full files",
                    "impact": "Reading full files when only need specific symbols",
                }
            )

        # Issue: Block-retry cycles
        if self.patterns["block_retry"]:
            self.issues.append(
                {
                    "severity": "medium",
                    "category": "enforcement_friction",
                    "description": f"{len(self.patterns['block_retry'])} block-retry cycles",
                    "recommendation": "Review AGENT_RULES.md - may not understand tool restrictions",
                    "impact": "Wasted attempts, agent confusion",
                }
            )

    def identify_wins(self):
        """Identify what's working well."""

        tool_usage = Counter(e["tool"] for e in self.events if e["type"] == "allowed")

        # Win: Using Task tool (delegation)
        if tool_usage.get("Task", 0) > 5:
            self.wins.append(
                {
                    "category": "delegation",
                    "description": f"Good use of subagents ({tool_usage['Task']} spawns)",
                    "impact": "Parallel work, focused agents",
                }
            )

        # Win: Low duplicate rate
        reads = [e for e in self.events if e["tool"] == "Read"]
        # Can't easily detect dupes without file paths, but low read count is good
        if len(reads) < 10 and len(self.events) > 50:
            self.wins.append(
                {
                    "category": "selective_reading",
                    "description": f"Minimal file reads ({len(reads)} total)",
                    "impact": "Using semantic tools instead of brute-force reading",
                }
            )

        # Win: Low block rate
        blocks = len([e for e in self.events if e["type"] == "blocked"])
        total = len(self.events)
        if total > 20 and blocks / total < 0.1:
            self.wins.append(
                {
                    "category": "compliance",
                    "description": f"Low block rate ({blocks}/{total} = {blocks/total*100:.1f}%)",
                    "impact": "Following workflow rules effectively",
                }
            )

    def check_subagent_efficiency(self):
        """Check subagent performance."""
        if not SUBAGENT_METRICS.exists():
            return

        metrics = json.loads(SUBAGENT_METRICS.read_text())

        for agent_type, stats in metrics.get("summary", {}).get("by_type", {}).items():
            avg_tokens = stats.get("avg_tokens", 0)
            max_tokens = stats.get("max_tokens", 0)

            if max_tokens > 3000000:
                self.issues.append(
                    {
                        "severity": "critical",
                        "category": "runaway_agent",
                        "description": f"{agent_type} used {max_tokens:,} tokens in single execution",
                        "recommendation": "URGENT: Add token budget enforcement to prevent this",
                        "impact": "Massive cost, no output, system waste",
                    }
                )
            elif avg_tokens > 200000:
                self.issues.append(
                    {
                        "severity": "high",
                        "category": "expensive_agents",
                        "description": f"{agent_type} averages {avg_tokens:,} tokens per execution",
                        "recommendation": "Add structured output requirements, enforce tool selection",
                        "impact": "Agents doing too much work for their purpose",
                    }
                )
            elif avg_tokens < 50000 and stats["count"] > 3:
                self.wins.append(
                    {
                        "category": "efficient_agents",
                        "description": f"{agent_type} averages only {avg_tokens:,} tokens",
                        "impact": "Efficient execution, good tool selection",
                    }
                )

    def generate_report(self):
        """Generate diagnostic report."""
        self.analyze_patterns()
        self.identify_issues()
        self.identify_wins()
        self.check_subagent_efficiency()

        print("=" * 70)
        print("EFFICIENCY DIAGNOSTIC REPORT")
        print("=" * 70)

        print(f"\n📊 Analyzed {len(self.events)} events")

        # Issues
        if self.issues:
            print(f"\n⚠️  ISSUES FOUND ({len(self.issues)}):\n")

            critical = [i for i in self.issues if i.get("severity") == "critical"]
            high = [i for i in self.issues if i.get("severity") == "high"]
            medium = [i for i in self.issues if i.get("severity") == "medium"]

            for issue_list, emoji in [(critical, "🔴"), (high, "🟠"), (medium, "🟡")]:
                for issue in issue_list:
                    print(f"{emoji} {issue['description']}")
                    print(f"   Category: {issue['category']}")
                    print(f"   Impact: {issue['impact']}")
                    print(f"   Fix: {issue['recommendation']}")
                    print()
        else:
            print("\n✅ NO ISSUES FOUND")

        # Wins
        if self.wins:
            print(f"\n✅ WHAT'S WORKING ({len(self.wins)}):\n")
            for win in self.wins:
                print(f"• {win['description']}")
                print(f"  Impact: {win['impact']}")
                print()

        # Specific recommendations
        print("\n💡 ACTIONABLE RECOMMENDATIONS:\n")

        if not self.issues:
            print("✅ System operating efficiently. Consider:")
            print("   1. Document current patterns as best practices")
            print("   2. Set up monitoring alerts for regressions")
            print("   3. Save current metrics as baseline")
        else:
            # Prioritize recommendations
            if any(i["severity"] == "critical" for i in self.issues):
                print("🔴 CRITICAL (Do immediately):")
                for issue in [i for i in self.issues if i["severity"] == "critical"]:
                    print(f"   • {issue['recommendation']}")

            if any(i["severity"] == "high" for i in self.issues):
                print("\n🟠 HIGH PRIORITY (This week):")
                for issue in [i for i in self.issues if i["severity"] == "high"]:
                    print(f"   • {issue['recommendation']}")

            if any(i["severity"] == "medium" for i in self.issues):
                print("\n🟡 MEDIUM PRIORITY (When possible):")
                for issue in [i for i in self.issues if i["severity"] == "medium"]:
                    print(f"   • {issue['recommendation']}")

        # Pattern summary
        if self.patterns:
            print("\n📈 PATTERNS DETECTED:\n")
            for pattern_type, instances in self.patterns.items():
                if instances:
                    print(f"   {pattern_type}: {len(instances)} occurrences")


def main():
    analyzer = EfficiencyAnalyzer()

    # Parse arguments
    recent = None

    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--recent" and i + 1 < len(sys.argv) - 1:
            recent = int(sys.argv[i + 2])
        elif arg == "--agent" and i + 1 < len(sys.argv) - 1:
            sys.argv[i + 2]

    analyzer.load_activity_log(recent=recent)
    analyzer.generate_report()


if __name__ == "__main__":
    main()
