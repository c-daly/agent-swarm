"""SC2 RL Gym Environments."""

from sc2rl.envs.minigames import (
    MoveToBeaconEnv,
    CollectMineralShardsEnv,
    DefeatRoachesEnv,
    FindAndDefeatZerglingsEnv,
)
from sc2rl.envs.fullgame import SC2FullGameEnv

__all__ = [
    "MoveToBeaconEnv",
    "CollectMineralShardsEnv",
    "DefeatRoachesEnv",
    "FindAndDefeatZerglingsEnv",
    "SC2FullGameEnv",
]
