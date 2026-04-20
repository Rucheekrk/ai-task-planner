import json
import os
import re
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()


def _get_conn():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "task_planner"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )
    try:
        from pgvector.psycopg2 import register_vector
        register_vector(conn)
    except Exception:
        pass
    return conn


def search_tasks(query: Optional[str] = None, owner: Optional[str] = None, status: Optional[str] = None) -> str:
    """Search active tasks in Postgres. All filters are optional — omit to return recent tasks."""
    conditions = ["is_active = TRUE"]
    params = []

    if query:
        conditions.append("(task_text ILIKE %s OR normalized_task_text ILIKE %s)")
        params.extend([f"%{query}%", f"%{query}%"])
    if owner:
        conditions.append("owner ILIKE %s")
        params.append(f"%{owner}%")
    if status:
        conditions.append("status = %s")
        params.append(status)

    where = " AND ".join(conditions)
    sql = f"""
        SELECT task_id, task_text, owner, status, deadline, priority, subtasks, created_at, updated_at
        FROM tasks
        WHERE {where}
        ORDER BY updated_at DESC
        LIMIT 20
    """

    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return json.dumps(rows, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_task_by_id(task_id: str) -> str:
    """Fetch a single task by its UUID, including all fields."""
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT task_id, task_text, normalized_task_text, owner, status,
                       deadline, blocker, priority, subtasks, is_active, created_at, updated_at
                FROM tasks
                WHERE task_id = %s
            """, (task_id,))
            row = cur.fetchone()
        conn.close()
        if row:
            return json.dumps(dict(row), default=str)
        return json.dumps({"error": f"No task found with id {task_id}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def create_task(task_text: str, owner: Optional[str] = None, deadline: Optional[str] = None, priority: str = "medium") -> str:
    """Insert a new task into Postgres. Use only for tasks the pipeline missed — pipeline handles bulk creation."""
    allowed_priorities = {"high", "medium", "low"}
    if priority not in allowed_priorities:
        priority = "medium"

    normalized = re.sub(r"[^\w\s]", "", task_text.lower().strip())

    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tasks (task_text, normalized_task_text, owner, deadline, priority, status)
                VALUES (%s, %s, %s, %s, %s, 'not_started')
                RETURNING task_id
            """, (task_text, normalized, owner or None, deadline or None, priority))
            task_id = str(cur.fetchone()[0])
        conn.commit()
        conn.close()
        return json.dumps({"task_id": task_id, "status": "created"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def update_task_status(task_id: str, field: str, value: str) -> str:
    """Update a single field on an existing task. Allowed fields: status, priority, owner, deadline, blocker."""
    allowed_fields = {"status", "priority", "owner", "deadline", "blocker"}
    if field not in allowed_fields:
        return json.dumps({
            "error": f"Field '{field}' not allowed. Choose from: {sorted(allowed_fields)}"
        })

    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE tasks SET {field} = %s, updated_at = NOW() WHERE task_id = %s",
                (value, task_id)
            )
            updated = cur.rowcount
        conn.commit()
        conn.close()
        if updated == 0:
            return json.dumps({"error": f"No task found with id {task_id}"})
        return json.dumps({"task_id": task_id, "field": field, "value": value, "status": "updated"})
    except Exception as e:
        return json.dumps({"error": str(e)})
