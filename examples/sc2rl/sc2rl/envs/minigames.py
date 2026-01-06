"""Minigame environment implementations for SC2 RL."""

from sc2rl.envs.base import SC2GymnasiumWrapper
from typing import Optional


class MoveToBeaconEnv(SC2GymnasiumWrapper):
    """
    Move marine to beacon minigame.

    Simplest SC2 minigame - good for testing and initial training.
    Agent controls a single marine and must move it to a randomly placed beacon.
    """

    def __init__(self, render_mode: Optional[str] = None, **kwargs):
        """
        Initialize MoveToBeacon environment.

        Args:
            render_mode: 'human' for visual, None for headless
            **kwargs: Additional environment arguments
        """
        super().__init__(
            map_name="MoveToBeacon",
            render_mode=render_mode,
            step_mul=8,
            screen_size=84,
            minimap_size=64,
            full_game=False,
            **kwargs
        )


class CollectMineralShardsEnv(SC2GymnasiumWrapper):
    """
    Collect mineral shards minigame.

    Agent controls 2 marines and must collect 20 mineral shards scattered
    across the map. Requires coordination and efficient pathfinding.
    """

    def __init__(self, render_mode: Optional[str] = None, **kwargs):
        """
        Initialize CollectMineralShards environment.

        Args:
            render_mode: 'human' for visual, None for headless
            **kwargs: Additional environment arguments
        """
        super().__init__(
            map_name="CollectMineralShards",
            render_mode=render_mode,
            step_mul=8,
            screen_size=84,
            minimap_size=64,
            full_game=False,
            **kwargs
        )


class DefeatRoachesEnv(SC2GymnasiumWrapper):
    """
    Defeat roaches combat minigame.

    Agent controls 9 marines and must defeat roaches. Requires
    micro-management and combat tactics.
    """

    def __init__(self, render_mode: Optional[str] = None, **kwargs):
        """
        Initialize DefeatRoaches environment.

        Args:
            render_mode: 'human' for visual, None for headless
            **kwargs: Additional environment arguments
        """
        super().__init__(
            map_name="DefeatRoaches",
            render_mode=render_mode,
            step_mul=8,
            screen_size=84,
            minimap_size=64,
            full_game=False,
            **kwargs
        )


class FindAndDefeatZerglingsEnv(SC2GymnasiumWrapper):
    """
    Find and defeat zerglings minigame.

    Agent controls 3 marines and must find and defeat groups of zerglings.
    Requires exploration and combat.
    """

    def __init__(self, render_mode: Optional[str] = None, **kwargs):
        """
        Initialize FindAndDefeatZerglings environment.

        Args:
            render_mode: 'human' for visual, None for headless
            **kwargs: Additional environment arguments
        """
        super().__init__(
            map_name="FindAndDefeatZerglings",
            render_mode=render_mode,
            step_mul=8,
            screen_size=84,
            minimap_size=64,
            full_game=False,
            **kwargs
        )
