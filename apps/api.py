from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from apps.agent import run_agent
from apps.logger import get_logger
from mcp_server.tools.postgres import get_task_by_id, search_tasks

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
# Request / response models
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    # Full input text — meeting transcript, SOW, email, etc.
    input_text: str
    # thread_id scopes the agent's Postgres memory; use distinct IDs per user/session
    thread_id: str = "default"


class ValidationOutcome(BaseModel):
    passed: bool
    iterations: int
    hit_max_iterations: bool
    final_feedback: str


class RunResponse(BaseModel):
    intent: str                          # task_planning | junk
    tasks_count: int                     # number of tasks stored
    tasks: List[Dict[str, Any]]          # task list with priority and subtasks
    unresolved_events: List[Dict[str, Any]]  # update events that failed matching
    validation_outcome: ValidationOutcome
    output: str                          # human-readable session summary


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """Liveness check — returns ok when the server is running."""
    return {"status": "ok"}


@app.post("/run", response_model=RunResponse)
async def run(request: RunRequest):
    """Run the ReAct agent on the provided input text.

    Classifies intent, runs the planning pipeline if actionable, and executes
    follow-up MCP tools (search, Jira, calendar) based on tool results.
    Results are persisted to Postgres and the session is checkpointed under thread_id.
    """
    logger.info(f"POST /run — thread_id={request.thread_id} input_len={len(request.input_text)}")

    try:
        # run_agent is synchronous — run in a thread pool to avoid blocking the event loop
        result = await run_in_threadpool(run_agent, request.input_text, request.thread_id)
    except Exception as e:
        logger.error(f"Agent failed: {e}")
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")

    pipeline_output = result.get("pipeline_output", {})
    validation_raw = pipeline_output.get("validation_outcome", {})

    return RunResponse(
        intent=result.get("plan", {}).get("intent", "unknown"),
        tasks_count=pipeline_output.get("tasks_count", 0),
        tasks=pipeline_output.get("tasks", []),
        unresolved_events=pipeline_output.get("unresolved_events", []),
        validation_outcome=ValidationOutcome(
            passed=validation_raw.get("passed", False),
            iterations=validation_raw.get("iterations", 0),
            hit_max_iterations=validation_raw.get("hit_max_iterations", False),
            final_feedback=validation_raw.get("final_feedback", ""),
        ),
        output=result.get("output", ""),
    )


@app.get("/tasks")
def list_tasks(
    query: Optional[str] = Query(None, description="Text search across task_text"),
    owner: Optional[str] = Query(None, description="Filter by owner name"),
    status: Optional[str] = Query(None, description="Filter by status"),
):
    """List active tasks with optional filters. Returns up to 20 results ordered by updated_at."""
    # search_tasks returns a JSON string — parse it before returning so FastAPI serialises it cleanly
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
