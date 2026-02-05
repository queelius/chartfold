-- chartfold SQLite schema
-- Every fact table has `source` and `source_doc_id` for provenance tracking.
-- Idempotent loading: DELETE WHERE source = ? then INSERT.

CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    name TEXT,
    date_of_birth TEXT,  -- ISO YYYY-MM-DD
    gender TEXT,
    mrn TEXT,
    address TEXT,
    phone TEXT,
    UNIQUE(source, name, date_of_birth)
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    doc_type TEXT,
    title TEXT,
    encounter_date TEXT,  -- ISO YYYY-MM-DD
    file_path TEXT,
    file_size_kb INTEGER,
    UNIQUE(source, doc_id)
);

CREATE TABLE IF NOT EXISTS encounters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_doc_id TEXT,
    encounter_date TEXT,  -- ISO YYYY-MM-DD
    encounter_end TEXT,
    encounter_type TEXT,
    facility TEXT,
    provider TEXT,
    reason TEXT,
    discharge_disposition TEXT
);

CREATE TABLE IF NOT EXISTS lab_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_doc_id TEXT,
    test_name TEXT NOT NULL,
    test_loinc TEXT,
    panel_name TEXT,
    value TEXT,            -- Original text: handles "<0.5", "positive", etc.
    value_numeric REAL,    -- Parsed number: NULL when not parseable
    unit TEXT,
    ref_range TEXT,
    interpretation TEXT,   -- H, L, N, A, etc.
    result_date TEXT,      -- ISO YYYY-MM-DD
    status TEXT
);

CREATE INDEX IF NOT EXISTS idx_lab_results_date ON lab_results(result_date);
CREATE INDEX IF NOT EXISTS idx_lab_results_test ON lab_results(test_name);
CREATE INDEX IF NOT EXISTS idx_lab_results_loinc ON lab_results(test_loinc);
CREATE INDEX IF NOT EXISTS idx_lab_results_source ON lab_results(source);

CREATE TABLE IF NOT EXISTS vitals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_doc_id TEXT,
    vital_type TEXT NOT NULL,  -- bp_systolic, bp_diastolic, weight, height, temp, hr, rr, spo2, bmi
    value REAL,
    value_text TEXT,
    unit TEXT,
    recorded_date TEXT  -- ISO YYYY-MM-DD
);

CREATE INDEX IF NOT EXISTS idx_vitals_date ON vitals(recorded_date);
CREATE INDEX IF NOT EXISTS idx_vitals_type ON vitals(vital_type);

CREATE TABLE IF NOT EXISTS medications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_doc_id TEXT,
    name TEXT NOT NULL,
    rxnorm_code TEXT,
    status TEXT,
    sig TEXT,
    route TEXT,
    start_date TEXT,
    stop_date TEXT,
    prescriber TEXT
);

CREATE INDEX IF NOT EXISTS idx_medications_status ON medications(status);

CREATE TABLE IF NOT EXISTS conditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_doc_id TEXT,
    condition_name TEXT NOT NULL,
    icd10_code TEXT,
    snomed_code TEXT,
    clinical_status TEXT,
    onset_date TEXT,
    resolved_date TEXT,
    category TEXT
);

CREATE INDEX IF NOT EXISTS idx_conditions_status ON conditions(clinical_status);
CREATE INDEX IF NOT EXISTS idx_conditions_icd ON conditions(icd10_code);

CREATE TABLE IF NOT EXISTS procedures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_doc_id TEXT,
    name TEXT NOT NULL,
    snomed_code TEXT,
    cpt_code TEXT,
    procedure_date TEXT,  -- ISO YYYY-MM-DD
    provider TEXT,
    facility TEXT,
    operative_note TEXT,
    status TEXT
);

CREATE INDEX IF NOT EXISTS idx_procedures_date ON procedures(procedure_date);

CREATE TABLE IF NOT EXISTS pathology_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_doc_id TEXT,
    procedure_id INTEGER,  -- FK to procedures(id)
    report_date TEXT,      -- ISO YYYY-MM-DD
    specimen TEXT,
    diagnosis TEXT,
    gross_description TEXT,
    microscopic_description TEXT,
    staging TEXT,
    margins TEXT,
    lymph_nodes TEXT,
    full_text TEXT,
    FOREIGN KEY (procedure_id) REFERENCES procedures(id)
);

CREATE INDEX IF NOT EXISTS idx_pathology_date ON pathology_reports(report_date);

CREATE TABLE IF NOT EXISTS imaging_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_doc_id TEXT,
    study_name TEXT,
    modality TEXT,         -- CT, MRI, US, XR, PET, etc.
    study_date TEXT,       -- ISO YYYY-MM-DD
    ordering_provider TEXT,
    findings TEXT,
    impression TEXT,
    full_text TEXT
);

