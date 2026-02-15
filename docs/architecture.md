# Architecture

chartfold uses a three-stage pipeline to process EHR data from multiple sources into a unified SQLite database.

## Pipeline Overview

```
┌─────────────────────┐
│  Raw EHR Files      │  XML, FHIR JSON, etc.
│  (Epic, MEDITECH,   │
│   athenahealth)     │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Source Parser      │  sources/epic.py, meditech.py, athena.py
│                     │  Extracts data into source-specific dicts
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Adapter            │  adapters/epic_adapter.py, etc.
│                     │  Normalizes to UnifiedRecords dataclasses
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  DB Loader          │  db.py + schema.sql
│                     │  Idempotent load into SQLite tables
└─────────────────────┘
```

## Stage Details

### 1. Source Parsers (`sources/`)

Each EHR format has a dedicated parser:

| Parser | Input Format | Key Features |
|--------|-------------|--------------|
| `epic.py` | CDA R2 XML | Uses `core/cda.py` for namespace handling |
| `meditech.py` | CCDA XML + FHIR JSON | Dual-format merge with deduplication |
| `athena.py` | FHIR R4 XML | Uses `core/fhir.py` for resource extraction |

Parsers return a dict with keys like `lab_results`, `medications`, `conditions`, etc.

**Source Configurations** (`sources/base.py`):
- `SourceConfig` dataclass defines per-EHR settings
- Section title mappings, file discovery patterns
- XML recovery mode for malformed documents

### 2. Adapters (`adapters/`)

Adapters normalize source-specific data into `UnifiedRecords`:

- Normalize dates to ISO 8601 (`YYYY-MM-DD`)
- Parse numeric values from text
- Deduplicate records using composite keys
- Map to dataclass instances (`models.py`)

**Key Helpers**:
- `core/utils.py:normalize_date_to_iso()` — Date normalization
- `core/utils.py:deduplicate_by_key()` — Composite key deduplication

### 3. DB Loader (`db.py`)

The loader is **idempotent**:
1. `DELETE FROM table WHERE source = ?` — Remove existing data for source
2. `INSERT` new records
3. Commit

This means re-running `chartfold load epic` safely replaces Epic data.

## Database Schema

16 clinical tables + system tables:

```sql
-- Core
patients, documents, encounters

-- Clinical data
lab_results, vitals, medications, conditions
procedures, pathology_reports, imaging_reports
clinical_notes, immunizations, allergies
social_history, family_history, mental_status

-- System
load_log        -- Audit trail
notes           -- Personal annotations
note_tags       -- Tag taxonomy
source_assets   -- Original file references
```

**Key Indexes**:
- Lab dates/test names/LOINC codes
- Vital types/dates
- Procedure/imaging dates
- Pathology reports FK to procedures (CASCADE)

## MEDITECH Dual-Format Merge

MEDITECH is the most complex source, merging two parallel data streams:

**FHIR JSON** (`US Core FHIR Resources.json`):
- Structured coded data (LOINC, ICD-10, RxNorm)
- Encounters, conditions, medications, observations, immunizations

**CCDA XML** (`CCDA/*.xml`):
- HTML-table-based extraction
- Labs, meds, notes, vitals, allergies, social/family/mental history

The adapter deduplicates across formats using composite keys:
- Labs: `(test.lower(), date_iso, value)`
- Conditions: `name.lower()`

FHIR conditions override CCDA problems when names match.

## Data Model (`models.py`)

16 dataclass types mapping 1:1 to SQLite tables:

- All dates are ISO `YYYY-MM-DD` strings
- Every record carries a `source` field for provenance
- `UnifiedRecords` container holds all records from a single source load

Lab results have both:
- `value` (text) — Handles `<0.5`, `positive`, etc.
- `value_numeric` (float) — `NULL` when not parseable

## Analysis Modules (`analysis/`)

Parameterized query helpers for data access:

| Module | Purpose |
|--------|---------|
| `lab_trends.py` | Lab series, abnormals, available tests |
| `medications.py` | Active meds, reconciliation, cross-source grouping |
| `surgical_timeline.py` | Procedures with linked pathology/imaging/meds |
| `visit_prep.py` | Bundle recent data for visit date |
| `visit_diff.py` | Everything new since date X |
| `data_quality.py` | Cross-source duplicate detection |
| `cross_source.py` | Encounter matching by date |

## Export Formats

| Format | Module | Features |
|--------|--------|----------|
| Markdown | `export.py` | Visit-focused, optional PDF |
| HTML SPA | `spa/export.py` | Embedded SQLite via sql.js, client-side queries, charts |
| JSON | `export_full.py` | Round-trip capable backup |
| Hugo | `hugo/generate.py` | Full static site with charts |

## MCP Server (`mcp/server.py`)

FastMCP server with 22 tools:
- SQL & schema queries
- Lab trends and abnormals
- Medication reconciliation
- Visit preparation
- Personal notes CRUD

Configuration in `mcp/config.json`.
