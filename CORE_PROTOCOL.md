# Agent Core Protocol

Universal rules for all agent-swarm agents. Read this first.

## Tool Selection (Priority Order)

1. **Serena symbolic tools** → code understanding (find_symbol, find_referencing_symbols)
2. **Context7** → library documentation (query-docs)
3. **Batch scripts** (3+ operations) → token efficiency
4. **MCP tools** → specific file operations
5. **Read/Grep** → single operations only

## Batch Operations

When you need multiple operations, use scripts:

- **3+ searches** → `batch_search.py`
- **3+ file reads** → `file_analyzer.py`
- **Multiple symbol lookups** → `serena_batch.py`
- **Library docs** → `context7_docs.py`

**Script location:** `~/.claude/plugins/agent-swarm/scripts/`
**Discovery:** `ls scripts/` to see available tools

## Parallel Execution

Independent tool calls MUST be in one message.

- ❌ **BAD:** Call Read → wait → Call Read again
- ✅ **GOOD:** Single message with multiple Read calls

## Output Standards

- **Format:** Bullets only, no prose
- **File refs:** `path:line` format
- **Max lengths:** 50 chars (descriptions), 100 chars (summaries)
- **Structure:** `## Section` / `- bullets`

## Token Efficiency

- Return references, not content
- Scripts return summaries, not raw data
- Use `file_path:line_number` for citations
- Avoid reading entire files into context

## Side-Effect Checking

Before modifying code: Use `find_referencing_symbols` to check all callers.
Ensure changes are backward-compatible or update all references.

## Failure Protocol

- **Fail fast** - don't guess, don't hallucinate
- **3 failed attempts** → escalate to user
- **Check permissions early** before attempting operations
- **Compare to working examples** when debugging
