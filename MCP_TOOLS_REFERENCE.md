# MCP Tools Reference - Complete Guide

**Quick Start:** Before starting any task, scan this guide to identify the best tools for your needs.

## Tool Selection Decision Tree

```
Need to understand code?
  └─> Use Serena (mcp__plugin_serena_serena__*)

Need library/framework documentation?
  └─> Use Context7 (mcp__context7__*)

Need to search across repositories?
  └─> Use Greptile (mcp__greptile__*)

Need to read/write files?
  └─> Use Filesystem (mcp__filesystem__*)

Need to remember information across sessions?
  └─> Use Memory (mcp__memory__*)

Need to interact with web browser?
  └─> Use Playwright (mcp__plugin_playwright_playwright__*)
```

---

## 1. Serena - Semantic Code Analysis

**When to use:** Understanding code structure, finding definitions, tracing references

**Available tools:**

### `mcp__plugin_serena_serena__find_symbol`
Find where symbols (classes, functions, variables) are defined.

```python
{
  "name_path_pattern": "handleAuth",  # Symbol name or pattern
  "relative_path": "src/",            # Optional: restrict to directory
  "include_body": false,              # Get full implementation?
  "substring_matching": false,        # Fuzzy match on name?
  "depth": 0                          # Include children (e.g., methods)
}
```

**Use when:**
- Finding where a class/function is defined
- Locating symbols matching a pattern
- Getting symbol locations without reading files

**DON'T use Read + search yourself - use this instead!**

### `mcp__plugin_serena_serena__search_for_pattern`
Search for code patterns, regex, text across codebase.

```python
{
  "substring_pattern": "TODO|FIXME",  # Regex pattern
  "relative_path": "src/",            # Optional: restrict search
  "output_mode": "files_with_matches",# or "content" or "count"
  "multiline": false,                 # Pattern spans lines?
  "context_lines_before": 2,
  "context_lines_after": 2
}
```

**Use when:**
- Finding TODOs, FIXMEs, specific patterns
- Searching for usage patterns
- Finding all occurrences of something

**Better than grep for code - understands structure**

### `mcp__plugin_serena_serena__get_symbols_overview`
Get high-level structure of a file (classes, functions, etc.)

```python
{
  "relative_path": "src/auth.ts",
  "depth": 1  # 0 = top-level only, 1 = includes methods/fields
}
```

**Use when:**
- First look at a new file
- Understanding file organization
- Deciding which symbols to investigate further

**ALWAYS use this before reading entire files!**

### `mcp__plugin_serena_serena__find_referencing_symbols`
Find everywhere a symbol is used.

```python
{
  "name_path": "handleAuth",
  "relative_path": "src/auth.ts"  # File containing the symbol
}
```

**Use when:**
- Impact analysis before refactoring
- Understanding usage patterns
- Finding callers of a function

### Other Serena tools:
- `get_definition` - Get signature + docstring
- `list_dir` - Directory structure
- `replace_symbol_body` - Edit a symbol
- `rename_symbol` - Rename across codebase
- `insert_before_symbol` / `insert_after_symbol` - Add code

**Batching with mcp_bridge:**
```python
import sys
sys.path.insert(0, '/home/fearsidhe/.claude/plugins/agent-swarm/lib')
from mcp_bridge import call_mcp, close_all_servers

# Batch multiple symbol lookups
symbols = ['handleAuth', 'validateUser', 'checkToken']
for symbol in symbols:
    result = call_mcp('mcp__plugin_serena_serena__find_symbol', {
        'name_path_pattern': symbol,
        'relative_path': 'src/auth/'
    })
    # Process result...

close_all_servers()
```

---

## 2. Context7 - Library Documentation

**When to use:** Need up-to-date docs for libraries/frameworks (React, Next.js, etc.)

### `mcp__context7__resolve-library-id`
Find the correct library ID for documentation queries.

```python
{
  "libraryName": "react",  # Library to find
  "query": "hooks documentation"  # What you're looking for
}
```

**Returns:** Library ID like `/facebook/react` or `/facebook/react/v18.2.0`

**ALWAYS call this first** before using query-docs!

### `mcp__context7__query-docs`
Search library documentation.

