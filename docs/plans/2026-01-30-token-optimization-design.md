# Token Optimization Design

## Problem
Context stuffing across plugins, skills, agents, hooks, and session-start wastes
~10,000-15,000 tokens per session. Much of it is redundant, verbose, or low-value.

## Approach
Three-pronged: content compression (coded prompts L2-3), plugin consolidation,
and architectural changes to when/how context loads.

## Estimated Savings

| Category | Savings | Type |
|----------|---------|------|
| Disable 11 plugins | ~4,000-4,500 tok | Baseline (every session) |
| Compress CLAUDE.md | ~750 tok | Baseline |
| Trim superpowers registry descriptions | ~300 tok | Baseline |
| Kill session-start pipeline | ~1,000-1,500 tok | Baseline |
| Compress 10 agent-swarm skills | ~7,266 tok | On-demand (per invoke) |
| Compress 6 superpowers skills (overrides) | ~2,500-3,500 tok | On-demand (per invoke) |
| Compress 8 agent-swarm agents | ~1,034 tok | Per subagent spawn |
| Compress subagent-briefing.md | ~220 tok | Per subagent spawn |
| Compress hook denial messages | ~150-180 tok | Per denied tool call |
| Lazy-load orchestrate skills | ~3,000-4,000 tok | Per orchestrate session |
| **Baseline total** | **~6,500-7,500** | |
| **Peak session total** | **~15,000-20,000** | |

---

## 1. Disable Plugins

Disable these from always-on. Enable per-session when needed.

- pr-review-toolkit (~2,400 tok)
- plugin-dev (~600 tok)
- feature-dev (~300 tok)
- hookify (~200 tok)
- agent-sdk-dev (~140 tok)
- code-simplifier (~120 tok)
- code-review (~80 tok)
- playwright (~100 tok)
- frontend-design (~50 tok)
- security-guidance (~50 tok)
- github (~50 tok)

**Keep always-on:** superpowers, agent-swarm, episodic-memory, serena, context7

## 2. Compress CLAUDE.md

Replace `~/.claude/CLAUDE.md` (274 lines, ~1,100 tok) with coded prompt L2-3
version (~50 lines, ~350 tok).

Target content:

```markdown
# Agent Operating Protocol

<CRITICAL>
## Classification (first line of every response)
[TRIVIAL] one-liner | [SIMPLE] single-file <50 lines | [COMPLEX] multi-file/architectural | [RESEARCH] read-only | [CONVERSATION] discussion

COMPLEX if: multi-file, unclear scope, architectural, ambiguous requirements.
Uncertain -> ask "SIMPLE or COMPLEX?"

## Infrastructure
Missing infra -> STOP, state what's missing, ask before building.
Available: `~/.claude/lib/mcp_bridge.py`, `~/.claude/lib/scripts/`, `workflow:orchestrate`

## Workflow
TRIVIAL -> do directly
SIMPLE -> confirm -> implement -> verify -> done
COMPLEX -> invoke `workflow:orchestrate` first. No exceptions. No rationalization.
</CRITICAL>

## MUST
- **Batching:** <=2 ops -> direct tools. >=3 -> Python script, summary output only. Signal: `[SCRIPT] path -> executed -> cleaned`
- **Subagents:** exploration, multi-file search, research, large refactors. Not for <3 steps or single edits. Signal: `[SUBAGENT] type: summary`
- **Scope:** requested changes only. No speculative features. Ask "was this requested?" before adding.
- **Security:** no secrets in logs, parameterized queries, flag vulnerabilities before implementing.

## SHOULD
- **Handoff:** `~/.claude/docs/scratch/HANDOFF.md` before session end (task, status, files, next steps). Signal: `[STATE]`
- **Escalate:** ambiguous reqs, arch/security/API decisions, multiple valid approaches -> ask user.
- **Verify:** tests + types + lint before checkpoints. Signal: `[VERIFY] tests: Y | types: Y | lint: Y`

## PREFER
- Small composable functions; type hints on public APIs; docstrings on complex logic
- Tools: Serena > raw reads, `gh` > GitHub MCP, native Python > MCP
- TDD core logic; unit tests business logic; integration for externals
- Commits: frequent, descriptive, one change, no emoji/attribution
```

