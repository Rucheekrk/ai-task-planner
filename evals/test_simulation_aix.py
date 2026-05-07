"""
End-to-end simulation test for the ai-x-vmware dataset.

Runs SOW + 8 meeting transcripts through the agent in chronological order,
all under the same project_id so task state accumulates across inputs.
Prints extracted tasks and field completeness after each run.
"""

import requests
import time
import json
import os
from pathlib import Path

API_URL = "http://localhost:8000"
PROJECT_ID = "sim-ai-x-vmware"
DATASET_DIR = Path("/Users/rucheekkashyap/Projects/LangGraph-Task-Agent/datasets/simulation-ai-x-vmware")

INPUTS = [
    ("SOW",         DATASET_DIR / "sow.txt"),
    ("Meeting 01",  DATASET_DIR / "meeting-01.txt"),
    ("Meeting 02",  DATASET_DIR / "meeting-02.txt"),
    ("Meeting 03",  DATASET_DIR / "meeting-03.txt"),
    ("Meeting 04",  DATASET_DIR / "meeting-04.txt"),
    ("Meeting 05",  DATASET_DIR / "meeting-05.txt"),
    ("Meeting 06",  DATASET_DIR / "meeting-06.txt"),
    ("Meeting 07",  DATASET_DIR / "meeting-07.txt"),
    ("Meeting 08",  DATASET_DIR / "meeting-08.txt"),
]

POLL_INTERVAL = 10   # seconds between job status polls
POLL_TIMEOUT  = 700  # max seconds to wait per run


def submit_run(input_text: str) -> str:
    resp = requests.post(f"{API_URL}/run", json={
        "input_text": input_text,
        "thread_id": PROJECT_ID,
        "force_run": True,
    })
    resp.raise_for_status()
    return resp.json()["job_id"]


def poll_job(job_id: str) -> dict:
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        resp = requests.get(f"{API_URL}/jobs/{job_id}")
        resp.raise_for_status()
        data = resp.json()
        if data["status"] in ("completed", "failed"):
            return data
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
    return {"status": "timeout", "result": None}


def field_score(task: dict) -> dict:
    """Return which normalized fields are populated for a task."""
    fields = ["task_text", "owner", "deadline", "status", "priority", "blocker"]
    return {f: bool(task.get(f) not in (None, "", [], "null", "unknown", "not_started"))
            for f in fields}


def print_run_result(label: str, result: dict):
    sep = "─" * 72
    print(f"\n{'═' * 72}")
    print(f"  {label}")
    print(f"{'═' * 72}")

    if result.get("status") == "failed":
        print(f"  ✗ RUN FAILED: {result.get('error', 'unknown error')}")
        return

    if result.get("status") == "timeout":
        print("  ✗ RUN TIMED OUT")
        return

    data = result.get("result", {})
    tasks = data.get("tasks", [])
    unresolved = data.get("unresolved_events", [])
    validation = data.get("validation_outcome", "")
    task_count = data.get("tasks_count", len(tasks))

    print(f"  Tasks extracted : {task_count}")
    print(f"  Validation      : {validation}")
    if unresolved:
        print(f"  Unresolved events: {len(unresolved)}")
        for u in unresolved:
            print(f"    ⚠  {u.get('task_text', u.get('task', '?'))} "
                  f"[{u.get('event_type', '?')}] owner={u.get('owner', '?')}")

    if not tasks:
        print("  (no tasks returned)")
        return

    # Field completeness summary
    field_totals = {f: 0 for f in ["owner", "deadline", "status", "priority", "blocker"]}
    for t in tasks:
        scores = field_score(t)
        for f, v in scores.items():
            if f in field_totals and v:
                field_totals[f] += 1

    print(f"\n  Field completeness across {len(tasks)} tasks:")
    for field, count in field_totals.items():
        pct = int(100 * count / len(tasks)) if tasks else 0
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        print(f"    {field:<12} {bar} {pct:3d}%  ({count}/{len(tasks)})")

    # Per-task detail
    print(f"\n  {sep}")
    print(f"  {'#':<4} {'Task':<46} {'Owner':<16} {'Deadline':<14} {'Priority':<10} {'Status'}")
    print(f"  {sep}")
    for i, t in enumerate(tasks, 1):
        task_text = (t.get("task_text") or t.get("normalized_task_text") or "")[:45]
        owner    = (t.get("owner") or "—")[:15]
        deadline = (t.get("deadline") or "—")[:13]
        priority = (t.get("priority") or "—")[:9]
        status   = (t.get("status") or "—")[:15]
        print(f"  {i:<4} {task_text:<46} {owner:<16} {deadline:<14} {priority:<10} {status}")

    print(f"  {sep}")


