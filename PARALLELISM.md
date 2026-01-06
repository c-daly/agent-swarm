# Parallelism Guide for Agent Swarm

Maximize throughput by running operations concurrently instead of sequentially.

## 1. Multiple Tool Calls (Most Important!)

**Always make independent tool calls in parallel when possible.**

### ❌ Bad (Sequential)
```
Assistant: Let me search for authentication files
[Tool: Glob] pattern="**/*auth*"
[Waits...]
Assistant: Now let me search for session files
[Tool: Glob] pattern="**/*session*"
[Waits...]
Assistant: Now let me read the config
[Tool: Read] file_path="config.json"
```
**Time: 3 sequential operations = 3x latency**

### ✅ Good (Parallel)
```
Assistant: Let me search for auth and session files, and read config
[Tool: Glob] pattern="**/*auth*"
[Tool: Glob] pattern="**/*session*"
[Tool: Read] file_path="config.json"
[All execute in parallel...]
```
**Time: 1 parallel batch = 1x latency**

## 2. Spawn Multiple Subagents

**Launch independent subagents concurrently, then collect results.**

### ❌ Bad (Sequential)
```
[Tool: Task] subagent_type="explorer" prompt="Find API routes"
[Waits for completion...]
[Tool: Task] subagent_type="researcher" prompt="Research auth patterns"
[Waits for completion...]
```
**Time: Agent1 + Agent2 runtime**

### ✅ Good (Parallel)
```
[Tool: Task] subagent_type="explorer" prompt="Find API routes" run_in_background=true
[Tool: Task] subagent_type="researcher" prompt="Research auth patterns" run_in_background=true
[Both agents run concurrently]
[Tool: TaskOutput] task_id=agent1
[Tool: TaskOutput] task_id=agent2
```
**Time: max(Agent1, Agent2) runtime**

## 3. Background Tasks + Continue Working

**Start long-running tasks in background, continue with other work.**

### Example: Long-Running Build
```
# Start build in background
[Tool: Bash] command="npm run build" run_in_background=true

# Continue with other work while build runs
[Tool: Read] file_path="tests/integration.test.ts"
[Tool: Edit] ...make changes...

# Check build result when needed
[Tool: TaskOutput] task_id="bash_xyz" block=true
```

## 4. Parallel Batch Scripts

**Use Python threading for I/O-bound operations.**

### Example: Parallel File Analysis
```python
import sys
sys.path.insert(0, '/home/fearsidhe/.claude/lib')
from mcp_bridge import native_read
from concurrent.futures import ThreadPoolExecutor

files = ['a.py', 'b.py', 'c.py', 'd.py', 'e.py']

def analyze_file(f):
    content = native_read(f)
    return {
        'file': f,
        'lines': content.count('\n'),
        'imports': content.count('import ')
    }

# Run in parallel (5 files analyzed concurrently)
with ThreadPoolExecutor(max_workers=5) as executor:
    results = list(executor.map(analyze_file, files))

for r in results:
    print(f"{r['file']}: {r['lines']} lines, {r['imports']} imports")
```

## 5. Agent Instruction Updates

### Explorer Agent
**Before:**
- Search pattern A
- Search pattern B
- Search pattern C

**After:**
- **Search patterns A, B, C in parallel** (single message, 3 Grep calls)
- Return aggregated summary

### Implementer Agent
**Before:**
- Create file1.py
- Create file2.py
- Create file3.py

**After:**
- **Create files 1-3 in parallel** (single message, 3 Write calls)
- Verify all succeeded

## 6. Workflow Configuration

Add parallel execution hints to `config/workflow.json`:

```json
{
  "execution": {
    "prefer_parallel": true,
    "max_concurrent_subagents": 3,
    "batch_tool_calls": true
  }
}
```

## Decision Matrix

| Scenario | Sequential | Parallel |
|----------|-----------|----------|
| 2+ independent tool calls | ❌ | ✅ |
| 2+ independent subagents | ❌ | ✅ |
| Tool B depends on Tool A result | ✅ | ❌ |
| Subagent B needs Subagent A output | ✅ | ❌ |
| Long task + continue working | ❌ | ✅ (background) |
| 5+ similar operations | ❌ | ✅ (batch script) |

## Measuring Impact

### Before Parallelism
```
Search 3 patterns: 450ms each = 1350ms total
Spawn 2 agents: 30s each = 60s total
Read 5 files: 200ms each = 1000ms total
Total: ~61 seconds
```

### After Parallelism
```
Search 3 patterns: 450ms parallel = 450ms total
Spawn 2 agents: 30s parallel = 30s total
Read 5 files: script with threading = ~300ms total
Total: ~31 seconds (2x faster!)
```

## Implementation Checklist

- [ ] Update explorer.md with parallel search patterns
- [ ] Update implementer.md with parallel write patterns
- [ ] Add parallel batch script examples to mcp_bridge
- [ ] Document run_in_background usage
- [ ] Add execution config to workflow.json
- [ ] Create diagnostic to detect missed parallel opportunities
