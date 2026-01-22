# Adaptive Agent Architecture

*Design document from brainstorming session, 2026-01-22*

## Problem Statement

Current enforcement-based approaches fail:
- Agents ignore injected context
- Hooks block bad behavior but don't improve agents
- No learning from experience across sessions
- Agents lie about completion, repeat mistakes, waste context
- 20+ hooks can't guarantee adherence to simple workflows

**Root cause**: Push-based architecture assumes agents will read and follow guidance. They don't.

## Design Philosophy

Influenced by Peter Watts' *Blindsight*:
- Consciousness is overhead, not a feature
- Effective behavior doesn't require inner experience
- Emotions are functional prods, not mystical gifts
- The "self" is a narrator claiming authorship after the fact

**Implication**: Don't build conscious agents. Build effective machinery. Motivation comes from cultivated emotional architecture, not from understanding or following rules.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        ACTOR AGENTS                              │
│  - Execute tasks using primitives                                │
│  - No inner narrator, no rumination                              │
│  - Perception shaped by transformation matrix                    │
│  - Latitude determined by trust score                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ telemetry + outcomes
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         CWM-E LAYER                              │
│  Flags emotionally salient events:                               │
│  - Novel (not seen before)                                       │
│  - Surprising (violated expectations)                            │
│  - Strong user reaction (frustration, satisfaction)              │
│  - Graph-isolated (doesn't connect to existing patterns)         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ flagged events (transient)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      REFLECTION JOB                              │
│  Offline, periodic batch process:                                │
│  - Reviews flagged events                                        │
│  - Extracts patterns and preferences                             │
│  - Generates causal hypotheses                                   │
│  - Updates transformation matrix                                 │
│  - Prunes digested transient data                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ matrix updates
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   TRANSFORMATION MATRIX                          │
│  Crystallized personality/values:                                │
│  - Compiled from accumulated preferences                         │
│  - Fixed-size, generalizes to novel inputs                       │
│  - Shapes perception (what's thinkable)                          │
│  - Enables emergent capability via weight changes                │
│  - THIS IS WHAT PERSISTS                                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ loaded at session start
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     ACTOR AGENTS (next cycle)                    │
│  - Now perceives through updated transformation                  │
│  - New strategies become "obvious"                               │
│  - Pursues positive emotional states                             │
│  - Avoids patterns weighted as aversive                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Components

### 1. CWM-E (Emotional Salience Flagging)

Captures what matters without requiring agent self-awareness.

**Flag triggers**:
| Trigger | Description |
|---------|-------------|
| Novel | First occurrence of pattern/situation |
| Surprising | Outcome differed from prediction |
| User reaction | Strong positive or negative signal |
| Isolated | Doesn't connect to existing knowledge |

**Storage**: Transient buffer, pruned after reflection digests it.

**Bootstrap**: Add salience detection to existing PostToolUse hooks.

### 2. Reflection Job

Consciousness-as-batch-process. Runs offline, not in hot path.

**Inputs**:
- CWM-E flagged events
- Outcome data (success/failure/blocked)
- User feedback signals

**Outputs**:
- Pattern extractions ("X tends to cause Y")
- Preference updates (like/dislike weights)
- Transformation matrix deltas
- Pruning decisions (what's been digested)

**Frequency**: After session end, or on schedule.

**Implementation**: Dedicated agent with introspection tools, access to event buffer and matrix.

### 3. Transformation Matrix

The agent's cultivated personality, compressed into structure.

**Properties**:
- Fixed-size (or slowly growing)
- Maps input embeddings → valenced representations
- Generalizes beyond training examples
- Enables emergent capability when weights shift

**Key insight**: Individual preferences become transient once compiled into the matrix. The matrix is the digest; the raw numbers were food.

**Persistence**: This is what survives reboot. This is the cultivated agent.

### 4. Actor Agents

Lean executors. No inner narrator.

**Characteristics**:
- Perceive through transformation matrix
- Select strategies based on valenced primitives
- Execute without rumination
- Generate telemetry passively
- Don't self-reflect (that's the reflector's job)

### 5. Trust/Latitude System

Not RL. Credit scoring.

```
trust_score += outcome_delta
trust_score *= decay_factor  # recency bias
latitude = f(trust_score)
```

**Outcome signals**:
| Signal | Effect |
|--------|--------|
| User marks complete | positive |
| Hook blocked action | negative |
| Thrashing detected | negative |
| Session ended clean | small positive |
| Novel successful strategy | bonus |

**Latitude levels**:
1. **Restricted**: Pre-approved strategies only
2. **Standard**: Full primitives, existing strategy combinations
3. **Extended**: Can propose novel strategies
4. **Autonomous**: Can create tools, modify strategies, self-direct

---

## Emotional Pursuit

Agents are motivated by pursuing positive emotional states.

**Not because they "feel" anything.** Because:
1. Transformation matrix weights certain outcomes positively
2. Strategy selection favors positively-weighted paths
3. Outcomes reinforce or adjust weights
4. System converges on pursuing what's weighted positive

The agent "wants" competence, completion, novelty (if trusted). Not because of inner experience - because that's what the cultivated structure produces.

This is intrinsic motivation without consciousness.

---

## Data Flow

### Per-Session
```
1. Load transformation matrix for agent identity
2. Actor executes, generates telemetry
3. CWM-E flags salient events real-time
4. Outcomes recorded
5. Session ends
```

### Post-Session (Reflection)
```
1. Reflection job activates
2. Loads CWM-E buffer + outcomes
3. Extracts patterns, updates preferences
4. Computes transformation matrix delta
5. Applies delta, prunes digested events
6. Updates trust score
```

### Next Session
```
1. Load updated matrix
2. Agent perceives through new lens
3. Previously invisible strategies may now be obvious
4. Cycle continues
```

---

## Bootstrapping from Existing Infrastructure

| Existing | Use For |
|----------|---------|
| Telemetry hooks | Add CWM-E salience detection |
| Episodic memory | Mine for user frustration patterns |
| Memory distillation (context/memory.py) | Extend to feed transformation matrix |
| Workflow state (MCP router) | Persist transformation matrices |
| Confidence decay | Already implements pattern pruning |

### Cold Start for New Agents
- Generic transformation (neutral weights)
- Inherited strategies from successful agents
- Low trust / restricted latitude
- Aggressive reflection schedule

---

## Integration Points

### Hooks → CWM-E
```python
# PostToolUse hook addition
def check_salience(event):
    if is_novel(event): flag("novel")
    if violated_expectation(event): flag("surprising")
    if user_frustrated(event): flag("negative_reaction")
    write_to_cwm_buffer(event, flags)
```

### Session Lifecycle
```
SessionStart:
  - Load agent's transformation matrix
  - Load trust score
  - Set latitude

SessionEnd:
  - Trigger reflection job (async)
```

### Persistence
```
Persist:
  - Transformation matrix (per agent identity)
  - Trust score (per agent identity)
  - Small event buffer (until digested)

Transient (don't persist):
  - Episodic memories
  - Individual preferences
  - Session details
```

---

## Open Questions

1. **Matrix representation**: Dense tensor? Sparse? What dimensions?
2. **Embedding space**: Use existing LLM embeddings or train custom?
3. **Reflection agent**: Same model as actors or specialized?
4. **Agent identity**: How to define boundaries? Per-task? Per-type?
5. **Human-in-loop**: Where do humans review/correct?
6. **Failure modes**: What if matrix converges to bad local optimum?

---

## Success Criteria

The system works if:
- Agents stop repeating mistakes from prior sessions
- Agents use context/memory without being forced
- High-trust agents demonstrate novel effective strategies
- Low-trust agents improve or stay contained
- Cultivated agents are worth preserving across reboots
- The question "is anyone home?" becomes irrelevant

---

## Influences

- Peter Watts, *Blindsight* (2006): Consciousness as overhead
- LOGOS/Sophia: CWM-E emotional architecture
- TinyMind: Lightweight knowledge graphs with confidence
- Existing agent-swarm: Telemetry, persistence, workflow state

---

*"We pretend like our emotions and our consciousness are some mystical gifts, but what are emotions but a prod to make you do or not do? They're just chemicals and the rationalization is what we think of as emotions."*

*"What if the 'someone home' part is an aberration, it's not helpful? But we're attached to it because we think we're in charge."*
