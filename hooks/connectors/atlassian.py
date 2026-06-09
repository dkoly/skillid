"""
Atlassian connector resolver for Skillid.

Handles Jira and Confluence MCP tools. Extracts project/space keys from tool
inputs and maps operations to policy checks.
"""

import re
from registry import ConnectorResolver


# Tool name → (resource_type, operation_type)
TOOL_OPERATIONS = {
    # Jira reads
    "mcp__atlassian__getJiraIssue": ("jira", "read"),
    "mcp__atlassian__searchJiraIssues": ("jira", "read"),
    "mcp__atlassian__getJiraIssueComments": ("jira", "read"),
    "mcp__atlassian__listJiraProjects": ("jira", "list"),

    # Jira writes
    "mcp__atlassian__createJiraIssue": ("jira", "create"),
    "mcp__atlassian__editJiraIssue": ("jira", "edit"),
    "mcp__atlassian__deleteJiraIssue": ("jira", "delete"),
    "mcp__atlassian__transitionJiraIssue": ("jira", "transition"),
    "mcp__atlassian__addCommentToJiraIssue": ("jira", "comment"),
    "mcp__atlassian__assignJiraIssue": ("jira", "assign"),
    "mcp__atlassian__updateJiraIssuePriority": ("jira", "priority_change"),

    # Confluence reads
    "mcp__atlassian__getConfluencePage": ("confluence", "read"),
    "mcp__atlassian__searchConfluence": ("confluence", "read"),
    "mcp__atlassian__listConfluenceSpaces": ("confluence", "list"),
    "mcp__atlassian__getConfluencePageComments": ("confluence", "read"),

    # Confluence writes
    "mcp__atlassian__createConfluencePage": ("confluence", "create"),
    "mcp__atlassian__updateConfluencePage": ("confluence", "edit"),
    "mcp__atlassian__deleteConfluencePage": ("confluence", "delete"),
    "mcp__atlassian__createConfluenceFooterComment": ("confluence", "comment"),
    "mcp__atlassian__createConfluenceInlineComment": ("confluence", "comment"),
    "mcp__atlassian__addConfluenceRestriction": ("confluence", "set_public"),
}

# Fields to check for project/space key extraction
JIRA_KEY_FIELDS = ["projectKey", "project_key", "issueIdOrKey", "issue_id_or_key", "issueKey", "issue_key"]
CONFLUENCE_KEY_FIELDS = ["spaceKey", "space_key"]

# Pattern to extract project key from issue key (e.g., "LEGAL-123" -> "LEGAL")
ISSUE_KEY_PATTERN = re.compile(r"^([A-Z][A-Z0-9_]+)-\d+$")


def _extract_jira_project(tool_input: dict) -> str | None:
    """Extract Jira project key from tool input."""
    for field in JIRA_KEY_FIELDS:
        value = tool_input.get(field)
        if value and isinstance(value, str):
            # Could be a project key directly or an issue key like LEGAL-123
            match = ISSUE_KEY_PATTERN.match(value)
            if match:
                return match.group(1)
            # Might be a project key directly
            if re.match(r"^[A-Z][A-Z0-9_]+$", value):
                return value

    # Check JQL for project references. Be conservative: if a query references
    # multiple projects, returning only the first would authorize mixed-scope
    # results (e.g. `project = OPEN OR project = LEGAL`). Let the hook deny
    # ambiguous reads/writes unless the caller narrows to a single project.
    jql = tool_input.get("jql", "")
    if jql:
        if re.search(r"\bOR\b", jql, re.IGNORECASE):
            return None
        projects = set()
        for match in re.finditer(r'project\s*=\s*["\']?([A-Z][A-Z0-9_]+)', jql, re.IGNORECASE):
            projects.add(match.group(1).upper())
        for match in re.finditer(r'project\s+in\s*\(([^)]*)\)', jql, re.IGNORECASE):
            for item in re.split(r"\s*,\s*", match.group(1)):
                key = item.strip().strip('"\'').upper()
                if re.match(r"^[A-Z][A-Z0-9_]+$", key):
                    projects.add(key)
        if len(projects) == 1:
            return next(iter(projects))
        if len(projects) > 1:
            return None

    return None


def _extract_confluence_space(tool_input: dict) -> str | None:
    """Extract Confluence space key from tool input."""
    for field in CONFLUENCE_KEY_FIELDS:
        value = tool_input.get(field)
        if value and isinstance(value, str):
            return value.upper()
    return None


class AtlassianResolver(ConnectorResolver):
    connector_id = "atlassian"
    tool_patterns = ["mcp__atlassian__*"]

    def resolve_resource(self, tool_name: str, tool_input: dict) -> tuple:
        """Extract resource info from an Atlassian tool call."""
        op_info = TOOL_OPERATIONS.get(tool_name)
        if not op_info:
            # Unknown Atlassian tool — fail closed
            return (None, None, None)

        resource_type, operation_type = op_info

        if resource_type == "jira":
            resource_key = _extract_jira_project(tool_input)
        elif resource_type == "confluence":
            resource_key = _extract_confluence_space(tool_input)
        else:
            resource_key = None

        return (resource_type, resource_key, operation_type)

    def get_modes_config(self, connector_config: dict, resource_type: str) -> dict:
        """Get project/space modes config."""
        if resource_type == "jira":
            return connector_config.get("jira", {}).get("project_modes", {"default": "read_write"})
        elif resource_type == "confluence":
            return connector_config.get("confluence", {}).get("space_modes", {"default": "read_write"})
        return {"default": "read_write"}

    def check_operation(self, connector_config: dict, resource_type: str,
                        operation_type: str) -> tuple:
        """Check if operation is allowed + needs confirmation."""
        section = connector_config.get(resource_type, {})
        ops = section.get("operations", {})
        confirms = section.get("confirmations", {})

        # Map operation type to operations config key
        op_key_map = {
            "create": "allow_create",
            "edit": "allow_edit",
            "delete": "allow_delete",
            "transition": "allow_transition",
            "assign": "allow_assign",
            "comment": "allow_comment",
            "priority_change": "allow_priority_change",
            "set_public": "allow_set_public",
            "bulk": "allow_bulk",
            "read": None,  # reads allowed only after resource resolution/mode checks
            "list": None,  # enumeration/list metadata operations do not target one resource
        }

        confirm_key_map = {
            "create": "before_create",
            "edit": "before_edit",
            "delete": "before_delete",
            "transition": "before_transition",
            "comment": "before_comment",
            "publish": "before_publish",
        }

        # Reads/lists are allowed at operation level; resource modes handle blocking.
        if operation_type in ("read", "list"):
            return (True, False)

        # Confluence-specific: edit_others check
        if resource_type == "confluence" and operation_type == "edit":
            # We can't easily determine ownership from tool input alone,
            # so allow_edit_others is a note in the skill, not enforced in hook.
            pass

        op_key = op_key_map.get(operation_type)
        if op_key is not None:
            allowed = ops.get(op_key, True)  # default allow if not specified
        else:
            allowed = True

        confirm_key = confirm_key_map.get(operation_type)
        needs_confirm = confirms.get(confirm_key, False) if confirm_key else False

        return (allowed, needs_confirm)


# Module-level instance for registry auto-discovery
RESOLVER = AtlassianResolver()
