# Debug, PR Comment, and Adversarial Testing Workflows

**Date:** 2026-01-22
**Status:** Design
**Related:** iterate workflow, agent-swarm plugin

---

## Overview

Three interconnected enhancements to enforce disciplined development:

1. **Debug Workflow** - Root-cause verification before fixing bugs
2. **PR Comment Workflow** - Understanding before addressing review feedback
3. **Iterate Enhancements** - Adversarial testing with measurable confidence

**Core principle:** You cannot fix what you haven't proven you understand.

---

## 1. Debug Workflow

### Purpose

Prevent "shotgun debugging" and symptom-only fixes by enforcing root-cause verification.

### Entry Points

- **Error-driven:** Stack trace, test failure, crash
- **Behavior-driven:** Unexpected behavior without crash

Both converge at TRIAGE.

### Phases

```
TRIAGE → REPRODUCE → HYPOTHESIZE → PROVE → FIX → VERIFY → PUSH → CHECK_STATUS
                                                                      ↓
                                                            ┌─────────┴─────────┐
                                                            ↓                   ↓
                                                       Issues found         All clear
                                                            ↓                   ↓
                                                       Loop back              DONE
                                                       to PROVE
```

### Phase Details

#### TRIAGE

**Purpose:** Gather comprehensive context before investigation.

**Required outputs (gate criteria):**
- **Severity:** P0 (system down), P1 (major feature broken), P2 (degraded), P3 (minor)
- **Affected components:** Which modules/services/files are involved
- **Error artifacts:** Stack traces, logs, error messages captured
- **Related files:** Files identified for investigation
- **Blast radius:** What else might be affected by this bug or its fix

**Tools allowed:** Read, Glob, Grep, Bash (read-only: `git log`, `git blame`, etc.)
**Tools blocked:** Edit, Write

**Adversary review:** Challenges completeness - "Did you check logs from X service?"

---

#### REPRODUCE

**Purpose:** Create automated proof the bug exists.

**Required outputs (gate criteria):**
- A failing test that demonstrates the bug
- Test must fail consistently (not flaky)

**Tools allowed:** Read, Glob, Grep, Edit/Write (test files and fixtures only)
**Allowed patterns:** `tests/`, `*_test.py`, `test_*.py`, `conftest.py`, `fixtures/`, `mocks/`
**Tools blocked:** Edit/Write on non-test files

**Adversary review:** "Does this test actually capture the reported behavior?"

**Kick-back:** Cannot reproduce → back to TRIAGE

---

#### HYPOTHESIZE

**Purpose:** Force explicit articulation of suspected cause.

**Required outputs (gate criteria):**
- **Hypothesis statement:** "The bug occurs because [X] when [Y]"
- **Testable prediction:** "If this hypothesis is correct, then [Z] should be observable"

**Example:**
```
Hypothesis: The bug occurs because the cache TTL is set to 0 when config is missing
Prediction: If true, removing config in test env should trigger the same error
```

**Tools allowed:** Read, Glob, Grep
**Tools blocked:** Edit, Write

**Adversary role (Hypothesis Challenger):**
- Proposes alternatives: "What if it's actually a race condition?"
- Challenges weak hypotheses: "This doesn't explain why it only fails on Tuesdays"
- States confidence level (high/medium/low)

**Kick-back:** Adversary high-confidence objection not addressed → stays in HYPOTHESIZE

---

#### PROVE

**Purpose:** Verify root cause before allowing any fix.

**Required outputs (gate criteria):**
1. **Prediction confirmed:** The predicted observation Z was found
2. **Mechanism traced:** Execution path showing *how* bug occurs (file:line references)
3. **Alternative ruled out:** At least one alternative explanation explicitly eliminated

**Tools allowed:** Read, Glob, Grep, Bash (debugging, test runs with print statements)
**Tools blocked:** Edit, Write

**Adversary role (Hypothesis Challenger continues):**
- "Your trace shows correlation, not causation"
- "You haven't ruled out [alternative X]"
- Must cite specific evidence for objections