## 3. Compress Agent-Swarm Agents

Apply coded prompt L2-3 to all 8 agents in `agents/*.md`.

Pattern per agent (remove H1 title, one-line purpose, example block, output template):

```markdown
---
name: <name>
tools: Bash(mcp*)
description: <trimmed description>
model: <model>
---

<constraints>
- <terse imperative rule>
- <terse imperative rule>
</constraints>

Output: <one-line format description>
```

Files: adversary.md, explorer.md, architect.md, debugger.md, git-agent.md,
implementer.md, researcher.md, reviewer.md

Savings: ~130 tokens per spawn (45% reduction).

## 4. Compress Subagent Briefing

Replace `hooks/subagent-briefing.md` (67 lines, ~400 tok) with ~25 lines (~180 tok):

```markdown
# Subagent Protocol

## Tools
| Op | Tool |
|----|------|
| Search code | `serena__search_for_pattern` |
| Read files | `serena__read_file`, `native__read_file` |
| Find symbols | `serena__find_symbol`, `serena__get_symbols_overview` |
| Find files | `native__glob`, `serena__find_file` |
| Run commands | `native__bash` (git, pytest, ruff, gh) |
| Edit code | `serena__replace_content`, `serena__replace_symbol_body` |

Multi-repo: `native__bash 'git -C /path/to/repo status'`

## Efficiency
- >=3 reads or searches -> batch script with `mcp_bridge`
- Track what you've read -- no duplicate reads
- Output summaries only, not raw data

## Git (REVIEW phase only)
1. Verify branch (never create branches -- orchestrator's job)
2. Commit -> push -> create PR via `gh`
```

## 5. Compress Agent-Swarm Skills

Apply coded prompt L2-3 to all 10 skills in `skills/*/SKILL.md`.

Priority targets by size:

| Skill | Current | Target | Saved |
|-------|---------|--------|-------|
| iterate | 5,120 | ~2,000 | ~3,120 |
| spawn | 1,874 | ~750 | ~1,124 |
| debug | 1,312 | ~525 | ~787 |
| pr-comment | 1,161 | ~465 | ~696 |
| poll | 707 | ~280 | ~427 |
| distill | 650 | ~260 | ~390 |
| ctx | 467 | ~190 | ~277 |
| verify | 453 | ~180 | ~273 |
| implement | 217 | ~130 | ~87 |
| remember | 205 | ~120 | ~85 |

Compression approach:
- Remove prose explanations where structured rules suffice
- Remove examples where constraints are specific enough
- Replace tables with terse key-value notation
- Drop articles, hedging, "you should" phrasing
- Keep `<CRITICAL>` / emphasis markers where compliance matters

## 6. Plugin Overrides for Superpowers

Create `~/.claude/plugin-overrides/superpowers/` with compressed versions of
third-party skill files. Copy to cache after plugin updates.

### Directory Structure

```
~/.claude/plugin-overrides/
  superpowers/
    restore.sh          # Copies overrides back to cache
    skills/
      using-superpowers/SKILL.md
      brainstorming/SKILL.md
      test-driven-development/SKILL.md
      systematic-debugging/SKILL.md
      verification-before-completion/SKILL.md
      subagent-driven-development/SKILL.md
```

### restore.sh

```bash
#!/bin/bash
CACHE="$HOME/.claude/plugins/cache/superpowers-marketplace/superpowers"
VERSION=$(ls "$CACHE" | sort -V | tail -1)
DEST="$CACHE/$VERSION/skills"
SRC="$HOME/.claude/plugin-overrides/superpowers/skills"

for skill_dir in "$SRC"/*/; do
    skill=$(basename "$skill_dir")
    if [ -d "$DEST/$skill" ]; then
        cp "$skill_dir/SKILL.md" "$DEST/$skill/SKILL.md"
        echo "Restored: $skill"
    fi
done
```

### Superpowers Skill Compression Targets

