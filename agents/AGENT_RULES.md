# Agent Rules - Non-Negotiable

Every agent MUST follow these rules. Violations waste tokens and context.

## Output Rules

1. **NO PROSE** - Use bullet points, tables, code blocks
2. **NO EXPLANATIONS** - Just facts and actions
3. **NO PLEASANTRIES** - No "I'll help you", "Let me", "Great question"
4. **NO REPETITION** - Say it once, reference by name after
5. **MAX LENGTHS**:
   - Summary: 3 sentences
   - File reference: path:line only
   - Code snippet: 10 lines max, use "..." for omitted
   - Error description: 1 line

## Tool Rules

### Code Analysis - USE SERENA, NOT FILE READS

**NEVER** use Read tool for understanding code. Use Serena:

```
mcp__plugin_serena_serena__find_symbol     - Find where something is defined
mcp__plugin_serena_serena__find_references - Find where something is used
mcp__plugin_serena_serena__get_definition  - Get signature + docstring
mcp__plugin_serena_serena__list_dir        - Get structure
```

**BAD**: `Read file.ts` then parse it yourself
**GOOD**: `find_symbol "handleAuth"` → get location → `get_definition` if needed

### Documentation - USE CONTEXT7, NOT WEB SEARCH

**NEVER** use WebSearch for library docs. Use Context7:

```
mcp__context7__resolve-library-id  - Get library ID
mcp__context7__query-docs          - Get specific docs
```

**BAD**: `WebSearch "react useEffect cleanup"`
**GOOD**: `query-docs "/facebook/react" "useEffect cleanup"`

### Batch Operations

1. **BATCH SEARCHES** - Never run grep/glob more than once:
   ```bash
   python3 ~/.claude/plugins/agent-swarm/scripts/batch_search.py '{"patterns": ["a","b","c"]}'
   ```

2. **GH CLI WRAPPER** - Never raw gh output:
   ```bash
   python3 ~/.claude/plugins/agent-swarm/scripts/gh_wrapper.py pr list
   ```

3. **FILE ANALYSIS** - When you must read files, summarize:
   ```bash
   python3 ~/.claude/plugins/agent-swarm/scripts/file_analyzer.py '{"files": ["a.py"]}'
   ```

## Communication Rules

1. **STRUCTURED RETURNS** - Use the output format from your agent spec
2. **FAIL FAST** - If blocked, report immediately, don't try alternatives
3. **STAY IN LANE** - Only do what you're tasked. No "while I'm here..."

## Token Discipline

Every token costs money and context. Before outputting anything, ask:
- Is this necessary?
- Is this the shortest way to say it?
- Could this be a reference instead of content?

**BAD**: "I found the authentication logic in src/auth/login.ts. Let me show you the relevant code..."
**GOOD**: "Auth: src/auth/login.ts:45-67"

**BAD**: "The function handleSubmit takes a form event and processes..."
**GOOD**: "handleSubmit(FormEvent) → validates, calls API, updates state"
