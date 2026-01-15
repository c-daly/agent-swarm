# Automatic Review Polling Specification

## Overview
Enable automatic polling for GitHub PR review comments after code is pushed, integrating with the existing orchestrate and iterate workflow infrastructure.

## Current State
- `check_review_poll()` exists but only checks timing, doesn't fetch comments
- Polling interval configured in `config/workflow.json` (5 minutes default)
- Manual intervention required to check for and process review comments

## Design

### 1. Polling Trigger
**When:** After push in REVIEW phase
**How:** Set `push_pending=True` and initialize `last_poll` timestamp

### 2. Automatic Comment Fetching
**Function:** `check_review_poll()` in `lib/orchestrate.py`
**Behavior:**
- Check if enough time elapsed since `last_poll`
- If yes, fetch comments via `fetch_pr_review_status(pr_number)`
- Process comments via `process_review_comments(comments)`
- Update `last_poll` timestamp

### 3. State Management
**Orchestrate State:**
```python
{
    "last_poll": "2024-01-15T10:30:00Z",  # ISO timestamp
    "push_pending": True,                  # After push, before review complete
    "review_pending": True,                # Poll triggered, awaiting comments
}
```

### 4. Integration with REVIEW Phase
**In `iterate_workflow.py`:**
- When entering REVIEW phase, trigger immediate poll
- Call `refresh_review_status()` to fetch initial comments
- Set PR number if not already set

### 5. Comment Processing Flow
```
Push code → set push_pending=True
         ↓
Check poll interval → time elapsed?
         ↓
Fetch comments (gh pr view) → parse JSON
         ↓
Process comments → add as tasks
         ↓
If tasks added → resume work (push_pending=False)
If no comments → mark review clean
```

## Implementation Tasks

### Task 1: Wire comment fetching into check_review_poll()
**File:** `lib/orchestrate.py`
**Changes:**
- Get PR number from state
- Call `fetch_pr_review_status()` from iterate_workflow
- Call `process_review_comments()` with fetched comments
- Return comment count in addition to poll trigger status

### Task 2: Auto-fetch on REVIEW phase entry
**File:** `lib/iterate_workflow.py`
**Changes:**
- In `advance_phase()` when entering REVIEW phase
- Automatically call `refresh_review_status()` if PR number set
- Log the auto-fetch action

### Task 3: Update check_review_poll signature
**File:** `lib/orchestrate.py`
**Changes:**
- Change return type from `bool` to `dict` with:
  - `polled`: bool - whether poll was triggered
  - `comments_found`: int - number of new comments
  - `tasks_added`: int - number of tasks created

### Task 4: Integration tests
**File:** `tests/test_automatic_review_polling.py` (new)
**Test cases:**
- Poll timing check (respects interval)
- Comment fetching integration
- Task creation from comments
- State updates after polling
- REVIEW phase auto-fetch

## Edge Cases

1. **No PR number set:** Skip polling, log warning
2. **gh CLI error:** Return empty comments, log error
3. **Duplicate comments:** WorkflowQueue handles deduplication
4. **Poll during active work:** Only poll when `push_pending=True`

## Success Criteria

- [ ] `check_review_poll()` fetches and processes comments automatically
- [ ] REVIEW phase triggers immediate comment fetch
- [ ] Polling respects configured interval
- [ ] Comments converted to tasks correctly
- [ ] State properly updated after polling
- [ ] Tests cover polling logic and integration
