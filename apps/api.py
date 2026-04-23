import threading
import uuid
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from apps.agent import run_agent
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


# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------

_jobs: Dict[str, Dict] = {}
_jobs_lock = threading.Lock()


def _run_agent_job(job_id: str, input_text: str, thread_id: str) -> None:
    try:
        result = run_agent(input_text, thread_id)
        with _jobs_lock:
            _jobs[job_id]["status"] = "completed"
            _jobs[job_id]["result"] = result
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        with _jobs_lock:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = str(e)


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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """Liveness check — returns ok when the server is running."""
    return {"status": "ok"}


@app.post("/run")
async def run(request: RunRequest):
    """Submit an agent run. Returns a job_id immediately; poll GET /jobs/{job_id} for results."""
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "result": None, "error": None}

    thread = threading.Thread(
        target=_run_agent_job,
        args=(job_id, request.input_text, request.thread_id),
        daemon=True,
    )
    thread.start()
    logger.info(f"POST /run — job_id={job_id} thread_id={request.thread_id}")
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    """Poll the status of an agent run. Returns status: running | completed | failed."""
    with _jobs_lock:
        job = _jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] == "completed":
        return {"status": "completed", "result": _format_run_result(job["result"])}

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