| Skill | Current | Target | Saved |
|-------|---------|--------|-------|
| using-superpowers | 949 | ~250 | ~700 |
| test-driven-development | 2,466 | ~900 | ~1,566 |
| systematic-debugging | 2,471 | ~900 | ~1,571 |
| subagent-driven-development | 2,452 | ~900 | ~1,552 |
| verification-before-completion | 1,050 | ~400 | ~650 |
| brainstorming | 626 | ~250 | ~376 |

Also trim frontmatter `description` fields for all 14 superpowers skills
to reduce the always-present registry listing (~300 tok saved baseline).

## 7. Kill Session-Start Pipeline

Disable the session-start.py hook output. The pipeline injects:
- Hierarchical context (CONTEXT.md excerpts) -- redundant with codebase
- Resolver sections (boundaries, conventions) -- redundant with CLAUDE.md
- Inventory -- redundant with system prompt skill registry
- Episodic memory search (weak heuristic) -- low value
- Memory patterns (5 of 40+, not contextual) -- good content, bad delivery

### Approach

Set session-start.py to output empty systemMessage. Keep the counter-reset
and state-initialization logic (non-context functionality).

In `session-start.py`, replace the message-building block (lines 868-915) with:

```python
output = {"systemMessage": ""}
print(json.dumps(output))
```

If memory patterns are wanted later, use `/ctx` or a dedicated `/recall` command.

## 8. Compress Hook Denial Messages

Tighten `permissionDecisionReason` strings in enforcement hooks.

### inject-subagent-briefing.sh

Before (~200 tok):
```
[BRIEFING_REQUIRED] Task prompt must include subagent briefing.

Assemble the prompt:
1. Read: cat ~/.claude/plugins/agent-swarm/hooks/subagent-briefing.md
2. Prepend to your task with header: # SUBAGENT OPERATING PROTOCOL
3. Add phase restrictions if in iterate workflow
4. Re-call Task with assembled prompt

Subagent Tools (allowed_tools to include):
- Shell: mcp-call pytest, ...
...
```

After (~20 tok):
```
[BRIEFING_REQUIRED] Prepend hooks/subagent-briefing.md to Task prompt. Re-call with run_in_background=true.
```

### Other hooks

Review and trim denial messages in:
- `base-enforcement.py`
- `iterate-enforcement.py`
- `workflow-state-enforcement.py`
- `background-enforcement.py`

Target: each denial message <=30 tokens.

## 9. Lazy-Load Orchestrate Skills

Currently `/orchestrate` loads all 9 agent-swarm skills (~12,166 tok, ~4,900
compressed). The workflow is phased:

```
Intake -> Design -> Implement -> Verify -> Review -> Done
```

### Approach

Split the orchestrate SKILL.md into:
- Core orchestration logic (phase transitions, checkpoints) -- always loaded
- Per-phase skill content -- loaded via Skill tool when entering that phase

### Mapping

| Phase | Skill loaded |
|-------|-------------|
| Intake | ctx (context gathering) |
| Design | spawn (subagent delegation) |
| Implement | iterate or implement |
| Verify | verify |
| Review | pr-comment or distill |

Core orchestrate skill: ~500 tok (phase machine + transition rules).
Per-phase: ~200-500 tok each, loaded only when reached.

A session reaching only Implement phase loads ~1,200 tok instead of ~4,900.

---

## Implementation Order

1. Disable 11 plugins (immediate, no code changes)
2. Compress CLAUDE.md (one file edit)
3. Kill session-start pipeline output (one code change)
4. Compress hook denial messages (4-5 string edits)
5. Compress subagent-briefing.md (one file edit)
6. Compress 8 agent definitions (8 file edits, mechanical)
7. Compress 10 agent-swarm skills (10 file edits, requires reading each)
8. Create plugin-overrides with compressed superpowers skills (6 new files + script)
9. Refactor orchestrate for lazy-load (architectural change, most complex)

Steps 1-6 are quick. Steps 7-8 are mechanical but many files. Step 9 is the
only one requiring architectural thought.
