"""Base Gymnasium wrapper for PySC2 environments."""

import gymnasium as gym
from gymnasium import spaces
from pysc2.env import sc2_env
from pysc2.lib import features, actions
import numpy as np
from typing import Optional, Tuple, Dict, Any

from sc2rl.envs.actions import ActionSpace
from sc2rl.envs.observations import ObservationProcessor
from sc2rl.envs.rewards import RewardShaper


class SC2GymnasiumWrapper(gym.Env):
    """Gymnasium-compatible wrapper for PySC2 environments."""

    metadata = {"render_modes": ["human", None]}

    def __init__(
        self,
        map_name: str,
        render_mode: Optional[str] = None,
        step_mul: int = 8,
        screen_size: int = 84,
        minimap_size: int = 64,
        full_game: bool = False,
        players: Optional[list] = None,
        **kwargs
    ):
        """
        Initialize SC2 Gymnasium wrapper.

        Args:
            map_name: SC2 map name (e.g., 'MoveToBeacon', 'Simple64')
            render_mode: 'human' for visual, None for headless
            step_mul: Number of game steps per action (higher = faster)
            screen_size: Screen feature layer size
            minimap_size: Minimap feature layer size
            full_game: Whether this is a full game (affects action space)
            players: List of sc2_env.Agent/Bot objects (None = single agent)
            **kwargs: Additional SC2Env arguments
        """
        super().__init__()

        self.map_name = map_name
        self.render_mode = render_mode
        self.step_mul = step_mul
        self.screen_size = screen_size
        self.minimap_size = minimap_size
        self.full_game = full_game

        # Create PySC2 environment
        if players is None:
            players = [sc2_env.Agent(sc2_env.Race.terran)]

        self._env = sc2_env.SC2Env(
            map_name=map_name,
            players=players,
            agent_interface_format=features.AgentInterfaceFormat(
                feature_dimensions=features.Dimensions(
                    screen=screen_size,
                    minimap=minimap_size
                ),
                use_feature_units=True,
            ),
            step_mul=step_mul,
            game_steps_per_episode=kwargs.get('game_steps_per_episode', 0),
            visualize=(render_mode == 'human'),
            **{k: v for k, v in kwargs.items() if k != 'game_steps_per_episode'}
        )

        # Initialize helpers
        self.obs_processor = ObservationProcessor(screen_size, minimap_size)
        self.reward_shaper = RewardShaper(scenario='fullgame' if full_game else 'minigame')

        # Define observation space (Dict space for multi-modal obs)
        num_screen_channels = 17  # PySC2 screen features
        num_minimap_channels = 7  # PySC2 minimap features
        num_player_features = 11  # Player info dimensions

        self.observation_space = spaces.Dict({
            'screen': spaces.Box(
                low=0.0, high=1.0,
                shape=(num_screen_channels, screen_size, screen_size),
                dtype=np.float32
            ),
            'minimap': spaces.Box(
                low=0.0, high=1.0,
                shape=(num_minimap_channels, minimap_size, minimap_size),
                dtype=np.float32
            ),
            'player': spaces.Box(
                low=0.0, high=1.0,
                shape=(num_player_features,),
                dtype=np.float32
            ),
            'available_actions': spaces.Box(
                low=0.0, high=1.0,
                shape=(13 if full_game else 5,),
                dtype=np.float32
            ),
        })

        # Define action space
        # For now, simple Discrete space (later can extend to MultiDiscrete for coords)
        num_actions = 13 if full_game else 5
        self.action_space = spaces.Discrete(num_actions)

        self._episode_count = 0

    def step(self, action: int) -> Tuple[Dict, float, bool, bool, Dict]:
        """
        Execute action and return transition.

        Args:
            action: Simplified action ID

        Returns:
            observation: Processed observation dict
            reward: Shaped reward
            terminated: Whether episode ended (win/loss)
            truncated: Whether episode was truncated
            info: Additional info
        """
        # Convert simplified action to PySC2 action
        # For spatial actions, we'll use random coordinates for now
        # (More sophisticated version would have the agent output coords)
        screen_coords = (
            np.random.randint(0, self.screen_size),
            np.random.randint(0, self.screen_size)
        )

        pysc2_action = ActionSpace.to_pysc2_action(
            action,
            screen_coords=screen_coords,
            full_game=self.full_game
        )

        # Execute in SC2
        try:
            timesteps = self._env.step([pysc2_action])
            timestep = timesteps[0]
        except Exception as e:
            # SC2 errors indicate serious problems - raise them
            raise RuntimeError(f"StarCraft II environment error during step: {e}. "
                             f"Check SC2 installation and PySC2 configuration.") from e

        # Process observation
        obs = self.obs_processor.process(timestep)

        # Calculate reward
        base_reward = timestep.reward
        reward = self.reward_shaper.shape_reward(timestep.observation, base_reward)

        # Check termination
        terminated = timestep.last()
        truncated = False  # SC2 handles episode length internally

        # Additional info
        info = {
            'score': timestep.observation.score_cumulative[0] if hasattr(timestep.observation, 'score_cumulative') else 0,
            'episode': self._episode_count,
        }

        return obs, reward, terminated, truncated, info

    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Tuple[Dict, Dict]:
        """
        Reset environment.

        Args:
            seed: Random seed
            options: Additional options

        Returns:
            observation: Initial observation
            info: Additional info
        """
        super().reset(seed=seed)

        # Reset SC2 environment
        try:
            timesteps = self._env.reset()
            timestep = timesteps[0]
        except Exception as e:
            # SC2 errors indicate serious problems - raise them
            raise RuntimeError(f"StarCraft II environment error during reset: {e}. "
                             f"Check SC2 installation and PySC2 configuration. "
                             f"Ensure SC2PATH environment variable is set correctly.") from e

        # Reset reward shaper
        self.reward_shaper.reset()

        # Process initial observation
        obs = self.obs_processor.process(timestep)

        self._episode_count += 1

        info = {
            'episode': self._episode_count,
        }

        return obs, info

    def render(self):
        """Rendering handled by PySC2 visualize flag."""
        # PySC2 handles rendering via the visualize parameter
        pass

    def close(self):
        """Clean up SC2 environment."""
        if hasattr(self, '_env'):
            self._env.close()

    def _get_empty_obs(self) -> Dict:
        """Get empty observation for error cases."""
        return {
            'screen': np.zeros((17, self.screen_size, self.screen_size), dtype=np.float32),
            'minimap': np.zeros((7, self.minimap_size, self.minimap_size), dtype=np.float32),
            'player': np.zeros(11, dtype=np.float32),
            'available_actions': np.zeros(13 if self.full_game else 5, dtype=np.float32),
        }
