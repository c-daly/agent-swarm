# Provider-Agnostic Refactoring Specification

## Goal

Refactor agent-swarm plugin to minimize Claude Code dependencies, enabling operation with alternative AI coding tools (e.g., "open code", Cursor, Aider) via configuration change only.

---

## Current Dependencies Analysis

### 1. Hardcoded Paths (31 files)
```
~/.claude/plugins/agent-swarm/
~/.claude/plugins/agent-swarm/.state/
Path.home() / ".claude/..."
```

**Files affected:** All hooks, lib modules, scripts

### 2. Tool Name References (10 files)
Native tools referenced by string name:
- `Task`, `Bash`, `Read`, `Edit`, `Write`, `Glob`, `Grep`, `WebFetch`, `WebSearch`

**Files:** `phase_model.py`, `combined_enforcement.py`, `monitor_agent.py`, etc.

### 3. Hook System (8+ files)
Claude Code-specific hook contracts:
- `hookSpecificOutput.message` - User-visible output
- `hookSpecificOutput.additionalContext` - Agent context injection
- `hookSpecificOutput.permissionDecision` - block/allow/ask
- Hook event types: `PreToolUse`, `PostToolUse`, `SubagentStart`, `SubagentStop`

**Files:** All `hooks/*.py` files

### 4. MCP Tool Names (12 files)
Provider-specific MCP tool patterns:
- `mcp__plugin_serena_serena__*` (20+ tools)
- `mcp__plugin_greptile_greptile__*` (5+ tools)
- `mcp__filesystem__*` (10+ tools)
- `mcp__context7__*` (2 tools)
- `mcp__memory__*` (6 tools)
- `mcp__plugin_episodic*`

### 5. Environment Variables (2 files)
- `CLAUDE_AGENT_ID` - Subagent identification
- `CLAUDE_DIR` - Base directory

---

## Abstraction Architecture

### Layer 1: Provider Adapter Interface

```python
# lib/provider_adapter.py

from abc import ABC, abstractmethod
from typing import Any, Optional
from dataclasses import dataclass

@dataclass
class HookResponse:
    """Provider-agnostic hook response."""
    decision: str  # "allow", "block", "ask"
    message: Optional[str] = None
    context_injection: Optional[str] = None
    metadata: Optional[dict] = None

@dataclass  
class ToolCall:
    """Normalized tool call representation."""
    category: str  # "file_read", "file_write", "shell", "search", "subagent"
    name: str      # Original provider-specific name
    params: dict
    
class ProviderAdapter(ABC):
    """Abstract interface for AI coding tool providers."""
    
    @abstractmethod
    def get_base_path(self) -> Path:
        """Return provider's plugin/extension base path."""
        pass
    
    @abstractmethod
    def get_state_path(self) -> Path:
        """Return path for state files."""
        pass
    
    @abstractmethod
    def normalize_tool_name(self, tool_name: str) -> str:
        """Map provider-specific tool name to canonical category."""
        pass
    
    @abstractmethod
    def format_hook_response(self, response: HookResponse) -> dict:
        """Format response for provider's hook system."""
        pass
    
    @abstractmethod
    def parse_hook_input(self, raw_input: dict) -> dict:
        """Parse provider's hook input format to normalized form."""
        pass
    
    @abstractmethod
    def get_agent_id(self) -> str:
        """Get current agent/session identifier."""
        pass
    
    @abstractmethod
    def spawn_subagent(self, task: str, agent_type: str) -> str:
        """Spawn a subagent, return task ID."""
        pass
```

### Layer 2: Tool Category Mapping

