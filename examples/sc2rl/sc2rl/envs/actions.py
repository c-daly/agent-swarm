"""Action space abstraction for StarCraft II.

Simplifies PySC2's 500+ functions to a manageable subset for RL training.
"""

from typing import List, Tuple
from pysc2.lib import actions, features
import numpy as np


class ActionSpace:
    """Simplified action space mapper for SC2."""

    # Common actions for minigames (ID -> (function_name, needs_coords))
    MINIGAME_ACTIONS = {
        0: ("no_op", False),
        1: ("select_army", False),
        2: ("move_screen", True),
        3: ("attack_screen", True),
        4: ("select_point", True),
    }

    # Extended actions for full game
    FULL_GAME_ACTIONS = {
        **MINIGAME_ACTIONS,
        5: ("build_supply_depot", True),
        6: ("build_barracks", True),
        7: ("train_marine", False),
        8: ("train_scv", False),
        9: ("select_idle_worker", False),
        10: ("harvest_gather", True),
        11: ("build_command_center", True),
        12: ("build_refinery", True),
    }

    @staticmethod
    def get_action_names(full_game: bool = False) -> List[str]:
        """Get list of action names."""
        action_set = ActionSpace.FULL_GAME_ACTIONS if full_game else ActionSpace.MINIGAME_ACTIONS
        return [name for name, _ in action_set.values()]

    @staticmethod
    def to_pysc2_action(action_id: int, screen_coords: Tuple[int, int] = None,
                       full_game: bool = False) -> actions.FunctionCall:
        """
        Convert simplified action to PySC2 FunctionCall.

        Args:
            action_id: Simplified action ID
            screen_coords: (x, y) coordinates for spatial actions
            full_game: Whether to use full game action set

        Returns:
            PySC2 FunctionCall
        """
        action_set = ActionSpace.FULL_GAME_ACTIONS if full_game else ActionSpace.MINIGAME_ACTIONS

        if action_id not in action_set:
            return actions.FUNCTIONS.no_op()

        action_name, needs_coords = action_set[action_id]

        # Map action names to PySC2 function IDs
        func_map = {
            "no_op": actions.FUNCTIONS.no_op,
            "select_army": lambda: actions.FUNCTIONS.select_army("select"),
            "move_screen": lambda coords: actions.FUNCTIONS.Move_screen("now", coords),
            "attack_screen": lambda coords: actions.FUNCTIONS.Attack_screen("now", coords),
            "select_point": lambda coords: actions.FUNCTIONS.select_point("select", coords),
            "build_supply_depot": lambda coords: actions.FUNCTIONS.Build_SupplyDepot_screen("now", coords),
            "build_barracks": lambda coords: actions.FUNCTIONS.Build_Barracks_screen("now", coords),
            "train_marine": lambda: actions.FUNCTIONS.Train_Marine_quick("now"),
            "train_scv": lambda: actions.FUNCTIONS.Train_SCV_quick("now"),
            "select_idle_worker": lambda: actions.FUNCTIONS.select_idle_worker("select"),
            "harvest_gather": lambda coords: actions.FUNCTIONS.Harvest_Gather_screen("now", coords),
            "build_command_center": lambda coords: actions.FUNCTIONS.Build_CommandCenter_screen("now", coords),
            "build_refinery": lambda coords: actions.FUNCTIONS.Build_Refinery_screen("now", coords),
        }

        if action_name not in func_map:
            return actions.FUNCTIONS.no_op()

        if needs_coords:
            if screen_coords is None:
                # Default to center of screen if no coords provided
                screen_coords = (42, 42)  # 84x84 screen center
            return func_map[action_name](screen_coords)
        else:
            return func_map[action_name]()
