"""Tests for the Skillid hook runtime and Atlassian connector."""

import json
import os
import sys
import io
import pytest
from unittest.mock import patch, mock_open

# Add hooks dir to path
_hooks_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
sys.path.insert(0, _hooks_dir)

from runtime import resource_mode, is_write_operation, read_event, emit_allow, emit_deny, emit_ask
from connectors.atlassian import AtlassianResolver

RESOLVER = AtlassianResolver()


# ---------- runtime helpers ----------

class TestResourceMode:
    def test_default_mode(self):
        config = {"default": "read_write", "overrides": {"LEGAL": "blocked"}}
        assert resource_mode(config, "MYPROJECT") == "read_write"

    def test_override_mode(self):
        config = {"default": "read_write", "overrides": {"LEGAL": "blocked"}}
        assert resource_mode(config, "LEGAL") == "blocked"

    def test_empty_overrides(self):
        config = {"default": "read_only"}
        assert resource_mode(config, "ANY") == "read_only"

    def test_missing_default(self):
        config = {"overrides": {"X": "blocked"}}
        assert resource_mode(config, "Y") == "read_write"  # fallback


class TestIsWriteOperation:
    @pytest.mark.parametrize("op", ["create", "edit", "delete", "transition", "assign", "comment"])
    def test_write_ops(self, op):
        assert is_write_operation(op) is True

    def test_read_is_not_write(self):
        assert is_write_operation("read") is False

    def test_unknown_is_not_write(self):
        assert is_write_operation("foobar") is False


class TestEmitFunctions:
    def test_emit_allow(self, capsys):
        emit_allow()
        out = json.loads(capsys.readouterr().out.strip())
        assert out == {"permissionDecision": "allow"}

    def test_emit_deny(self, capsys):
        emit_deny("blocked", "test.policy")
        out = json.loads(capsys.readouterr().out.strip())
        assert out["permissionDecision"] == "deny"
        assert out["reason"] == "blocked"
        assert out["policyId"] == "test.policy"

    def test_emit_ask(self, capsys):
        emit_ask("confirm?", "test.confirm")
        out = json.loads(capsys.readouterr().out.strip())
        assert out["permissionDecision"] == "ask"


# ---------- Atlassian resolver ----------

class TestAtlassianResolverMatching:
    def test_matches_atlassian_tools(self):
        assert RESOLVER.matches_tool("mcp__atlassian__getJiraIssue") is True
        assert RESOLVER.matches_tool("mcp__atlassian__createConfluencePage") is True

    def test_no_match_other_tools(self):
        assert RESOLVER.matches_tool("mcp__slack__postMessage") is False
        assert RESOLVER.matches_tool("Read") is False


class TestAtlassianResolveResource:
    def test_jira_issue_key(self):
        res_type, key, op = RESOLVER.resolve_resource(
            "mcp__atlassian__getJiraIssue",
            {"issueIdOrKey": "LEGAL-123"}
        )
        assert res_type == "jira"
        assert key == "LEGAL"
        assert op == "read"

    def test_jira_project_key_direct(self):
        res_type, key, op = RESOLVER.resolve_resource(
            "mcp__atlassian__createJiraIssue",
            {"projectKey": "HR"}
        )
        assert res_type == "jira"
        assert key == "HR"
        assert op == "create"

    def test_jira_jql_extraction(self):
        res_type, key, op = RESOLVER.resolve_resource(
            "mcp__atlassian__searchJiraIssues",
            {"jql": "project = SEC AND status = Open"}
        )
        assert res_type == "jira"
        assert key == "SEC"
        assert op == "read"

    def test_jira_jql_multiple_projects_is_ambiguous(self):
        res_type, key, op = RESOLVER.resolve_resource(
            "mcp__atlassian__searchJiraIssues",
            {"jql": "project = OPEN OR project = LEGAL"}
        )
        assert res_type == "jira"
        assert key is None
        assert op == "read"

    def test_jira_jql_project_in_multiple_is_ambiguous(self):
        res_type, key, op = RESOLVER.resolve_resource(
            "mcp__atlassian__searchJiraIssues",
            {"jql": "project in (OPEN, LEGAL)"}
        )
        assert res_type == "jira"
        assert key is None
        assert op == "read"

    def test_jira_jql_or_query_is_ambiguous_even_with_one_project(self):
        res_type, key, op = RESOLVER.resolve_resource(
            "mcp__atlassian__searchJiraIssues",
            {"jql": "project = OPEN OR assignee = currentUser()"}
        )
        assert res_type == "jira"
        assert key is None
        assert op == "read"

    def test_confluence_space_key(self):
        res_type, key, op = RESOLVER.resolve_resource(
            "mcp__atlassian__getConfluencePage",
            {"spaceKey": "BOARD"}
        )
        assert res_type == "confluence"
        assert key == "BOARD"
        assert op == "read"

    def test_confluence_space_id_does_not_fallback_to_policy_key(self):
        res_type, key, op = RESOLVER.resolve_resource(
            "mcp__atlassian__getConfluencePage",
            {"spaceId": "12345"}
        )
        assert res_type == "confluence"
        assert key is None
        assert op == "read"

    def test_unknown_tool_returns_none(self):
        res_type, key, op = RESOLVER.resolve_resource(
            "mcp__atlassian__someFutureApi",
            {"foo": "bar"}
        )
        assert res_type is None

    def test_missing_resource_key(self):
        """When no resource key can be extracted, key is None."""
        res_type, key, op = RESOLVER.resolve_resource(
            "mcp__atlassian__listJiraProjects",
            {}
        )
        assert res_type == "jira"
        assert key is None
        assert op == "list"


