ALTER TABLE jobs ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'owner';
ALTER TABLE artifacts ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'owner';

DROP INDEX artifacts_cache_key;
CREATE INDEX artifacts_owner_key ON artifacts (owner_id, cache_key, created_at);
CREATE INDEX jobs_owner_state ON jobs (owner_id, state, queue);

CREATE TABLE idempotency_v3 (
    owner_id TEXT NOT NULL,
    key TEXT NOT NULL,
    route TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'done')),
    status INTEGER,
    body TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (owner_id, key)
) WITHOUT ROWID;
INSERT INTO idempotency_v3
    (owner_id, key, route, request_digest, state, status, body, created_at, expires_at)
    SELECT 'owner', key, route, request_digest, state, status, body, created_at, expires_at
    FROM idempotency;
DROP TABLE idempotency;
ALTER TABLE idempotency_v3 RENAME TO idempotency;
CREATE INDEX idempotency_expires ON idempotency (expires_at);

UPDATE jobs SET doc = json_set(doc, '$.owner_id', 'owner');

CREATE TABLE credentials (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    label TEXT,
    last4 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    key_id TEXT,
    nonce BLOB,
    ciphertext BLOB,
    UNIQUE (owner_id, provider)
);
CREATE INDEX credentials_owner ON credentials (owner_id, created_at);
