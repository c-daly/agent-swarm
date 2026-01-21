# Observer System Design

## Overview

A monitoring and intervention system that extends existing agent-swarm infrastructure to detect agent drift, prevent common mistakes, and improve test quality through adversarial testing.

**Design principles:**
- Build on existing infrastructure (telemetry, sequence detection, kill mechanisms, router)
- Use deterministic code where possible; LLM only where reasoning is required
- Graduated intervention: observe → nudge → modify → kill
- Adversarial testing must be fair (test the spec, not invented requirements)

---

## Component 1: Health Scoring

**Purpose:** Detect agent drift before catastrophic failure.

**Input:** Telemetry stream (already being collected)

### Signals to Extract

| Signal | Source | Indicates |
|--------|--------|-----------|
| `apology_count` | Agent text | Agent knows it's failing |
| `hedge_ratio` | Agent text | Confidence degrading ("I think", "probably") |
| `vague_reference_count` | Agent text | "the file" instead of specific paths |
| `tool_repetition_score` | Tool calls | Same tool, similar params = stuck |
| `file_reread_count` | Tool calls | Forgot what it already read |
| `failed_tool_rate` | Tool results | File not found, errors |
| `circular_behavior` | Existing sequence detection | Problematic loops |
| `time_since_progress` | Timestamps | Stuck duration |
| `output_length_trend` | Agent text | Shrinking = giving up |

### Hard Failure Rules (Immediate Action)

```python
HARD_FAILURES = [
    apology_count > 4,
    circular_behavior == True,
    failed_tool_rate > 0.5,
    file_not_found_count > 3,
]
```

### Soft Drift Scoring

```python
drift_score = (
    apology_count * 3 +
    hedge_ratio * 10 +
    vague_reference_count * 2 +
    tool_repetition_score * 5 +
    file_reread_count * 3 +
    (time_since_progress / 60) * 2
)

NUDGE_THRESHOLD = 10
WARN_THRESHOLD = 20
KILL_THRESHOLD = 35
```

### Implementation Notes

- Track signals over rolling window (last N turns), not entire session
- Extends existing problematic sequence detection
- Text signals: regex/string matching (count apology words, hedge phrases)
- Tool signals: aggregate from telemetry events
- Threshold values are starting points - tune based on observation

---

## Component 2: Tool Interception

**Purpose:** Prevent obvious mistakes at the router level without LLM involvement.

**Location:** Middleware in MCP router

### Interception Rules

| Condition | Action |
|-----------|--------|
| Re-reading same file (3+ times) | Return cached content + reminder note |
| Edit without prior read | Block, force read first |
| Overly broad glob pattern | Narrow to likely relevant directory |
| Dangerous bash command | Block with explanation |
| Duplicate tool call (same params) | Return previous result + "you just did this" |

### Implementation

```python
class ToolInterceptor:
    def __init__(self):
        self.file_read_cache = {}
        self.recent_tool_calls = []
    
    def intercept(self, tool_name, params):
        # Re-read prevention
        if tool_name == "read_file":
            path = params["file_path"]
            if path in self.file_read_cache:
                read_count = self.file_read_cache[path]["count"]
                if read_count >= 2:
                    return augment_result(
                        self.file_read_cache[path]["content"],
                        f"Note: You have read this file {read_count + 1} times."
                    )
        
        # Repetition detection
        call_sig = (tool_name, stable_hash(params))
        if call_sig in self.recent_tool_calls[-5:]:
            return block("You just made this exact call. Results unchanged.")
        
        # Dangerous command blocking (existing infrastructure)
        if tool_name == "bash" and is_dangerous(params["command"]):
            return block("Command blocked for safety.")
        
        # Edit without read
        if tool_name == "edit_file":
            path = params["file_path"]
            if path not in self.file_read_cache:
                return block("Cannot edit file you haven't read. Read it first.")
        
        return None  # Allow through
```

### Integration

- Runs as router middleware, before tool execution
- No LLM needed - pure deterministic logic
- State persists per agent session
- Complements existing hook enforcement

---

## Component 3: Graduated Intervention

**Purpose:** Respond proportionally to detected drift.

### Intervention Ladder

| Level | Trigger | Action |
|-------|---------|--------|
| **Observe** | Normal operation | Log telemetry, no action |
| **Nudge** | `drift_score > 10` | Inject soft reminder into context |
| **Warn** | `drift_score > 20` | Inject strong warning, log alert |
| **Modify** | Specific bad patterns | Tool interception (see Component 2) |
| **Kill** | `drift_score > 35` or hard failure | Terminate agent |

### Context Injection Messages

```python
INTERVENTIONS = {
    "nudge": "Reminder: Verify your understanding matches reality before proceeding.",
    
    "warn": "WARNING: Drift detected. Stop. Re-read the task requirements. "
            "Confirm file paths and function names are accurate before continuing.",
    
    "reread_reminder": "Note: You've read this file multiple times. "
                       "Consider taking notes or batching your operations.",
    
    "repetition_warning": "You are repeating similar operations. "
                          "If stuck, try a different approach.",
}
```

### Post-Kill Options

1. Restart same agent with fresh context
2. Restart with condensed context (key facts only)
3. Escalate to human review
4. Spawn different agent type (if implementer stuck, try architect first)

### Realistic Expectations

- **High confidence:** Kill detection saves compute on lost causes
- **Medium confidence:** Soft drift scoring needs tuning; signals may fire too late
- **Low confidence:** Nudge/warn injections often ignored by confused agents

