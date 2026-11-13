BEGIN;
CREATE TABLE report_runs (
    id INTEGER PRIMARY KEY,
    template_key TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    generated_by INTEGER REFERENCES users(id),
    period_start TEXT,
    period_end TEXT,
    output_relative_path TEXT,
    qualifications TEXT NOT NULL
);

INSERT INTO schema_migrations(version, name, applied_at)
VALUES (2, '002_report_runs', datetime('now'));
COMMIT;
