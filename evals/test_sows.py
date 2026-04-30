#!/usr/bin/env python3
"""
test_sows.py — Automated test runner for all 4 SOW inputs.

Runs each SOW twice (force_run=True on second run), measures timing,
compares against expected outputs, checks cross-run consistency and
cross-project isolation.

Usage:
    python3 test_sows.py
"""

import json
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

import requests

API_BASE = "http://localhost:8000"
DATASETS = Path("datasets")
INPUTS = DATASETS / "inputs"
EXPECTED = DATASETS / "expected-outputs"
POLL_INTERVAL = 5   # seconds between job status polls
JOB_TIMEOUT = 600   # max seconds to wait per run

SOWS = [
    {"id": "sow-1", "input": "input-sow-1.txt", "expected": "expected-output-sow-1.txt"},
    {"id": "sow-2", "input": "input-sow-2.txt", "expected": "expected-output-sow-2.txt"},
    {"id": "sow-3", "input": "input-sow-3.txt", "expected": "expected-output-sow-3.txt"},
    {"id": "sow-4", "input": "input-sow-4.txt", "expected": "expected-output-sow-4.txt"},
]


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def submit_run(input_text: str, thread_id: str, force_run: bool = False) -> str:
    r = requests.post(f"{API_BASE}/run", json={
        "input_text": input_text,
        "thread_id": thread_id,
        "force_run": force_run,
    }, timeout=15)
    r.raise_for_status()
    return r.json()["job_id"]


def poll_until_done(job_id: str) -> dict:
    start = time.time()
    while time.time() - start < JOB_TIMEOUT:
        r = requests.get(f"{API_BASE}/jobs/{job_id}", timeout=10)
        r.raise_for_status()
        job = r.json()
        if job["status"] in ("completed", "failed"):
            return job
        elapsed = int(time.time() - start)
        print(f"      polling... {elapsed}s elapsed", end="\r")
        time.sleep(POLL_INTERVAL)
    return {"status": "timeout"}


def fetch_project_tasks(project_id: str) -> list:
    r = requests.get(f"{API_BASE}/tasks", params={"project_id": project_id}, timeout=10)
    r.raise_for_status()
    return r.json().get("tasks", [])


# ---------------------------------------------------------------------------
# Parsing + comparison
# ---------------------------------------------------------------------------

def parse_expected_tasks(expected_file: Path) -> list:
    """Extract task names from expected output file (numbered list items)."""
    content = expected_file.read_text()
    # Match top-level numbered tasks: "1. Task name" — excludes subtask bullet points
    tasks = re.findall(r'^\d+\.\s+(.+)$', content, re.MULTILINE)
    return [t.strip() for t in tasks]


