#!/bin/bash
# Example: Fast headless training on MoveToBeacon minigame

python scripts/train.py \
  --env MoveToBeacon \
  --algo ppo \
  --headless \
  --steps 100000 \
  --save-freq 10000

echo "Training complete! Model saved to models/MoveToBeacon_ppo"
