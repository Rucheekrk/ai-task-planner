import json
import os
from typing import Optional

# _fetch_tasks_filtered lives in postgres.py — the single source of all MCP-layer DB queries
from mcp_server.tools.postgres import _fetch_tasks_filtered


# ---------------------------------------------------------------------------
# Formatters — convert a list of task dicts into the requested output format
# ---------------------------------------------------------------------------

def _as_markdown(tasks, filter_owner, filter_priority, filter_status):
    # Build the active filter summary line (omit keys with no value)
    filters = {k: v for k, v in {
        "owner": filter_owner, "priority": filter_priority, "status": filter_status
    }.items() if v}

    lines = ["# Task Report"]
    if filters:
        lines.append("**Filters:** " + ", ".join(f"{k}={v}" for k, v in filters.items()))
    lines.append(f"\n**Total tasks:** {len(tasks)}\n")

    # Main table — one row per task
    lines.append("| Task | Owner | Status | Priority | Deadline |")
    lines.append("|------|-------|--------|----------|----------|")
    for t in tasks:
        lines.append(
            f"| {t['task_text']} | {t.get('owner') or '—'} | {t.get('status') or '—'} "
            f"| {t.get('priority') or '—'} | {t.get('deadline') or '—'} |"
        )

    # Subtasks section — only included for tasks that have subtasks
    subtask_sections = [t for t in tasks if t.get("subtasks")]
    if subtask_sections:
        lines.append("\n## Subtasks")
        for t in subtask_sections:
            lines.append(f"\n**{t['task_text']}**")
            for s in t["subtasks"]:
                lines.append(f"- {s}")

    return "\n".join(lines)


def _as_excel(tasks):
    import pandas as pd

    # Flatten each task dict into a spreadsheet-friendly row.
    # Subtasks are joined as a semicolon-separated string since Excel cells are scalar.
    rows = [{
        "task_id": str(t["task_id"]),
        "task_text": t["task_text"],
        "owner": t.get("owner") or "",
        "status": t.get("status") or "",
        "priority": t.get("priority") or "",
        "deadline": str(t.get("deadline") or ""),
        "subtasks": "; ".join(t["subtasks"]) if t.get("subtasks") else "",
        "created_at": str(t.get("created_at") or ""),
        "updated_at": str(t.get("updated_at") or ""),
    } for t in tasks]

    df = pd.DataFrame(rows)

    # Write to reports/ directory — created on first use
    os.makedirs("reports", exist_ok=True)
    path = "reports/task_report.xlsx"
    df.to_excel(path, index=False, engine="openpyxl")
    return path


# ---------------------------------------------------------------------------
# MCP tool — registered in server.py via mcp.tool()
# ---------------------------------------------------------------------------

def generate_report(
    format: str = "markdown",
    filter_owner: Optional[str] = None,
    filter_priority: Optional[str] = None,
    filter_status: Optional[str] = None,
) -> str:
    """Generate a task report. format: markdown | json | excel. All filters are optional."""
    allowed_formats = {"markdown", "json", "excel"}
    if format not in allowed_formats:
        return json.dumps({"error": f"Format '{format}' not supported. Choose from: {sorted(allowed_formats)}"})

    # Fetch tasks from Postgres — filtering applied at query time
    try:
        tasks = _fetch_tasks_filtered(filter_owner, filter_priority, filter_status)
    except Exception as e:
        return json.dumps({"error": f"DB query failed: {e}"})

    # Return raw task list as JSON
    if format == "json":
        return json.dumps({"tasks_count": len(tasks), "tasks": tasks}, default=str)

    # Return markdown-formatted report string
    if format == "markdown":
        return json.dumps({
            "tasks_count": len(tasks),
            "report": _as_markdown(tasks, filter_owner, filter_priority, filter_status),
        })

    # Write Excel file to disk and return the file path
    if format == "excel":
        try:
            path = _as_excel(tasks)
            return json.dumps({"tasks_count": len(tasks), "file": path})
        except Exception as e:
            return json.dumps({"error": f"Excel generation failed: {e}"})