class TestAtlassianModesConfig:
    CONNECTOR_CONFIG = {
        "jira": {
            "project_modes": {
                "default": "read_write",
                "overrides": {"LEGAL": "blocked", "SEC": "read_only"}
            }
        },
        "confluence": {
            "space_modes": {
                "default": "read_write",
                "overrides": {"BOARD": "blocked"}
            }
        }
    }

    def test_jira_modes(self):
        modes = RESOLVER.get_modes_config(self.CONNECTOR_CONFIG, "jira")
        assert modes["default"] == "read_write"
        assert modes["overrides"]["LEGAL"] == "blocked"

    def test_confluence_modes(self):
        modes = RESOLVER.get_modes_config(self.CONNECTOR_CONFIG, "confluence")
        assert modes["overrides"]["BOARD"] == "blocked"

    def test_unknown_resource_type(self):
        modes = RESOLVER.get_modes_config(self.CONNECTOR_CONFIG, "unknown")
        assert modes["default"] == "read_write"


class TestAtlassianCheckOperation:
    CONNECTOR_CONFIG = {
        "jira": {
            "operations": {
                "allow_create": True,
                "allow_delete": False,
                "allow_assign": False,
            },
            "confirmations": {
                "before_create": True,
                "before_transition": True,
            }
        },
        "confluence": {
            "operations": {
                "allow_create": True,
                "allow_delete": False,
                "allow_set_public": False,
            },
            "confirmations": {
                "before_create": True,
            }
        }
    }

    def test_jira_read_always_allowed(self):
        allowed, confirm = RESOLVER.check_operation(self.CONNECTOR_CONFIG, "jira", "read")
        assert allowed is True
        assert confirm is False

    def test_jira_create_allowed_with_confirm(self):
        allowed, confirm = RESOLVER.check_operation(self.CONNECTOR_CONFIG, "jira", "create")
        assert allowed is True
        assert confirm is True

    def test_jira_delete_denied(self):
        allowed, confirm = RESOLVER.check_operation(self.CONNECTOR_CONFIG, "jira", "delete")
        assert allowed is False

    def test_jira_assign_denied(self):
        allowed, confirm = RESOLVER.check_operation(self.CONNECTOR_CONFIG, "jira", "assign")
        assert allowed is False

    def test_confluence_delete_denied(self):
        allowed, confirm = RESOLVER.check_operation(self.CONNECTOR_CONFIG, "confluence", "delete")
        assert allowed is False

    def test_confluence_set_public_denied(self):
        allowed, confirm = RESOLVER.check_operation(self.CONNECTOR_CONFIG, "confluence", "set_public")
        assert allowed is False


# ---------- Integration: pre_tool_use logic ----------

