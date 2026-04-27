CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS vector;

--Task table: Stores current latest state of each task
CREATE TABLE tasks (
    task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_text TEXT NOT NULL,
    normalized_task_text TEXT NOT NULL,
    owner TEXT,
    status TEXT DEFAULT 'not_started',
    deadline TEXT,
    blocker TEXT,
    priority TEXT DEFAULT 'medium',
    subtasks TEXT[] DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    task_embedding vector(384),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Migration (run if table already exists):
-- ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority TEXT DEFAULT 'medium';
-- ALTER TABLE tasks ADD COLUMN IF NOT EXISTS subtasks TEXT[] DEFAULT '{}';
-- ALTER TABLE tasks ADD COLUMN IF NOT EXISTS task_embedding vector(384);

--Extracted Events table: Stores every extracted event from input
CREATE TABLE task_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID REFERENCES tasks(task_id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    task_text TEXT NOT NULL,
    owner TEXT,
    status TEXT,
    deadline TEXT,
    blocker TEXT,
    dependency TEXT,
    match_method TEXT,
    match_confidence TEXT,
    source_input TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Unresolved Events table: Human review queue for update events that matched no existing task.
-- These are NOT auto-created as tasks — they require human review to decide:
-- link to an existing task, approve as new, or discard.
CREATE TABLE unresolved_events (
    unresolved_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,
    task_text TEXT NOT NULL,
    owner TEXT,
    status TEXT,
    deadline TEXT,
    blocker TEXT,
    dependency TEXT,
    reason TEXT NOT NULL DEFAULT 'no_match_found',
    source_input TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Migration (run if tables already exist):
-- CREATE TABLE IF NOT EXISTS unresolved_events (
--     unresolved_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
--     event_type TEXT NOT NULL,
--     task_text TEXT NOT NULL,
--     owner TEXT,
--     status TEXT,
--     deadline TEXT,
--     blocker TEXT,
--     dependency TEXT,
--     reason TEXT NOT NULL DEFAULT 'no_match_found',
--     source_input TEXT,
--     created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
-- );

-- Agent jobs table: persists async /run job state across restarts.
-- Rows older than 24 hours are purged by the cleanup helper in db.py.
CREATE TABLE IF NOT EXISTS agent_jobs (
    job_id UUID PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'running',   -- running | completed | failed
    result JSONB,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_jobs_created_at ON agent_jobs(created_at);

-- Migration (run against an existing DB):
-- CREATE TABLE IF NOT EXISTS agent_jobs (
--     job_id UUID PRIMARY KEY,
--     status TEXT NOT NULL DEFAULT 'running',
--     result JSONB,
--     error TEXT,
--     created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
-- );
-- CREATE INDEX IF NOT EXISTS idx_agent_jobs_created_at ON agent_jobs(created_at);

-- Source documents table: stores each unique input document exactly once.
-- task_events references this via source_doc_id instead of storing the full text per row.
-- content_hash (SHA256) enables fast exact-dedup without full-text comparison.
CREATE TABLE IF NOT EXISTS source_documents (
    doc_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    content_hash CHAR(64) NOT NULL UNIQUE,
    pipeline_result JSONB,          -- cached formatted API result; NULL until first successful run
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_source_documents_hash ON source_documents(content_hash);

-- Migration for existing DBs (run in order):
-- ALTER TABLE task_events ADD COLUMN IF NOT EXISTS source_doc_id UUID REFERENCES source_documents(doc_id);
-- ALTER TABLE task_events DROP COLUMN IF EXISTS source_input;

CREATE INDEX idx_tasks_normalized_task_text ON tasks(normalized_task_text);
CREATE INDEX idx_tasks_owner ON tasks(owner);
CREATE INDEX idx_task_events_task_id ON task_events(task_id);
CREATE INDEX idx_task_events_event_type ON task_events(event_type);
CREATE INDEX idx_task_events_created_at ON task_events(created_at);
CREATE INDEX idx_unresolved_events_event_type ON unresolved_events(event_type);
CREATE INDEX idx_unresolved_events_created_at ON unresolved_events(created_at);

-- pgvector HNSW index for fast approximate nearest-neighbour semantic search.
-- hnsw is preferred over ivfflat: works on empty tables, no reindex needed as data grows,
-- and delivers faster + more accurate queries at the cost of slightly more memory.
-- vector_cosine_ops matches the cosine similarity used in fetch_semantic_task_match().
CREATE INDEX idx_tasks_embedding_hnsw ON tasks
    USING hnsw (task_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Migration (run against existing DB — only needed if schema was applied before this index was added):
-- CREATE INDEX IF NOT EXISTS idx_tasks_embedding_hnsw ON tasks
--     USING hnsw (task_embedding vector_cosine_ops)
--     WITH (m = 16, ef_construction = 64);