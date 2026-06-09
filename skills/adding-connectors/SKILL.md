---
name: adding-connectors
description: How to add a new connector to the Skillid policy plugin
allowed-tools: "*"
---

# Adding a New Connector

Follow these steps to add a new connector (e.g., Slack, M365, Ramp) to the Skillid policy plugin.

## 1. Add policy section to `policy.yaml`

Add a new entry under `connectors:` following the pattern:

```yaml
connectors:
  <connector_id>:
    enabled: true
    # Connector-specific config...
    <resource_type>:
      <resource>_modes:
        default: "read_write"
        overrides:
          <KEY>: "blocked"
          <KEY>: "read_only"
      operations:
        allow_<op>: true
      confirmations:
        before_<op>: false
```

## 2. Create resolver at `hooks/connectors/<connector_id>.py`

Required structure:

```python
from registry import ConnectorResolver

# Map every MCP tool name to (resource_type, operation_type)
TOOL_OPERATIONS = {
    "mcp__<prefix>__<toolName>": ("<resource_type>", "<operation>"),
    # operation is one of: read, create, edit, delete, comment, ...
}

class MyResolver(ConnectorResolver):
    connector_id = "<connector_id>"
    tool_patterns = ["mcp__<prefix>__*"]

    def resolve_resource(self, tool_name, tool_input):
        # Return (resource_type, resource_key, operation_type)
        # resource_key = the key to look up in modes overrides
        # Return (None, None, None) if extraction fails (fail-closed)
        ...

    def get_modes_config(self, connector_config, resource_type):
        # Return dict with 'default' and 'overrides' keys
        ...

    def check_operation(self, connector_config, resource_type, operation_type):
        # Return (allowed: bool, needs_confirm: bool)
        ...

RESOLVER = MyResolver()
```

### Key rules for resolvers
- **Fail closed**: if you can't extract the resource key, return `(None, None, None)` — the generic enforcer will deny.
- **Map every tool**: list all tools from the MCP server in `TOOL_OPERATIONS`. Unknown tools in a matched connector get denied.
- **Extract resource keys from tool_input**: check the MCP server's tool schemas for field names (e.g., `projectKey`, `channelId`).

## 3. Update `hooks/hooks.json`

Add matchers for the new connector's tools:

```json
{
  "PreToolUse": [
    {
      "matcher": "mcp__<prefix>__.*",
      "hooks": [{"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/pre_tool_use.py"}]
    }
  ],
  "PostToolUse": [
    {
      "matcher": "<read tool names pipe-separated>",
      "hooks": [{"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/post_tool_read.py"}]
    }
  ]
}
```

## 4. Add a skill at `skills/<connector>-policy/SKILL.md`

Short summary of what's enforced. Follow the format in `skills/atlassian-policy/SKILL.md`. Keep under 600 tokens.

## 5. How to discover MCP tool names

Ask the agent to inspect the MCP server's tool list, or run:
```
/mcp
```
in Claude Code to see connected servers and their tools. Each tool has a name, description, and input schema — use these to build `TOOL_OPERATIONS` and the resource extraction logic.

## 6. Test

Run from the project root:
```bash
python3 -m pytest tests/ -v
```

Test with mock events that simulate tool calls for each mode (blocked, read_only, read_redacted, read_write) and each operation type.
