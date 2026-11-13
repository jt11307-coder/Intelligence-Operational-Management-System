BEGIN;
PRAGMA foreign_keys = ON;

CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    role TEXT NOT NULL CHECK (role IN (
        'administrator', 'crime_analyst', 'command_staff', 'supervisor', 'read_only'
    )),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id),
    deactivated_at TEXT
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    user_id INTEGER,
    username TEXT,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    detail TEXT,
    result TEXT NOT NULL
);
CREATE INDEX idx_audit_time ON audit_log(occurred_at);

CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by INTEGER
);

CREATE TABLE divisions (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    unit_type TEXT NOT NULL,
    parent_id INTEGER REFERENCES divisions(id),
    active INTEGER NOT NULL DEFAULT 1,
    confirmed INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE officers (
    id INTEGER PRIMARY KEY,
    badge TEXT,
    display_name TEXT NOT NULL,
    division_id INTEGER REFERENCES divisions(id),
    active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_officers_badge ON officers(badge);

CREATE TABLE command_assignments (
    id INTEGER PRIMARY KEY,
    officer_id INTEGER REFERENCES officers(id),
    user_id INTEGER REFERENCES users(id),
    division_id INTEGER NOT NULL REFERENCES divisions(id),
    title TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    CHECK (officer_id IS NOT NULL OR user_id IS NOT NULL)
);

CREATE TABLE zones (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    zone_type TEXT NOT NULL,
    description TEXT,
    streets_json TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE zone_neighbors (
    zone_id INTEGER NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    neighbor_id INTEGER NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    PRIMARY KEY (zone_id, neighbor_id),
    CHECK (zone_id <> neighbor_id)
);

CREATE TABLE locations (
    id INTEGER PRIMARY KEY,
    raw_address TEXT,
    normalized_address TEXT,
    street TEXT,
    intersection TEXT,
    business TEXT,
    city TEXT,
    latitude REAL,
    longitude REAL,
    coord_quality TEXT NOT NULL DEFAULT 'none' CHECK (coord_quality IN ('exact', 'approximate', 'none')),
    coord_source TEXT,
    zone_id INTEGER REFERENCES zones(id)
);
CREATE INDEX idx_locations_norm ON locations(normalized_address);
CREATE INDEX idx_locations_street ON locations(street);

CREATE TABLE source_pdfs (
    id INTEGER PRIMARY KEY,
    original_filename TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    byte_size INTEGER NOT NULL,
    page_count INTEGER,
    stored_relative_path TEXT NOT NULL,
    encrypted INTEGER NOT NULL DEFAULT 1,
    first_stored_at TEXT NOT NULL
);

CREATE TABLE source_pages (
    id INTEGER PRIMARY KEY,
    source_pdf_id INTEGER NOT NULL REFERENCES source_pdfs(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    text_enc TEXT NOT NULL,
    UNIQUE (source_pdf_id, page_number)
);

CREATE TABLE import_batches (
    id INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id),
    finished_at TEXT,
    summary_json TEXT,
    error TEXT
);
CREATE INDEX idx_batches_status ON import_batches(status);

CREATE TABLE import_files (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    source_pdf_id INTEGER REFERENCES source_pdfs(id),
    original_filename TEXT NOT NULL,
    sha256 TEXT,
    page_count INTEGER,
    declared_start TEXT,
    declared_end TEXT,
    status TEXT NOT NULL,
    error TEXT
);

CREATE TABLE incidents (
    id INTEGER PRIMARY KEY,
    cad_number TEXT NOT NULL,
    event_date TEXT,
    event_time TEXT,
    received_time TEXT,
    dispatch_time TEXT,
    arrival_time TEXT,
    clear_time TEXT,
    call_type TEXT,
    call_classification TEXT,
    call_source TEXT,
    priority TEXT,
    disposition TEXT,
    final_disposition TEXT,
    call_taker TEXT,
    location_id INTEGER REFERENCES locations(id),
    business_landmark TEXT,
    extraction_confidence REAL,
    review_status TEXT NOT NULL DEFAULT 'unreviewed',
    source_pdf_id INTEGER REFERENCES source_pdfs(id),
    source_page INTEGER,
    first_batch_id INTEGER REFERENCES import_batches(id),
    last_batch_id INTEGER REFERENCES import_batches(id),
    match_key TEXT NOT NULL UNIQUE,
    excluded INTEGER NOT NULL DEFAULT 0,
    exclusion_reason TEXT,
    follow_up INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_incidents_date ON incidents(event_date);
CREATE INDEX idx_incidents_cad ON incidents(cad_number);
CREATE INDEX idx_incidents_excluded ON incidents(excluded);

CREATE TABLE incident_field_history (
    id INTEGER PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    batch_id INTEGER REFERENCES import_batches(id),
    changed_at TEXT NOT NULL,
    changed_by INTEGER REFERENCES users(id),
    change_reason TEXT NOT NULL
);

CREATE TABLE incident_conflicts (
    id INTEGER PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    batch_id INTEGER REFERENCES import_batches(id),
    field_name TEXT NOT NULL,
    existing_value TEXT,
    incoming_value TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    resolved_by INTEGER REFERENCES users(id),
    resolved_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_conflicts_status ON incident_conflicts(status);

CREATE TABLE narratives (
    id INTEGER PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    narrative_time TEXT,
    author TEXT,
    body TEXT NOT NULL,
    body_sha256 TEXT NOT NULL,
    source_pdf_id INTEGER REFERENCES source_pdfs(id),
    source_page INTEGER,
    UNIQUE (incident_id, body_sha256)
);
CREATE INDEX idx_narratives_incident ON narratives(incident_id, sequence);

CREATE VIRTUAL TABLE narratives_fts USING fts5(
    body,
    author,
    content='narratives',
    content_rowid='id'
);

CREATE TRIGGER narratives_ai AFTER INSERT ON narratives BEGIN
    INSERT INTO narratives_fts(rowid, body, author) VALUES (new.id, new.body, new.author);
END;

CREATE TRIGGER narratives_ad AFTER DELETE ON narratives BEGIN
    INSERT INTO narratives_fts(narratives_fts, rowid, body, author)
    VALUES ('delete', old.id, old.body, old.author);
END;

CREATE TRIGGER narratives_au AFTER UPDATE ON narratives BEGIN
    INSERT INTO narratives_fts(narratives_fts, rowid, body, author)
    VALUES ('delete', old.id, old.body, old.author);
    INSERT INTO narratives_fts(rowid, body, author) VALUES (new.id, new.body, new.author);
END;

CREATE TABLE incident_officers (
    id INTEGER PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    officer_id INTEGER REFERENCES officers(id),
    role TEXT NOT NULL,
    unit_call_sign TEXT,
    CHECK (officer_id IS NOT NULL OR unit_call_sign IS NOT NULL)
);
CREATE INDEX idx_incident_officers_incident ON incident_officers(incident_id);

CREATE TABLE vehicles (
    id INTEGER PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    role TEXT,
    description TEXT,
    state TEXT,
    plate_enc TEXT
);

CREATE TABLE sensitive_persons (
    id INTEGER PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    payload_enc TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE report_references (
    id INTEGER PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    ref_type TEXT NOT NULL,
    ref_number TEXT NOT NULL,
    UNIQUE (incident_id, ref_type, ref_number)
);

CREATE TABLE citations (
    id INTEGER PRIMARY KEY,
    incident_id INTEGER REFERENCES incidents(id) ON DELETE CASCADE,
    traffic_activity_id INTEGER,
    citation_number TEXT,
    verified_violation INTEGER NOT NULL DEFAULT 0,
    warning INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL
);

CREATE TABLE classifications (
    id INTEGER PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    polarity TEXT NOT NULL CHECK (polarity IN (
        'occurred', 'alleged', 'historical', 'negated', 'precautionary', 'contradictory', 'insufficient'
    )),
    confidence TEXT NOT NULL CHECK (confidence IN (
        'confirmed_structured', 'verified_narrative', 'probable_review', 'insufficient', 'contradictory', 'user_accepted'
    )),
    counts_officially INTEGER NOT NULL DEFAULT 0,
    significant INTEGER NOT NULL DEFAULT 0,
    evidence_json TEXT NOT NULL,
    rule_key TEXT,
    status TEXT NOT NULL DEFAULT 'system',
    created_at TEXT NOT NULL,
    reviewed_by INTEGER REFERENCES users(id),
    reviewed_at TEXT
);
CREATE INDEX idx_class_incident ON classifications(incident_id);
CREATE INDEX idx_class_official ON classifications(category, counts_officially);

CREATE TABLE classification_history (
    id INTEGER PRIMARY KEY,
    classification_id INTEGER NOT NULL REFERENCES classifications(id) ON DELETE CASCADE,
    old_status TEXT,
    new_status TEXT,
    old_category TEXT,
    new_category TEXT,
    changed_by INTEGER,
    changed_at TEXT NOT NULL,
    reason TEXT
);

CREATE TABLE classification_rules (
    id INTEGER PRIMARY KEY,
    rule_key TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    confirmation TEXT NOT NULL DEFAULT 'starter_unconfirmed',
    updated_at TEXT NOT NULL,
    confirmed_by INTEGER REFERENCES users(id),
    confirmed_at TEXT
);

CREATE TABLE agency_codes (
    code TEXT PRIMARY KEY,
    label TEXT,
    definition TEXT,
    status TEXT NOT NULL DEFAULT 'unconfirmed',
    match_json TEXT,
    notes TEXT,
    confirmed_by INTEGER REFERENCES users(id),
    confirmed_at TEXT
);

CREATE TABLE code_mentions (
    id INTEGER PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    evidence TEXT NOT NULL,
    status TEXT NOT NULL,
    UNIQUE (incident_id, code)
);

CREATE TABLE cad_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    confirmation TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    confirmed_by INTEGER REFERENCES users(id),
    confirmed_at TEXT
);

CREATE TABLE patterns (
    id INTEGER PRIMARY KEY,
    pattern_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    pattern_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    confidence TEXT NOT NULL,
    limitations TEXT NOT NULL,
    trigger_rule TEXT NOT NULL,
    baseline_json TEXT NOT NULL,
    date_start TEXT,
    date_end TEXT,
    area_label TEXT,
    explanation TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE pattern_incidents (
    pattern_id INTEGER NOT NULL REFERENCES patterns(id) ON DELETE CASCADE,
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    PRIMARY KEY (pattern_id, incident_id)
);

CREATE TABLE pattern_reviews (
    id INTEGER PRIMARY KEY,
    pattern_id INTEGER NOT NULL REFERENCES patterns(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    decision TEXT NOT NULL CHECK (decision IN ('accept', 'reject', 'annotate', 'monitor')),
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE recommendations (
    id INTEGER PRIMARY KEY,
    pattern_id INTEGER REFERENCES patterns(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    identified TEXT NOT NULL,
    evidence TEXT NOT NULL,
    why TEXT NOT NULL,
    resources TEXT NOT NULL,
    measurement TEXT NOT NULL,
    limitations TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    reviewed_by INTEGER REFERENCES users(id),
    reviewed_at TEXT
);

CREATE TABLE compstat_cycles (
    id INTEGER PRIMARY KEY,
    start_date TEXT NOT NULL UNIQUE,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);

CREATE TABLE cycle_meetings (
    id INTEGER PRIMARY KEY,
    cycle_id INTEGER NOT NULL REFERENCES compstat_cycles(id) ON DELETE CASCADE,
    meeting_type TEXT NOT NULL,
    held_on TEXT,
    agenda TEXT,
    notes TEXT,
    decisions TEXT
);

CREATE TABLE assignments (
    id INTEGER PRIMARY KEY,
    action_number TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    geographic_area TEXT,
    baseline_period TEXT,
    baseline_measurements TEXT,
    commander_officer_id INTEGER REFERENCES officers(id),
    commander_user_id INTEGER REFERENCES users(id),
    objective TEXT,
    intervention TEXT,
    start_date TEXT,
    due_date TEXT,
    resources TEXT,
    planned_activity TEXT,
    success_metrics TEXT,
    status TEXT NOT NULL DEFAULT 'proposed',
    outcomes TEXT,
    final_assessment TEXT,
    follow_up_recommendation TEXT,
    cycle_id INTEGER REFERENCES compstat_cycles(id),
    urgent INTEGER NOT NULL DEFAULT 0,
    recommendation_id INTEGER REFERENCES recommendations(id),
    created_at TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id),
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_assignments_status ON assignments(status);

CREATE TABLE assignment_divisions (
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    division_id INTEGER NOT NULL REFERENCES divisions(id),
    participation TEXT NOT NULL CHECK (participation IN ('accountable', 'supporting')),
    PRIMARY KEY (assignment_id, division_id)
);

CREATE TABLE assignment_incidents (
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    PRIMARY KEY (assignment_id, incident_id)
);

CREATE TABLE assignment_notes (
    id INTEGER PRIMARY KEY,
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    note_type TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id)
);

CREATE TABLE outcome_measurements (
    id INTEGER PRIMARY KEY,
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    metric_name TEXT NOT NULL,
    baseline_value TEXT,
    current_value TEXT,
    measured_at TEXT NOT NULL,
    note TEXT
);

CREATE TABLE traffic_imports (
    id INTEGER PRIMARY KEY,
    original_filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    imported_by INTEGER REFERENCES users(id),
    row_count INTEGER NOT NULL,
    mapping_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    counting_rule_status TEXT NOT NULL,
    stored_relative_path TEXT NOT NULL
);

CREATE TABLE traffic_activity (
    id INTEGER PRIMARY KEY,
    import_id INTEGER NOT NULL REFERENCES traffic_imports(id) ON DELETE CASCADE,
    occurred_at TEXT,
    officer_name TEXT,
    shift_name TEXT,
    division_name TEXT,
    location_text TEXT,
    duty_type TEXT,
    directed INTEGER NOT NULL DEFAULT 0,
    stops INTEGER NOT NULL DEFAULT 0,
    citation_references INTEGER NOT NULL DEFAULT 0,
    verified_violations INTEGER NOT NULL DEFAULT 0,
    warnings INTEGER NOT NULL DEFAULT 0,
    dui INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_traffic_time ON traffic_activity(occurred_at);

CREATE TABLE saved_searches (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    filter_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, name)
);

CREATE TABLE saved_reports (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    template_key TEXT NOT NULL,
    filter_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, name)
);

CREATE TABLE presentation_drafts (
    id INTEGER PRIMARY KEY,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    commentary_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by INTEGER REFERENCES users(id),
    UNIQUE (period_start, period_end)
);

CREATE TABLE backups (
    id INTEGER PRIMARY KEY,
    relative_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by INTEGER,
    reason TEXT NOT NULL,
    plaintext_sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    verified_at TEXT,
    kind TEXT NOT NULL
);

CREATE TABLE exception_queue (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER REFERENCES import_batches(id),
    incident_id INTEGER REFERENCES incidents(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL,
    original_enc TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    resolution TEXT,
    resolved_by INTEGER,
    resolved_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_exceptions_status ON exception_queue(status);

CREATE TABLE geocode_reference (
    id INTEGER PRIMARY KEY,
    address_key TEXT NOT NULL UNIQUE,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    quality TEXT NOT NULL CHECK (quality IN ('exact', 'approximate')),
    source_name TEXT NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE TABLE staffing (
    id INTEGER PRIMARY KEY,
    division_id INTEGER NOT NULL REFERENCES divisions(id),
    shift_name TEXT,
    on_date TEXT NOT NULL,
    headcount REAL NOT NULL CHECK (headcount >= 0),
    note TEXT
);

CREATE TABLE data_deletions (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    snapshot_enc TEXT NOT NULL,
    deleted_by INTEGER,
    deleted_at TEXT NOT NULL
);

INSERT INTO schema_migrations(version, name, applied_at)
VALUES (1, '001_initial', datetime('now'));
COMMIT;
