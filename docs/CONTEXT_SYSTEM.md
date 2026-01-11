# Hierarchical Context System

## Overview

A context management system that provides Claude with layered, scoped knowledge at every level of the directory hierarchy. Context flows from user-global settings down through project, repo, and feature levels, with each layer adding specificity.

## Design Principles

1. **Locality of Reference** - Context closest to the work takes precedence
2. **Inheritance** - General context flows down unless overridden
3. **Distillation Over Accumulation** - Memory is refined, not just appended
4. **Minimal Footprint** - Context files stay small and relevant

## Hierarchy Levels

```
~/.claude/                          # USER LEVEL
├── CONTEXT.md                      # Identity, preferences, global settings
├── MEMORY.md                       # Distilled cross-project learnings
└── projects/
    └── my-project/                 # PROJECT LEVEL (multi-repo)
        ├── CONTEXT.md              # Project vision, architecture decisions
        ├── MEMORY.md               # Project-wide learnings
        └── repos/
            └── agent-swarm/        # REPO LEVEL
                ├── .claude/
                │   ├── CONTEXT.md  # Repo purpose, conventions, patterns
                │   └── MEMORY.md   # Repo-specific learnings
                └── features/
                    └── auth/       # FEATURE LEVEL
                        ├── .context/
                        │   ├── CONTEXT.md  # Feature scope, requirements
                        │   └── MEMORY.md   # Feature implementation learnings
                        └── components/
                            └── login/  # COMPONENT LEVEL
                                └── .context/
                                    └── CONTEXT.md  # Component details
```

## Context File Types

### CONTEXT.md - Static Knowledge
Describes what something IS. Relatively stable, updated intentionally.

```markdown
# Context: [Scope Name]

## Purpose
What this scope is for, its core mission.

## Boundaries
What belongs here vs. adjacent scopes.

## Conventions
Patterns, naming, style decisions specific to this scope.

## Key Decisions
Architectural choices and their rationale.

## Dependencies
What this scope relies on, integrates with.
```

### MEMORY.md - Distilled Learnings
What has been LEARNED. Evolves through distillation, not direct editing.

```markdown
# Memory: [Scope Name]

## Patterns Observed
- Pattern: [description]
  Confidence: high/medium/low
  Last reinforced: [date]

## Pitfalls Discovered
- [What went wrong and why]

## Preferences Inferred
- [Observed user preferences at this scope]

## Effective Approaches
- [What worked well]
```

### EPISODES.md - Recent Sessions (Ephemeral)
Raw session history, awaiting distillation. Auto-purged after distillation.

```markdown
# Episodes: [Scope Name]

## Session: 2026-01-10T14:30:00Z
- Task: [what was attempted]
- Outcome: [success/failure/partial]
- Learnings: [raw observations]
- Duration: [time spent]

## Session: 2026-01-09T09:15:00Z
...
```

## Context Resolution Algorithm

When Claude starts working in a directory, the context loader:

```python
def resolve_context(working_dir: Path) -> AggregatedContext:
    """
    Walk up the directory tree collecting context.
    More specific context overrides more general.
    """
    contexts = []

    # 1. Collect from current dir up to filesystem root
    current = working_dir
    while current != current.parent:
        context_file = find_context_file(current)
        if context_file:
            contexts.append(load_context(context_file))
        current = current.parent

    # 2. Add user-level context from ~/.claude
    user_context = load_user_context()
    contexts.append(user_context)

    # 3. Reverse so general comes first
    contexts.reverse()

    # 4. Merge with later (more specific) overriding earlier
    return merge_contexts(contexts)
```

### Merge Strategy

| Field Type | Merge Behavior |
|------------|----------------|
| Scalars | Override (specific wins) |
| Lists | Append (accumulate) |
| Dicts | Deep merge |
| Conflicts | Explicit `@override` annotation forces replacement |

## Memory Distillation System

### The Problem with Episodic Memory

Raw session logs grow unbounded and become noise. Important patterns get buried in details.

### Distillation Process

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  EPISODES   │ ──► │  DISTILLER   │ ──► │   MEMORY    │
│  (raw)      │     │  (process)   │     │  (refined)  │
└─────────────┘     └──────────────┘     └─────────────┘
       │                   │                    │
       │                   │                    │
       ▼                   ▼                    ▼
   time-bound         pattern-based        persistent
   detailed           extractive           semantic
   append-only        periodic             evolving
```

### Distillation Rules

1. **Frequency → Confidence**: Patterns observed repeatedly increase confidence
2. **Recency → Relevance**: Recent observations weigh more heavily
3. **Contradiction → Resolution**: Conflicting observations trigger explicit handling
4. **Decay → Cleanup**: Unobserved patterns gradually fade

### Distillation Triggers

| Trigger | Action |
|---------|--------|
| Session end | Queue episodes for distillation |
| Episode count > N | Force immediate distillation |
| Manual `/distill` command | User-triggered distillation |
| Time-based (daily/weekly) | Scheduled maintenance |

### Distillation Algorithm

```python
def distill(episodes: list[Episode], memory: Memory) -> Memory:
    """
    Extract patterns from episodes and merge into memory.
    """
    new_memory = memory.copy()

    for episode in episodes:
        patterns = extract_patterns(episode)
        for pattern in patterns:
            if pattern in new_memory:
                # Reinforce existing pattern
                new_memory.reinforce(pattern, episode.timestamp)
            else:
                # Add new pattern with low confidence
                new_memory.add(pattern, confidence='low')

    # Decay old patterns not recently reinforced
    new_memory.apply_decay()

    # Remove patterns below confidence threshold
    new_memory.prune(min_confidence=0.2)

    return new_memory