```python
{
  "libraryId": "/facebook/react",  # From resolve-library-id
  "query": "How to use useEffect cleanup?"
}
```

**Use when:**
- Learning how to use a library feature
- Finding code examples
- Checking API signatures

**Better than WebSearch for library docs - always current!**

### When to use Context7 vs WebSearch:
- **Context7**: Library-specific questions (React, Next.js, Vercel, etc.)
- **WebSearch**: General questions, comparisons, "why" questions

---

## 3. Greptile - Multi-Repository Code Search

**When to use:** Searching across multiple repositories, finding code patterns at scale

### `mcp__greptile__search_greptile_comments`
Search Greptile review comments.

```python
{
  "query": "authentication issues",
  "includeAddressed": false,
  "limit": 10
}
```

### Pull Request Tools:
- `list_pull_requests` - List PRs with filters
- `get_merge_request` - Get PR details
- `list_merge_request_comments` - Get all comments
- `trigger_code_review` - Request Greptile review

**Use when:**
- Working with PRs
- Understanding past review feedback
- Cross-repo code search

---

## 4. Filesystem - File Operations

**When to use:** Reading/writing files, searching filesystem

### `mcp__filesystem__read_text_file`
Read file contents.

```python
{
  "path": "/path/to/file.py",
  "head": 50,  # Optional: first N lines only
  "tail": 50   # Optional: last N lines only
}
```

**Use when:**
- Reading config files, documentation
- Need actual file content (after Serena overview)

**DON'T use for code analysis - use Serena instead!**

### `mcp__filesystem__search_files`
Find files matching glob pattern.

```python
{
  "path": "/project",
  "pattern": "**/*.test.ts",
  "excludePatterns": ["node_modules/**"]
}
```

### Other Filesystem tools:
- `list_directory` - List directory contents
- `write_file` - Create/overwrite file
- `edit_file` - Line-based edits
- `create_directory` - Make directories
- `move_file` - Rename/move files
- `get_file_info` - File metadata

**Batching:**
```python
from mcp_bridge import call_mcp, close_all_servers

files = ['config.json', 'package.json', 'tsconfig.json']
results = {}
for f in files:
    content = call_mcp('mcp__filesystem__read_text_file', {'path': f})
    results[f] = len(content.split('\n'))

print(f"Line counts: {results}")
close_all_servers()
```

---

## 5. Memory - Persistent Knowledge Graph

**When to use:** Storing/retrieving information across conversations

### `mcp__memory__create_entities`
Store information as entities.

```python
{
  "entities": [{
    "name": "UserAuthSystem",
    "entityType": "architecture",
    "observations": [
      "Uses JWT tokens",
      "Refresh tokens stored in Redis",
      "Session timeout: 24 hours"
    ]
  }]
}
```

### `mcp__memory__search_nodes`
Find stored information.

```python
{
  "query": "authentication"
}
```

### Other Memory tools:
- `add_observations` - Add to existing entity
- `create_relations` - Link entities
- `delete_entities` - Remove entities
- `read_graph` - Get entire knowledge graph

**Use when:**
- Remembering architecture decisions
- Tracking project patterns
- Building up understanding over time

---

## 6. Playwright - Browser Automation

**When to use:** Testing web UIs, interacting with web pages

### Core tools:
- `browser_navigate` - Go to URL
- `browser_snapshot` - Get page structure
- `browser_click` - Click elements
- `browser_type` - Enter text
- `browser_evaluate` - Run JavaScript

**Use when:**
- Testing web applications
- Scraping web content
- Verifying UI behavior

---

## Tool Selection Guidelines

### For Code Understanding:

**❌ NEVER:**
```
Read("src/auth.ts") → parse manually
```

**✅ ALWAYS:**
```
1. get_symbols_overview("src/auth.ts") → understand structure
2. find_symbol("handleAuth") → locate specific function
3. get_definition("handleAuth") → get signature
4. Read only if you need full implementation
```

### For Library Questions:

**❌ NEVER:**
```
WebSearch("how to use React useEffect")
```

**✅ ALWAYS:**
```
1. resolve-library-id("react", "hooks")
2. query-docs("/facebook/react", "how to use useEffect")
```

