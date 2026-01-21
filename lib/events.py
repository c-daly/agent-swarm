"""Minimal event callbacks. Not pub/sub, just hooks.

Usage:
    from events import on, emit

    # Register listener
    on("agent:spawned", lambda e: print(f"Agent {e['agent_id']} started"))

    # Emit event
    emit("agent:spawned", {"agent_id": "abc123", "description": "Fix bug"})
"""

from typing import Callable, Any
from collections import defaultdict

_listeners: dict[str, list[Callable]] = defaultdict(list)


def on(event: str, callback: Callable) -> None:
    """Register callback for event."""
    _listeners[event].append(callback)


def off(event: str, callback: Callable) -> None:
    """Unregister callback for event."""
    if callback in _listeners[event]:
        _listeners[event].remove(callback)


def emit(event: str, data: Any = None) -> None:
    """Fire callbacks for event. Errors in listeners don't break emitter."""
    for cb in _listeners[event]:
        try:
            cb(data)
        except Exception:
            pass


def clear(event: str = None) -> None:
    """Clear listeners. If event specified, clear only that event."""
    if event:
        _listeners[event].clear()
    else:
        _listeners.clear()