```python
# lib/tool_categories.py

from enum import Enum, auto

class ToolCategory(Enum):
    FILE_READ = auto()
    FILE_WRITE = auto()
    CODE_QUERY = auto()
    CODE_EDIT = auto()
    FILE_SEARCH = auto()
    SHELL_SAFE = auto()
    SHELL_DANGEROUS = auto()
    WEB_RESEARCH = auto()
    SUBAGENT = auto()
    MEMORY = auto()
    USER_INTERACTION = auto()

# Canonical tool names (provider-agnostic)
CANONICAL_TOOLS = {
    ToolCategory.FILE_READ: ["read_file", "cat", "view"],
    ToolCategory.FILE_WRITE: ["write_file", "edit_file", "create_file"],
    ToolCategory.FILE_SEARCH: ["glob", "grep", "find", "search"],
    ToolCategory.SHELL_SAFE: ["shell", "bash", "terminal"],
    ToolCategory.SUBAGENT: ["spawn_agent", "task", "delegate"],
    # ... etc
}
```

### Layer 3: Provider Implementations

```python
# lib/providers/claude_code.py

class ClaudeCodeAdapter(ProviderAdapter):
    """Adapter for Claude Code CLI."""
    
    TOOL_MAP = {
        # Native tools
        "Read": ToolCategory.FILE_READ,
        "Edit": ToolCategory.FILE_WRITE,
        "Write": ToolCategory.FILE_WRITE,
        "Bash": ToolCategory.SHELL_SAFE,  # categorized by shell_virtualizer
        "Task": ToolCategory.SUBAGENT,
        "Glob": ToolCategory.FILE_SEARCH,
        "Grep": ToolCategory.FILE_SEARCH,
        # MCP tools
        "mcp__plugin_serena_serena__read_file": ToolCategory.FILE_READ,
        "mcp__plugin_serena_serena__create_text_file": ToolCategory.FILE_WRITE,
        # ... full mapping
    }
    
    HOOK_EVENT_MAP = {
        "PreToolUse": "pre_tool",
        "PostToolUse": "post_tool", 
        "SubagentStart": "subagent_start",
        "SubagentStop": "subagent_stop",
    }
    
    def get_base_path(self) -> Path:
        return Path.home() / ".claude/plugins/agent-swarm"
    
    def get_state_path(self) -> Path:
        return self.get_base_path() / ".state"
    
    def get_agent_id(self) -> str:
        return os.environ.get("CLAUDE_AGENT_ID", "main")
    
    def format_hook_response(self, response: HookResponse) -> dict:
        result = {"hookSpecificOutput": {"hookEventName": self._current_event}}
        if response.decision == "block":
            result["hookSpecificOutput"]["permissionDecision"] = "block"
        if response.message:
            result["hookSpecificOutput"]["message"] = response.message
        if response.context_injection:
            result["hookSpecificOutput"]["additionalContext"] = response.context_injection
        return result
```

```python
# lib/providers/open_code.py (future)

class OpenCodeAdapter(ProviderAdapter):
    """Adapter for open-source code assistants."""
    
    def get_base_path(self) -> Path:
        # Open Code uses different path structure
        return Path.home() / ".config/opencode/plugins/agent-swarm"
    
    # ... implementation
```

---

## Configuration Structure

```yaml
# config.yaml

provider: claude_code  # or: open_code, cursor, aider

paths:
  base: ${HOME}/.claude/plugins/agent-swarm
  state: ${base}/.state
  logs: ${base}/.logs

# Override tool mappings if needed
tool_overrides:
  # custom_tool_name: category

# Feature flags
features:
  phase_enforcement: true
  greptile_review: true
  tdd_workflow: true
  
# Provider-specific settings
claude_code:
  hook_format: v1
  use_mcp_tools: true
  
open_code:
  hook_format: custom
  api_endpoint: http://localhost:8080
```

---

## Migration Plan

### Phase 1: Create Abstraction Layer
1. Create `lib/provider_adapter.py` with base interface
2. Create `lib/providers/` directory
3. Implement `ClaudeCodeAdapter` with current behavior
4. Add config loading from `config.yaml`

### Phase 2: Refactor Hooks
1. Create `lib/hook_handler.py` that uses adapter
2. Refactor each hook to use `hook_handler`:
   - `combined_enforcement.py`
   - `subagent-enforcement.py`
   - `subagent-complete.py`
   - `post_tool_use.py`
   - etc.

