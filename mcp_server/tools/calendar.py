import json
from typing import Optional


def check_owner_availability(owner: str, deadline: Optional[str] = None) -> str:
    """Check calendar availability for a task owner around a deadline. Requires calendar API credentials."""
    return json.dumps({
        "status": "not_configured",
        "message": (
            "Calendar integration is not yet configured. "
            "Connect a Google Calendar or Outlook API to enable."
        ),
        "owner": owner,
        "deadline": deadline,
    })
