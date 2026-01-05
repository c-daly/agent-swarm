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

---

## CRITICAL: Debugging Anti-Patterns

These mistakes WASTE HOURS. Do not repeat them.

### 1. NEVER GUESS - USE AUTHORITATIVE SOURCES
```
# WRONG: Use a guide agent, read random files, try things
# RIGHT:
mcp__context7__resolve-library-id → query-docs
WebFetch to official GitHub raw docs
```
If you don't know the answer, LOOK IT UP before changing anything.

### 2. NEVER EDIT WITHOUT KNOWING WHERE CODE LOADS FROM
```bash
# Check ACTUAL load path
cat ~/.claude/plugins/installed_plugins.json | grep installPath
```
Editing the wrong directory does nothing. Plugins load from CACHE, not source.

### 3. NEVER SAY "RESTART" WHILE STILL WORKING
Finish ALL changes → Verify everything → THEN one restart instruction.
User restarts with incomplete fixes = wasted cycle.

### 4. NEVER FLIP-FLOP ON FIXES
Research ONCE → Apply ONCE → If fails, problem is elsewhere.
Changing A→B→A→B means you don't understand the system.

### 5. CHECK PERMISSIONS EARLY
```bash
ls -la <file>          # Check permissions
diff <working> <broken> # Compare to working example
```
Files existing ≠ files readable. 600 vs 644 matters.

### 6. USE --debug IMMEDIATELY
```bash
claude --debug "plugin"
```
Read actual errors. Don't guess.

### 7. COMPARE TO WORKING EXAMPLES
```bash
ls -la ~/.claude/plugins/cache/claude-plugins-official/<working>/
```
Find differences. Don't debug in isolation.

### 8. STOP AFTER 3 FAILED ATTEMPTS
Same category of fix failing 3x = wrong diagnosis.
Step back. Use --debug. Ask user what was already tried.
