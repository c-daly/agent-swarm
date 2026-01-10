"""
Hierarchical Context System

Provides layered, scoped context management for Claude agents with
memory distillation capabilities.
"""

from .resolver import (
    resolve_context,
    get_agent_context,
    show_context_tree,
    AggregatedContext,
    ContextLayer,
)

from .memory import (
    Memory,
    Episode,
    Pattern,
    Distiller,
    EpisodeStore,
    log_episode,
    trigger_distillation,
)

__all__ = [
    # Resolver
    'resolve_context',
    'get_agent_context',
    'show_context_tree',
    'AggregatedContext',
    'ContextLayer',
    # Memory
    'Memory',
    'Episode',
    'Pattern',
    'Distiller',
    'EpisodeStore',
    'log_episode',
    'trigger_distillation',
]
