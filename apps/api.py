import hashlib
import threading
import uuid
from typing import Any, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from apps.agent import run_agent
from apps.db.db import (
    cache_pipeline_result,
    cleanup_old_jobs,
    complete_job,
    create_job,
    ensure_jobs_table,
    fail_job,
    get_cached_pipeline_result,
    get_job,
)
from apps.logger import get_logger
from mcp_server.tools.postgres import get_task_by_id, search_tasks, update_task_status

load_dotenv()
logger = get_logger("API")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AI Task Planner",
    description="LangGraph ReAct agent that extracts, plans, and stores tasks from raw input.",
    version="1.0.0",
)


@app.on_event("startup")
def _startup():
    # Create agent_jobs table if it doesn't exist, then purge stale rows from previous runs.
    ensure_jobs_table()
    deleted = cleanup_old_jobs(max_age_hours=24)
    if deleted:
        logger.info(f"Startup cleanup: removed {deleted} stale job row(s)")


def _run_agent_job(job_id: str, input_text: str, thread_id: str) -> None:
    try:
        result = run_agent(input_text, thread_id)
        complete_job(job_id, result)
        # Cache the formatted result so the same input can be served instantly next time.
        formatted = _format_run_result(result)
        cache_pipeline_result(input_text, formatted)
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        fail_job(job_id, str(e))


def _format_run_result(result: dict) -> dict:
    pipeline_output = result.get("pipeline_output", {})
    validation_raw = pipeline_output.get("validation_outcome", {})
    return {
        "intent": result.get("plan", {}).get("intent", "unknown"),
        "tasks_count": pipeline_output.get("tasks_count", 0),
        "tasks": pipeline_output.get("tasks", []),
        "event_signals": pipeline_output.get("event_signals", []),
        "unresolved_events": pipeline_output.get("unresolved_events", []),
        "validation_outcome": {
            "passed": validation_raw.get("passed", False),
            "iterations": validation_raw.get("iterations", 0),
            "hit_max_iterations": validation_raw.get("hit_max_iterations", False),
            "final_feedback": validation_raw.get("final_feedback", ""),
        },
        "output": result.get("output", ""),
    }


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    input_text: str
    thread_id: str = "default"
    force_run: bool = False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """Liveness check — returns ok when the server is running."""
    return {"status": "ok"}


@app.post("/run")
async def run(request: RunRequest):
    """Submit an agent run. Returns a job_id immediately; poll GET /jobs/{job_id} for results.
    Set force_run=true to bypass the cache and re-run the pipeline even for a known input."""
    job_id = str(uuid.uuid4())
    content_hash = hashlib.sha256(request.input_text.encode()).hexdigest()

    if not request.force_run:
        cached = get_cached_pipeline_result(content_hash)
        if cached:
            # Serve cached result immediately — no agent run needed.
            # Store the result under a _cached_result key so poll_job can detect it
            # and return it directly without passing it through _format_run_result again.
            create_job(job_id)
            complete_job(job_id, {"_cached_result": cached})
            logger.info(f"POST /run — cache hit, job_id={job_id} hash={content_hash[:12]}…")
            return {"job_id": job_id, "from_cache": True}

    create_job(job_id)
    thread = threading.Thread(
        target=_run_agent_job,
        args=(job_id, request.input_text, request.thread_id),
        daemon=True,
    )
    thread.start()
    logger.info(f"POST /run — job_id={job_id} thread_id={request.thread_id} force={request.force_run}")
    return {"job_id": job_id, "from_cache": False}


@app.get("/jobs/{job_id}")
def poll_job(job_id: str):
    """Poll the status of an agent run. Returns status: running | completed | failed."""
    job = get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] == "completed":
        raw = job["result"]
        if isinstance(raw, dict) and "_cached_result" in raw:
            return {"status": "completed", "result": raw["_cached_result"], "from_cache": True}
        return {"status": "completed", "result": _format_run_result(raw), "from_cache": False}

    if job["status"] == "failed":
        return {"status": "failed", "error": job.get("error", "unknown error")}

    return {"status": "running"}


@app.get("/tasks")
def list_tasks(
    query: Optional[str] = Query(None, description="Text search across task_text"),
    owner: Optional[str] = Query(None, description="Filter by owner name"),
    status: Optional[str] = Query(None, description="Filter by status"),
):
    """List active tasks with optional filters. Returns up to 20 results ordered by updated_at."""
    import json
    raw = search_tasks(query=query, owner=owner, status=status)
    data = json.loads(raw)

    if isinstance(data, dict) and "error" in data:
        raise HTTPException(status_code=500, detail=data["error"])

    return {"tasks": data, "count": len(data)}


@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    """Fetch a single task by its UUID."""
    import json
    raw = get_task_by_id(task_id)
    data = json.loads(raw)

    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])

    return data


class TaskPatchRequest(BaseModel):
    field: str   # status | priority | owner | deadline | blocker
    value: str


@app.patch("/tasks/{task_id}")
def patch_task(task_id: str, body: TaskPatchRequest):
    """Update a single field on an existing task."""
    import json
    raw = update_task_status(task_id=task_id, field=body.field, value=body.value)
    data = json.loads(raw)

    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])

    return data
