# Explore-Before-Prompt Pattern

## Problem Statement

When the orchestrator spawns implementer agents, it sometimes lacks sufficient context to write effective prompts. This leads to:
- Vague prompts that lack file paths, patterns, or concrete examples
- Implementers spending tokens on exploration they could have received upfront
- Poor implementation quality due to missing context

## Solution

Implement a two-phase pattern:
1. **Detection**: Orchestrator detects when it lacks sufficient context
2. **Exploration**: Spawn explorer agent to gather context
3. **Implementation**: Use explorer output to write detailed implementer prompts

## Architecture

### 1. Detection Logic

**Module**: `lib/exploration_helpers.py`

**Function**: `needs_exploration(task: dict, available_context: dict) -> bool`

**Detection Criteria** (returns True if ANY match):
- Task references files/modules not yet read by orchestrator
- Task description is vague (< 10 words, no file paths)
- No code snippets or file references in available context
- Task uses vague verbs ("improve", "fix", "refactor") without specifics
- Task mentions "similar to" or "like in" without providing examples

**Inputs**:
- `task`: Task dictionary with `description`, `type`, `metadata`
- `available_context`: Dict with `files_read`, `code_snippets`, `patterns_known`

**Output**: Boolean indicating whether exploration is needed

### 2. Exploration Patterns

**Pattern 1: File Discovery**
- **When**: Task mentions file/module names not in context
- **Explorer Prompt**: "Find all files related to [module/feature]. Return file paths, key functions, and usage patterns."
- **Usage**: Implementer gets exact file paths and entry points

**Pattern 2: Pattern Matching**
- **When**: Task says "similar to X" or "like in Y"
- **Explorer Prompt**: "Find implementations of [X]. Show patterns, common approaches, and helper functions used."
- **Usage**: Implementer follows established patterns

**Pattern 3: Dependency Mapping**
- **When**: Task involves modifying existing code
- **Explorer Prompt**: "Map dependencies for [component]. Find callers, imports, and side effects."
- **Usage**: Implementer knows what else needs updating

**Pattern 4: Context Enrichment**
- **When**: Task is vague (< 10 words)
- **Explorer Prompt**: "Explore [area] to understand current implementation. Return structure, key files, and existing patterns."
- **Usage**: Orchestrator rewrites task with specific details

### 3. Prompt Templates

**Template Storage**: `lib/prompt_templates.py`

```python
EXPLORATION_PROMPTS = {
    "file_discovery": """Find all files related to {topic}.

Return:
- File paths with brief descriptions
- Key functions/classes in each file
- Usage patterns or examples
- Entry points for modification

Limit: 20 files max, 2000 chars total.""",

    "pattern_matching": """Find implementations of {feature}.

Return:
- Files where pattern is used
- Common approaches or styles
- Helper functions typically involved
- Examples of correct usage

Limit: 15 patterns max, 2000 chars total.""",

    "dependency_mapping": """Map dependencies for {component}.

Return:
- Files that import/use this component
- Functions that call these methods
- Potential side effects of changes
- Test files covering this code

Limit: 20 references max, 2000 chars total.""",

    "context_enrichment": """Explore {area} to understand current implementation.

Return:
- Directory structure
- Key files and their purposes
- Existing patterns in use
- Suggested starting points

Limit: 20 files max, 2000 chars total."""
}

IMPLEMENTER_PROMPTS = {
    "with_exploration": """Implement: {task_description}

**Context from Exploration:**
{explorer_output}

**Requirements:**
{requirements}

**Files to Modify:**
{suggested_files}

Follow the patterns shown above. Verify side effects before changes.""",

    "without_exploration": """Implement: {task_description}

**Requirements:**
{requirements}

Explore the codebase first to understand existing patterns. Verify side effects before changes."""
}
```

### 4. Orchestrator Integration

**Location**: `lib/iterate_workflow.py` or `lib/orchestrate.py`

