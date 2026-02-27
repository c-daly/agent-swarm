# ./lib

Shared utilities and scripts for Claude Code operations.

## Files

### `mcp_bridge.py`
Programmatic access to MCP tools from Python scripts.

**Native helpers (fast, no MCP required):**
- `native_glob(pattern, path)` - Glob pattern matching
- `native_grep(pattern, path, ...)` - Ripgrep-based search

**MCP protocol support (for batching MCP tool calls):**
- `call_mcp(tool_name, arguments)` - Call MCP tools programmatically
- `close_all_servers()` - Cleanup function
- `MCPBridge` class - Convenience wrapper

**Example:**
```python
import sys
sys.path.insert(0, './lib')
from mcp_bridge import native_glob, native_grep

# Fast local operations
files = native_glob("**/*.py", "/project")
results = native_grep("TODO", "/project", output_mode="content")
```

## scripts/

Common batch operation scripts.

### `batch_search.py`
Search multiple patterns efficiently.
```bash
python3 ./lib/scripts/batch_search.py "TODO" "FIXME" "XXX" --path src/
```

### `batch_glob.py`
Find files matching multiple patterns.
```bash
python3 ./lib/scripts/batch_glob.py "*.py" "*.md" --path /project
```

## Usage in CLAUDE.md Scripts

When CLAUDE.md instructs you to write scripts, use these utilities:

```python
#!/usr/bin/env python3
import sys
sys.path.insert(0, './lib')
from mcp_bridge import native_glob, native_grep

# Your batch operation here
files = native_glob("**/*.py", ".")
for f in files:
    results = native_grep("class ", f, output_mode="count")
    print(f"{f}: {results['total']} classes")
```

## Installation

This directory should be in your dotclaude git repo:
```bash
cd ~/.claude
git add lib/
git commit -m "Add lib infrastructure"
git push
```
