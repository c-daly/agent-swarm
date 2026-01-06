"""A2C algorithm configuration for SC2."""

from stable_baselines3 import A2C
from sc2rl.algorithms.ppo import SC2FeaturesExtractor


def create_a2c_agent(env, **kwargs):
    """
    Create A2C agent with SC2-tuned hyperparameters.

    Args:
        env: SC2 Gymnasium environment
        **kwargs: Override default hyperparameters

    Returns:
        A2C agent instance
    """
    policy_kwargs = {
        'features_extractor_class': SC2FeaturesExtractor,
        'features_extractor_kwargs': {'features_dim': 256},
    }

    default_config = {
        'learning_rate': 7e-4,
        'n_steps': 5,
        'gamma': 0.99,
        'gae_lambda': 1.0,
        'ent_coef': 0.01,
        'vf_coef': 0.5,
        'max_grad_norm': 0.5,
        'policy': 'MultiInputPolicy',
        'policy_kwargs': policy_kwargs,
        'verbose': 1,
    }

    # Merge with user-provided kwargs
    config = {**default_config, **kwargs}

    return A2C(env=env, **config)
