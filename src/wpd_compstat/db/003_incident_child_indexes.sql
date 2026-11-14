BEGIN;
CREATE INDEX IF NOT EXISTS idx_vehicles_incident ON vehicles(incident_id);
CREATE INDEX IF NOT EXISTS idx_persons_incident ON sensitive_persons(incident_id);
CREATE INDEX IF NOT EXISTS idx_citations_incident ON citations(incident_id);
CREATE INDEX IF NOT EXISTS idx_field_history_incident ON incident_field_history(incident_id);
CREATE INDEX IF NOT EXISTS idx_conflicts_incident ON incident_conflicts(incident_id);
CREATE INDEX IF NOT EXISTS idx_exceptions_incident ON exception_queue(incident_id);

INSERT INTO schema_migrations(version, name, applied_at)
VALUES (3, '003_incident_child_indexes', datetime('now'));
COMMIT;