CREATE INDEX IF NOT EXISTS idx_imaging_date ON imaging_reports(study_date);
CREATE INDEX IF NOT EXISTS idx_imaging_modality ON imaging_reports(modality);

CREATE TABLE IF NOT EXISTS clinical_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_doc_id TEXT,
    note_type TEXT,
    author TEXT,
    note_date TEXT,        -- ISO YYYY-MM-DD
    content TEXT,
    content_format TEXT DEFAULT 'text'
);

CREATE INDEX IF NOT EXISTS idx_notes_date ON clinical_notes(note_date);
CREATE INDEX IF NOT EXISTS idx_notes_type ON clinical_notes(note_type);

CREATE TABLE IF NOT EXISTS immunizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_doc_id TEXT,
    vaccine_name TEXT,
    cvx_code TEXT,
    admin_date TEXT,       -- ISO YYYY-MM-DD
    lot_number TEXT,
    site TEXT,
    status TEXT
);

CREATE TABLE IF NOT EXISTS allergies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_doc_id TEXT,
    allergen TEXT,
    reaction TEXT,
    severity TEXT,
    status TEXT,
    onset_date TEXT
);

CREATE TABLE IF NOT EXISTS social_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_doc_id TEXT,
    category TEXT,
    value TEXT,
    recorded_date TEXT
);

CREATE TABLE IF NOT EXISTS family_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_doc_id TEXT,
    relation TEXT,
    condition TEXT,
    age_at_onset TEXT,
    deceased INTEGER  -- 0 or 1
);

CREATE TABLE IF NOT EXISTS mental_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_doc_id TEXT,
    instrument TEXT,       -- PHQ-9, PHQ-2, GAD-7, etc.
    question TEXT,
    answer TEXT,
    score INTEGER,
    total_score INTEGER,
    recorded_date TEXT
);

CREATE TABLE IF NOT EXISTS load_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    loaded_at TEXT NOT NULL,  -- ISO datetime
    duration_seconds REAL,
    patients_count INTEGER DEFAULT 0,
    documents_count INTEGER DEFAULT 0,
    encounters_count INTEGER DEFAULT 0,
    lab_results_count INTEGER DEFAULT 0,
    vitals_count INTEGER DEFAULT 0,
    medications_count INTEGER DEFAULT 0,
    conditions_count INTEGER DEFAULT 0,
    procedures_count INTEGER DEFAULT 0,
    pathology_reports_count INTEGER DEFAULT 0,
    imaging_reports_count INTEGER DEFAULT 0,
    clinical_notes_count INTEGER DEFAULT 0,
    immunizations_count INTEGER DEFAULT 0,
    allergies_count INTEGER DEFAULT 0,
    social_history_count INTEGER DEFAULT 0,
    family_history_count INTEGER DEFAULT 0,
    mental_status_count INTEGER DEFAULT 0,
    source_assets_count INTEGER DEFAULT 0
);

-- Personal notes / analysis storage (created by Claude or user)
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,        -- ISO datetime
    updated_at TEXT NOT NULL,        -- ISO datetime
    ref_table TEXT,                  -- optional: "lab_results", "encounters", etc.
    ref_id INTEGER                   -- optional: row ID in ref_table
);

CREATE TABLE IF NOT EXISTS note_tags (
    note_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
    UNIQUE(note_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created_at);
CREATE INDEX IF NOT EXISTS idx_notes_ref ON notes(ref_table, ref_id);
CREATE INDEX IF NOT EXISTS idx_note_tags_tag ON note_tags(tag);

-- Source assets (PDFs, images, etc. not parsed but tracked)
CREATE TABLE IF NOT EXISTS source_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    asset_type TEXT NOT NULL,      -- pdf, png, html, xsl, etc.
    file_path TEXT NOT NULL,       -- absolute path on disk
    file_name TEXT NOT NULL,       -- basename for display
    file_size_kb INTEGER,
    content_type TEXT,             -- MIME type
    title TEXT,                    -- from TOC or inferred from directory
    encounter_date TEXT,           -- ISO YYYY-MM-DD if known
    encounter_id TEXT,             -- e.g., V00003336701 (MEDITECH)
    doc_id TEXT,                   -- cross-ref to documents.doc_id (nullable)
    ref_table TEXT,                -- clinical table (nullable)
    ref_id INTEGER,                -- row ID in ref_table (nullable)
    metadata TEXT                  -- JSON blob for source-specific extras
);

CREATE INDEX IF NOT EXISTS idx_source_assets_source ON source_assets(source);
CREATE INDEX IF NOT EXISTS idx_source_assets_type ON source_assets(asset_type);
CREATE INDEX IF NOT EXISTS idx_source_assets_date ON source_assets(encounter_date);
CREATE INDEX IF NOT EXISTS idx_source_assets_ref ON source_assets(ref_table, ref_id);
