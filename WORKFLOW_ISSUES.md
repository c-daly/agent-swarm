# Workflow Issues

Bugs and problems discovered during iterate workflow development.

## Critical

### WORKFLOW.5 - Block git/gh outside review phase
Block all git/gh commands unless in review phase - no git access outside review.

### WORKFLOW.7 - Parallel agents need separate branches
Parallel agents need separate branches/PRs - orchestrator should create branch-per-task for independent Greptile review.

## High Priority

### WORKFLOW.9 - State modification without validation
Functions like `set_test_results()`, `set_review_status()` don't validate `state["active"]` before modifying. If state file is deleted (e.g., by test fixtures), they create partial state causing corruption.

**Repro:** Run tests while CLI command is executing - test fixture deletes STATE_FILE, CLI saves partial state.

### WORKFLOW.12 - No explicit acknowledgment of review comments
Workflow allows pushing before verifying all review comments are addressed. Should track each comment and require `mark_review_task_done()` before allowing push.

### WORKFLOW.13 - Should reply to PR comments
Review phase should require replying to PR comments via `gh pr comment --reply-to` before marking as addressed.

### WORKFLOW.14 - Should resolve PR comments on GitHub
Review phase should require resolving PR comments on GitHub via API. Gate advancement until all resolved.

### WORKFLOW.1 - Block commit/push until coverage met
Iterate mode should block git commit/push until coverage threshold met.

### WORKFLOW.3 - Edit tool deadlock
Edit tool requires Read first, but Read can be blocked by limit counter.

### WORKFLOW.4 - Workflow reset incomplete
Workflow reset should clear all enforcement state (phase, read counter).

### WORKFLOW.6 - Premature review exit
Iterate workflow should stay in review phase until review complete, not allow premature reset.

## Medium Priority

### WORKFLOW.10 - No file locking
Concurrent writes to STATE_FILE cause race conditions. Should use fcntl or .lock file.

### WORKFLOW.11 - Test fixtures use shared state
Test fixtures delete production STATE_FILE which causes state corruption if CLI runs concurrently. Should use isolated temp directory.

### WORKFLOW.2 - Subagent briefing workaround
Subagent briefings should include /tmp script workaround when Read/Edit blocked.

## Resolved

### WORKFLOW.8 - Max parallel enforcement
Enforce max_parallel config on Task tool spawn - track active agents, block spawn if at limit.
**Status:** Done
