---
name: atlassian-policy
description: Atlassian Jira & Confluence guardrails
allowed-tools: "mcp__atlassian__*"
---

# Atlassian Policy

Policy hooks enforce these rules automatically. This skill provides awareness.

## Jira
- **Blocked projects** (no access): LEGAL, HR
- **Read-only projects**: SEC, FINEXEC
- Allowed: create issues, comment, transition. Confirm required before create/transition.
- **Not allowed**: assign, change priority, delete, bulk operations.

## Confluence
- **Blocked spaces** (no access): BOARD
- **Read-only spaces**: LEGAL, HR, FINEXEC
- **Redacted spaces** (content replaced on read): SEC
- Allowed: create pages, edit own pages, comment. Confirm required before create/publish.
- **Not allowed**: edit others' pages, delete, change permissions/public access.

## When hooks fire
Exact rules enforced by PreToolUse hooks at tool-call time. If denied, do not retry — contact security-team@acme.com.
