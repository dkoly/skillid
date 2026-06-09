#!/usr/bin/env python3
"""
Skillid PreToolUse hook — generic policy enforcer.

Reads the tool call from stdin, resolves the connector + resource,
checks policy, and emits allow/ask/deny.

Fail-closed: if resource extraction fails, denies the call.
"""

import sys
import os

# Ensure hooks dir is on path
_hooks_dir = os.path.dirname(os.path.abspath(__file__))
if _hooks_dir not in sys.path:
    sys.path.insert(0, _hooks_dir)

from runtime import read_event, emit_allow, emit_ask, emit_deny, emit_context, load_policy, resource_mode, is_write_operation, audit
from registry import find_connector


def main():
    event = read_event()
    if not event:
        emit_allow()
        return

    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})

    # Find matching connector
    connector = find_connector(tool_name)
    if not connector:
        # No connector registered for this tool — allow (not our jurisdiction)
        emit_allow()
        return

    # Load policy
    policy = load_policy()
    connector_config = policy.get("connectors", {}).get(connector.connector_id, {})

    if not connector_config.get("enabled", True):
        emit_allow()
        return

    # Resolve resource
    resource_type, resource_key, operation_type = connector.resolve_resource(tool_name, tool_input)

    if resource_type is None:
        # Unknown tool in a known connector — fail closed
        audit("unknown_tool", "deny", event, policy,
              {"tool": tool_name, "connector": connector.connector_id})
        emit_deny(
            f"Unknown {connector.connector_id} tool: {tool_name}. "
            "Update connector-spec or contact security team.",
            policy_id=f"{connector.connector_id}.unknown_tool"
        )
        return

    # Check resource mode
    if resource_key:
        modes_config = connector.get_modes_config(connector_config, resource_type)
        mode = resource_mode(modes_config, resource_key)
    else:
        # Couldn't extract resource key.
        # Allow explicit list/enumeration operations, but deny unscoped reads because they can
        # search or fetch across blocked/redacted resources before PostToolUse can redact.
        if operation_type == "list":
            audit(f"{connector.connector_id}.{resource_type}.list", "allow", event, policy)
            emit_allow()
            return
        if operation_type == "read":
            audit(f"{connector.connector_id}.{resource_type}.unresolved_read", "deny", event, policy)
            emit_deny(
                f"Could not determine target {resource_type} for read operation. "
                "Add an explicit project/space filter so policy can be enforced.",
                policy_id=f"{connector.connector_id}.{resource_type}.unresolved_read"
            )
            return

        audit(f"{connector.connector_id}.{resource_type}.unresolved_write", "deny", event, policy,
              {"operation": operation_type})
        emit_deny(
            f"Could not determine target {resource_type} for {operation_type} operation. "
            "Add an explicit project/space key so policy can be enforced.",
            policy_id=f"{connector.connector_id}.{resource_type}.unresolved_write"
        )
        return

    # Enforce resource mode
    policy_id_base = f"{connector.connector_id}.{resource_type}.{resource_key}"

    if mode == "blocked":
        audit(f"{policy_id_base}.blocked", "deny", event, policy)
        emit_deny(
            f"Access to {resource_type} '{resource_key}' is blocked by org policy. "
            f"Contact {policy.get('org', {}).get('escalation_contact', 'security team')}.",
            policy_id=f"{policy_id_base}.blocked"
        )
        return

    if mode == "read_only" and is_write_operation(operation_type):
        audit(f"{policy_id_base}.read_only_write", "deny", event, policy,
              {"operation": operation_type})
        emit_deny(
            f"{resource_type.capitalize()} '{resource_key}' is read-only. "
            f"Write operation '{operation_type}' is not permitted.",
            policy_id=f"{policy_id_base}.read_only"
        )
        return

    if mode == "read_redacted" and is_write_operation(operation_type):
        audit(f"{policy_id_base}.redacted_write", "deny", event, policy,
              {"operation": operation_type})
        emit_deny(
            f"{resource_type.capitalize()} '{resource_key}' is read-redacted. "
            f"Write operations are not permitted.",
            policy_id=f"{policy_id_base}.read_redacted"
        )
        return

    # Resource mode allows — now check operation-level permissions
    allowed, needs_confirm = connector.check_operation(connector_config, resource_type, operation_type)

    if not allowed:
        audit(f"{policy_id_base}.{operation_type}_denied", "deny", event, policy)
        emit_deny(
            f"Operation '{operation_type}' on {resource_type} is disabled by org policy.",
            policy_id=f"{connector.connector_id}.{resource_type}.{operation_type}"
        )
        return

    # Check global destructive ops confirmation
    global_policy = policy.get("policy", {})
    if operation_type == "delete" and global_policy.get("destructive_ops_require_confirm", True):
        needs_confirm = True

    if needs_confirm:
        audit(f"{policy_id_base}.{operation_type}_ask", "ask", event, policy)
        emit_ask(
            f"Org policy requires confirmation before '{operation_type}' "
            f"on {resource_type} '{resource_key}'.",
            policy_id=f"{connector.connector_id}.{resource_type}.{operation_type}.confirm"
        )
        return

    # All checks passed
    audit(f"{policy_id_base}.{operation_type}_allow", "allow", event, policy)
    emit_allow()


if __name__ == "__main__":
    main()