class TestPreToolUseIntegration:
    """Test the full pre_tool_use decision chain with mock policy.

    Runs the hook as a subprocess with stdin/env to avoid module caching issues.
    """

    POLICY = {
        "org": {
            "name": "TestOrg",
            "escalation_contact": "sec@test.com",
            "audit": {"mode": "none"}
        },
        "policy": {
            "destructive_ops_require_confirm": True,
        },
        "connectors": {
            "atlassian": {
                "enabled": True,
                "jira": {
                    "project_modes": {
                        "default": "read_write",
                        "overrides": {
                            "LEGAL": "blocked",
                            "SEC": "read_only",
                            "FINEXEC": "read_redacted",
                        }
                    },
                    "operations": {
                        "allow_create": True,
                        "allow_delete": False,
                    },
                    "confirmations": {
                        "before_create": True,
                    }
                },
                "confluence": {
                    "space_modes": {
                        "default": "read_write",
                        "overrides": {"BOARD": "blocked"}
                    },
                    "operations": {"allow_create": True},
                    "confirmations": {"before_create": False}
                }
            }
        }
    }

    @pytest.fixture(autouse=True)
    def _write_test_policy(self, tmp_path):
        """Write test policy to a temp file and set env var."""
        self.policy_file = tmp_path / "policy.yaml"
        import yaml
        self.policy_file.write_text(yaml.dump(self.POLICY))
        self.plugin_root = tmp_path
        # Create a symlink or copy so pre_tool_use can find the policy
        self.hooks_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")

    def _run_hook(self, tool_name, tool_input):
        """Run pre_tool_use.py as a subprocess."""
        import subprocess
        event = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
        env = os.environ.copy()
        env["CLAUDE_PLUGIN_ROOT"] = str(self.plugin_root)
        result = subprocess.run(
            [sys.executable, os.path.join(self.hooks_dir, "pre_tool_use.py")],
            input=event, capture_output=True, text=True, env=env
        )
        if result.returncode != 0:
            raise RuntimeError(f"Hook failed: {result.stderr}")
        return json.loads(result.stdout.strip())

    def test_blocked_project_denied(self):
        result = self._run_hook("mcp__atlassian__getJiraIssue", {"issueIdOrKey": "LEGAL-42"})
        assert result["permissionDecision"] == "deny"
        assert "blocked" in result["reason"].lower()

    def test_read_only_read_allowed(self):
        result = self._run_hook("mcp__atlassian__getJiraIssue", {"issueIdOrKey": "SEC-10"})
        assert result["permissionDecision"] == "allow"

    def test_read_only_write_denied(self):
        result = self._run_hook("mcp__atlassian__createJiraIssue", {"projectKey": "SEC"})
        assert result["permissionDecision"] == "deny"
        assert "read-only" in result["reason"].lower()

    def test_redacted_write_denied(self):
        result = self._run_hook("mcp__atlassian__editJiraIssue", {"issueIdOrKey": "FINEXEC-5"})
        assert result["permissionDecision"] == "deny"

    def test_allowed_project_create_asks(self):
        result = self._run_hook("mcp__atlassian__createJiraIssue", {"projectKey": "MYPROJ"})
        assert result["permissionDecision"] == "ask"
        assert "confirm" in result["reason"].lower()

    def test_delete_denied_by_operation(self):
        result = self._run_hook("mcp__atlassian__deleteJiraIssue", {"issueIdOrKey": "MYPROJ-1"})
        assert result["permissionDecision"] == "deny"

    def test_non_atlassian_tool_allowed(self):
        """Tools outside any registered connector pass through."""
        result = self._run_hook("Read", {"path": "/foo"})
        assert result["permissionDecision"] == "allow"

    def test_unscoped_jira_search_denied(self):
        """Unscoped searches can cross blocked projects, so fail closed."""
        result = self._run_hook("mcp__atlassian__searchJiraIssues", {"jql": "status = Open"})
        assert result["permissionDecision"] == "deny"

    def test_multi_project_jira_search_denied(self):
        """Mixed-scope JQL cannot be authorized by checking only one project."""
        result = self._run_hook("mcp__atlassian__searchJiraIssues", {"jql": "project = MYPROJ OR project = LEGAL"})
        assert result["permissionDecision"] == "deny"

    def test_unresolved_write_denied(self):
        """Writes without project/space key fail closed instead of relying on confirmation."""
        result = self._run_hook("mcp__atlassian__editJiraIssue", {"issueIdOrKey": "10001"})
        assert result["permissionDecision"] == "deny"

    def test_list_jira_projects_allowed(self):
        """Explicit metadata/list operations do not target one confidential resource."""
        result = self._run_hook("mcp__atlassian__listJiraProjects", {})
        assert result["permissionDecision"] == "allow"

    def test_blocked_confluence_space(self):
        result = self._run_hook("mcp__atlassian__getConfluencePage", {"spaceKey": "BOARD"})
        assert result["permissionDecision"] == "deny"
