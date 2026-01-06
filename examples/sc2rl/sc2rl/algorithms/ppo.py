"""PPO algorithm configuration for SC2."""

from stable_baselines3 import PPO
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
import gymnasium as gym
import torch
import torch.nn as nn
from typing import Dict


class SC2FeaturesExtractor(BaseFeaturesExtractor):
    """
    Custom feature extractor for SC2 Dict observations.

    Processes screen/minimap with CNNs and concatenates with player features.
    """

    def __init__(self, observation_space: gym.spaces.Dict, features_dim: int = 256):
        super().__init__(observation_space, features_dim)

        # Screen CNN (processes screen features)
        screen_shape = observation_space['screen'].shape
        self.screen_cnn = nn.Sequential(
            nn.Conv2d(screen_shape[0], 16, kernel_size=5, stride=1, padding=2),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(16, 32, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Flatten(),
        )

        # Minimap CNN (processes minimap features)
        minimap_shape = observation_space['minimap'].shape
        self.minimap_cnn = nn.Sequential(
            nn.Conv2d(minimap_shape[0], 8, kernel_size=5, stride=1, padding=2),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(8, 16, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Flatten(),
        )

        # Calculate CNN output dimensions
        with torch.no_grad():
            screen_sample = torch.zeros(1, *screen_shape)
            minimap_sample = torch.zeros(1, *minimap_shape)
            screen_features = self.screen_cnn(screen_sample)
            minimap_features = self.minimap_cnn(minimap_sample)
            cnn_output_dim = screen_features.shape[1] + minimap_features.shape[1]

        # Player features dimension
        player_dim = observation_space['player'].shape[0]

        # Combined layer
        total_input_dim = cnn_output_dim + player_dim
        self.combined_layer = nn.Sequential(
            nn.Linear(total_input_dim, features_dim),
            nn.ReLU(),
        )

    def forward(self, observations: Dict[str, torch.Tensor]) -> torch.Tensor:
        screen_features = self.screen_cnn(observations['screen'])
        minimap_features = self.minimap_cnn(observations['minimap'])
        player_features = observations['player']

        combined = torch.cat([screen_features, minimap_features, player_features], dim=1)
        return self.combined_layer(combined)


def create_ppo_agent(env, **kwargs):
    """
    Create PPO agent with SC2-tuned hyperparameters.

    Args:
        env: SC2 Gymnasium environment
        **kwargs: Override default hyperparameters

    Returns:
        PPO agent instance
    """
    policy_kwargs = {
        'features_extractor_class': SC2FeaturesExtractor,
        'features_extractor_kwargs': {'features_dim': 256},
    }

    default_config = {
        'learning_rate': 2.5e-4,
        'n_steps': 128,
        'batch_size': 64,
        'n_epochs': 4,
        'gamma': 0.99,
        'gae_lambda': 0.95,
        'clip_range': 0.1,
        'ent_coef': 0.01,
        'policy': 'MultiInputPolicy',
        'policy_kwargs': policy_kwargs,
        'verbose': 1,
    }

    # Merge with user-provided kwargs
    config = {**default_config, **kwargs}

    return PPO(env=env, **config)
