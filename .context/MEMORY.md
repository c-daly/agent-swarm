# Memory: Agent-Swarm

> This file captures patterns, pitfalls, preferences, and effective approaches
> discovered across sessions.

## Patterns Observed

- DONE workflow phase blocks ALL tools - creates unrecoverable deadlock
  Confidence: high | Last reinforced: 2026-01-10

- SessionStart hook referenced non-existent enforcement_state.json instead of session.json
  Confidence: high | Last reinforced: 2026-01-10

- Invalid hook event name in hooks.json disables ALL hooks, not just the broken one
  Confidence: high | Last reinforced: 2026-01-10

- Modifying hooks.json requires Claude Code restart to take effect
  Confidence: high | Last reinforced: 2026-01-10

- Infrastructure referenced in CLAUDE.md may not actually exist on disk
  Confidence: high | Last reinforced: 2026-01-10

- Git hygiene failure: local builds not committed lead to total loss on clone
  Confidence: high | Last reinforced: 2026-01-10

- The hook system runs synchronously; async patterns cause race conditions
  Confidence: high | Last reinforced: 2026-01-08

- State file must be updated atomically to prevent corruption
  Confidence: high | Last reinforced: 2026-01-10

- Explorer agents work best with explicit file count limits
  Confidence: medium | Last reinforced: 2026-01-05

- SessionStart/SessionEnd/PreCompact hooks use systemMessage field, NOT hookSpecificOutput.message
  Confidence: high | Last reinforced: 2026-01-10

- PreToolUse/PostToolUse hooks use hookSpecificOutput with hookEventName, different schema
  Confidence: high | Last reinforced: 2026-01-10

## Pitfalls Discovered

- Getting trapped in workflow phases while trying to test workflow
  Confidence: high | Last reinforced: 2026-01-10

- Agent ignoring CLAUDE.md instructions to use batch scripts for multiple file reads
  Confidence: high | Last reinforced: 2026-01-10

- Phase enforcement triggering even when not in active workflow context
  Confidence: high | Last reinforced: 2026-01-10

- Typo in hooks.json event name ("PreCompacting" vs "PreCompact") breaks entire hook system
  Confidence: high | Last reinforced: 2026-01-10

- Going in circles searching files instead of using claude-code-guide MCP wastes time
  Confidence: high | Last reinforced: 2026-01-10

- Pattern-matching hook output format from other hooks without checking schema leads to wrong implementation
  Confidence: high | Last reinforced: 2026-01-10

- Enforcement hooks can block operations while referencing infrastructure that doesn't exist
  Confidence: high | Last reinforced: 2026-01-10

- CLAUDE.md "verified working" doesn't mean it's in git or actually exists
  Confidence: high | Last reinforced: 2026-01-10

- MCP servers from plugins won't appear in settings.json mcpServers key
  Confidence: high | Last reinforced: 2026-01-10

- Bash cat/grep detection can have false positives on script content
  Confidence: medium | Last reinforced: 2026-01-09

- Phase transitions must update state BEFORE allowing next tool call
  Confidence: high | Last reinforced: 2026-01-10

## Preferences Inferred

- User expects use of proper tools (MCPs) rather than file searching/guessing
  Confidence: high | Last reinforced: 2026-01-10

- When stuck, consult documentation via claude-code-guide immediately
  Confidence: high | Last reinforced: 2026-01-10

- Check schema documentation (claude-code-guide/context7) BEFORE implementing, not after
  Confidence: high | Last reinforced: 2026-01-10

- User prefers tabular output over prose for status information
  Confidence: medium | Last reinforced: 2026-01-07

- Breaking changes should be documented in ENFORCEMENT_FIXES.md
  Confidence: high | Last reinforced: 2026-01-10

- Infrastructure must be committed immediately after creation
  Confidence: high | Last reinforced: 2026-01-10

- Git commit messages should NOT include Co-Authored-By - hooks handle this automatically
  Confidence: high | Last reinforced: 2026-01-10

## Effective Approaches

- Delete session.json to escape workflow deadlock as emergency recovery
  Confidence: high | Last reinforced: 2026-01-10

- Use claude-code-guide agent for Claude Code documentation instead of guessing
  Confidence: high | Last reinforced: 2026-01-10

- Validate hooks.json with python3 -m json.tool after any modifications
  Confidence: high | Last reinforced: 2026-01-10

- Test hook output with: python3 hooks/hook.py <<< '{}' | python3 -m json.tool
  Confidence: high | Last reinforced: 2026-01-10

- Check activity.log timestamp to verify hooks are actually firing
  Confidence: high | Last reinforced: 2026-01-10

- Write comprehensive MISSING_*.md docs when discovering infrastructure gaps
  Confidence: high | Last reinforced: 2026-01-10

- Use systematic research scripts to discover all references to missing components
  Confidence: high | Last reinforced: 2026-01-10

- Using JSON sidecars alongside markdown for reliable parsing
  Confidence: high | Last reinforced: 2026-01-10

- Pre-computing context at agent spawn rather than on-demand
  Confidence: medium | Last reinforced: 2026-01-08

---
*Last distilled: 2026-01-10*
