"""Full game SC2 environment implementation."""

from sc2rl.envs.base import SC2GymnasiumWrapper
from pysc2.env import sc2_env
from typing import Optional


class SC2FullGameEnv(SC2GymnasiumWrapper):
    """
    Full 1v1 StarCraft II game environment.

    Agent plays against built-in AI opponent. Requires macro and micro
    management, resource gathering, unit production, and strategic planning.
    """

    def __init__(
        self,
        race: str = "random",
        opponent_race: str = "random",
        difficulty: str = "medium",
        map_name: str = "Simple64",
        render_mode: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize full game environment.

        Args:
            race: Player race ('terran', 'protoss', 'zerg', 'random')
            opponent_race: Opponent race
            difficulty: AI difficulty ('very_easy', 'easy', 'medium', 'hard',
                       'very_hard', 'elite', 'cheat_vision', 'cheat_money', 'cheat_insane')
            map_name: Map name (default 'Simple64')
            render_mode: 'human' for visual, None for headless
            **kwargs: Additional environment arguments
        """
        self.race = self._parse_race(race)
        self.opponent_race = self._parse_race(opponent_race)
        self.difficulty = self._parse_difficulty(difficulty)

        # Create players list with AI opponent
        players = [
            sc2_env.Agent(self.race),
            sc2_env.Bot(
                self.opponent_race,
                self.difficulty
            )
        ]

        # Initialize base environment
        super().__init__(
            map_name=map_name,
            render_mode=render_mode,
            step_mul=16,  # Slower for strategic decisions
            screen_size=84,
            minimap_size=64,
            full_game=True,  # Use extended action set
            players=players,
            **kwargs
        )

    @staticmethod
    def _parse_race(race: str) -> sc2_env.Race:
        """Convert race string to SC2 Race enum."""
        race_map = {
            'terran': sc2_env.Race.terran,
            'protoss': sc2_env.Race.protoss,
            'zerg': sc2_env.Race.zerg,
            'random': sc2_env.Race.random,
        }
        return race_map.get(race.lower(), sc2_env.Race.random)

    @staticmethod
    def _parse_difficulty(difficulty: str) -> sc2_env.Difficulty:
        """Convert difficulty string to SC2 Difficulty enum."""
        difficulty_map = {
            'very_easy': sc2_env.Difficulty.very_easy,
            'easy': sc2_env.Difficulty.easy,
            'medium': sc2_env.Difficulty.medium,
            'medium_hard': sc2_env.Difficulty.medium_hard,
            'hard': sc2_env.Difficulty.hard,
            'very_hard': sc2_env.Difficulty.very_hard,
            'cheat_vision': sc2_env.Difficulty.cheat_vision,
            'cheat_money': sc2_env.Difficulty.cheat_money,
            'cheat_insane': sc2_env.Difficulty.cheat_insane,
        }
        return difficulty_map.get(difficulty.lower(), sc2_env.Difficulty.medium)
