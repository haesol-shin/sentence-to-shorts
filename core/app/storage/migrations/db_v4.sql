-- One row per provider request. The event id is <job_id>:<attempt>:<call_seq>:<try>;
-- a repeated id is ignored by the writer, and cost is never stored here.
CREATE TABLE usage_events (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    job_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    call_seq INTEGER NOT NULL CHECK (call_seq >= 1),
    try_index INTEGER NOT NULL CHECK (try_index >= 0),
    stage TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT,
    credential_id TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_write_tokens INTEGER,
    outcome TEXT NOT NULL CHECK (outcome IN ('ok', 'failed')),
    price_version TEXT
);
CREATE INDEX usage_events_owner_time ON usage_events (owner_id, occurred_at);
CREATE INDEX usage_events_job ON usage_events (job_id);

-- Usage.cost_usd was always null; canonical JSON forbids floats. Old usage
-- entries keep their other fields and gain cache_write_tokens through the
-- schema default when the document is read again.
UPDATE jobs SET doc = json_set(doc, '$.usage', (
    SELECT json_group_array(json_remove(value, '$.cost_usd'))
    FROM json_each(doc, '$.usage')
));
