# Context: Agent-Swarm

## Purpose
Multi-agent orchestration and enforcement system for Claude Code.
Enables complex workflows with specialized agents while maintaining
efficiency, safety, and predictable behavior.

## Boundaries
- This is an enforcement/orchestration layer, not application code
- Hooks intercept tool calls; they don't implement features
- Agents perform work; orchestrator coordinates
- Config defines phases; hooks enforce them

## Conventions
- Python 3.10+ for all scripts
- Hooks must be fast (<100ms) - they run on every tool call
- JSON for state, Markdown for documentation
- Phase names are lowercase, hyphenated

## Key Decisions
- **Pre-tool hooks for enforcement**: Decided to intercept BEFORE tool execution
  rather than after. Allows blocking, not just logging.
- **Subagent-only implementation**: The implement phase requires subagents to
  prevent orchestrator from doing direct implementation work.
- **Markdown-first context**: Context files are human-readable markdown with
  optional JSON sidecars for reliable parsing.
- **Distillation over accumulation**: Memory is refined, not just appended.
  Patterns gain/lose confidence over time.

## Dependencies
- Claude Code hooks system (preToolUse, postToolUse)
- Python 3.10+ (dataclasses, pathlib, typing)
- No external packages required for core functionality

## Patterns
- **Hook chain**: combined-enforcement.py → post-task-tracking.py
- **State file**: `.state/session.json` tracks phase, counts, approvals
- **Agent definitions**: `agents/*.md` with model hints
- **Workflow phases**: intake → explore → design → implement → review → git
