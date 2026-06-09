# Skillid — Project Instructions for Claude Code

This is a Claude Code plugin that enforces org-level agent guardrails via policy-driven hooks and skills.

## Architecture

- **`policy.yaml`** — single source of truth. All rules are data, not code.
- **`hooks/`** — Python scripts that fire on Claude Code tool calls (PreToolUse / PostToolUse).
  - `runtime.py` — shared helper: reads stdin events, emits JSON decisions, handles audit.
  - `registry.py` — auto-discovers connector resolvers from `hooks/connectors/`.
  - `pre_tool_use.py` — generic enforcer for all connectors. One script, not per-tool.
  - `post_tool_read.py` — redacts tool output for `read_redacted` resources.
  - `connectors/<name>.py` — per-connector resolver. Extracts resource keys from tool inputs, maps tool names to operations.
- **`skills/`** — Claude Code skills (SKILL.md files). Guidance the model sees in context.
- **`.claude-plugin/plugin.json`** — plugin metadata.

## Key design principles

1. **Fail-closed**: unknown tools in a known connector → denied. Can't extract resource key on a write → ask for confirmation.
2. **Single generic hook**: `pre_tool_use.py` handles all connectors via the registry. Don't create per-tool hook scripts.
3. **Policy as data**: all rules live in `policy.yaml`. Hook logic is generic.
4. **Skills are concise**: under 600 tokens each. Model gets awareness; hooks do enforcement.
5. **Adding a connector** = add YAML section + one resolver file in `hooks/connectors/`. See `skills/adding-connectors/SKILL.md`.

## Resource modes

| Mode | Reads | Writes | Model sees content? |
|------|-------|--------|---------------------|
| `read_write` | ✅ | ✅ | Yes |
| `read_only` | ✅ | ❌ denied | Yes |
| `read_redacted` | ✅ (redacted) | ❌ denied | No — replaced with [REDACTED] |
| `blocked` | ❌ denied | ❌ denied | No |

## Testing

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -v
```

Integration tests run hooks as subprocesses with temp policy files — no mocking of stdin/stdout needed.

## Important: don't put secrets in policy.yaml

`policy.yaml` is committed to git. It contains policy rules, not credentials. Audit endpoints, org names, and escalation contacts are fine. Tokens, passwords, and API keys are not.
