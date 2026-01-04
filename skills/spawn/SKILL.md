---
name: spawn
description: How to spawn subagents correctly. Use this reference when you need to delegate work to a specialized agent.
---

# Spawning Subagents

## Why Subagents

1. **Model efficiency**: Orchestrator uses opus, subagents use cheaper models
2. **Context isolation**: Subagent work doesn't flood main context
3. **Parallelization**: Multiple subagents can work simultaneously
4. **Focus**: Each agent has a specific role with clear constraints

## How to Spawn

Use the Task tool with these parameters:

```json
{
  "description": "3-5 word summary",
  "prompt": "Detailed instructions for the agent",
  "subagent_type": "Explore|Plan|general-purpose",
  "model": "haiku|sonnet|opus"
}
```

## Agent Selection

| Need | Agent | Model | subagent_type |
|------|-------|-------|---------------|
| Find code/files | explorer | haiku | Explore |
| Web/doc research | researcher | haiku | general-purpose |
| Plan implementation | architect | sonnet | Plan |
| Write code | implementer | sonnet | general-purpose |
| Review changes | reviewer | sonnet | general-purpose |
| Fix bugs | debugger | sonnet | general-purpose |
| Git operations | git-agent | haiku | general-purpose |

## Prompt Structure

Every subagent prompt MUST include:

1. **Task**: What exactly to do (one clear objective)
2. **Scope**: What files/areas to touch
3. **Output**: What to return (be specific about format)
4. **Constraints**: What NOT to do

### Example Prompts

**Explorer (finding code):**
```
Find all authentication-related code.

Scope: src/ directory
Output: List of file:line references with one-line descriptions
Constraints: Don't read file contents, just locate. Use Serena tools.
```

**Implementer (writing code):**
```
Add input validation to the login form.

Scope: src/components/LoginForm.tsx only
Output: Summary of changes made
Constraints: Don't modify other files. Don't add new dependencies.
Follow existing patterns in the codebase.
```

**Reviewer (checking code):**
```
Review changes to authentication flow.

Scope: Files modified in current branch vs main
Output: PASS or NEEDS_CHANGES with specific issues
Constraints: Focus on bugs and security. Skip style issues.
```

## Parallel Spawning

When tasks are independent, spawn multiple in one message:

```
I'll spawn three subagents in parallel:
1. Explorer to find auth files
2. Explorer to find test files
3. Researcher to get latest JWT best practices

[Three Task tool calls in same message]
```

## Anti-Patterns

**DON'T:**
- Spawn subagent for one-liner tasks
- Use opus model for subagents (reserved for orchestrator)
- Give vague prompts like "look around"
- Spawn subagent to do what you could do in 2 tool calls

**DO:**
- Batch related work into one subagent
- Specify exact output format
- Use cheapest model that can do the job
- Set clear scope boundaries

## Subagent Context

Subagents receive:
- The prompt you provide
- Agent rules from AGENT_RULES.md (via hook injection)
- Access to same tools as you

Subagents do NOT receive:
- Your conversation history
- Current phase/state (unless you tell them)
- Other subagents' results (unless you include them)
