"""Recovery mode bypass for enforcement debugging.

When enforcement code itself is broken, this provides a way to bypass
restrictions so the enforcement can be fixed.

Usage:
    - Set AGENT_RECOVERY=1 environment variable, OR
    - Run enter_recovery("reason") to enable via state, OR
    - Use /recover skill

Recovery mode auto-expires after RECOVERY_TIMEOUT_MINUTES to prevent
accidental permanent bypass.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# Add lib/ to path for agent_state import
import sys
sys.path.insert(0, str(Path(__file__).parent))

# Import agent_state module for per-agent state isolation
from agent_state import load_state, save_state

# State management
STATE_DIR = Path.home() / ".claude" / "plugins" / "agent-swarm" / ".state"
AUDIT_LOG = STATE_DIR / "recovery_audit.log"

# Recovery times out after this many minutes (safety)
RECOVERY_TIMEOUT_MINUTES = 30


def _load_state() -> dict[str, Any]:
    """Load session state from file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return load_state()


def _save_state(state: dict[str, Any]) -> None:
    """Save session state to file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    save_state(state)


def _log_audit(action: str, reason: str = "") -> None:
    """Log recovery actions for audit trail."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat()
    entry = f"[{timestamp}] {action}: {reason}\n"
    with open(AUDIT_LOG, "a") as f:
        f.write(entry)


def _check_timeout(entered_str: str) -> bool:
    """Check if recovery has timed out.
    
    Returns True if still valid, False if expired.
    """
    try:
        entered = datetime.fromisoformat(entered_str)
        expiry = entered + timedelta(minutes=RECOVERY_TIMEOUT_MINUTES)
        return datetime.now() < expiry
    except (ValueError, TypeError):
        return False


def is_recovery_mode() -> bool:
    """Check if recovery mode is currently active.
    
    Recovery mode can be enabled via:
    1. AGENT_RECOVERY=1 environment variable (immediate, no timeout)
    2. State flag set by enter_recovery() (with timeout)
    
    Returns:
        True if recovery mode is active, False otherwise.
    """
    # Check environment variable first (takes precedence)
    if os.environ.get("AGENT_RECOVERY") == "1":
        return True
    
    # Check state flag
    state = _load_state()
    if not state.get("recovery_mode"):
        return False
    
    # Check timeout
    entered = state.get("recovery_entered")
    if not entered:
        return False
    
    if not _check_timeout(entered):
        # Expired - auto-clear
        state["recovery_mode"] = False
        state["recovery_expired"] = datetime.now().isoformat()
        _save_state(state)
        _log_audit("EXPIRED", f"Recovery timed out after {RECOVERY_TIMEOUT_MINUTES} minutes")
        return False
    
    return True


def enter_recovery(reason: str) -> None:
    """Enable recovery mode with reason for audit.
    
    Args:
        reason: Why recovery mode is being enabled (for audit log)
    """
    state = _load_state()
    state["recovery_mode"] = True
    state["recovery_reason"] = reason
    state["recovery_entered"] = datetime.now().isoformat()
    # Clear any previous exit time
    state.pop("recovery_exited", None)
    state.pop("recovery_expired", None)
    _save_state(state)
    _log_audit("ENTER", reason)


def exit_recovery() -> None:
    """Disable recovery mode."""
    state = _load_state()
    state["recovery_mode"] = False
    state["recovery_exited"] = datetime.now().isoformat()
    _save_state(state)
    _log_audit("EXIT", "Recovery mode disabled")


def get_recovery_state() -> Optional[dict[str, Any]]:
    """Get current recovery state for display.
    
    Returns:
        Dict with reason, entered time, etc. if in recovery mode.
        None if not in recovery mode.
    """
    if not is_recovery_mode():
        return None
    
    # Check if via env var
    if os.environ.get("AGENT_RECOVERY") == "1":
        return {
            "reason": "Environment variable AGENT_RECOVERY=1",
            "entered": "N/A (env var)",
            "source": "environment",
        }
    
    # From state
    state = _load_state()
    return {
        "reason": state.get("recovery_reason", "Unknown"),
        "entered": state.get("recovery_entered", "Unknown"),
        "source": "state",
    }


def format_recovery_status() -> str:
    """Format recovery status for display."""
    recovery_state = get_recovery_state()
    if not recovery_state:
        return "[RECOVERY] Not active"
    
    return (
        f"[RECOVERY] ⚠️ ACTIVE\n"
        f"  Reason: {recovery_state['reason']}\n"
        f"  Since: {recovery_state['entered']}\n"
        f"  Source: {recovery_state['source']}\n"
        f"  Timeout: {RECOVERY_TIMEOUT_MINUTES} minutes"
    )
