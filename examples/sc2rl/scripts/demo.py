#!/usr/bin/env python3
"""
SC2 RL Gym Demo Script

Quick demo to verify installation and see a random agent in action.

Usage:
  python scripts/demo.py --env MoveToBeacon --visual
"""

import argparse
import time

from sc2rl.envs.minigames import (
    MoveToBeaconEnv,
    CollectMineralShardsEnv,
    DefeatRoachesEnv,
)
from sc2rl.envs.fullgame import SC2FullGameEnv


def main():
    parser = argparse.ArgumentParser(description='SC2 RL Gym Demo')

    parser.add_argument(
        '--env',
        default='MoveToBeacon',
        choices=['MoveToBeacon', 'CollectMineralShards', 'DefeatRoaches', 'fullgame'],
        help='Environment to demo (default: MoveToBeacon)'
    )
    parser.add_argument(
        '--visual',
        action='store_true',
        help='Show game window'
    )
    parser.add_argument(
        '--episodes',
        type=int,
        default=3,
        help='Number of episodes to run (default: 3)'
    )

    args = parser.parse_args()

    render_mode = 'human' if args.visual else None

    print(f"\n🎮 SC2 RL Gym Demo")
    print(f"   Environment: {args.env}")
    print(f"   Mode: {'Visual' if args.visual else 'Headless'}")
    print(f"   Episodes: {args.episodes}\n")

    # Create environment
    env_map = {
        'MoveToBeacon': MoveToBeaconEnv,
        'CollectMineralShards': CollectMineralShardsEnv,
        'DefeatRoaches': DefeatRoachesEnv,
        'fullgame': SC2FullGameEnv,
    }

    print("Creating environment...")
    try:
        env = env_map[args.env](render_mode=render_mode)
        print("✓ Environment created\n")
    except Exception as e:
        print(f"✗ Error: {e}")
        print("\nMake sure StarCraft II is installed properly.")
        return 1

    # Run random agent
    print("Running random agent...\n")

    for episode in range(args.episodes):
        obs, info = env.reset()
        done = False
        steps = 0
        total_reward = 0

        print(f"Episode {episode + 1}:")

        while not done and steps < 1000:
            # Take random action
            action = env.action_space.sample()
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            steps += 1
            done = terminated or truncated

            if args.visual:
                time.sleep(0.05)  # Slow down for visibility

        print(f"  Steps: {steps}, Reward: {total_reward:.2f}, "
              f"Score: {info.get('score', 0)}\n")

    env.close()
    print("✨ Demo complete!\n")
    return 0


if __name__ == '__main__':
    exit(main())
