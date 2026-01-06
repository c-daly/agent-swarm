"""Observation preprocessing for StarCraft II environments.

Converts PySC2's multi-modal observations into normalized format for RL.
"""

import numpy as np
from pysc2.lib import features
from typing import Dict


class ObservationProcessor:
    """Processes PySC2 observations into normalized Dict space."""

    def __init__(self, screen_size: int = 84, minimap_size: int = 64):
        """
        Initialize observation processor.

        Args:
            screen_size: Size of screen feature layers
            minimap_size: Size of minimap feature layers
        """
        self.screen_size = screen_size
        self.minimap_size = minimap_size

    def process(self, timestep) -> Dict[str, np.ndarray]:
        """
        Convert PySC2 TimeStep to normalized dict observation.

        Args:
            timestep: PySC2 TimeStep object

        Returns:
            Dictionary with keys:
                - 'screen': (C, H, W) screen features
                - 'minimap': (C, H, W) minimap features
                - 'player': (N,) player/game info
                - 'available_actions': (M,) binary mask of available actions
        """
        obs = timestep.observation

        # Extract and normalize screen features
        screen = self._process_screen(obs['feature_screen'])

        # Extract and normalize minimap features
        minimap = self._process_minimap(obs['feature_minimap'])

        # Extract player/game information
        player = self._process_player(obs['player'])

        # Get available actions mask
        available_actions = self._process_available_actions(obs['available_actions'])

        return {
            'screen': screen,
            'minimap': minimap,
            'player': player,
            'available_actions': available_actions,
        }

    def _process_screen(self, screen_features: np.ndarray) -> np.ndarray:
        """
        Process screen feature layers.

        Args:
            screen_features: Raw screen features (H, W, C)

        Returns:
            Normalized screen features (C, H, W)
        """
        # Transpose from HWC to CHW for PyTorch
        screen = np.transpose(screen_features, (2, 0, 1))

        # Normalize to [0, 1]
        # PySC2 features have varying ranges - using simple scaling for now
        # For production, should use per-channel normalization based on PySC2 specs
        screen = screen.astype(np.float32)

        # Avoid division by zero
        screen_max = screen.max(axis=(1, 2), keepdims=True)
        screen_max = np.where(screen_max == 0, 1, screen_max)
        screen = screen / screen_max

        return screen

    def _process_minimap(self, minimap_features: np.ndarray) -> np.ndarray:
        """
        Process minimap feature layers.

        Args:
            minimap_features: Raw minimap features (H, W, C)

        Returns:
            Normalized minimap features (C, H, W)
        """
        # Transpose from HWC to CHW
        minimap = np.transpose(minimap_features, (2, 0, 1))

        # Normalize to [0, 1]
        # Using per-channel normalization
        minimap = minimap.astype(np.float32)

        # Avoid division by zero
        minimap_max = minimap.max(axis=(1, 2), keepdims=True)
        minimap_max = np.where(minimap_max == 0, 1, minimap_max)
        minimap = minimap / minimap_max

        return minimap

    def _process_player(self, player_features: np.ndarray) -> np.ndarray:
        """
        Process player/game information.

        Args:
            player_features: Raw player features

        Returns:
            Normalized player features
        """
        # Normalize player features
        player = player_features.astype(np.float32)

        # Common normalization: resources to [0, 1]
        # Indices: 0=minerals, 1=vespene, 2=food_used, 3=food_cap, etc.
        if len(player) >= 4:
            player[0] = np.clip(player[0] / 2000.0, 0, 1)  # minerals
            player[1] = np.clip(player[1] / 2000.0, 0, 1)  # vespene
            player[2] = np.clip(player[2] / 200.0, 0, 1)   # food_used
            player[3] = np.clip(player[3] / 200.0, 0, 1)   # food_cap

        return player

    def _process_available_actions(self, available_actions: np.ndarray) -> np.ndarray:
        """
        Process available actions into binary mask.

        Args:
            available_actions: Array of available PySC2 function IDs

        Returns:
            Binary mask of available actions in simplified space
        """
        from pysc2.lib import actions as pysc2_actions

        # Create binary mask for simplified action space
        max_actions = 13  # Max ID in our action space
        mask = np.zeros(max_actions, dtype=np.float32)

        # Map PySC2 function IDs to our simplified action IDs
        # Based on ActionSpace class mapping
        pysc2_to_simplified = {
            pysc2_actions.FUNCTIONS.no_op.id: 0,
            pysc2_actions.FUNCTIONS.select_army.id: 1,
            pysc2_actions.FUNCTIONS.Move_screen.id: 2,
            pysc2_actions.FUNCTIONS.Attack_screen.id: 3,
            pysc2_actions.FUNCTIONS.select_point.id: 4,
            pysc2_actions.FUNCTIONS.Build_SupplyDepot_screen.id: 5,
            pysc2_actions.FUNCTIONS.Build_Barracks_screen.id: 6,
            pysc2_actions.FUNCTIONS.Train_Marine_quick.id: 7,
            pysc2_actions.FUNCTIONS.Train_SCV_quick.id: 8,
            pysc2_actions.FUNCTIONS.select_idle_worker.id: 9,
            pysc2_actions.FUNCTIONS.Harvest_Gather_screen.id: 10,
            pysc2_actions.FUNCTIONS.Build_CommandCenter_screen.id: 11,
            pysc2_actions.FUNCTIONS.Build_Refinery_screen.id: 12,
        }

        # Mark available actions as 1.0
        for pysc2_id in available_actions:
            if pysc2_id in pysc2_to_simplified:
                simplified_id = pysc2_to_simplified[pysc2_id]
                mask[simplified_id] = 1.0

        # Always allow no-op as fallback
        mask[0] = 1.0

        return mask