def fetch_all_project_tasks() -> list:
    resp = requests.get(f"{API_URL}/tasks", params={"project_id": PROJECT_ID})
    if resp.status_code == 200:
        return resp.json()
    return []


def print_final_summary(all_tasks: list):
    sep = "─" * 72
    print(f"\n\n{'█' * 72}")
    print(f"  FINAL PROJECT STATE — {PROJECT_ID}")
    print(f"{'█' * 72}")
    print(f"  Total active tasks in DB: {len(all_tasks)}\n")

    # Group by owner
    by_owner: dict = {}
    for t in all_tasks:
        owner = t.get("owner") or "Unassigned"
        by_owner.setdefault(owner, []).append(t)

    for owner, tasks in sorted(by_owner.items()):
        print(f"  ── {owner} ({len(tasks)} tasks) ──")
        for t in tasks:
            text = (t.get("task_text") or t.get("normalized_task_text") or "")[:55]
            deadline = t.get("deadline") or "no deadline"
            status   = t.get("status") or "—"
            priority = t.get("priority") or "—"
            blocker  = "⚠ BLOCKED" if t.get("blocker") else ""
            print(f"    • {text}")
            print(f"      deadline={deadline}  status={status}  priority={priority}  {blocker}")
        print()

    # Overall field completeness across all tasks
    if all_tasks:
        fields = ["owner", "deadline", "status", "priority", "blocker"]
        print(f"  Overall field completeness ({len(all_tasks)} tasks total):")
        for field in fields:
            count = sum(1 for t in all_tasks
                        if t.get(field) not in (None, "", [], "null", "unknown", "not_started"))
            pct = int(100 * count / len(all_tasks))
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            print(f"    {field:<12} {bar} {pct:3d}%  ({count}/{len(all_tasks)})")
    print(f"\n{'█' * 72}")


def main():
    print(f"Starting end-to-end simulation: project_id={PROJECT_ID}")
    print(f"Inputs: {len(INPUTS)} files (SOW + 8 meetings)\n")

    run_summary = []

    for label, path in INPUTS:
        if not path.exists():
            print(f"[SKIP] {label}: file not found at {path}")
            continue

        input_text = path.read_text(encoding="utf-8")
        print(f"[→] Submitting {label} ({len(input_text):,} chars)...", flush=True)

        try:
            job_id = submit_run(input_text)
            print(f"    job_id={job_id}  polling every {POLL_INTERVAL}s...", flush=True)
            result = poll_job(job_id)
        except Exception as e:
            result = {"status": "failed", "error": str(e)}

        task_count = result.get("result", {}).get("tasks_count", 0) if result.get("result") else 0
        run_summary.append((label, result.get("status"), task_count))
        print_run_result(label, result)

    # Print aggregate final state from DB
    print("\n[→] Fetching final project task state from DB...")
    all_tasks = fetch_all_project_tasks()
    print_final_summary(all_tasks)

    # Run summary table
    print("\n  RUN SUMMARY:")
    print(f"  {'Input':<14} {'Status':<12} {'Tasks'}")
    print(f"  {'─'*14} {'─'*12} {'─'*6}")
    for label, status, count in run_summary:
        status_icon = "✓" if status == "completed" else "✗"
        print(f"  {label:<14} {status_icon} {status:<11} {count}")


if __name__ == "__main__":
    main()
