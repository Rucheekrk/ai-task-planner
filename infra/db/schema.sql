CREATE EXTENSION IF NOT EXISTS "pgcrypto";

--Task table: Stores current latest state of each task
CREATE TABLE tasks (
    task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_text TEXT NOT NULL,
    normalized_task_text TEXT NOT NULL,
    owner TEXT,
    status TEXT DEFAULT 'not_started',
    deadline TEXT,
    blocker TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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

CREATE INDEX idx_tasks_normalized_task_text ON tasks(normalized_task_text);
CREATE INDEX idx_tasks_owner ON tasks(owner);
CREATE INDEX idx_task_events_task_id ON task_events(task_id);
CREATE INDEX idx_task_events_event_type ON task_events(event_type);
CREATE INDEX idx_task_events_created_at ON task_events(created_at);