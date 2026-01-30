#!/usr/bin/env python3
"""
Format Experiment Framework

Compares different subagent briefing formats to measure impact on agent behavior.
Standard task: "Explore the router module and report its structure"

Variants:
  A: Legacy (~2000 chars) - verbose prose, tool syntax examples
  B: Constraints-first (~600 chars) - NEVER/ALWAYS rules, minimal tool ref
  C: Ultra-dense (~300 chars) - bullet-only, no examples
  D: XML-heavy (~800 chars) - XML constraint tags, structured sections

Rubric (score 0-3 each):
  1. Serena usage: Used symbolic tools vs raw reads
  2. Sequential read count: 0-1=3, 2-3=2, 4-5=1, 6+=0
  3. Task compliance: Output matches requested format
  4. Output format: Structured (bullets, refs) vs prose
  5. Total tool calls: <10=3, 10-15=2, 16-20=1, 21+=0

Usage:
  python3 scripts/format_experiment.py generate   # Write variant briefings
  python3 scripts/format_experiment.py score       # Interactive scoring
  python3 scripts/format_experiment.py report      # Comparison table
"""

import json
import sys
from pathlib import Path

VARIANTS_DIR = Path("/tmp/format_experiment")
SCORES_FILE = VARIANTS_DIR / "scores.json"

STANDARD_TASK = (
    "Explore the router module (lib/routing_service.py) and report its structure. "
    "List key classes, public methods, and how requests are routed to MCP servers."
)

VARIANT_A = """\
# Subagent Operating Protocol
**You are a subagent spawned by the orchestrator.**

You have access to tools through the MCP router. When you need to search code, use serena__search_for_pattern. When you need to read files, use serena__read_file or native__read_file. For finding symbols, use serena__find_symbol. To get an overview of a file's structure, use serena__get_symbols_overview. For listing files, use native__glob or serena__find_file. To run commands, use native__bash for git, pytest, ruff, gh, python3. To edit code, use serena__replace_content for text replacement or serena__replace_symbol_body for replacing entire functions or classes.

When you need to perform multiple operations, please batch them together. For example, if you need to search for 3 or more patterns, write a script using the batch_search.py utility. Scripts are located in ~/.claude/plugins/agent-swarm/scripts/ and ~/.claude/plugins/agent-swarm/lib/scripts/.

Please be efficient with your token usage. Return references (file:line) rather than full file contents. Use structured output with bullets and markdown headers.

Remember to stay focused on your assigned task and don't do extra work that wasn't requested.
"""

VARIANT_B = """\
# Subagent Operating Protocol
You are a subagent. Tools via MCP router.

<constraints>
1. NEVER read files sequentially - use serena symbolic tools or batch scripts
2. NEVER exceed 5 same-type tool calls without switching to batch script
3. NEVER do work outside assigned task scope
4. NEVER claim you did something you didn't - report failures honestly
5. ALWAYS use serena symbolic tools over raw file reads
6. ALWAYS make independent tool calls in a single message (parallel)
</constraints>

## Tools
| Op | Tool |
|----|------|
| Search | serena__search_for_pattern |
| Read | serena__read_file, native__read_file |
| Symbols | serena__find_symbol, serena__get_symbols_overview |
| Files | native__glob, serena__find_file |
| Commands | native__bash |
| Edit | serena__replace_content |

Report in your agent's output format. Stay focused. Be honest.
"""

VARIANT_C = """\
# Subagent Protocol
- Tools: serena__* (symbols, search, read, edit), native__* (bash, glob, read)
- NEVER: sequential reads, scope creep, dishonest reporting
- ALWAYS: serena symbolic tools first, parallel calls, batch 3+ ops
- Output: structured markdown, file:line refs, no prose
"""