**Flow**:
```python
def spawn_implementation_agent(task: dict, context: dict):
    """Spawn implementer, with optional exploration first."""

    if needs_exploration(task, context):
        # Phase 1: Explore
        exploration_type = detect_exploration_type(task)
        explorer_prompt = format_explorer_prompt(exploration_type, task)

        explorer_result = spawn_agent(
            type="agent-swarm:explorer",
            model="haiku",
            token_budget=50000,
            prompt=explorer_prompt
        )

        # Phase 2: Implement with context
        enriched_context = {**context, "exploration": explorer_result}
        implementer_prompt = format_implementer_prompt(task, enriched_context)
    else:
        # Direct implementation
        implementer_prompt = format_implementer_prompt(task, context)

    return spawn_agent(
        type="agent-swarm:implementer",
        model="sonnet",
        token_budget=100000,
        prompt=implementer_prompt
    )
```

## Documentation Updates

### File: `skills/iterate/SKILL.md`

Add new section after "Orchestrator responsibilities":

```markdown
### Explore-Before-Prompt Pattern

**When to use exploration:**

The orchestrator should spawn an explorer agent BEFORE spawning an implementer when:
- Task references files/modules not yet read
- Task description is vague (< 10 words, no specifics)
- Task uses vague verbs ("improve", "fix") without context
- Task mentions "similar to X" without providing examples
- No code snippets or file paths in available context

**Exploration workflow:**

1. Detect: Call `needs_exploration(task, context)` helper
2. Explore: Spawn explorer with targeted prompt (see prompt templates)
3. Enrich: Parse explorer output, add to context
4. Implement: Spawn implementer with enriched prompt

**Prompt templates available:**
- `file_discovery` - Find relevant files for a topic
- `pattern_matching` - Find existing implementations to follow
- `dependency_mapping` - Map side effects before changes
- `context_enrichment` - Understand unfamiliar area

**Example:**

```python
# Bad: vague prompt
Task(
    description="Fix auth system",
    prompt="Fix the authentication system bugs"
)

# Good: explore-first
explorer_output = Task(
    subagent_type="agent-swarm:explorer",
    prompt="Find all authentication-related files. Return file paths, key functions, and current auth flow."
)

Task(
    description="Fix auth token expiration",
    prompt=f"Fix auth token expiration bug in authentication system.

Context from exploration:
{explorer_output}

Requirements:
- Token should expire after 24h
- Refresh tokens should work
- Tests must pass

Files to modify (from exploration above):
- auth/tokens.py - Token generation logic
- auth/middleware.py - Token validation
"
)
```
```

## Testing

### File: `lib/test_exploration_helpers.py`

Test cases:
1. **Test vague task detection**: Task with < 10 words triggers exploration
2. **Test file reference detection**: Task mentioning unread files triggers exploration
3. **Test pattern detection**: Task with "improve"/"fix" without specifics triggers exploration
4. **Test negative cases**: Well-specified tasks don't trigger exploration
5. **Test context override**: Rich context prevents exploration even for vague task

## Implementation Tasks

Decompose into task queue:

1. **Create `lib/exploration_helpers.py`**
   - Implement `needs_exploration()` function
   - Implement `detect_exploration_type()` function
   - Add helper utilities

2. **Create `lib/prompt_templates.py`**
   - Define exploration prompt templates
   - Define implementer prompt templates
   - Add formatting functions

3. **Update `skills/iterate/SKILL.md`**
   - Add "Explore-Before-Prompt Pattern" section
   - Add example workflows
   - Document when to use pattern

4. **Create `lib/test_exploration_helpers.py`**
   - Write test cases for detection logic
   - Test all detection criteria
   - Test edge cases

5. **Update orchestrator logic** (if needed)
   - Integration points in `lib/orchestrate.py` or workflow
   - Example usage in comments

## Success Criteria

- [ ] `needs_exploration()` correctly identifies when exploration is needed
- [ ] Prompt templates cover common scenarios (file discovery, patterns, dependencies, context)
- [ ] Documentation clearly explains when and how to use pattern
- [ ] Tests achieve >90% coverage on detection logic
- [ ] Example workflows demonstrate usage

## Non-Goals

- Automatic exploration (orchestrator must explicitly call pattern)
- Explorer result parsing/validation (orchestrator handles output)
- Caching of exploration results (future enhancement)
