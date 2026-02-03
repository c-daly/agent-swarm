"""Backwards compatibility redirect to protocol_assembly.py."""

from lib.protocol_assembly import (
    UNIVERSAL_PROTOCOL,
    AGENT_PROTOCOL,
    SUBAGENT_PROTOCOL,
    ROLE_PROTOCOLS,
    DEFAULT_ROLE,
    get_role_protocol,
    assemble_agent_briefing,
    assemble_subagent_briefing,
    estimate_tokens,
    # Old names
    COMPRESSED_PROTOCOLS,
    DEFAULT_PROTOCOL,
    get_compressed_protocol,
    generate_agent_briefing,
)

__all__ = [
    "UNIVERSAL_PROTOCOL",
    "AGENT_PROTOCOL", 
    "SUBAGENT_PROTOCOL",
    "ROLE_PROTOCOLS",
    "DEFAULT_ROLE",
    "get_role_protocol",
    "assemble_agent_briefing",
    "assemble_subagent_briefing",
    "estimate_tokens",
    "COMPRESSED_PROTOCOLS",
    "DEFAULT_PROTOCOL",
    "get_compressed_protocol",
    "generate_agent_briefing",
]
