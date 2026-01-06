#!/bin/bash
# Example: Train on full game (longer training time required)

python scripts/train.py \
  --env fullgame \
  --algo ppo \
  --race terran \
  --opponent-race protoss \
  --difficulty medium \
  --headless \
  --steps 1000000 \
  --save-freq 50000

echo "Full game training complete"