### Phase 3: Refactor Core Modules
1. Update `lib/agent_state.py` to use adapter paths
2. Update `lib/phase_model.py` to use canonical tool names
3. Update `lib/workflow.py` to use adapter for subagent spawning

### Phase 4: Extract Tool Mappings
1. Move all tool name strings to `lib/providers/claude_code.py`
2. Create `TOOL_CATEGORIES` mapping in adapter
3. Update `phase_model.py` to reference adapter mappings

### Phase 5: Create Alternative Provider
1. Implement `OpenCodeAdapter` (or other target provider)
2. Test with config switch
3. Document provider requirements

---

## File Changes Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `lib/provider_adapter.py` | NEW | Abstract adapter interface |
| `lib/providers/__init__.py` | NEW | Provider package |
| `lib/providers/claude_code.py` | NEW | Claude Code implementation |
| `lib/hook_handler.py` | NEW | Adapter-aware hook utilities |
| `config.yaml` | NEW | Configuration file |
| `lib/agent_state.py` | MODIFY | Use adapter for paths |
| `lib/phase_model.py` | MODIFY | Use adapter for tool mapping |
| `lib/workflow.py` | MODIFY | Use adapter for subagent spawn |
| `hooks/*.py` | MODIFY | Use hook_handler |

---

## Success Criteria

1. **Config-driven provider selection**: Change `provider: X` in config, plugin works
2. **No hardcoded Claude paths**: All paths from adapter
3. **No hardcoded tool names in core logic**: All from adapter mapping
4. **Hook format abstraction**: Different providers can have different hook formats
5. **Tests pass with mock provider**: Can test without Claude Code installed

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Hook system varies wildly between providers | Define minimum hook contract, providers implement |
| Some features require Claude-specific APIs | Feature flags in config, graceful degradation |
| Performance overhead from abstraction | Keep adapter methods simple, cache mappings |
| Breaking existing functionality | Maintain ClaudeCodeAdapter as reference implementation |

---

## Task Queue (for decomposition)

```
T1: Create lib/provider_adapter.py with abstract interface
T2: Create lib/providers/claude_code.py with current behavior
T3: Create lib/hook_handler.py using adapter
T4: Add config.yaml loading
T5: Refactor lib/agent_state.py to use adapter paths
T6: Refactor lib/phase_model.py to use adapter tool mapping
T7: Refactor hooks/combined_enforcement.py to use hook_handler
T8: Refactor hooks/subagent-enforcement.py to use hook_handler
T9: Refactor hooks/subagent-complete.py to use hook_handler
T10: Refactor remaining hooks
T11: Update lib/workflow.py to use adapter
T12: Create tests with mock provider
T13: Document provider implementation requirements
```

---

## Appendix: Current Tool Mappings

### Claude Code Native Tools
- `Task` → SUBAGENT
- `Bash` → SHELL (categorized by virtualizer)
- `Read` → FILE_READ
- `Edit` → FILE_WRITE
- `Write` → FILE_WRITE
- `Glob` → FILE_SEARCH
- `Grep` → FILE_SEARCH
- `WebFetch` → WEB_RESEARCH
- `WebSearch` → WEB_RESEARCH

### Serena MCP Tools
- `mcp__plugin_serena_serena__read_file` → FILE_READ
- `mcp__plugin_serena_serena__create_text_file` → FILE_WRITE
- `mcp__plugin_serena_serena__replace_content` → FILE_WRITE
- `mcp__plugin_serena_serena__find_symbol` → CODE_QUERY
- `mcp__plugin_serena_serena__get_symbols_overview` → CODE_QUERY
- `mcp__plugin_serena_serena__replace_symbol_body` → CODE_EDIT

### Greptile MCP Tools
- `mcp__plugin_greptile_greptile__*` → WEB_RESEARCH

### Filesystem MCP Tools
- `mcp__filesystem__read_*` → FILE_READ
- `mcp__filesystem__write_file` → FILE_WRITE
- `mcp__filesystem__search_files` → FILE_SEARCH
