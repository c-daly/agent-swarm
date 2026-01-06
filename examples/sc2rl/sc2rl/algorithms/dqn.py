"""DQN algorithm configuration for SC2."""

from stable_baselines3 import DQN
from sc2rl.algorithms.ppo import SC2FeaturesExtractor


def create_dqn_agent(env, **kwargs):
    """
    Create DQN agent with SC2-tuned hyperparameters.

    Args:
        env: SC2 Gymnasium environment
        **kwargs: Override default hyperparameters

    Returns:
        DQN agent instance
    """
    policy_kwargs = {
        'features_extractor_class': SC2FeaturesExtractor,
        'features_extractor_kwargs': {'features_dim': 256},
    }

    default_config = {
        'learning_rate': 1e-4,
        'buffer_size': 10000,
        'learning_starts': 1000,
        'batch_size': 32,
        'tau': 1.0,
        'gamma': 0.99,
        'train_freq': 4,
        'gradient_steps': 1,
        'exploration_fraction': 0.1,
        'exploration_initial_eps': 1.0,
        'exploration_final_eps': 0.05,
        'policy': 'MultiInputPolicy',
        'policy_kwargs': policy_kwargs,
        'verbose': 1,
    }

    # Merge with user-provided kwargs
    config = {**default_config, **kwargs}

    return DQN(env=env, **config)