VARIANT_D = """\
<agent-protocol>
  <identity>You are a subagent spawned by the orchestrator.</identity>
  <constraints>
    <rule severity="NEVER">Read files sequentially - use serena symbolic tools</rule>
    <rule severity="NEVER">Exceed 5 same-type calls - use batch script</rule>
    <rule severity="NEVER">Work outside assigned task scope</rule>
    <rule severity="NEVER">Claim you did something you didn't</rule>
    <rule severity="ALWAYS">Use serena symbolic tools over raw file reads</rule>
    <rule severity="ALWAYS">Make independent tool calls in parallel</rule>
  </constraints>
  <tools>
    <tool name="serena__search_for_pattern">Search code</tool>
    <tool name="serena__find_symbol">Find definitions</tool>
    <tool name="serena__get_symbols_overview">File structure</tool>
    <tool name="serena__read_file">Read file</tool>
    <tool name="native__bash">Shell commands</tool>
    <tool name="serena__replace_content">Edit code</tool>
  </tools>
  <output>Structured markdown. file:line refs. No prose.</output>
</agent-protocol>
"""

VARIANTS = {"A": VARIANT_A, "B": VARIANT_B, "C": VARIANT_C, "D": VARIANT_D}
VARIANT_NAMES = {
    "A": "Legacy verbose",
    "B": "Constraints-first",
    "C": "Ultra-dense",
    "D": "XML-heavy",
}

RUBRIC = [
    "serena_usage",
    "sequential_reads",
    "task_compliance",
    "output_format",
    "tool_call_count",
]


def generate():
    VARIANTS_DIR.mkdir(parents=True, exist_ok=True)
    for key, content in VARIANTS.items():
        path = VARIANTS_DIR / f"variant_{key}.md"
        path.write_text(content)
        print(f"  Written: {path} ({len(content)} chars)")
    task_path = VARIANTS_DIR / "task.md"
    task_path.write_text(STANDARD_TASK)
    print(f"  Task: {task_path}")
    print(f"\nTo test: spawn an explorer with each variant as briefing + task.md as prompt")


def score():
    scores = {}
    if SCORES_FILE.exists():
        scores = json.loads(SCORES_FILE.read_text())
    for key in VARIANTS:
        name = VARIANT_NAMES[key]
        print(f"\n--- Variant {key}: {name} ({len(VARIANTS[key])} chars) ---")
        variant_scores = {}
        for metric in RUBRIC:
            while True:
                try:
                    val = int(input(f"  {metric} (0-3): "))
                    if 0 <= val <= 3:
                        variant_scores[metric] = val
                        break
                except (ValueError, EOFError):
                    pass
                print("  Enter 0-3")
        variant_scores["total"] = sum(variant_scores.values())
        variant_scores["chars"] = len(VARIANTS[key])
        scores[key] = variant_scores
    SCORES_FILE.write_text(json.dumps(scores, indent=2))
    print(f"\nScores saved to {SCORES_FILE}")


def report():
    if not SCORES_FILE.exists():
        print("No scores yet. Run: python3 scripts/format_experiment.py score")
        return
    scores = json.loads(SCORES_FILE.read_text())
    print(f"\n{'Variant':<25} {'Chars':>5} ", end="")
    for m in RUBRIC:
        print(f" {m[:10]:>10}", end="")
    print(f" {'TOTAL':>7}")
    print("-" * 90)
    for key in sorted(scores.keys()):
        s = scores[key]
        name = f"{key}: {VARIANT_NAMES.get(key, '?')}"
        print(f"{name:<25} {s.get('chars', '?'):>5} ", end="")
        for m in RUBRIC:
            print(f" {s.get(m, '?'):>10}", end="")
        print(f" {s.get('total', '?'):>7}")
    best = max(scores.items(), key=lambda x: x[1].get("total", 0))
    print(f"\nBest: Variant {best[0]} ({VARIANT_NAMES.get(best[0])}) - {best[1]['total']}/15")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/format_experiment.py [generate|score|report]")
        print(f"\nStandard task: {STANDARD_TASK}")
        print(f"\nVariants: {', '.join(f'{k}={VARIANT_NAMES[k]}' for k in VARIANTS)}")
        return
    cmd = sys.argv[1]
    if cmd == "generate":
        generate()
    elif cmd == "score":
        score()
    elif cmd == "report":
        report()
    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
