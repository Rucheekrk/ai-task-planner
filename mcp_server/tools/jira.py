import json
from typing import Optional


def sync_task_to_jira(task_id: str, task_text: str, priority: str = "medium", assignee: Optional[str] = None) -> str:
    """Push a task to Jira as a new issue. Requires JIRA_URL, JIRA_TOKEN, JIRA_PROJECT env vars."""
    return json.dumps({
        "status": "not_configured",
        "message": (
            "Jira integration is not yet configured. "
            "Set JIRA_URL, JIRA_TOKEN, and JIRA_PROJECT in .env to enable."
        ),
        "task_id": task_id,
    })
