import psycopg2
from psycopg2.extras import RealDictCursor
from pgvector.psycopg2 import register_vector  # enable pgvector support for psycopg2
from apps.utils.embeddings import get_embedding
import os


# Create and return a PostgreSQL database connection
def get_connection():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "task_planner"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )
    register_vector(conn) #required for pgvector

    return conn


# Insert a new task into the tasks table and return its task_id
def insert_task(task):
    conn = get_connection()
    cur = conn.cursor()

    embedding = get_embedding(task.get("task_text")) # generating embedding before insert

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


# Insert every extracted event into the task_events history table
def insert_event(event):
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


# Update a single field of an existing task
def update_task_field(task_id, field_name, field_value):
    # Allow only specific fields to prevent SQL injection
    allowed_fields = {"status", "deadline", "owner", "blocker", "priority"}

    if field_name not in allowed_fields:
        raise ValueError(f"Invalid field name: {field_name}")
    
    # Create DB connection
    conn = get_connection()
    cur = conn.cursor()

    # Build dynamic SQL safely using allowed field names
    query = f"""
        UPDATE tasks
        SET {field_name} = %s,
            updated_at = NOW()
        WHERE task_id = %s
    """

    # Execute update query
    cur.execute(query, (field_value, task_id))

    # Commit transaction
    conn.commit()

    # Close DB connection
    cur.close()
    conn.close()

# Update subtasks array for an existing task (separate function due to array type)
def update_task_subtasks(task_id, subtasks: list):
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


# Fetch an existing active task by exact normalized text (used for deduplication before insert)
def fetch_task_by_normalized_text(normalized_text: str):
    """
    Return the task_id of an existing active task whose normalized_task_text
    matches exactly, or None if no such task exists.
    """
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


# Fetch active tasks (passed on for exact, partial or fuzzy match in match node)
def fetch_active_tasks():
    """
    Fetch active/open tasks from DB for matching against new transcript tasks.
    """
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


# Fetch semantic task match (passed on for semantic match in match node)
def fetch_semantic_task_match(task_text: str):
    """
    Find the nearest active task in DB using pgvector similarity search.
    Returns the best matching task row with similarity score, or None.
    """
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
