#!/usr/bin/env python3
"""State management CLI for agent-swarm workflow.

Replaces manual Python snippets with simple commands.

Usage:
    python3 state.py transition <phase>
    python3 state.py checkpoint <phase> <on|off>
    python3 state.py autopilot <on|off|toggle>
    python3 state.py show [key]
    python3 state.py config <get|set> <key> [value]
"""

import json
import sys
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent.parent / ".state"
SESSION_FILE = STATE_DIR / "session.json"
WORKFLOW_FILE = STATE_DIR / "workflow.json"

VALID_PHASES = ["INTAKE", "DESIGN", "IMPLEMENT", "VERIFY", "REVIEW", "DONE"]


def load_json(path, default=None):
    """Load JSON file, return default if not found."""
    if not path.exists():
        return default or {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {path}: {e}", file=sys.stderr)
        sys.exit(1)


def save_json(path, data):
    """Save JSON file with formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def transition(phase):
    """Transition to new phase, check checkpoints, reset counters."""
    phase = phase.upper()

    if phase not in VALID_PHASES:
        print(f"ERROR: Invalid phase '{phase}'", file=sys.stderr)
        print(f"Valid phases: {', '.join(VALID_PHASES)}", file=sys.stderr)
        sys.exit(1)

    # Load current state
    state = load_json(SESSION_FILE, {
        "phase": "INTAKE",
        "search_count": 0,
        "read_count": 0,
        "files_read": [],
        "classification_given": False,
        "classification_type": None,
        "workflow_invoked": False
    })

    workflow = load_json(WORKFLOW_FILE, {
        "checkpoints": {},
        "autopilot": {"override": False}
    })

    old_phase = state.get("phase", "NONE")

    # Check if checkpoint required
    checkpoint_required = workflow.get("checkpoints", {}).get(phase, False)
    autopilot = workflow.get("autopilot", {}).get("override", False)

    if checkpoint_required and not autopilot:
        print(f"⚠️  CHECKPOINT: {old_phase} → {phase}", file=sys.stderr)
        print(f"Checkpoint required for {phase} phase", file=sys.stderr)
        print("User approval needed before proceeding", file=sys.stderr)
        sys.exit(1)

    # Update state
    state["phase"] = phase
    state["search_count"] = 0
    state["read_count"] = 0

    save_json(SESSION_FILE, state)

    print(f"[ORCHESTRATOR] {old_phase} → {phase}")


def checkpoint(phase, status):
    """Enable/disable checkpoint for a phase."""
    phase = phase.upper()
    status = status.lower()

    if phase not in VALID_PHASES:
        print(f"ERROR: Invalid phase '{phase}'", file=sys.stderr)
        sys.exit(1)

    if status not in ["on", "off"]:
        print(f"ERROR: Status must be 'on' or 'off', got '{status}'", file=sys.stderr)
        sys.exit(1)

    workflow = load_json(WORKFLOW_FILE, {"checkpoints": {}, "autopilot": {}})

    if "checkpoints" not in workflow:
        workflow["checkpoints"] = {}

    workflow["checkpoints"][phase] = (status == "on")
    save_json(WORKFLOW_FILE, workflow)

    print(f"Checkpoint for {phase}: {'enabled' if status == 'on' else 'disabled'}")


def autopilot(action):
    """Manage autopilot mode."""
    action = action.lower()

    if action not in ["on", "off", "toggle"]:
        print(f"ERROR: Action must be 'on', 'off', or 'toggle', got '{action}'", file=sys.stderr)
        sys.exit(1)

    workflow = load_json(WORKFLOW_FILE, {"checkpoints": {}, "autopilot": {"override": False}})

    if "autopilot" not in workflow:
        workflow["autopilot"] = {"override": False}

    current = workflow["autopilot"].get("override", False)

    if action == "toggle":
        new_value = not current
    else:
        new_value = (action == "on")

    workflow["autopilot"]["override"] = new_value
    save_json(WORKFLOW_FILE, workflow)

    print(f"Autopilot: {'enabled' if new_value else 'disabled'}")


def show(key=None):
    """Display current state or specific key."""
    state = load_json(SESSION_FILE)

    if not state:
        print("No session state found")
        return

    if key:
        if key in state:
            value = state[key]
            if isinstance(value, (dict, list)):
                print(json.dumps(value, indent=2))
            else:
                print(value)
        else:
            print(f"ERROR: Key '{key}' not found in state", file=sys.stderr)
            sys.exit(1)
    else:
        print(json.dumps(state, indent=2))


def config(action, key, value=None):
    """Manage workflow configuration."""
    workflow = load_json(WORKFLOW_FILE)

    if action == "get":
        # Support dot notation: autopilot.override
        parts = key.split(".")
        current = workflow
        for part in parts:
            if part in current:
                current = current[part]
            else:
                print(f"ERROR: Key '{key}' not found", file=sys.stderr)
                sys.exit(1)

        if isinstance(current, (dict, list)):
            print(json.dumps(current, indent=2))
        else:
            print(current)

    elif action == "set":
        if value is None:
            print("ERROR: Value required for 'set' action", file=sys.stderr)
            sys.exit(1)

        # Parse value as JSON if possible
        try:
            parsed_value = json.loads(value)
        except json.JSONDecodeError:
            parsed_value = value

        # Support dot notation
        parts = key.split(".")
        current = workflow
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        current[parts[-1]] = parsed_value
        save_json(WORKFLOW_FILE, workflow)

        print(f"Set {key} = {parsed_value}")

    else:
        print(f"ERROR: Invalid action '{action}', use 'get' or 'set'", file=sys.stderr)
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "transition": (transition, 1),
        "checkpoint": (checkpoint, 2),
        "autopilot": (autopilot, 1),
        "show": (show, 0),
        "config": (config, 2),
    }

    if command not in commands:
        print(f"ERROR: Unknown command '{command}'", file=sys.stderr)
        print(f"Valid commands: {', '.join(commands.keys())}", file=sys.stderr)
        sys.exit(1)

    func, min_args = commands[command]

    # show() can take 0 or 1 args, config can take 2 or 3
    if command == "show":
        func(*args[:1])
    elif command == "config":
        if len(args) < min_args:
            print(f"ERROR: '{command}' requires at least {min_args} arguments", file=sys.stderr)
            sys.exit(1)
        func(*args[:3])
    else:
        if len(args) != min_args:
            print(f"ERROR: '{command}' requires exactly {min_args} arguments", file=sys.stderr)
            sys.exit(1)
        func(*args)


if __name__ == "__main__":
    main()
