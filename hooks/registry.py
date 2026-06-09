"""
Connector registry and resource resolvers.

Each connector has:
- tool_patterns: list of glob patterns matching MCP tool names
- resolve_resource(tool_name, tool_input) -> (resource_type, resource_key, operation_type)
- get_modes_config(connector_config, resource_type) -> modes dict with default + overrides
- check_operation(connector_config, resource_type, operation_type) -> (allowed, needs_confirm)

To add a new connector:
1. Add its section to policy.yaml under connectors:
2. Add a resolver module in hooks/connectors/<name>.py
3. Register it in CONNECTORS below
"""

import fnmatch
import importlib
import os
import sys

# Ensure hooks dir is on path for imports
_hooks_dir = os.path.dirname(os.path.abspath(__file__))
if _hooks_dir not in sys.path:
    sys.path.insert(0, _hooks_dir)


class ConnectorResolver:
    """Base class for connector resolvers."""

    connector_id: str = ""
    tool_patterns: list = []

    def matches_tool(self, tool_name: str) -> bool:
        """Check if a tool name matches this connector."""
        return any(fnmatch.fnmatch(tool_name, p) for p in self.tool_patterns)

    def resolve_resource(self, tool_name: str, tool_input: dict) -> tuple:
        """Extract resource info from a tool call.

        Returns:
            (resource_type, resource_key, operation_type)
            resource_type: e.g. 'jira_project', 'confluence_space'
            resource_key: e.g. 'LEGAL', 'HR'
            operation_type: e.g. 'create', 'edit', 'delete', 'read'

            Returns (None, None, None) if extraction fails -> fail-closed.
        """
        raise NotImplementedError

    def get_modes_config(self, connector_config: dict, resource_type: str) -> dict:
        """Get the modes config (default + overrides) for a resource type."""
        raise NotImplementedError

    def check_operation(self, connector_config: dict, resource_type: str,
                        operation_type: str) -> tuple:
        """Check if an operation is allowed and whether it needs confirmation.

        Returns:
            (allowed: bool, needs_confirm: bool)
        """
        raise NotImplementedError


def _load_connector_modules():
    """Dynamically load all connector modules from hooks/connectors/."""
    connectors_dir = os.path.join(_hooks_dir, "connectors")
    resolvers = []

    if not os.path.isdir(connectors_dir):
        return resolvers

    for fname in os.listdir(connectors_dir):
        if fname.endswith(".py") and not fname.startswith("_"):
            module_name = f"connectors.{fname[:-3]}"
            try:
                mod = importlib.import_module(module_name)
                if hasattr(mod, "RESOLVER"):
                    resolvers.append(mod.RESOLVER)
            except Exception as e:
                print(f"[skillid] failed to load connector {fname}: {e}", file=sys.stderr)

    return resolvers


# Loaded once at import time
CONNECTORS: list = _load_connector_modules()


def find_connector(tool_name: str):
    """Find the connector resolver matching a tool name. Returns None if no match."""
    for connector in CONNECTORS:
        if connector.matches_tool(tool_name):
            return connector
    return None
