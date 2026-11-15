CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    queue TEXT NOT NULL CHECK (queue IN ('light', 'heavy')),
    state TEXT NOT NULL CHECK (
        state IN ('queued', 'running', 'succeeded', 'failed', 'cancelling', 'cancelled')
    ),
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    video_id TEXT,
    created_at TEXT NOT NULL,
    doc TEXT NOT NULL
);
CREATE INDEX jobs_queue_state ON jobs (queue, state, created_at, id);
CREATE INDEX jobs_state ON jobs (state);
CREATE INDEX jobs_video_kind ON jobs (video_id, kind, state);

CREATE TABLE idempotency (
    key TEXT PRIMARY KEY,
    route TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'done')),
    status INTEGER,
    body TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE INDEX idempotency_expires ON idempotency (expires_at);
