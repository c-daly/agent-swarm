# StarCraft II Reinforcement Learning Gym

A production-ready Gymnasium-compatible environment for training reinforcement learning agents on StarCraft II, supporting both minigames and full game scenarios with popular algorithms (PPO, DQN, A2C) via Stable-Baselines3.

## Features

- ✅ **Gymnasium-compatible** - Modern RL environment API
- ✅ **Multiple scenarios** - Minigames (MoveToBeacon, CollectMineralShards, DefeatRoaches) and full 1v1 games
- ✅ **Popular algorithms** - PPO, DQN, A2C with SC2-tuned hyperparameters
- ✅ **Visual & headless modes** - Watch your agent train or run fast headless training
- ✅ **Easy CLI** - Simple command-line interface for training and evaluation
- ✅ **Custom CNN architecture** - Processes SC2's multi-modal observations (screen, minimap, player stats)
- ✅ **Reward shaping** - Adds intermediate rewards to sparse win/loss signals

## Installation

### Prerequisites

1. **StarCraft II** (choose one):
   - **Visual mode**: Full SC2 client (free Starter Edition works)
   - **Headless mode**: Linux headless client (~500MB)

   ```bash
   # Linux headless client (recommended for training)
   wget http://blzdistsc2-a.akamaihd.net/Linux/SC2.4.10.zip
   unzip SC2.4.10.zip -d ~/StarCraftII
   ```

2. **Python 3.8+** with pip

### Install SC2RL Gym

```bash
cd examples/sc2rl
pip install -e .
```

This will install all dependencies:
- pysc2 (StarCraft II interface)
- gymnasium (environment API)
- stable-baselines3 (RL algorithms)
- torch (neural networks)

## Quick Start

### 1. Test Installation

```bash
# Run a quick demo with random agent
python scripts/demo.py --env MoveToBeacon --visual
```

### 2. Train an Agent

```bash
# Headless training (fast)
python scripts/train.py \
  --env MoveToBeacon \
  --algo ppo \
  --headless \
  --steps 100000

# Visual training (watch AI learn)
python scripts/train.py \
  --env CollectMineralShards \
  --algo ppo \
  --visual \
  --steps 50000
```

### 3. Evaluate Trained Agent

```bash
python scripts/evaluate.py \
  --env MoveToBeacon \
  --model models/MoveToBeacon_ppo \
  --episodes 10 \
  --visual
```

## Usage

### Training

```bash
python scripts/train.py --env <ENV> --algo <ALGO> [OPTIONS]
```

**Environments:**
- `MoveToBeacon` - Navigate marine to beacon (simplest)
- `CollectMineralShards` - Collect minerals with marines
- `DefeatRoaches` - Combat micromanagement
- `FindAndDefeatZerglings` - Exploration + combat
- `fullgame` - Full 1v1 game vs AI

**Algorithms:**
- `ppo` - Proximal Policy Optimization (most popular for SC2)
- `dqn` - Deep Q-Network (classic)
- `a2c` - Advantage Actor-Critic (lightweight)

**Options:**
- `--visual` - Show game window (slower, good for debugging)
- `--headless` - No graphics (faster training)
- `--steps N` - Total training steps
- `--save-freq N` - Save checkpoint every N steps

**Full game options:**
- `--race {terran,protoss,zerg,random}` - Player race
- `--opponent-race {terran,protoss,zerg,random}` - Opponent race
- `--difficulty {very_easy,easy,medium,hard,very_hard}` - AI difficulty

### Examples

#### Minigame Training

```bash
# Quick headless training on MoveToBeacon
python scripts/train.py --env MoveToBeacon --algo ppo --headless --steps 100000

# Watch DQN learn to collect minerals
python scripts/train.py --env CollectMineralShards --algo dqn --visual --steps 50000
```

#### Full Game Training

```bash
# Train Terran vs Protoss (medium difficulty)
python scripts/train.py \
  --env fullgame \
  --algo ppo \
  --race terran \
  --opponent-race protoss \
  --difficulty medium \
  --headless \
  --steps 1000000

# Visual training to watch strategy development
python scripts/train.py \
  --env fullgame \
  --algo a2c \
  --race zerg \
  --visual \
  --steps 500000
```

