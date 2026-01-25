# Test Audit Agent Design

## Problem

The current test suite (1,470 tests, ~20,500 lines) provides false confidence:
- Tests pass even when code is broken
- Heavy mocking tests glue, not logic
- Tests drift as code evolves - written for code that no longer exists
- TDD creates accumulation without curation

## Solution

An interactive audit agent that:
1. Calculates optimal test distribution from production code analysis
2. Compares existing tests against that optimal
3. Works autonomously on clear decisions, asks for guidance on ambiguous ones
4. Provides a compass toward minimal effective coverage

## Core Concept

**Don't start from existing tests. Start from the code.**

The agent analyzes production code to determine what tests *should* exist, then reconciles with what actually exists. The optimal distribution is a north star you approach over time, not a mandate.

## Interaction Model

### Dry-run (default)

```
$ audit-tests

Optimal test distribution (23 tests needed):
  lib/orchestrate.py - 4 tests (state transitions, error recovery)
  lib/iterate_workflow.py - 3 tests (phase gates, rollback)
  hooks/workflow-enforcement.py - 2 tests (block conditions)
  ...

Current state (1470 tests):
  Match optimal: 12 (keep)
  Redundant: 1441 (delete)
  Missing: 11 (write)

Efficiency: 1.6% (23 optimal / 1470 actual)

Run with --execute to begin interactive audit
```

### Interactive execution

The agent works until it hits friction, then checks in:

```
Audit progress:

Completed (high confidence):
  ✓ Identified 847 redundant tests (clear duplicates)
  ✓ Identified 203 dead code tests (targets don't exist)
  ✓ Optimal coverage for lib/orchestrate.py: 4 tests (have 3, need 1)

Stuck on:
  - lib/iterate_workflow.py has 89 tests, optimal is ~5
    But 12 of them test error paths I can't trace statically
    Should I: (a) keep all 12 conservatively, (b) keep none and flag as gap,
    (c) let me describe each and you pick?

  - test_mcp_native.py has heavy integration tests
    They mock external services but test real logic
    Is this pattern valuable or should pure unit tests replace them?

Waiting for guidance before continuing...
```

## Detection Signals

### Health signals (for identifying bad tests)

| Signal | Detection Method | Confidence |
|--------|------------------|------------|
| Assertion weakness | AST analysis - count/type of assertions | High |
| Dead code coverage | Cross-ref test targets with reachable code | High |
| Duplication | Semantic similarity between test bodies | High |
| Code drift | Git history - target changed since test written | Medium |
| Mock sprawl | Count mock/patch decorators (threshold: 3) | Medium |

### Critical path heuristics (for optimal distribution)

Production code is weighted by criticality:

- **Entry points** - Functions called from `__main__`, CLI handlers, hook entry points
- **State transitions** - Anything modifying workflow state
- **Error paths** - Except blocks, error handlers, recovery logic
- **High fan-in** - Functions called from many places

### Configuration override

User can specify additional critical paths in config:

```yaml
# audit-config.yaml
critical_paths:
  - lib/orchestrate.py::WorkflowState.transition_to
  - lib/iterate_workflow.py::*  # entire module is critical
  - hooks/*  # all hooks are critical

ignore_tests:
  - test_integration_*  # keep these regardless
```

## Output

### After completion

```
Audit complete:

Deleted: 1,203 tests
Kept: 267 tests
Gaps identified: 8 (recommendations in gaps.md)

New efficiency: 8.6% (23 optimal / 267 actual)

Coverage impact:
  lib/orchestrate.py: 89% → 91% (kept critical paths)
  lib/mcp_native.py: 94% → 67% (gap: error handling)
  lib/iterate_workflow.py: 78% → 82% (cleaner coverage)

Committed: "chore: test audit - remove 1,203 redundant tests"
```

### Gap recommendations file

```markdown
# Test Gaps - 2026-01-25

## High Priority

### lib/mcp_native.py - error handling
No coverage for connection failure recovery.
Suggested test:
- Test retry logic when MCP server unavailable
- Test graceful degradation on timeout

### lib/orchestrate.py - state rollback
No coverage for failed transition rollback.
Suggested test:
- Test state restoration after transition failure

## Medium Priority
...
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Test Audit Agent                    │
├─────────────────────────────────────────────────────┤
│                                                      │
│  ┌─────────────┐    ┌─────────────┐                │
│  │  Code       │    │  Optimal    │                │
│  │  Analyzer   │───▶│  Calculator │                │
│  └─────────────┘    └─────────────┘                │
│        │                   │                        │
│        ▼                   ▼                        │
│  ┌─────────────┐    ┌─────────────┐                │
│  │  Test       │    │  Comparator │                │
│  │  Parser     │───▶│             │                │
│  └─────────────┘    └─────────────┘                │
│                           │                         │
│                           ▼                         │
│                    ┌─────────────┐                  │
│                    │  Decision   │                  │
│                    │  Engine     │                  │
│                    └─────────────┘                  │
│                      │       │                      │
│              ┌───────┘       └───────┐              │
│              ▼                       ▼              │
│       High Confidence          Needs Guidance       │
│       (auto-execute)           (ask user)          │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### Components

**Code Analyzer**
- Parses production code AST
- Builds call graph from entry points
- Identifies critical paths (heuristics + config)
- Detects unreachable code

**Optimal Calculator**
- Given critical paths, calculates minimal test set
- Weights by criticality
- Produces "ideal" test distribution

**Test Parser**
- Parses existing test files
- Extracts: targets, assertions, mocks, coverage
- Computes health signals

**Comparator**
- Maps existing tests to optimal distribution
- Identifies: matches, redundancies, gaps

**Decision Engine**
- High-confidence decisions: execute automatically
- Ambiguous decisions: collect and ask user
- Tracks progress, reports incrementally

## Usage

```bash
# Dry run - see what would happen
audit-tests

# Interactive execution
audit-tests --execute

# With custom config
audit-tests --config audit-config.yaml --execute

# Aggressive mode (less asking, more deleting)
audit-tests --execute --aggressive
```

## Success Criteria

1. Test suite reduced by >50% while maintaining critical coverage
2. No regressions in functionality after audit
3. Clear documentation of what's covered and what's not
4. Agent asks for guidance on genuinely ambiguous decisions
5. Audit runs in <5 minutes for this codebase size

## Future Enhancements

- **Failure tracking** - Over time, track which tests catch real bugs vs never fail
- **CI integration** - Run audit on PR, warn if adding redundant tests
- **Auto-generate** - For identified gaps, generate test skeletons