def fuzzy_score(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def compare_tasks(actual: list, expected: list, threshold: float = 0.60) -> dict:
    """
    Match each expected task to the closest actual task via fuzzy scoring.
    Threshold 0.60 — loose enough to handle paraphrasing, tight enough to
    avoid false positives.
    """
    unmatched_actual = list(actual)
    matched, missed = [], []

    for exp in expected:
        best_score, best_act = 0.0, None
        for act in unmatched_actual:
            score = fuzzy_score(exp, act)
            if score > best_score:
                best_score, best_act = score, act

        if best_act and best_score >= threshold:
            matched.append({"expected": exp, "actual": best_act, "score": round(best_score, 2)})
            unmatched_actual.remove(best_act)
        else:
            missed.append(exp)

    return {
        "matched": matched,
        "missed": missed,
        "extra": unmatched_actual,   # actual tasks not in expected
        "match_rate": round(len(matched) / len(expected) * 100, 1) if expected else 0.0,
    }


def consistency_check(tasks_run1: list, tasks_run2: list) -> dict:
    """Compare task lists from two runs of the same SOW."""
    set1, set2 = set(t.lower().strip() for t in tasks_run1), set(t.lower().strip() for t in tasks_run2)
    overlap = set1 & set2
    score = round(len(overlap) / max(len(set1), len(set2)) * 100, 1) if (set1 or set2) else 0.0
    added   = [t for t in tasks_run2 if t.lower().strip() not in set1]
    removed = [t for t in tasks_run1 if t.lower().strip() not in set2]
    return {
        "score": score,
        "same_count": len(tasks_run1) == len(tasks_run2),
        "added_in_run2": added,
        "removed_in_run2": removed,
    }


# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------

def run_tests():
    print("\n" + "=" * 70)
    print("AI Task Planner — SOW Test Suite")
    print("=" * 70)

    # Verify API is reachable
    try:
        requests.get(f"{API_BASE}/health", timeout=5).raise_for_status()
        print("✅ API online\n")
    except Exception:
        print("❌ API is offline — start the server and retry.")
        return

    all_results = []

    for sow in SOWS:
        sow_id   = sow["id"]
        inp      = (INPUTS / sow["input"]).read_text()
        exp_file = EXPECTED / sow["expected"]
        expected_tasks = parse_expected_tasks(exp_file)

        print(f"\n{'─' * 70}")
        print(f"  {sow_id.upper()}  |  {len(inp):,} chars  |  {len(expected_tasks)} expected tasks")
        print(f"{'─' * 70}")

        runs = []

        for run_num in range(1, 3):
            force = True
            label = f"run {run_num} (force re-run)"
            print(f"\n  [{label}]")

            try:
                t0 = time.time()
                job_id = submit_run(inp, thread_id=sow_id, force_run=force)
                job    = poll_until_done(job_id)
                elapsed = round(time.time() - t0, 1)
                print()  # clear the polling line
            except Exception as e:
                print(f"\n  ❌ Submit/poll error: {e}")
                runs.append({"run": run_num, "status": "error", "error": str(e)})
                continue

            if job["status"] == "timeout":
                print(f"  ❌ TIMED OUT after {JOB_TIMEOUT}s")
                runs.append({"run": run_num, "status": "timeout", "elapsed": JOB_TIMEOUT})
                continue

            if job["status"] == "failed":
                print(f"  ❌ FAILED: {job.get('error')}")
                runs.append({"run": run_num, "status": "failed", "error": job.get("error"), "elapsed": elapsed})
                continue

            result     = job["result"]
            actual_tasks = [t["task"] for t in result.get("tasks", [])]
            comparison = compare_tasks(actual_tasks, expected_tasks)
            validation = result.get("validation_outcome", {})

            print(f"  ✅  {elapsed}s  |  extracted: {result.get('tasks_count', 0)}  |  expected: {len(expected_tasks)}  |  match: {comparison['match_rate']}%")
            print(f"      validation: {'passed ✅' if validation.get('passed') else 'failed ❌'}  ({validation.get('iterations', '?')} iterations)  |  from_cache: {job.get('from_cache', False)}")

            if comparison["missed"]:
                print(f"\n      MISSED ({len(comparison['missed'])} tasks):")
                for t in comparison["missed"]:
                    print(f"        ✗ {t}")

            if comparison["extra"]:
                print(f"\n      EXTRA — not in expected ({len(comparison['extra'])} tasks):")
                for t in comparison["extra"]:
                    print(f"        + {t}")

            runs.append({
                "run": run_num,
                "status": "completed",
                "elapsed": elapsed,
                "tasks_count": result.get("tasks_count", 0),
                "actual_tasks": actual_tasks,
                "comparison": comparison,
                "validation": validation,
                "from_cache": job.get("from_cache", False),
            })

        # Consistency between run 1 and run 2
        consistency = None
        r1 = next((r for r in runs if r["run"] == 1 and r["status"] == "completed"), None)
        r2 = next((r for r in runs if r["run"] == 2 and r["status"] == "completed"), None)
        if r1 and r2:
            consistency = consistency_check(r1["actual_tasks"], r2["actual_tasks"])
            print(f"\n  CONSISTENCY run1 vs run2: {consistency['score']}%  |  same count: {consistency['same_count']}")
            if consistency["added_in_run2"]:
                print(f"    New in run 2:     {consistency['added_in_run2']}")
            if consistency["removed_in_run2"]:
                print(f"    Missing in run 2: {consistency['removed_in_run2']}")

        all_results.append({
            "sow_id": sow_id,
            "expected_task_count": len(expected_tasks),
            "runs": runs,
            "consistency": consistency,
        })

    # -------------------------------------------------------------------------
    # Cross-project isolation check
    # -------------------------------------------------------------------------
    print(f"\n{'─' * 70}")
    print("  CROSS-PROJECT ISOLATION CHECK")
    print(f"{'─' * 70}")

    all_ids = [s["id"] for s in SOWS]
    isolation_results = {}

    for sow_id in all_ids:
        my_tasks = {t["task_text"].lower().strip() for t in fetch_project_tasks(sow_id)}
        violations = []
        for other_id in all_ids:
            if other_id == sow_id:
                continue
            other_tasks = {t["task_text"].lower().strip() for t in fetch_project_tasks(other_id)}
            overlap = my_tasks & other_tasks
            if overlap:
                violations.append({"other": other_id, "tasks": list(overlap)})

        isolated = len(violations) == 0
        isolation_results[sow_id] = {"isolated": isolated, "violations": violations}
        status = "✅ Isolated" if isolated else "❌ LEAK DETECTED"
        print(f"  {sow_id}: {status}  ({len(my_tasks)} tasks in DB)")
        if not isolated:
            for v in violations:
                print(f"    → leaks into {v['other']}: {v['tasks']}")

    # -------------------------------------------------------------------------
    # Summary table
    # -------------------------------------------------------------------------
    print(f"\n{'═' * 70}")
    print("  SUMMARY")
    print(f"{'═' * 70}")
    print(f"  {'SOW':<8} {'Runs OK':<10} {'Avg Time':<12} {'Avg Match%':<14} {'Consistency%':<14} {'Isolated'}")
    print(f"  {'─'*8} {'─'*10} {'─'*12} {'─'*14} {'─'*14} {'─'*8}")

    for r in all_results:
        ok_runs    = [x for x in r["runs"] if x["status"] == "completed"]
        avg_time   = f"{round(sum(x['elapsed'] for x in ok_runs)/len(ok_runs),1)}s" if ok_runs else "N/A"
        avg_match  = f"{round(sum(x['comparison']['match_rate'] for x in ok_runs)/len(ok_runs),1)}%" if ok_runs else "N/A"
        con_score  = f"{r['consistency']['score']}%" if r["consistency"] else "N/A"
        isolated   = "✅" if isolation_results.get(r["sow_id"], {}).get("isolated") else "❌"
        print(f"  {r['sow_id']:<8} {len(ok_runs)}/2{'':<7} {avg_time:<12} {avg_match:<14} {con_score:<14} {isolated}")

    # Save full results
    ts = time.strftime("%m-%d-%y_%H-%M-%S")
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)
    out = results_dir / f"test_results_{ts}.json"
    with open(out, "w") as f:
        json.dump({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "results": all_results, "isolation": isolation_results}, f, indent=2, default=str)
    print(f"\n  Full results saved → {out}")
    print(f"{'═' * 70}\n")


if __name__ == "__main__":
    run_tests()
