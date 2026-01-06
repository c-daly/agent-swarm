#!/usr/bin/env python3
"""
SC2 RL Gym Training Script

Train reinforcement learning agents on StarCraft II environments.

Examples:
  # Headless training (fast)
  python scripts/train.py --env MoveToBeacon --algo ppo --headless --steps 100000

  # Visual training (watch AI learn)
  python scripts/train.py --env CollectMineralShards --algo dqn --visual --steps 50000

  # Full game with specific race
  python scripts/train.py --env fullgame --algo ppo --race terran --visual --steps 1000000
"""

import argparse
import os
from pathlib import Path

from sc2rl.envs.minigames import (
    MoveToBeaconEnv,
    CollectMineralShardsEnv,
    DefeatRoachesEnv,
    FindAndDefeatZerglingsEnv,
)
from sc2rl.envs.fullgame import SC2FullGameEnv
from sc2rl.algorithms import get_algorithm
from stable_baselines3.common.callbacks import CheckpointCallback


def main():
    parser = argparse.ArgumentParser(
        description='Train RL agents on StarCraft II',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Environment selection
    parser.add_argument(
        '--env',
        required=True,
        choices=['MoveToBeacon', 'CollectMineralShards', 'DefeatRoaches',
                'FindAndDefeatZerglings', 'fullgame'],
        help='SC2 environment to train on'
    )

    # Algorithm selection
    parser.add_argument(
        '--algo',
        required=True,
        choices=['ppo', 'dqn', 'a2c'],
        help='RL algorithm to use'
    )

    # Rendering mode
    render_group = parser.add_mutually_exclusive_group()
    render_group.add_argument(
        '--visual',
        action='store_true',
        help='Show game window (slower, good for debugging)'
    )
    render_group.add_argument(
        '--headless',
        action='store_true',
        help='No graphics (faster training)'
    )

    # Training parameters
    parser.add_argument(
        '--steps',
        type=int,
        default=100000,
        help='Total timesteps to train (default: 100000)'
    )
    parser.add_argument(
        '--save-freq',
        type=int,
        default=10000,
        help='Save model every N steps (default: 10000)'
    )
    parser.add_argument(
        '--save-path',
        type=str,
        default='models',
        help='Directory to save models (default: models/)'
    )

    # Full game specific parameters
    parser.add_argument(
        '--race',
        default='random',
        choices=['terran', 'protoss', 'zerg', 'random'],
        help='Player race for full game (default: random)'
    )
    parser.add_argument(
        '--opponent-race',
        default='random',
        choices=['terran', 'protoss', 'zerg', 'random'],
        help='Opponent race for full game (default: random)'
    )
    parser.add_argument(
        '--difficulty',
        default='medium',
        choices=['very_easy', 'easy', 'medium', 'hard', 'very_hard'],
        help='Opponent difficulty for full game (default: medium)'
    )

    args = parser.parse_args()

    # Determine render mode
    if args.visual:
        render_mode = 'human'
        print("🎮 Visual mode enabled - SC2 window will be shown")
    else:
        render_mode = None
        print("⚡ Headless mode - training without graphics")

    # Create environment
    print(f"\n🌟 Creating {args.env} environment...")

    env_map = {
        'MoveToBeacon': MoveToBeaconEnv,
        'CollectMineralShards': CollectMineralShardsEnv,
        'DefeatRoaches': DefeatRoachesEnv,
        'FindAndDefeatZerglings': FindAndDefeatZerglingsEnv,
        'fullgame': SC2FullGameEnv,
    }

    env_kwargs = {'render_mode': render_mode}

    # Add full game specific arguments
    if args.env == 'fullgame':
        env_kwargs.update({
            'race': args.race,
            'opponent_race': args.opponent_race,
            'difficulty': args.difficulty,
        })
        print(f"   Race: {args.race} vs {args.opponent_race} ({args.difficulty})")

    try:
        env = env_map[args.env](**env_kwargs)
        print("✓ Environment created successfully")
    except Exception as e:
        print(f"✗ Error creating environment: {e}")
        print("\nMake sure StarCraft II is installed and PySC2 is configured correctly.")
        return 1

    # Create agent
    print(f"\n🤖 Creating {args.algo.upper()} agent...")
    try:
        agent = get_algorithm(args.algo, env)
        print("✓ Agent created successfully")
    except Exception as e:
        print(f"✗ Error creating agent: {e}")
        env.close()
        return 1

    # Set up checkpoint callback
    checkpoint_dir = Path(args.save_path) / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_callback = CheckpointCallback(
        save_freq=args.save_freq,
        save_path=str(checkpoint_dir),
        name_prefix=f"{args.env}_{args.algo}",
        save_replay_buffer=False,
        save_vecnormalize=False,
    )

    # Train
    print(f"\n🚀 Starting training for {args.steps:,} steps...")
    print(f"   Algorithm: {args.algo.upper()}")
    print(f"   Environment: {args.env}")
    print(f"   Save frequency: every {args.save_freq:,} steps")
    print(f"   Checkpoints: {checkpoint_dir}\n")

    try:
        agent.learn(
            total_timesteps=args.steps,
            callback=checkpoint_callback,
            progress_bar=True,
        )
        print("\n✓ Training completed successfully!")
    except KeyboardInterrupt:
        print("\n⚠ Training interrupted by user")
    except Exception as e:
        print(f"\n✗ Training error: {e}")
        env.close()
        return 1

    # Save final model
    save_dir = Path(args.save_path)
    save_dir.mkdir(parents=True, exist_ok=True)

    model_name = f"{args.env}_{args.algo}"
    save_path = save_dir / model_name

    print(f"\n💾 Saving model to {save_path}...")
    try:
        agent.save(save_path)
        print("✓ Model saved successfully!")
    except Exception as e:
        print(f"✗ Error saving model: {e}")

    # Cleanup
    env.close()
    print("\n✨ Done!")
    return 0


if __name__ == '__main__':
    exit(main())
