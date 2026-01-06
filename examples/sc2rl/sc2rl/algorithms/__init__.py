"""RL algorithm configurations for SC2."""

from sc2rl.algorithms.ppo import create_ppo_agent
from sc2rl.algorithms.dqn import create_dqn_agent
from sc2rl.algorithms.a2c import create_a2c_agent

__all__ = [
    "create_ppo_agent",
    "create_dqn_agent",
    "create_a2c_agent",
]


def get_algorithm(algo_name: str, env, **kwargs):
    """
    Get algorithm by name.

    Args:
        algo_name: 'ppo', 'dqn', or 'a2c'
        env: Gymnasium environment
        **kwargs: Additional algorithm arguments

    Returns:
        Configured SB3 algorithm instance
    """
    algo_map = {
        'ppo': create_ppo_agent,
        'dqn': create_dqn_agent,
        'a2c': create_a2c_agent,
    }

    if algo_name.lower() not in algo_map:
        raise ValueError(f"Unknown algorithm: {algo_name}. Choose from {list(algo_map.keys())}")

    return algo_map[algo_name.lower()](env, **kwargs)
