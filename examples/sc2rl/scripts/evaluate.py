#!/usr/bin/env python3
"""
SC2 RL Gym Evaluation Script

Evaluate trained agents on StarCraft II environments.

Examples:
  python scripts/evaluate.py --env MoveToBeacon --model models/MoveToBeacon_ppo --episodes 10
  python scripts/evaluate.py --env fullgame --model models/fullgame_ppo --visual
"""

import argparse
import numpy as np
from pathlib import Path

from sc2rl.envs.minigames import (
    MoveToBeaconEnv,
    CollectMineralShardsEnv,
    DefeatRoachesEnv,
    FindAndDefeatZerglingsEnv,
)
from sc2rl.envs.fullgame import SC2FullGameEnv
from stable_baselines3 import PPO, DQN, A2C


def main():
    parser = argparse.ArgumentParser(description='Evaluate trained SC2 RL agents')

    parser.add_argument(
        '--env',
        required=True,
        choices=['MoveToBeacon', 'CollectMineralShards', 'DefeatRoaches',
                'FindAndDefeatZerglings', 'fullgame'],
        help='SC2 environment'
    )
    parser.add_argument(
        '--model',
        required=True,
        type=str,
        help='Path to saved model'
    )
    parser.add_argument(
        '--algo',
        default='ppo',
        choices=['ppo', 'dqn', 'a2c'],
        help='Algorithm used (default: ppo)'
    )
    parser.add_argument(
        '--episodes',
        type=int,
        default=5,
        help='Number of episodes to evaluate (default: 5)'
    )
    parser.add_argument(
        '--visual',
        action='store_true',
        help='Show game window'
    )

    args = parser.parse_args()

    # Determine render mode
    render_mode = 'human' if args.visual else None

    # Create environment
    print(f"Creating {args.env} environment...")
    env_map = {
        'MoveToBeacon': MoveToBeaconEnv,
        'CollectMineralShards': CollectMineralShardsEnv,
        'DefeatRoaches': DefeatRoachesEnv,
        'FindAndDefeatZerglings': FindAndDefeatZerglingsEnv,
        'fullgame': SC2FullGameEnv,
    }

    env = env_map[args.env](render_mode=render_mode)

    # Load model
    print(f"Loading model from {args.model}...")
    algo_map = {
        'ppo': PPO,
        'dqn': DQN,
        'a2c': A2C,
    }

    try:
        model = algo_map[args.algo].load(args.model)
        print("✓ Model loaded successfully")
    except Exception as e:
        print(f"✗ Error loading model: {e}")
        env.close()
        return 1

    # Evaluate
    print(f"\nEvaluating for {args.episodes} episodes...\n")

    episode_rewards = []
    episode_scores = []

    for episode in range(args.episodes):
        obs, info = env.reset()
        done = False
        episode_reward = 0
        steps = 0

        while not done:
            action, _states = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            episode_reward += reward
            steps += 1
            done = terminated or truncated

        episode_rewards.append(episode_reward)
        episode_scores.append(info.get('score', 0))

        print(f"Episode {episode + 1}: Reward = {episode_reward:.2f}, "
              f"Score = {info.get('score', 0)}, Steps = {steps}")

    # Summary statistics
    print(f"\n{'='*50}")
    print(f"Evaluation Summary ({args.episodes} episodes)")
    print(f"{'='*50}")
    print(f"Mean Reward:  {np.mean(episode_rewards):.2f} ± {np.std(episode_rewards):.2f}")
    print(f"Mean Score:   {np.mean(episode_scores):.2f} ± {np.std(episode_scores):.2f}")
    print(f"Min Reward:   {np.min(episode_rewards):.2f}")
    print(f"Max Reward:   {np.max(episode_rewards):.2f}")
    print(f"{'='*50}\n")

    env.close()
    return 0


if __name__ == '__main__':
    exit(main())
