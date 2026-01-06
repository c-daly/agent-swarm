"""Reward shaping utilities for SC2 environments.

Adds intermediate rewards to sparse win/loss signals from StarCraft II.
"""

import numpy as np
from typing import Optional


class RewardShaper:
    """Shapes sparse SC2 rewards for better learning."""

    def __init__(self, scenario: str = "minigame"):
        """
        Initialize reward shaper.

        Args:
            scenario: 'minigame' or 'fullgame'
        """
        self.scenario = scenario
        self.prev_score = 0
        self.prev_minerals = 0
        self.prev_army_value = 0

    def shape_reward(self, obs, base_reward: float) -> float:
        """
        Add intermediate rewards beyond win/loss.

        Args:
            obs: PySC2 observation
            base_reward: Base reward from environment (usually 0 or 1/-1 for win/loss)

        Returns:
            Shaped reward
        """
        shaped_reward = base_reward

        if self.scenario == "minigame":
            shaped_reward += self._minigame_rewards(obs)
        elif self.scenario == "fullgame":
            shaped_reward += self._fullgame_rewards(obs)

        return shaped_reward

    def _minigame_rewards(self, obs) -> float:
        """Calculate rewards for minigames."""
        reward = 0.0

        # Score increase (main signal for minigames)
        try:
            current_score = obs['score_cumulative'][0]
            score_delta = current_score - self.prev_score
            reward += score_delta / 100.0  # Normalize
            self.prev_score = current_score
        except (KeyError, IndexError, TypeError):
            # Observation doesn't have score, skip reward shaping
            pass

        return reward

    def _fullgame_rewards(self, obs) -> float:
        """Calculate rewards for full game."""
        reward = 0.0

        # Resource collection
        try:
            player = obs['player']
            if len(player) >= 2:
                current_minerals = player[0]
                minerals_delta = current_minerals - self.prev_minerals
                reward += minerals_delta / 1000.0  # Small reward for eco
                self.prev_minerals = current_minerals
        except (KeyError, IndexError, TypeError):
            # Observation doesn't have player info, skip reward shaping
            pass

        # Army value (if available)
        # This would require parsing unit values from observations
        # Simplified for now

        # Building completion, unit production, etc.
        # Can be extended based on specific goals

        return reward

    def reset(self):
        """Reset reward shaper state for new episode."""
        self.prev_score = 0
        self.prev_minerals = 0
        self.prev_army_value = 0