Focus implementation effort on kill detection and tool interception first.

---

## Component 4: Adversarial Testing

**Purpose:** Improve test quality by proposing hard but fair test cases.

**Location:** TEST phase in iterate workflow

### When It Runs

After basic tests pass during TEST phase.

### Flow

```
TEST phase:
  1. Run pytest → pass
  2. Run coverage → check
  3. Adversarial assessment:
     - Coverage gaps? → write test → kick back to test_writing
     - Quality gaps?  → write test → kick back to test_writing
     - All good?      → proceed to review
```

### Fairness Rules

The adversarial tests MUST:
- Be derived from the stated spec/contract
- Pass if the implementation correctly follows the spec
- Fail only if there's a genuine gap

NOT allowed:
- Inventing new requirements
- Testing out-of-scope behavior
- Edge cases that contradict the contract

### Quality Assessment

**Quantitative (automated):**
- Line coverage
- Branch coverage
- Mutation testing (optional, via flag)

**Qualitative (LLM-assessed):**

| Pattern | What to Look For |
|---------|------------------|
| Happy path only | Tests only check "normal" inputs |
| Boundary blindness | No tests at 0, -1, MAX, empty, null |
| Assert weakness | Checking existence instead of correctness |
| State gaps | Only tests initial state |
| Error path missing | No "what if X fails?" tests |

### Assessment Prompt

```
Given this specification:
{spec}

And these existing tests:
{tests}

Review for:
1. Missing boundary cases (0, empty, max, negative)
2. Missing error paths (what if dependencies fail?)
3. Weak assertions (checking existence instead of correctness)
4. Untested state transitions
5. Any spec requirement with no corresponding test

For each gap, write a test that:
- Tests behavior the spec REQUIRES
- Would pass if spec is correctly implemented
- Would fail if there's a gap

Do NOT invent new requirements.
```

### Mutation Testing (Optional)

**Enable via flag:** `/iterate --mutation-testing`

**Flow:**
1. Run mutation testing (mutmut/cosmic-ray)
2. Collect surviving mutations (changes tests didn't catch)
3. For each survivor:
   - Feed mutation to adversarial agent
   - Agent writes test that would catch it
4. Add tests, kick back to test_writing

**Mutation test generation prompt:**
```
This mutation survived testing:

Original: {original_code}
Mutated:  {mutated_code}

Write a test that:
- Passes on the original
- Fails on the mutated version
```

**Trade-off:** Slower but thorough. Use for new features or CI pipelines.

### Implementation

- LLM: Haiku (cheap, fast, sufficient for pattern matching)
- Input: spec, test files, implementation, coverage report
- Output: new test cases to add
- Integration: adds tests to suite, triggers kick back to test_writing

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│                      MCP Router                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │           Tool Interceptor (deterministic)           │    │
│  │  - Re-read prevention                                │    │
│  │  - Edit-without-read blocking                        │    │
│  │  - Duplicate call detection                          │    │
│  │  - Dangerous command blocking                        │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Telemetry Stream                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Health Scorer (deterministic)                   │
│  - Signal extraction from telemetry                          │
│  - Drift score calculation                                   │
│  - Hard failure detection                                    │
│  - Extends existing sequence detection                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│            Intervention Engine (deterministic)               │
│  - Graduated response (nudge → warn → kill)                 │
│  - Context injection                                         │
│  - Agent termination                                         │
│  - Uses existing kill infrastructure                         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│           Adversarial Tester (LLM - Haiku)                  │
│  - Runs in TEST phase                                        │
│  - Assesses test quality/coverage                            │
│  - Generates gap-exposing tests                              │
│  - Optional: mutation-guided test generation                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Priority

### Phase 1: High-Value, Low-Effort
1. **Tool interception** - Add router middleware for re-read prevention, duplicate detection
2. **Health scoring** - Extend sequence detection with drift signals
3. **Kill trigger** - Wire health score to existing kill mechanism

### Phase 2: Medium Effort
4. **Adversarial test assessment** - LLM reviews tests for gaps in TEST phase
5. **Context injection** - Graduated nudge/warn messages

### Phase 3: Optional Enhancements
6. **Mutation testing integration** - Flag-enabled thorough mode
7. **Threshold tuning** - Collect data, adjust weights
8. **Post-kill strategies** - Restart policies, escalation paths

---

## Configuration

```yaml
observer:
  health_scoring:
    enabled: true
    nudge_threshold: 10
    warn_threshold: 20
    kill_threshold: 35
    window_size: 10  # turns
    
  tool_interception:
    enabled: true
    max_file_rereads: 2
    block_edit_without_read: true
    block_duplicate_calls: true
    
  adversarial_testing:
    enabled: true
    model: haiku
    mutation_testing: false  # Enable with --mutation-testing flag
    
  intervention:
    nudge_enabled: true
    warn_enabled: true
    kill_enabled: true
    post_kill_strategy: "restart_fresh"  # or "escalate", "try_architect"
```

---

## Open Questions

1. **Signal weights** - Starting values are guesses. Need observation to tune.
2. **Intervention effectiveness** - Nudge/warn may be ignored. Monitor and adjust.
3. **Mutation testing speed** - May need to limit scope or run async.
4. **Adversarial fairness edge cases** - What if agent disputes a test as unfair?

---

## Success Metrics

- Reduction in agent sessions that "go off the rails"
- Earlier detection of failing agents (less wasted compute)
- Improved test coverage scores
- Fewer surviving mutations after adversarial pass
- Reduced human intervention frequency
