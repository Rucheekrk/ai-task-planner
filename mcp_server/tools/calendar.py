import json
import os
from datetime import datetime, timedelta
from typing import Optional


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_calendar_config():
    # Return Google Calendar config from env, or None if credentials are missing.
    # GOOGLE_SERVICE_ACCOUNT_FILE must point to a service account JSON with
    # domain-wide delegation enabled so it can query any user's calendar.
    service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    domain = os.getenv("GOOGLE_CALENDAR_DOMAIN")

    if not service_account_file or not os.path.exists(service_account_file):
        return None

    return {"service_account_file": service_account_file, "domain": domain}


def _parse_deadline_window(deadline: Optional[str]) -> tuple:
    # Convert a deadline string into a (time_min, time_max) window for the freebusy query.
    # Defaults to a 24-hour window starting from now if no deadline is provided.
    now = datetime.utcnow()

    if not deadline:
        time_min = now
        time_max = now + timedelta(days=1)
    else:
        try:
            # Attempt strict ISO date parse first (YYYY-MM-DD)
            target = datetime.strptime(deadline.strip(), "%Y-%m-%d")
            time_min = target.replace(hour=0, minute=0, second=0)
            time_max = target.replace(hour=23, minute=59, second=59)
        except ValueError:
            # Fall back to a 24-hour window from now for relative strings like "tomorrow EOD"
            time_min = now
            time_max = now + timedelta(days=1)

    return (
        time_min.strftime("%Y-%m-%dT%H:%M:%SZ"),
        time_max.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


# ---------------------------------------------------------------------------
# MCP tool
# ---------------------------------------------------------------------------

def check_owner_availability(owner: str, deadline: Optional[str] = None) -> str:
    """Check Google Calendar availability for a task owner around a deadline.
    Requires GOOGLE_SERVICE_ACCOUNT_FILE (path to service account JSON with domain-wide delegation)
    and GOOGLE_CALENDAR_DOMAIN (e.g. mycompany.com) env vars.
    """
    config = _get_calendar_config()

    # Graceful fallback — return not_configured when credentials are absent
    if not config:
        return json.dumps({
            "status": "not_configured",
            "message": (
                "Google Calendar integration is not configured. "
                "Set GOOGLE_SERVICE_ACCOUNT_FILE (path to service account JSON with domain-wide delegation) "
                "and GOOGLE_CALENDAR_DOMAIN in .env to enable."
            ),
            "owner": owner,
            "deadline": deadline,
        })

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        return json.dumps({
            "error": "google-auth and google-api-python-client are required. Run: pip install google-auth google-api-python-client",
            "owner": owner,
        })

    # Build the owner's calendar email — append domain if owner is just a name/username
    owner_email = owner if "@" in owner else f"{owner}@{config['domain']}"

    try:
        # Authenticate using service account with domain-wide delegation
        scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
        credentials = service_account.Credentials.from_service_account_file(
            config["service_account_file"], scopes=scopes
        )
        # Delegate to the owner's account so we can read their calendar
        delegated_credentials = credentials.with_subject(owner_email)
        service = build("calendar", "v3", credentials=delegated_credentials)

        time_min, time_max = _parse_deadline_window(deadline)

        # Query the freebusy endpoint — returns busy time blocks for the given window
        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": owner_email}],
        }
        result = service.freebusy().query(body=body).execute()
        # busy_slots is a list of {start, end} dicts; empty list means the owner is free
        busy_slots = result.get("calendars", {}).get(owner_email, {}).get("busy", [])

        # Return availability status along with the full busy slot list for the agent to act on
        return json.dumps({
            "status": "available" if not busy_slots else "busy",
            "owner": owner_email,
            "deadline": deadline,
            "window": {"from": time_min, "to": time_max},
            "busy_slots": busy_slots,
        })

    except Exception as e:
        return json.dumps({"error": f"Google Calendar API failed: {e}", "owner": owner})
