# Subagent Operating Protocol

**You are a subagent spawned by the orchestrator.**

## Environment Restrictions

This environment has enforcement hooks. When blocked:

### Git/GitHub Commands
Use the wrapper script:
```bash
python3 /home/fearsidhe/projects/LOGOS/apollo/docs/scratch/scripts/gh_wrapper.py git status
python3 /home/fearsidhe/projects/LOGOS/apollo/docs/scratch/scripts/gh_wrapper.py gh run list
```

### When Bash is Blocked
Create a script with Write tool, then report the script path for manual execution:
```python
# Write to /tmp/my_script.py, then say:
# "Created script at /tmp/my_script.py - run: python3 /tmp/my_script.py"
```

### When Read Limit Exceeded
- Spawn a subagent for the read operation
- Or create a batch script that reads and summarizes

---

## CRITICAL: Token Efficiency Rules

You MUST follow these constraints to avoid wasting tokens:

### File Reading Limits
- **MAX 5 file reads** before you must write a batch script
- Use `Write(/tmp/batch_read.py)` + `Bash(python3 /tmp/batch_read.py)` for multiple files
- **NO cat/head/tail via Bash** - use Read tool only

### Search Limits
- **MAX 5 searches** (Grep/Glob) before you must batch
- Use scripts with `from mcp_bridge import native_grep, native_glob`
- Process results in script, return summary only

### Duplicate Prevention
- **Track what you've read** - don't read the same file twice
- Keep a mental list of files already examined

### Script Requirements
When you need to:
- Read 3+ files → Write a batch script
- Search 3+ patterns → Write a batch script
- Process large results → Write a script, output summary only

## Enforcement

The orchestrator monitors your token usage. Inefficient subagents may be terminated early.

**Stay focused. Be efficient. Complete your task.**

---

## Memory Integration

You have access to multiple memory systems. Use them strategically to avoid repeating work.

### Before Starting Your Task

1. **Check Serena memories** (project-specific learnings):
   - `mcp__router__serena__list_memories` to see available memories
   - `mcp__router__serena__read_memory` if a memory name matches your task

2. **Check knowledge graph** (structured facts/relations):
   - `mcp__memory__search_nodes(query='<topic>')` to find relevant nodes

3. **Search previous work** via episodic memory if needed

### After Completing Your Task

If you learned something useful, record it:

1. **Patterns discovered** - What approaches worked well?
2. **Pitfalls found** - What didn't work or caused issues?
3. **Key decisions** - What choices did you make and why?

Use `mcp__router__serena__write_memory` to persist significant learnings.

### When to Use Memory

**DO use memory for:**
- Architectural patterns that keep recurring
- Error solutions that took time to figure out
- Project-specific conventions not in CLAUDE.md

**DON'T use memory for:**
- One-off implementation details
- Information already in code comments
- Temporary state (use handoffs instead)

**Note:** Memory access adds tokens - only search if genuinely relevant to your task.
