# Memory: Agent-Swarm

> This file captures patterns, pitfalls, preferences, and effective approaches
> discovered across sessions.

## Patterns Observed

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

## Pitfalls Discovered

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

- User prefers tabular output over prose for status information
  Confidence: medium | Last reinforced: 2026-01-07

- Breaking changes should be documented in ENFORCEMENT_FIXES.md
  Confidence: high | Last reinforced: 2026-01-10

- Infrastructure must be committed immediately after creation
  Confidence: high | Last reinforced: 2026-01-10

## Effective Approaches

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
