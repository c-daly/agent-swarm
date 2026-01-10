# Context: User Profile

> This file goes in `~/.claude/CONTEXT.md`
> It provides global context about the user across all projects.

## Purpose
Personal preferences and identity for Claude interactions.

## Preferences
- Concise responses preferred over verbose explanations
- Code over prose when possible
- Direct feedback, even if critical
- Prefer existing patterns over introducing new dependencies

## Conventions
- Use TypeScript for new frontend code
- Python 3.10+ for backend/scripts
- Commit messages: imperative mood, 50 char subject line
- PR descriptions include: summary, test plan, screenshots if UI

## Key Decisions
- I work across multiple repositories; maintain awareness of shared patterns
- I value correctness over speed; take time to verify assumptions
- I prefer fixing root causes over workarounds
- Document decisions that aren't obvious from code

## Pitfalls to Avoid
- Over-engineering simple problems
- Adding dependencies without checking for stdlib alternatives
- Changing code style in files I'm not modifying
- Making changes beyond what was asked
