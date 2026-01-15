# MCP Router Specification

## Overview

Create a passthrough MCP router - an MCP server that forwards requests to target servers without modification.

## Goals

1. Accept MCP requests via stdio
2. Forward to appropriate target server
3. Return responses unchanged
4. Thread-safe with request queue
5. Expose MCP API for server registration

## Components

1. **Router Server** (`lib/mcp_router.py`)
   - MCP server accepting stdio transport
   - Exposes registration API as MCP tools
   - Request queue for thread-safe handling
   - Forwards requests, returns responses

2. **Request Queue** (`lib/router_queue.py`)
   - Thread-safe queue for incoming requests
   - Handles backpressure
   - Correlates responses to requests

3. **Config** (`config/mcp_router.json`)
   - Persists registered servers

## MCP API

- `router_register` - Register an MCP server for routing
  - Args: server_name, command, args, tool_prefix
- `router_list` - List registered servers
- `router_unregister` - Remove a server

## Implementation Tasks

- [ ] Create thread-safe request queue
- [ ] Create MCP server with stdio transport
- [ ] Implement register/list/unregister tools
- [ ] Load/persist server configurations
- [ ] Implement request forwarding via queue
- [ ] Return responses to caller

## Success Criteria

1. Servers can register via MCP API
2. Existing MCP tools work through router without behavior change
3. Handles concurrent requests safely via queue
