"""Tests for centralized configuration loading."""
import json
import pytest
from pathlib import Path
from tempfile import NamedTemporaryFile


class TestBackendConfig:
    """Tests for the BackendConfig dataclass."""

    def test_backend_config_required_fields(self):
        """BackendConfig requires name and command."""
        from lib.config import BackendConfig
        
        config = BackendConfig(name="test", command=["python", "-m", "test"])
        assert config.name == "test"
        assert config.command == ["python", "-m", "test"]

    def test_backend_config_default_values(self):
        """BackendConfig should have sensible defaults."""
        from lib.config import BackendConfig
        
        config = BackendConfig(name="test", command=["echo"])
        assert config.tool_prefix == ""
        assert config.max_concurrent == 10
        assert config.request_timeout == 60.0
        assert config.pool_size == 2

    def test_backend_config_custom_values(self):
        """BackendConfig should accept custom values."""
        from lib.config import BackendConfig
        
        config = BackendConfig(
            name="custom",
            command=["node", "server.js"],
            tool_prefix="custom__",
            max_concurrent=5,
            request_timeout=30.0,
            pool_size=4,
        )
        assert config.tool_prefix == "custom__"
        assert config.max_concurrent == 5
        assert config.request_timeout == 30.0
        assert config.pool_size == 4

    def test_backend_config_is_immutable(self):
        """BackendConfig should be frozen (immutable)."""
        from lib.config import BackendConfig
        
        config = BackendConfig(name="test", command=["echo"])
        with pytest.raises(AttributeError):
            config.name = "changed"


class TestLoadBackends:
    """Tests for the load_backends function."""

    def test_load_backends_from_valid_json(self):
        """load_backends should parse valid JSON config."""
        from lib.config import load_backends, BackendConfig
        
        config_data = {
            "serena": {
                "command": ["python", "-m", "serena"],
                "tool_prefix": "serena__"
            }
        }
        
        with NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()
            
            backends = load_backends(Path(f.name))
            
        assert "serena" in backends
        assert isinstance(backends["serena"], BackendConfig)
        assert backends["serena"].command == ["python", "-m", "serena"]
        assert backends["serena"].tool_prefix == "serena__"

    def test_load_backends_with_all_options(self):
        """load_backends should parse all config options."""
        from lib.config import load_backends
        
        config_data = {
            "fast": {
                "command": ["fast-server"],
                "tool_prefix": "fast__",
                "max_concurrent": 20,
                "request_timeout": 30.0,
                "pool_size": 4
            }
        }
        
        with NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()
            
            backends = load_backends(Path(f.name))
            
        assert backends["fast"].max_concurrent == 20
        assert backends["fast"].request_timeout == 30.0
        assert backends["fast"].pool_size == 4

    def test_load_backends_missing_file_returns_empty(self):
        """load_backends should return empty dict for missing file."""
        from lib.config import load_backends
        
        result = load_backends(Path("/nonexistent/config.json"))
        assert result == {}

    def test_load_backends_invalid_json_raises(self):
        """load_backends should raise ConfigValidationError for invalid JSON."""
        from lib.config import load_backends, ConfigValidationError
        
        with NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("not valid json {{{")
            f.flush()
            
            with pytest.raises(ConfigValidationError):
                load_backends(Path(f.name))

    def test_load_backends_missing_command_raises(self):
        """load_backends should raise ConfigValidationError if command is missing."""
        from lib.config import load_backends, ConfigValidationError
        
        config_data = {
            "bad": {
                "tool_prefix": "bad__"
                # missing command
            }
        }
        
        with NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()
            
            with pytest.raises(ConfigValidationError, match="command"):
                load_backends(Path(f.name))

    def test_load_backends_invalid_max_concurrent_raises(self):
        """load_backends should raise ConfigValidationError for invalid max_concurrent."""
        from lib.config import load_backends, ConfigValidationError
        
        config_data = {
            "bad": {
                "command": ["test"],
                "max_concurrent": 0  # must be positive
            }
        }
        
        with NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()
            
            with pytest.raises(ConfigValidationError, match="max_concurrent"):
                load_backends(Path(f.name))

    def test_load_backends_multiple_backends(self):
        """load_backends should handle multiple backends."""
        from lib.config import load_backends
        
        config_data = {
            "serena": {"command": ["serena"]},
            "context7": {"command": ["context7"]},
            "playwright": {"command": ["playwright"]}
        }
        
        with NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()
            
            backends = load_backends(Path(f.name))
            
        assert len(backends) == 3
        assert all(name in backends for name in ["serena", "context7", "playwright"])
