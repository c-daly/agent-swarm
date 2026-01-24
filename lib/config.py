#!/usr/bin/env python3
"""Centralized configuration loading for MCP router.

Provides BackendConfig dataclass and load_backends() function
for loading and validating backend configurations.
"""

import json
from dataclasses import dataclass
from pathlib import Path


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""
    pass


@dataclass(frozen=True)
class BackendConfig:
    """Configuration for a single MCP backend.
    
    Attributes:
        name: Unique backend identifier
        command: Subprocess command to spawn the backend
        tool_prefix: Prefix for tool names from this backend
        max_concurrent: Maximum concurrent requests to this backend
        request_timeout: Timeout in seconds for individual requests
        pool_size: Number of connections to maintain per backend
    """
    name: str
    command: list[str]
    tool_prefix: str = ""
    max_concurrent: int = 10
    request_timeout: float = 60.0
    pool_size: int = 2


def load_backends(config_path: Path) -> dict[str, BackendConfig]:
    """Load backend configurations from a JSON file.
    
    Args:
        config_path: Path to backends.json file
        
    Returns:
        Dictionary mapping backend names to BackendConfig objects
        
    Raises:
        ConfigValidationError: If JSON is invalid or required fields missing
    """
    if not config_path.exists():
        return {}
    
    try:
        content = config_path.read_text()
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ConfigValidationError(f"Invalid JSON in {config_path}: {e}")
    
    backends: dict[str, BackendConfig] = {}
    
    for name, cfg in data.items():
        # Validate required fields
        if "command" not in cfg:
            raise ConfigValidationError(
                f"Backend '{name}' missing required field 'command'"
            )
        
        # Validate optional fields if present
        if "max_concurrent" in cfg:
            if not isinstance(cfg["max_concurrent"], int) or cfg["max_concurrent"] < 1:
                raise ConfigValidationError(
                    f"Backend '{name}': max_concurrent must be a positive integer"
                )
        
        if "request_timeout" in cfg:
            timeout = cfg["request_timeout"]
            if not isinstance(timeout, (int, float)) or timeout <= 0:
                raise ConfigValidationError(
                    f"Backend '{name}': request_timeout must be a positive number"
                )
        
        if "pool_size" in cfg:
            if not isinstance(cfg["pool_size"], int) or cfg["pool_size"] < 1:
                raise ConfigValidationError(
                    f"Backend '{name}': pool_size must be a positive integer"
                )
        
        # Build config with defaults
        backends[name] = BackendConfig(
            name=name,
            command=cfg["command"],
            tool_prefix=cfg.get("tool_prefix", ""),
            max_concurrent=cfg.get("max_concurrent", 10),
            request_timeout=cfg.get("request_timeout", 60.0),
            pool_size=cfg.get("pool_size", 2),
        )
    
    return backends
