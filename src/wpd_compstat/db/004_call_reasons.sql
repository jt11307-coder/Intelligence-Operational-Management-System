BEGIN;
CREATE TABLE IF NOT EXISTS call_reasons (
    code TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    match_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO schema_migrations(version, name, applied_at)
VALUES (4, '004_call_reasons', datetime('now'));
COMMIT;