**Kick-back:** Prediction not confirmed → back to HYPOTHESIZE

---

#### FIX

**Purpose:** Implement minimal change addressing proven root cause.

**Allowed:**
- Changes directly addressing proven root cause
- Test updates for regression coverage

**Not allowed:**
- "While I'm here" improvements
- Scope creep
- Unrelated refactoring

**Tools allowed:** Read, Glob, Grep, Edit, Write, Bash
**Tools blocked:** None

**Adversary review:** "Does the fix match what was proven in PROVE phase?"

---

#### VERIFY

**Purpose:** Full CI-level verification before push.

**Required outputs (gate criteria):**
- Reproduction test now passes
- Full test suite passes
- Lint/type checks pass

**Tools allowed:** Read, Glob, Grep, Bash (test runners)
**Tools blocked:** Edit, Write

---

#### PUSH

**Purpose:** Submit the fix.

**Action:** Push changes to branch/PR.

---

#### CHECK_STATUS

**Purpose:** Confirm fix is accepted in real environment.

**Checks:**
- CI passes?
- No new review comments on the fix?
- No new bug reports related to the change?

**Kick-back:** Any issues → back to PROVE (root cause understanding may be incomplete)

**Exit:** All clear → DONE

---

### Kick-back Logic Summary

| Scenario | Kick-back to | Rationale |
|----------|-------------|-----------|
| Can't reproduce | TRIAGE | Need more context |
| Prediction not confirmed | HYPOTHESIZE | Form new hypothesis |
| Hypothesis invalidated | REPRODUCE | Confirm bug still exists |
| Fix doesn't verify | PROVE | Root cause understanding may be wrong |
| CHECK_STATUS fails | PROVE | Understanding incomplete |

### Iteration Limits

- 5 total kick-backs, then escalate to user
- Prevents infinite loops
- User can override with acknowledgment

---

## 2. PR Comment Workflow

### Purpose

Prevent "made it worse" when addressing review feedback by enforcing understanding before fixing.

### Phases

```
UNDERSTAND → FIX → VERIFY → PUSH → CHECK_REVIEWS
                                        ↓
                              ┌─────────┴─────────┐
                              ↓                   ↓
                         New comments         No new comments
                              ↓                   ↓
                         Loop back              DONE
                         to UNDERSTAND
```

### Phase Details

#### UNDERSTAND

**Purpose:** Demonstrate comprehension of reviewer's concern before changing code.

**Required outputs (gate criteria):**
- **Articulation:** "The reviewer wants [X] because [Y]"
- **Current code problem:** "The current code causes this concern because [Z]"

**If unclear:** Ask clarifying question on the PR - do not guess.

**Tools allowed:** Read, Glob, Grep
**Tools blocked:** Edit, Write

**Adversary review:**
- "Are you sure that's what they meant?"
- "The comment also mentions Z, did you address that?"
- States confidence level

---

#### FIX

**Purpose:** Minimal change addressing the understood concern.

**Allowed:**
- Changes directly addressing articulated understanding
- No "while I'm here" additions

**Tools allowed:** All
**Tools blocked:** None

**Adversary review:** "Does this fix match what you articulated in UNDERSTAND?"

---

#### VERIFY

**Purpose:** Confirm fix doesn't break anything.

**Required:**
- Tests pass
- Lint passes
- Change addresses what was articulated in UNDERSTAND

**Tools allowed:** Read, Glob, Grep, Bash (test runners)
**Tools blocked:** Edit, Write

---

#### PUSH

**Purpose:** Submit the fix for re-review.

---

#### CHECK_REVIEWS

**Purpose:** Confirm reviewer is satisfied.

**Checks:**
- New comments on the same lines/files?
- New comments on your fix specifically?

