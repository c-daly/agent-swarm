---
name: distill
description: Distill session episodes into persistent memory patterns
user_invocable: true
---

## Usage
```
/distill           # Distill episodes at current scope
/distill show      # Show current memory
/distill episodes  # Show pending episodes
```

## How It Works
1. Extract patterns from `.context/EPISODES.md` learnings
2. Classify as pattern, pitfall, preference, or approach
3. Match against existing `.context/MEMORY.md` patterns
4. Reinforce matches (increases confidence), add new, decay old, prune low

## CLI
```bash
python3 ~/.claude/plugins/agent-swarm/context/memory.py distill .   # Distill
python3 ~/.claude/plugins/agent-swarm/context/memory.py show .      # Show
python3 ~/.claude/plugins/agent-swarm/context/memory.py episodes .  # Pending
```

## Confidence
- Reinforcement: each observation increases confidence
- Decay: patterns not seen in 30+ days lose confidence
- Pruning: below 0.2 removed

## Logging
Agents log learnings with: `LEARNING: [description]`
Captured by post-task hooks -> EPISODES.md.
