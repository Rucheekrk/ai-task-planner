import base64
import json
import os
from typing import Optional

import requests


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_jira_config():
    # Return Jira credentials from env, or None if any required value is missing.
    # All four fields are required for a valid Jira API connection.
    url = os.getenv("JIRA_URL")
    token = os.getenv("JIRA_API_TOKEN")
    email = os.getenv("JIRA_USER_EMAIL")
    project = os.getenv("JIRA_PROJECT_KEY")

    if not all([url, token, email, project]):
        return None

    return {"url": url, "token": token, "email": email, "project": project}


def _auth_headers(config: dict) -> dict:
    # Jira Cloud uses HTTP Basic auth: base64(email:api_token)
    credentials = base64.b64encode(f"{config['email']}:{config['token']}".encode()).decode()
    return {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# Priority labels in our system map to Jira's built-in priority names
_PRIORITY_MAP = {
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}


# ---------------------------------------------------------------------------
# MCP tool
# ---------------------------------------------------------------------------

def sync_task_to_jira(
    task_id: str,
    task_text: str,
    priority: str = "medium",
    assignee: Optional[str] = None,
) -> str:
    """Push a task to Jira as a new issue. Requires JIRA_URL, JIRA_API_TOKEN, JIRA_USER_EMAIL, JIRA_PROJECT_KEY env vars."""
    config = _get_jira_config()

    # Graceful fallback — return not_configured when credentials are absent
    if not config:
        return json.dumps({
            "status": "not_configured",
            "message": (
                "Jira integration is not configured. "
                "Set JIRA_URL, JIRA_API_TOKEN, JIRA_USER_EMAIL, and JIRA_PROJECT_KEY in .env to enable."
            ),
            "task_id": task_id,
        })

    # Map internal priority label to Jira's display name; default to Medium for unknown values
    jira_priority = _PRIORITY_MAP.get(priority.lower(), "Medium")

    # Build the Jira issue payload — issuetype Task maps to a standard Jira task
    payload = {
        "fields": {
            "project": {"key": config["project"]},
            "summary": task_text,
            "issuetype": {"name": "Task"},
            "priority": {"name": jira_priority},
        }
    }

    # Assignee is matched by display name — must match the Jira user's name exactly
    if assignee:
        payload["fields"]["assignee"] = {"name": assignee}

    try:
        response = requests.post(
            f"{config['url']}/rest/api/3/issue",
            json=payload,
            headers=_auth_headers(config),
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        # Return the Jira issue key (e.g. "PROJ-42") and internal task_id for cross-reference
        return json.dumps({
            "status": "created",
            "jira_issue_key": data.get("key"),
            "jira_issue_id": data.get("id"),
            "task_id": task_id,
        })

    except requests.exceptions.HTTPError as e:
        # Include response body for easier debugging (e.g. field validation errors)
        body = e.response.text[:300] if e.response else ""
        return json.dumps({"error": f"Jira API error {e.response.status_code}: {body}", "task_id": task_id})

    except requests.exceptions.RequestException as e:
        return json.dumps({"error": f"Jira request failed: {e}", "task_id": task_id})