**Kick-back:** New comments → back to UNDERSTAND (you didn't address it properly)

**Exit:** No new comments → DONE

**Iteration limit:** After 2-3 loops, escalate to user rather than infinite ping-pong.

---

## 3. Iterate Enhancements

### 3.1 Adversary at Design Gate

**Where:** DESIGN → ORCHESTRATE transition

**Purpose:** Challenge architecture and spec before spawning implementers.

**Adversary challenges:**
- "This design doesn't handle [edge case]"
- "Have you considered [alternative approach]?"
- "This will conflict with [existing system X]"

**Gate:** Adversary must be satisfied (or overruled with justification) before proceeding.

---

### 3.2 UNDERSTAND Gate in REVIEW Phase

**Where:** Before addressing each PR/Greptile comment

**Purpose:** Prevent "made it worse" when fixing review comments.

**Flow:**
```
REVIEW comment arrives
        ↓
   UNDERSTAND (articulate what reviewer wants)
        ↓
   FIX (address it)
        ↓
   VERIFY (tests pass)
        ↓
   Next comment or CHECK_STATUS
```

---

### 3.3 CHECK_STATUS After Push

**Where:** After pushing in REVIEW phase

**Purpose:** Don't advance until CI green AND no new comments.

**Current behavior:** REVIEW polls for comments
**Enhanced behavior:** Explicit CHECK_STATUS phase with loop-back

---

### 3.4 Adversarial Testing with Measurable Confidence

**Where:** TEST phase and TEST_WRITING phase

**Purpose:** Move beyond coverage % to meaningful test confidence.

#### Adversary Roles in TDD Loop

```
TEST_WRITING ──────────────────→ IMPLEMENT ───→ TEST ───→ REVIEW
      │                              │            │
      ↓                              ↓            ↓
 Adversary:                    Adversary:    Adversary:
 "Right tests?"                "Try to       "Tests actually
 "Edge cases?"                  break it"    prove anything?"
```

#### Confidence Dimensions

| Dimension | How Adversary Measures | Calculation |
|-----------|----------------------|-------------|
| **Attack survival** | Proposes N edge cases, tests catch X | X/N |
| **Mutation survival** | Mutates code M ways, tests fail F times | F/M |
| **Dimension coverage** | Happy path, errors, edges, boundaries | checklist % |
| **Specificity** | Would test catch ONLY this bug? | high/med/low |
| **Mock fidelity** | Do mocks match real behavior? | verified/assumed |
| **Redundancy** | Tests overlapping with existing coverage | flagged count |

#### Confidence Score Output

```
Test Confidence: 73%
├── Attack survival:     8/10 (80%)
├── Mutation survival:   6/10 (60%)
├── Dimension coverage:  4/5  (80%)
├── Specificity:         medium
├── Mock fidelity:       2 verified, 1 assumed
└── Redundancy:          2 flagged (recommend removal)
```

#### Gate Requirement

Tests must reach configurable minimum confidence threshold (default: 70%) before advancing from TEST phase.

#### Adversary's Systematic Approach

1. **Attack generation:** Propose edge cases, boundary conditions, error scenarios
2. **Mutation testing:** Suggest code mutations that should break tests
3. **Coverage analysis:** Check dimension coverage checklist
4. **Specificity check:** Verify tests wouldn't pass with related-but-different bugs
5. **Mock audit:** Flag mocks that haven't been verified against real behavior
6. **Redundancy analysis:** Identify tests that duplicate existing coverage
7. **Score calculation:** Aggregate dimensions into confidence score
8. **Recommendation:** Pass (meets threshold), Fail (below threshold), or Conditional (close, specific improvements needed)

#### Redundancy Analysis (Test Explosion Prevention)

**Problem:** TDD workflows can create test explosion - new tests added every iteration without checking if they're truly independent.

**Adversary checks for:**
- Tests that assert the same behavior as existing tests
- Tests whose failure would be caught by another test
- Tests that exercise identical code paths
- Copy-pasted tests with minor variations that don't add coverage

**Output:**
```
Redundancy Analysis:
├── test_user_login_success: UNIQUE - tests auth flow
├── test_user_login_valid: REDUNDANT - overlaps with test_user_login_success
│   └── Recommendation: Remove or merge
├── test_login_with_email: UNIQUE - tests email-specific path
└── test_login_returns_token: REDUNDANT - assertion covered by test_user_login_success
    └── Recommendation: Remove
```

**Action:** Adversary flags redundant tests for removal BEFORE adding new ones. This keeps the test suite lean and meaningful.

---

## 4. Adversary Handling

### Evidence Requirement

Adversary must cite specific code/logic flaws for objections. "I'm not convinced" is not sufficient.

### Confidence Levels

| Level | Meaning | Override rule |
|-------|---------|---------------|
| **High** | Strong evidence of flaw | Must address or appeal to user |
| **Medium** | Reasonable concern | Should address, can appeal with justification |
| **Low** | Minor nitpick | Can override with brief rationale |

### Appeal Process

1. Main agent presents counter-evidence
2. User breaks ties
3. If user overrules adversary 2x, adversary is noted but not a blocker for rest of session

---

## 5. Tool Restrictions Summary

### Debug Workflow

| Phase | Allowed | Blocked |
|-------|---------|---------|
| TRIAGE | Read, Glob, Grep, Bash (read-only) | Edit, Write |
| REPRODUCE | Read, Glob, Grep, Edit/Write (tests/fixtures) | Edit/Write (non-test) |
| HYPOTHESIZE | Read, Glob, Grep | Edit, Write |
| PROVE | Read, Glob, Grep, Bash (investigation) | Edit, Write |
| FIX | All | - |
| VERIFY | Read, Glob, Grep, Bash (test runners) | Edit, Write |
| CHECK_STATUS | Read, Bash (CI check) | Edit, Write |

### PR Comment Workflow

| Phase | Allowed | Blocked |
|-------|---------|---------|
| UNDERSTAND | Read, Glob, Grep | Edit, Write |
| FIX | All | - |
| VERIFY | Read, Glob, Grep, Bash (test runners) | Edit, Write |
| CHECK_REVIEWS | Read, Bash (gh commands) | Edit, Write |

---

## 6. Implementation Notes

### Shared Infrastructure

- Reuse `iterate_workflow.py` patterns for state management
- Reuse `workflow_client.py` for MCP router state
- Adversary can be existing `agent-swarm:adversary` agent with enhanced prompts

### New Components Needed

1. **Debug workflow state machine** (`lib/debug_workflow.py`)
2. **PR comment workflow state machine** (`lib/pr_comment_workflow.py`)
3. **Adversary confidence scoring** (enhancement to adversary agent)
4. **Test confidence calculator** (`lib/test_confidence.py`)

### Hook Integration

- Tool restrictions enforced via hooks (same pattern as iterate)
- Phase gates checked before advancing

---

## 7. Success Criteria

### Debug Workflow
- Bugs fixed on first attempt (no "made it worse")
- Root cause documented for each fix
- Reproduction tests exist for all fixed bugs

### PR Comment Workflow
- Review ping-pong reduced (fewer back-and-forth cycles)
- No "made it worse" incidents
- All comments addressed with demonstrated understanding

### Iterate Enhancements
- Test confidence scores tracked over time
- Adversary catches real issues (not just noise)
- Design challenges surface problems before implementation

---

## 8. Open Questions

1. Should confidence thresholds be per-project configurable?
2. How to handle adversary disagreements that are genuinely subjective?
3. Should CHECK_STATUS have a timeout before escalating?
4. Integration with existing Greptile review flow?

---

## Appendix: Workflow Comparison

| Aspect | Debug | PR Comment | Iterate (enhanced) |
|--------|-------|------------|-------------------|
| Entry | Bug report | Review comment | Task/spec |
| Core gate | PROVE | UNDERSTAND | TEST (confidence) |
| Adversary focus | Hypothesis | Understanding | Design + Tests |
| Exit condition | CHECK_STATUS clear | No new comments | Review approved |
| Loop-back trigger | Any failure | New comments | Test/review failures |
