import json
from typing import Optional


def generate_report(format: str = "markdown", filter_owner: Optional[str] = None) -> str:
    """Generate a task report in the requested format (markdown, json, excel). Queries active tasks from Postgres."""
    allowed_formats = {"markdown", "json", "excel"}
    if format not in allowed_formats:
        return json.dumps({
            "error": f"Format '{format}' not supported. Choose from: {sorted(allowed_formats)}"
        })

    return json.dumps({
        "status": "not_configured",
        "message": (
            f"Report generation in '{format}' format is not yet implemented. "
            "Use search_tasks to query tasks directly for now."
        ),
        "format": format,
        "filter_owner": filter_owner,
    })
