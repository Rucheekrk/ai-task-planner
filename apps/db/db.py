import psycopg2
from psycopg2.extras import RealDictCursor
from pgvector.psycopg2 import register_vector
from apps.utils.embeddings import get_embedding
import os


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def get_connection():
    # Open a new psycopg2 connection using env-configured credentials.
    # register_vector() is required to enable pgvector type support for this connection.
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "task_planner"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )
    register_vector(conn)
    return conn


# ---------------------------------------------------------------------------
# Task writes
# ---------------------------------------------------------------------------

def insert_task(task):
    # Generate a 384-dim embedding before insert so the task is immediately
    # available for semantic similarity search in the match node
    embedding = get_embedding(task.get("task_text"))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO tasks (
                task_text,
                normalized_task_text,
                owner,
                status,
                deadline,
                blocker,
                priority,
                subtasks,
                task_embedding)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING task_id
    """, (
        task.get("task_text"),
        task.get("normalized_task_text"),
        task.get("owner"),
        task.get("status"),
        task.get("deadline"),
        task.get("blocker"),
        task.get("priority", "medium"),
        task.get("subtasks", []),
        embedding,
    ))

    task_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()

    return task_id


def insert_event(event):
    # Append an immutable event record to task_events.
    # Every matched event (new task, update, blocker, etc.) is logged here for audit history.
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO task_events (
            task_id, event_type, task_text, owner, status,
            deadline, blocker, dependency, match_method,
            match_confidence, source_input
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        event.get("matched_task_id"),
        event.get("event_type"),
        event.get("task_text"),
        event.get("owner"),
        event.get("status"),
        event.get("deadline"),
        event.get("blocker"),
        event.get("dependency"),
        event.get("match_method"),
        event.get("match_confidence"),
        event.get("source_input"),
    ))

    conn.commit()
    cur.close()
    conn.close()


def update_task_field(task_id, field_name, field_value):
    # Update a single field on an existing task row.
    # field_name is validated against an allowlist to prevent SQL injection
    # before being interpolated into the query string.
    allowed_fields = {"status", "deadline", "owner", "blocker", "priority"}

    if field_name not in allowed_fields:
        raise ValueError(f"Invalid field name: {field_name}")

    conn = get_connection()
    cur = conn.cursor()

    # Safe to interpolate field_name here — it has been validated against the allowlist above
    query = f"""
        UPDATE tasks
        SET {field_name} = %s,
            updated_at = NOW()
        WHERE task_id = %s
    """

    cur.execute(query, (field_value, task_id))
    conn.commit()
    cur.close()
    conn.close()


def update_task_subtasks(task_id, subtasks: list):
    # Update the subtasks array for an existing task.
    # Kept separate from update_task_field because subtasks is a TEXT[] array type,
    # not a simple scalar — psycopg2 handles the array serialization here.
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE tasks
        SET subtasks = %s,
            updated_at = NOW()
        WHERE task_id = %s
    """, (subtasks, task_id))

    conn.commit()
    cur.close()
    conn.close()


def log_unresolved_event(event: dict, source_input: str = ""):
    # Write a failed-match update event to the unresolved_events review queue.
    # Called when a non-new_task event could not be matched to any existing DB task
    # after all 4 match stages (exact, partial, fuzzy, semantic).
    # No task is created — these events require human review before any action is taken.
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO unresolved_events (
            event_type, task_text, owner, status,
            deadline, blocker, dependency, reason, source_input
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        event.get("event_type"),
        event.get("task_text"),
        event.get("owner"),
        event.get("status"),
        event.get("deadline"),
        event.get("blocker"),
        event.get("dependency"),
        "no_match_found",
        source_input,
    ))

    conn.commit()
    cur.close()
    conn.close()


# ---------------------------------------------------------------------------
# Job store (agent_jobs table)
# ---------------------------------------------------------------------------

def ensure_jobs_table():
    # Create agent_jobs if it doesn't exist yet.
    # Called once at API startup so no manual migration is needed.
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_jobs (
            job_id UUID PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'running',
            result JSONB,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_jobs_created_at ON agent_jobs(created_at)
    """)
    conn.commit()
    cur.close()
    conn.close()


def create_job(job_id: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO agent_jobs (job_id, status) VALUES (%s, 'running')",
        (job_id,),
    )
    conn.commit()
    cur.close()
    conn.close()


def complete_job(job_id: str, result: dict):
    import json as _json
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE agent_jobs SET status = 'completed', result = %s WHERE job_id = %s",
        (_json.dumps(result), job_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def fail_job(job_id: str, error: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE agent_jobs SET status = 'failed', error = %s WHERE job_id = %s",
        (error, job_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_job(job_id: str):
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT job_id, status, result, error FROM agent_jobs WHERE job_id = %s",
            (job_id,),
        )
        row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def cleanup_old_jobs(max_age_hours: int = 24):
    # Delete completed/failed jobs older than max_age_hours to prevent unbounded table growth.
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM agent_jobs WHERE created_at < NOW() - INTERVAL '%s hours'",
        (max_age_hours,),
    )
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return deleted


# ---------------------------------------------------------------------------
# Task reads
# ---------------------------------------------------------------------------

def fetch_task_by_normalized_text(normalized_text: str):
    # Check if a task with this normalized text already exists in the DB.
    # Used as a deduplication guard in store_tasks — prevents inserting the same
    # task twice when LLM output varies slightly across runs.
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT task_id
            FROM tasks
            WHERE normalized_task_text = %s
              AND is_active = TRUE
            LIMIT 1
        """, (normalized_text,))
        row = cur.fetchone()
    conn.close()
    return row["task_id"] if row else None


def fetch_active_tasks():
    # Fetch all active tasks for the match node to compare incoming events against.
    # Returns all columns needed for exact, partial, and fuzzy matching.
    # task_embedding is included here for completeness but semantic search uses
    # fetch_semantic_task_match() with a vector query instead.
    query = """
        SELECT
            task_id,
            task_text,
            normalized_task_text,
            owner,
            status,
            deadline,
            blocker,
            task_embedding,
            created_at,
            updated_at
        FROM tasks
        WHERE is_active = TRUE
        ORDER BY updated_at DESC, created_at DESC
    """

    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query)
        rows = cur.fetchall()

    return [dict(row) for row in rows]


def fetch_semantic_task_match(task_text: str):
    # Find the closest active task using pgvector cosine similarity (<=> operator).
    # Returns the single best match row with a similarity_score field,
    # or None if no tasks exist or the input is empty.
    # The match node applies a minimum threshold of 0.60 before accepting the result.
    if not task_text:
        return None

    embedding = get_embedding(task_text)
    if not embedding:
        return None

    conn = get_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT
                task_id,
                task_text,
                normalized_task_text,
                owner,
                status,
                deadline,
                blocker,
                task_embedding,
                1 - (task_embedding <=> %s::vector) AS similarity_score
            FROM tasks
            WHERE is_active = TRUE
              AND task_embedding IS NOT NULL
            ORDER BY task_embedding <=> %s::vector
            LIMIT 1
        """, (embedding, embedding))

        row = cur.fetchone()

    conn.close()

    return dict(row) if row else None