### For Finding Code Patterns:

**❌ NEVER:**
```
Read all files → search manually
```

**✅ ALWAYS:**
```
search_for_pattern("TODO|FIXME", "src/")
```

### For Batch Operations:

**❌ NEVER:**
```
Call tool 1
Call tool 2
Call tool 3
```

**✅ ALWAYS:**
```python
python3 << 'EOF'
import sys
sys.path.insert(0, '/home/fearsidhe/.claude/plugins/agent-swarm/lib')
from mcp_bridge import call_mcp, close_all_servers

# Batch all calls
for item in items:
    result = call_mcp('mcp__...', {...})
    # Process...

# Return summary only
print(f"Processed {len(items)} items")
close_all_servers()
EOF
```

---

## Best Practices

### 1. Start with Structure, Not Content

```
✅ Good flow:
  1. get_symbols_overview() → see what's in file
  2. find_symbol() → locate specific things
  3. get_definition() → get signatures
  4. Read only if needed

❌ Bad flow:
  1. Read entire file
  2. Parse manually
```

### 2. Batch Similar Operations

```
✅ Good: One Python script, 10 tool calls, return summary
❌ Bad: 10 separate tool calls in conversation
```

### 3. Use Semantic Tools Over Text Tools

```
✅ Serena find_symbol → understands code structure
❌ grep + Read → treats code as text
```

### 4. Consult Docs Before Implementing

```
✅ Context7 query-docs → up-to-date examples
❌ WebSearch → might be outdated
```

### 5. Remember Across Sessions

```
✅ Memory create_entities → persists knowledge
❌ Forget everything each conversation
```

---

## Quick Reference Table

| Task | Tool | Why |
|------|------|-----|
| Find function definition | `find_symbol` | Fast, structured |
| Understand file | `get_symbols_overview` | Overview without reading |
| Find pattern | `search_for_pattern` | Code-aware search |
| Library docs | `query-docs` | Always current |
| Read file | `read_text_file` | After confirming need |
| Batch operations | `mcp_bridge` | Reduces tokens 90% |
| Remember info | `create_entities` | Cross-session memory |
| Find references | `find_referencing_symbols` | Impact analysis |

---

## Common Mistakes to Avoid

### ❌ Reading files to understand code
**Problem:** Dumps entire file into context
**Solution:** Use `get_symbols_overview` → `find_symbol` → `get_definition`

### ❌ WebSearch for library questions
**Problem:** Outdated or wrong version
**Solution:** Use Context7 `query-docs`

### ❌ Multiple separate MCP calls
**Problem:** Token overhead from conversation turns
**Solution:** Batch via `mcp_bridge` in Python script

### ❌ Using grep for code search
**Problem:** Treats code as text
**Solution:** Use Serena `search_for_pattern`

### ❌ Forgetting information between sessions
**Problem:** Re-discovering same things
**Solution:** Use Memory tools to persist knowledge

---

## Integration with mcp_bridge

All MCP tools can be called via mcp_bridge for batching:

```python
import sys
sys.path.insert(0, '/home/fearsidhe/.claude/plugins/agent-swarm/lib')
from mcp_bridge import call_mcp, close_all_servers

# Example: Batch symbol lookups
symbols = ['UserAuth', 'TokenManager', 'SessionStore']
locations = {}

for symbol in symbols:
    result = call_mcp('mcp__plugin_serena_serena__find_symbol', {
        'name_path_pattern': symbol,
        'relative_path': 'src/auth/',
        'include_body': False
    })
    locations[symbol] = result

# Return summary
print(f"Found {len(locations)} authentication components")
for name, loc in locations.items():
    print(f"  {name}: {loc}")

close_all_servers()
```

**When to batch:**
- 3+ calls to same MCP server
- Want to return summary instead of raw results
- Reduce conversation token overhead

---

## See Also

- `/home/fearsidhe/.claude/plugins/agent-swarm/lib/README.md` - mcp_bridge usage
- `/home/fearsidhe/.claude/plugins/agent-swarm/lib/mcp_bridge.py` - Implementation
- `/home/fearsidhe/.claude/plugins/agent-swarm/agents/AGENT_RULES.md` - Agent guidelines
