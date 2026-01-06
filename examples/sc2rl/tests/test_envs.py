"""Tests for SC2 RL environments."""

import pytest
import numpy as np
from gymnasium import spaces

from sc2rl.envs.minigames import MoveToBeaconEnv, CollectMineralShardsEnv
from sc2rl.envs.fullgame import SC2FullGameEnv


class TestEnvironmentSpaces:
    """Test observation and action spaces."""

    def test_minigame_action_space(self):
        """Test minigame has correct action space."""
        env = MoveToBeaconEnv(render_mode=None)
        assert isinstance(env.action_space, spaces.Discrete)
        assert env.action_space.n == 5  # Minigame actions
        env.close()

    def test_fullgame_action_space(self):
        """Test full game has extended action space."""
        env = SC2FullGameEnv(render_mode=None)
        assert isinstance(env.action_space, spaces.Discrete)
        assert env.action_space.n == 13  # Full game actions
        env.close()

    def test_observation_space_structure(self):
        """Test observation space is correct Dict space."""
        env = MoveToBeaconEnv(render_mode=None)
        assert isinstance(env.observation_space, spaces.Dict)
        assert 'screen' in env.observation_space.spaces
        assert 'minimap' in env.observation_space.spaces
        assert 'player' in env.observation_space.spaces
        assert 'available_actions' in env.observation_space.spaces
        env.close()


class TestEnvironmentBasics:
    """Test basic environment functionality."""

    @pytest.mark.skip(reason="Requires SC2 installation")
    def test_reset_returns_valid_observation(self):
        """Test reset returns valid observation."""
        env = MoveToBeaconEnv(render_mode=None)
        obs, info = env.reset()

        assert isinstance(obs, dict)
        assert 'screen' in obs
        assert 'minimap' in obs
        assert 'player' in obs

        # Check shapes
        assert obs['screen'].shape == (17, 84, 84)
        assert obs['minimap'].shape == (7, 64, 64)

        env.close()

    @pytest.mark.skip(reason="Requires SC2 installation")
    def test_step_returns_correct_format(self):
        """Test step returns correct Gymnasium format."""
        env = MoveToBeaconEnv(render_mode=None)
        env.reset()

        action = env.action_space.sample()
        obs, reward, terminated, truncated, info = env.step(action)

        assert isinstance(obs, dict)
        assert isinstance(reward, (int, float))
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info, dict)

        env.close()


class TestFullGame:
    """Test full game specific features."""

    def test_race_parsing(self):
        """Test race string parsing."""
        from pysc2.env import sc2_env

        assert SC2FullGameEnv._parse_race('terran') == sc2_env.Race.terran
        assert SC2FullGameEnv._parse_race('protoss') == sc2_env.Race.protoss
        assert SC2FullGameEnv._parse_race('zerg') == sc2_env.Race.zerg
        assert SC2FullGameEnv._parse_race('random') == sc2_env.Race.random

    def test_difficulty_parsing(self):
        """Test difficulty string parsing."""
        from pysc2.env import sc2_env

        assert SC2FullGameEnv._parse_difficulty('very_easy') == sc2_env.Difficulty.very_easy
        assert SC2FullGameEnv._parse_difficulty('medium') == sc2_env.Difficulty.medium
        assert SC2FullGameEnv._parse_difficulty('very_hard') == sc2_env.Difficulty.very_hard


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
