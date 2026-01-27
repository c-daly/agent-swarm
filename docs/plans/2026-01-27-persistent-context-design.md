# Persistent Context System Design

**Date:** 2026-01-27
**Status:** Approved
**Goal:** Persistent context that builds up over time like a real colleague's memory.

## Core Principles

### 1. Universal Hierarchy
All persistent files follow the same scope rules:
- ~/.claude/ - User level (global preferences)
- Workspace level - directories containing multiple .git children (inferred)
- Repo level - directories with .git
- Feature/component level - any directory with .context/

File types at each level: CONTEXT.md, MEMORY.md, HANDOFF.md, EPISODES.md

### 2. Scope Detection
Walk up from cwd to ~/.claude/, detecting:
- Component/Feature - directory with .context/
- Repo - directory with .git
- Workspace - directory with multiple .git children
- User - ~/.claude/

### 3. Automatic Scope Inference for Saving
- Mentions specific paths → deepest common directory
- Contains "always/never/I prefer" → user level
- Same learning across 2+ repos → promote to workspace/user

## Learning Triggers

### 1. Manual (/remember)
- Immediate save, brief confirmation
- Auto scope inference with optional --scope override

### 2. Real-time Correction Detection
- After 2-3 similar corrections, propose saving the pattern
- Shows what's being learned, saves immediately

### 3. Session/Task Completion Distill
- Proposes learnings with inferred scopes
- User approves, dismisses, or edits

## Distill Operations
1. Episodes → Memory (extract learnings)
2. Memory compaction (merge redundant, prune low-confidence)
3. Promotion (patterns across 2+ scopes go up)
4. Handoff cleanup (archive old, keep recent)

## Session Start Loading
Walk up from cwd, load from each .context/:
- CONTEXT.md (merge with inheritance rules)
- MEMORY.md (all learnings, tagged by scope)
- HANDOFF.md (if < 48 hours old)
- EPISODES.md not loaded (raw logs)

## Implementation Tasks
1. Enhance resolver (workspace detection, multi-file)
2. New /remember command
3. Correction detection
4. Save-at-scope utility
5. Enhanced session-end distill with promotion
