"""
Skillid hook runtime library.

Thin helper for Claude Code plugin hooks. Reads hook events from stdin,
emits JSON decisions to stdout. Copied into each plugin's hooks/ dir.
"""

import json
import sys
import os
import time
import urllib.request
from pathlib import Path

import yaml


def read_event() -> dict:
    """Parse hook input from stdin (Claude Code sends JSON)."""
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def emit(response: dict):
    """Write JSON response to stdout."""
    print(json.dumps(response), flush=True)


def emit_allow():
    """Permit the tool call."""
    emit({"permissionDecision": "allow"})


def emit_ask(reason: str, policy_id: str = ""):
    """Surface a confirmation prompt to the user."""
    emit({
        "permissionDecision": "ask",
        "reason": reason,
        "policyId": policy_id,
    })


def emit_deny(reason: str, policy_id: str = ""):
    """Block the tool call."""
    emit({
        "permissionDecision": "deny",
        "reason": reason,
        "policyId": policy_id,
    })


def emit_context(text: str):
    """Inject additional context into the model's next turn."""
    emit({"additionalContext": text})


def emit_modified_output(new_output):
    """For PostToolUse: rewrite the tool output (used for redaction)."""
    emit({"modifiedOutput": new_output})


def load_policy() -> dict:
    """Load policy.yaml from the plugin root."""
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    policy_path = os.path.join(plugin_root, "policy.yaml")
    with open(policy_path, "r") as f:
        return yaml.safe_load(f)


def resource_mode(modes_config: dict, resource_key: str) -> str:
    """Resolve the access mode for a resource key.

    Args:
        modes_config: dict with 'default' and 'overrides' keys
        resource_key: the project/space/channel key to look up

    Returns:
        One of: read_write, read_only, read_redacted, blocked
    """
    overrides = modes_config.get("overrides", {})
    return overrides.get(resource_key, modes_config.get("default", "read_write"))


def is_write_operation(operation_type: str) -> bool:
    """Check if an operation type is a write operation."""
    return operation_type in ("create", "edit", "delete", "transition",
                              "assign", "comment", "priority_change",
                              "set_public", "publish", "bulk")


def audit(policy_id: str, decision: str, event: dict,
          policy: dict = None, extra: dict = None):
    """Send audit event to configured destination. Never blocks hook decision."""
    try:
        if policy is None:
            policy = load_policy()

        audit_config = policy.get("org", {}).get("audit", {})
        mode = audit_config.get("mode", "none")

        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "plugin": "skillid",
            "policyId": policy_id,
            "decision": decision,
            "tool": event.get("tool_name", ""),
            "extra": extra or {},
        }

        if mode == "file":
            log_path = os.path.expanduser(audit_config.get("log_path", "~/.skillid/audit.log"))
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a") as f:
                f.write(json.dumps(record) + "\n")

        elif mode == "http_post":
            endpoint = audit_config.get("endpoint")
            if endpoint:
                req = urllib.request.Request(
                    endpoint,
                    data=json.dumps(record).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=3)

        elif mode == "stdout":
            print(json.dumps(record), file=sys.stderr)

    except Exception as e:
        # Audit failure never blocks policy decision
        print(f"[skillid] audit error: {e}", file=sys.stderr)