```

## Integration with Agent-Swarm

### Phase-Aware Context

Different phases need different context emphasis:

| Phase | Context Priority |
|-------|-----------------|
| intake | User preferences, project goals |
| explore | Repo conventions, component boundaries |
| design | Architectural decisions, patterns |
| implement | Feature context, code conventions |
| review | Quality standards, pitfalls |
| git | Commit conventions, branch patterns |

### Agent-Specific Views

```python
def get_agent_context(agent_type: str, working_dir: Path) -> str:
    """
    Return context tailored for a specific agent type.
    """
    full_context = resolve_context(working_dir)

    # Filter to what this agent needs
    if agent_type == 'explorer':
        return full_context.sections(['boundaries', 'conventions'])
    elif agent_type == 'implementer':
        return full_context.sections(['conventions', 'patterns', 'pitfalls'])
    elif agent_type == 'architect':
        return full_context.sections(['purpose', 'key_decisions', 'dependencies'])
    # ...
```

### Context Updates

Agents can propose context updates during their work:

```python
# In implementer agent output
{
    "context_updates": [
        {
            "scope": "feature/auth",
            "type": "pattern",
            "content": "JWT tokens require refresh handling in this codebase",
            "confidence": "medium"
        }
    ]
}
```

These proposals are:
1. Validated by the orchestrator
2. Added to EPISODES.md immediately
3. Distilled into MEMORY.md on session end

## File Discovery

### Search Order for Context Files

Within each directory level:

1. `.context/CONTEXT.md` (preferred - hidden directory)
2. `.claude/CONTEXT.md` (repo-level standard)
3. `CONTEXT.md` (visible, for shared visibility)
4. `.context.md` (hidden single file)

### Inheritance Control

```markdown
# Context: Feature Auth

@inherit: true          # Default: inherit from parent
@override: conventions  # Override specific sections
@ignore: pitfalls       # Don't inherit this section
```

## Token Budget Management

Context can't be unlimited. Budget allocation:

| Level | Max Tokens | Notes |
|-------|-----------|-------|
| User | 500 | Core identity, preferences |
| Project | 1000 | Vision, cross-repo patterns |
| Repo | 1500 | Conventions, architecture |
| Feature | 1000 | Scope-specific details |
| Component | 500 | Implementation details |
| **Total Max** | 4500 | Hard limit for context |

### Compression Strategies

1. **Summarization**: Long context gets AI-summarized
2. **Relevance Filtering**: Only load sections relevant to current phase
3. **Recency Weighting**: Recent memory items prioritized
4. **Explicit Importance**: `@priority: high` annotations

## Commands

| Command | Description |
|---------|-------------|
| `/context` | Show resolved context for current directory |
| `/context edit [level]` | Edit context at specific level |
| `/context add [pattern]` | Add a pattern to current scope memory |
| `/distill` | Force immediate memory distillation |
| `/context tree` | Show context hierarchy visualization |

## Implementation Phases

### Phase 1: Core Resolution
- [ ] Context file discovery
- [ ] Hierarchy walking
- [ ] Basic merge logic
- [ ] Integration with agent startup

### Phase 2: Memory System
- [ ] Episode logging
- [ ] Distillation algorithm
- [ ] Confidence/decay mechanics
- [ ] Scheduled distillation

### Phase 3: Agent Integration
- [ ] Phase-aware filtering
- [ ] Agent-specific views
- [ ] Context update proposals
- [ ] Token budget enforcement

### Phase 4: User Experience
- [ ] `/context` commands
- [ ] Visualization
- [ ] Manual editing workflow
- [ ] Export/import

## Example: Full Context Resolution

Working directory: `/home/user/projects/acme/repos/api-server/src/auth/oauth`

Resolved context aggregates:

```
~/.claude/CONTEXT.md
  └── "I prefer concise code, avoid over-abstraction"

~/.claude/projects/acme/CONTEXT.md
  └── "Acme project uses microservices, shared auth"

/repos/api-server/.claude/CONTEXT.md
  └── "Express.js, TypeScript, PostgreSQL"

/src/auth/.context/CONTEXT.md
  └── "Auth module handles JWT, OAuth, sessions"

/src/auth/oauth/.context/CONTEXT.md
  └── "OAuth2 with Google, GitHub providers"
```

Final merged context for an implementer agent:

```markdown
## User Preferences
- Concise code, avoid over-abstraction

## Project Context
- Microservices architecture
- Shared authentication across services

## Repository
- Stack: Express.js, TypeScript, PostgreSQL
- Conventions: ESLint strict, Prettier

## Feature: Auth
- Handles: JWT tokens, OAuth flows, sessions
- Patterns: Token refresh middleware pattern

## Component: OAuth
- Providers: Google, GitHub
- Pattern: Strategy pattern for provider abstraction
```
