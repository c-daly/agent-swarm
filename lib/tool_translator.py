"""Tool Translation Layer for MCP Router.

Translates native Claude tools to their MCP-proxied equivalents,
ensuring all tool calls flow through the router for permission enforcement.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ToolMapping:
    """Defines how a native tool maps to an MCP tool.

    Attributes:
        native_name: The native Claude tool name (e.g., "Read")
        mcp_name: The MCP tool name (e.g., "mcp__router__native__read_file")
        arg_map: Dict mapping native arg names to MCP arg names
        transform: Optional callable to transform args beyond simple renaming
    """
    native_name: str
    mcp_name: str
    arg_map: dict[str, str] = field(default_factory=dict)
    transform: Optional[Callable[[dict], dict]] = None

    def translate_args(self, args: dict) -> dict:
        """Translate arguments from native format to MCP format."""
        result = {}

        for native_key, value in args.items():
            # Skip metadata fields (passed through unchanged)
            if native_key.startswith("_"):
                result[native_key] = value
                continue

            # Map to MCP arg name if defined, otherwise pass through
            mcp_key = self.arg_map.get(native_key, native_key)
            result[mcp_key] = value

        # Apply custom transformation if defined
        if self.transform:
            result = self.transform(result)

        return result


class ToolTranslator:
    """Translates native Claude tools to MCP-proxied equivalents.

    This ensures all tool calls flow through the router for:
    - Permission enforcement
    - Telemetry tracking
    - Audit logging

    Usage:
        translator = ToolTranslator()
        mcp_tool, mcp_args = translator.translate("Read", {"file_path": "/tmp/x"})
    """

    # Default mappings for native tools -> MCP tools
    DEFAULT_MAPPINGS: list[ToolMapping] = [
        ToolMapping(
            native_name="Read",
            mcp_name="mcp__router__native__read_file",
            arg_map={
                "file_path": "file_path",
                "offset": "offset",
                "limit": "limit",
            },
        ),
        ToolMapping(
            native_name="Write",
            mcp_name="mcp__router__native__write_file",
            arg_map={
                "file_path": "file_path",
                "content": "content",
            },
        ),
        ToolMapping(
            native_name="Edit",
            mcp_name="mcp__router__native__edit_file",
            arg_map={
                "file_path": "file_path",
                "old_string": "old_string",
                "new_string": "new_string",
                "replace_all": "replace_all",
            },
        ),
        ToolMapping(
            native_name="Glob",
            mcp_name="mcp__router__native__glob",
            arg_map={
                "pattern": "pattern",
                "path": "path",
            },
        ),
        ToolMapping(
            native_name="Grep",
            mcp_name="mcp__router__native__grep",
            arg_map={
                "pattern": "pattern",
                "path": "path",
                "glob": "file_glob",
                "output_mode": "output_mode",
                "-i": "case_insensitive",
            },
        ),
        ToolMapping(
            native_name="Bash",
            mcp_name="mcp__router__native__bash",
            arg_map={
                "command": "command",
                "timeout": "timeout",
                "description": "description",
            },
        ),
    ]

    def __init__(self, mappings: Optional[list[ToolMapping]] = None):
        """Initialize with optional custom mappings.

        Args:
            mappings: Custom tool mappings. If None, uses DEFAULT_MAPPINGS.
        """
        self._mappings: dict[str, ToolMapping] = {}

        # Load default mappings
        for mapping in self.DEFAULT_MAPPINGS:
            self._mappings[mapping.native_name] = mapping

        # Override with custom mappings if provided
        if mappings:
            for mapping in mappings:
                self._mappings[mapping.native_name] = mapping

    def register(self, mapping: ToolMapping) -> None:
        """Register a new tool mapping.

        Args:
            mapping: The tool mapping to register.
        """
        self._mappings[mapping.native_name] = mapping

    def unregister(self, native_name: str) -> Optional[ToolMapping]:
        """Unregister a tool mapping.

        Args:
            native_name: The native tool name to unregister.

        Returns:
            The removed mapping, or None if not found.
        """
        return self._mappings.pop(native_name, None)

    def has_mapping(self, tool_name: str) -> bool:
        """Check if a tool has a translation mapping.

        Args:
            tool_name: The tool name to check.

        Returns:
            True if the tool has a mapping, False otherwise.
        """
        return tool_name in self._mappings

    def get_mapping(self, tool_name: str) -> Optional[ToolMapping]:
        """Get the mapping for a tool.

        Args:
            tool_name: The native tool name.

        Returns:
            The ToolMapping if found, None otherwise.
        """
        return self._mappings.get(tool_name)

    def translate(
        self,
        tool_name: str,
        args: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Translate a native tool call to MCP format.

        Args:
            tool_name: The native tool name.
            args: The native tool arguments.

        Returns:
            Tuple of (mcp_tool_name, mcp_args).
            If no mapping exists, returns the original tool and args.
        """
        mapping = self._mappings.get(tool_name)

        if mapping is None:
            # No translation needed - pass through
            return tool_name, args

        mcp_args = mapping.translate_args(args)
        return mapping.mcp_name, mcp_args

    def reverse_lookup(self, mcp_name: str) -> Optional[str]:
        """Find the native tool name for an MCP tool.

        Args:
            mcp_name: The MCP tool name.

        Returns:
            The native tool name if found, None otherwise.
        """
        for native_name, mapping in self._mappings.items():
            if mapping.mcp_name == mcp_name:
                return native_name
        return None

    def list_mappings(self) -> dict[str, str]:
        """List all registered mappings.

        Returns:
            Dict mapping native names to MCP names.
        """
        return {
            native: mapping.mcp_name
            for native, mapping in self._mappings.items()
        }


# Singleton instance for convenience
_default_translator: Optional[ToolTranslator] = None


def get_translator() -> ToolTranslator:
    """Get the default translator instance."""
    global _default_translator
    if _default_translator is None:
        _default_translator = ToolTranslator()
    return _default_translator


def translate_tool(
    tool_name: str,
    args: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Convenience function to translate a tool call.

    Args:
        tool_name: The native tool name.
        args: The native tool arguments.

    Returns:
        Tuple of (mcp_tool_name, mcp_args).
    """
    return get_translator().translate(tool_name, args)
