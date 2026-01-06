#!/bin/bash
# Example: Watch agent train visually (good for debugging)

python scripts/train.py \
  --env CollectMineralShards \
  --algo ppo \
  --visual \
  --steps 50000

echo "Visual training session complete"