## Architecture

```
sc2rl/
├── envs/
│   ├── base.py           # Base Gymnasium wrapper for PySC2
│   ├── minigames.py      # Minigame environments
│   ├── fullgame.py       # Full game environment
│   ├── observations.py   # Observation preprocessing
│   ├── actions.py        # Action space abstraction
│   └── rewards.py        # Reward shaping
├── algorithms/
│   ├── ppo.py            # PPO configuration
│   ├── dqn.py            # DQN configuration
│   └── a2c.py            # A2C configuration
└── utils/
    └── ...               # Utilities
```

### Key Components

**Environment Wrapper** (`envs/base.py`):
- Converts PySC2 to Gymnasium API
- Handles headless/visual mode switching
- Processes multi-modal observations (screen, minimap, player stats)
- Simplifies action space (500+ functions → ~13 most useful)

**Observation Processing** (`envs/observations.py`):
- Extracts screen and minimap feature layers
- Normalizes player statistics
- Returns Dict observation space compatible with SB3

**Reward Shaping** (`envs/rewards.py`):
- Adds intermediate rewards to sparse win/loss signals
- Tracks score increases, resource collection, army value
- Configurable for minigames vs full game

**Custom CNN** (`algorithms/ppo.py`):
- Processes screen/minimap with convolutional layers
- Combines with player features
- Shared across all algorithms

## Environment Details

### Minigames

| Environment | Description | Difficulty | Training Time |
|-------------|-------------|------------|---------------|
| MoveToBeacon | Navigate to beacon | Easy | ~100k steps |
| CollectMineralShards | Resource collection | Medium | ~200k steps |
| DefeatRoaches | Combat micro | Medium | ~300k steps |
| FindAndDefeatZerglings | Exploration + combat | Hard | ~500k steps |

### Full Game

- 1v1 match against built-in AI
- Configurable race and difficulty
- Requires 1M+ steps for decent performance
- Full macro and micro management

## Troubleshooting

### SC2 not found

```
Error: SC2 not installed or PySC2 not configured
```

**Solution:** Install SC2 and set environment variable:
```bash
export SC2PATH=~/StarCraftII
```

### Out of memory

Reduce batch size in algorithm configs or use headless mode.

### Slow training

- Use `--headless` flag
- Increase `step_mul` (trades reaction time for speed)
- Use A2C instead of PPO (lighter algorithm)

### Visual mode not working

Ensure you have the full SC2 client installed (not just headless).

## Advanced Usage

### Custom Hyperparameters

```python
from sc2rl.envs.minigames import MoveToBeaconEnv
from sc2rl.algorithms import create_ppo_agent

env = MoveToBeaconEnv(render_mode=None)
agent = create_ppo_agent(
    env,
    learning_rate=1e-4,
    n_steps=256,
    batch_size=128
)
agent.learn(total_timesteps=200000)
```

### Extending with New Environments

```python
from sc2rl.envs.base import SC2GymnasiumWrapper

class MyCustomEnv(SC2GymnasiumWrapper):
    def __init__(self, render_mode=None, **kwargs):
        super().__init__(
            map_name="YourMapName",
            render_mode=render_mode,
            step_mul=8,
            **kwargs
        )
```

## Performance Tips

1. **Headless mode** - 3-5x faster than visual
2. **Minigames first** - Learn basics before full game
3. **PPO for stability** - Most reliable for SC2
4. **Start simple** - MoveToBeacon → CollectMineralShards → Full game
5. **Monitor closely** - Visual mode for first 10k steps, then headless

## References

- [PySC2 GitHub](https://github.com/deepmind/pysc2)
- [Stable-Baselines3 Docs](https://stable-baselines3.readthedocs.io/)
- [Gymnasium API](https://gymnasium.farama.org/)
- [SC2 AI Community](https://github.com/Blizzard/s2client-proto)

## License

MIT License - See main agent-swarm LICENSE

## Contributing

This is an example project within the agent-swarm plugin. Contributions welcome!
