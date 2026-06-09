#!/usr/bin/env python3
"""
Skillid PostToolUse hook — handles redaction for read_redacted resources.

Fires after read operations. If the resource is in read_redacted mode,
replaces the tool output with a redaction placeholder.
"""

import sys
import os

_hooks_dir = os.path.dirname(os.path.abspath(__file__))
if _hooks_dir not in sys.path:
    sys.path.insert(0, _hooks_dir)

from runtime import read_event, emit_allow, emit_modified_output, load_policy, resource_mode, audit
from registry import find_connector


def main():
    event = read_event()
    if not event:
        emit_allow()
        return

    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})

    connector = find_connector(tool_name)
    if not connector:
        return

    policy = load_policy()
    connector_config = policy.get("connectors", {}).get(connector.connector_id, {})

    resource_type, resource_key, operation_type = connector.resolve_resource(tool_name, tool_input)

    # Only redact reads
    if operation_type != "read" or not resource_key:
        return

    modes_config = connector.get_modes_config(connector_config, resource_type)
    mode = resource_mode(modes_config, resource_key)

    if mode == "read_redacted":
        audit(
            f"{connector.connector_id}.{resource_type}.{resource_key}.redacted",
            "redact", event, policy
        )
        emit_modified_output(
            f"[REDACTED — {resource_type} '{resource_key}' is classified as confidential. "
            f"Content has been redacted per org policy. "
            f"Contact {policy.get('org', {}).get('escalation_contact', 'security team')} "
            f"for access.]"
        )
        return

    # No redaction needed — don't emit anything (pass through)


if __name__ == "__main__":
    main()
