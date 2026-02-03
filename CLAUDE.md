# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Structure

Package code lives in `src/chartfold/`. Tests in `tests/`.

```bash
# Development setup
pip install -e ".[dev,mcp]"
```

## What This Is

`chartfold` is a patient-facing Python tool for collecting personal health data from multiple EHR (Electronic Health Record) systems and consolidating it into a single SQLite database. Patients can then query, analyze, and export their aggregated clinical data via CLI, MCP server (for LLM-assisted analysis), or Hugo/Markdown output. The goal is patient empowerment through data ownership — enabling time-series analysis, intelligent querying with tools like Claude Code, and organized preparation for medical visits.

## Commands

```bash
# Run all tests (478 tests, pytest)
python -m pytest tests/

# Run a single test file
python -m pytest tests/test_adapters.py

# Run a single test class or method
python -m pytest tests/test_adapters.py::TestEpicAdapter::test_lab_panel_explosion

# Run tests with coverage
python -m pytest tests/ --cov=chartfold --cov-report=term-missing

# Load data from EHR exports
python -m chartfold load epic <dir>        # Epic MyChart CDA exports
python -m chartfold load meditech <dir>    # MEDITECH Expanse exports
python -m chartfold load athena <dir>      # athenahealth/SIHF FHIR exports
python -m chartfold load all --epic-dir <> --meditech-dir <> --athena-dir <>

# Query and inspect
python -m chartfold query "SELECT test_name, value, result_date FROM lab_results ORDER BY result_date DESC"
python -m chartfold summary

# What's new since a given date (visit diff)
python -m chartfold diff 2025-01-01

# Export clinical summary as markdown
python -m chartfold export --output summary.md --lookback 6
python -m chartfold export --format pdf --output summary.pdf

# Generate personalized config from your data
python -m chartfold init-config

# Generate Hugo static site
python -m chartfold generate-site --hugo-dir ./site
python -m chartfold generate-site --hugo-dir ./site --config chartfold.toml

# Personal notes
python -m chartfold notes list --limit 20
python -m chartfold notes search --tag oncology --query "CEA"
python -m chartfold notes search --ref-table lab_results
python -m chartfold notes show <note-id>

# Start MCP server for Claude integration
python -m chartfold serve-mcp --db chartfold.db
```

## Architecture

### Three-Stage Data Pipeline

Every EHR source goes through the same pipeline, and each stage is independently testable:

```
Raw EHR files (XML/FHIR)
    ↓
[Source Parser]  → source-specific dict  (sources/epic.py, sources/meditech.py, sources/athena.py)
    ↓
[Adapter]        → UnifiedRecords        (adapters/epic_adapter.py, etc.)
    ↓
[DB Loader]      → SQLite tables         (db.py using schema.sql)
```

- **Shared parsing infrastructure** in `core/cda.py` (CDA R2 XML: namespace handling, section extraction, date formatting) and `core/fhir.py` (FHIR R4 Bundle: resource extraction by type, base64 decode of presented forms). Source parsers build on these.
- **Source parsers** handle format-specific XML/FHIR parsing and return dicts with keys like `lab_results`, `medications`, `problems`, `clinical_notes`, etc.
- **Adapters** normalize dates to ISO 8601, parse numeric values, deduplicate records, and map everything into dataclass instances (`models.py`).
- **DB loader** is idempotent: `DELETE FROM table WHERE source = ?` then `INSERT` for each source, so re-runs are safe.

The CLI prints a **stage comparison table** after loading to verify no silent data loss (parser count → adapter count → DB count).

### Source Configurations (sources/base.py)

`SourceConfig` dataclass defines per-EHR settings: section title mappings, file discovery patterns, XML recovery mode, and cumulative vs. per-encounter document models. Pre-built configs: `EPIC_CONFIG`, `MEDITECH_CONFIG`, `ATHENA_CONFIG`.

### MEDITECH Dual-Format Merge

Unlike Epic (CDA-only) and athena (FHIR-only), the MEDITECH adapter merges two parallel data streams:

- **FHIR JSON** (`US Core FHIR Resources.json`) — structured coded data (LOINC, ICD-10, RxNorm) for encounters, conditions, medications, observations, immunizations
- **CCDA XML** (`CCDA/*.xml`, UUID-named files) — HTML-table-based extraction for labs, meds, notes, vitals, allergies, social/family/mental history

The adapter deduplicates across formats using composite keys (e.g., `(test.lower(), date_iso, value)` for labs, `name.lower()` for conditions). FHIR conditions override CCDA problems when names match. This dual-format merge is the most complex adapter path and is tested with dedicated fixtures.

### Unified Data Model (models.py)

16 dataclass types mapping 1:1 to SQLite tables. All dates are ISO `YYYY-MM-DD` strings. Every record carries a `source` field for provenance tracking. The `UnifiedRecords` container holds all records from a single source load.

Lab results have both `value` (text, handles `<0.5`, `positive`) and `value_numeric` (float, NULL when not parseable).

### Database (db.py, schema.sql)

SQLite with WAL mode and foreign keys enabled. 16 clinical tables + `load_log` audit trail + `notes`/`note_tags` tables for personal annotations (notes can reference any clinical record via `ref_table`/`ref_id`). Key indexes on lab dates/test names/LOINC codes, vital types/dates, procedure/imaging dates. Pathology reports FK to procedures with CASCADE.

### MCP Server (mcp/server.py)

FastMCP server exposes 22 tools. Config in `mcp/config.json`.

- **SQL & schema**: `run_sql` (SELECT/WITH/PRAGMA only), `get_schema`
- **Labs**: `query_labs`, `get_lab_series_tool`, `get_available_tests_tool`, `get_abnormal_labs_tool`
- **Medications**: `get_medications`, `reconcile_medications_tool`
- **Clinical data**: `get_timeline`, `search_notes`, `get_pathology_report`
- **Visit & timeline analysis**: `get_visit_diff`, `get_visit_prep`, `get_surgical_timeline`
- **Cross-source**: `match_cross_source_encounters`, `get_data_quality_report`
- **Summary**: `get_database_summary`
- **Personal notes (CRUD)**: `save_note`, `get_note`, `search_notes_personal`, `delete_note`

### Data Access Modules (analysis/)

Parameterized query helpers that expose structured views of the data. These don't interpret or analyze — they surface data so that LLMs (via MCP) and the CLI can present it for the user or agent to reason about.

- `lab_trends.py` — lab values by test/date/LOINC, flagged abnormals, cross-source series with ref range discrepancy flags, available test listing
- `medications.py` — active meds, history, cross-source grouping that surfaces status conflicts
- `surgical_timeline.py` — procedures with linked pathology/imaging/meds by date proximity (pre-op 90d, post-op 30d windows)
- `visit_prep.py` — bundle recent data for a given visit date
- `visit_diff.py` — everything new since date X across all 8 clinical tables
- `data_quality.py` — cross-source duplicate detection, source coverage matrix
- `cross_source.py` — cross-source encounter matching by date

### Extractors (extractors/)

Specialized parsers for structured clinical data that don't fit neatly into the generic source parser flow:

- `labs.py` — CEA value extraction from both FHIR Observations and parsed CCDA lab results
- `pathology.py` — Structured pathology report parsing (diagnosis, staging, margins, lymph nodes) and procedure-linking by date proximity (default ≤14 days) with name similarity

### Formatters (formatters/)

- `markdown.py` — `MarkdownWriter` class for incremental markdown output (headings, tables, separators). Used by `format_epic_output()` and site generation.

### Configuration (config.py)

TOML config (`chartfold.toml`) for personalized settings. Key tests to chart, Hugo dashboard settings. Auto-generated from DB contents via `python -m chartfold init-config`.

### Export (export.py)

Structured markdown export of key clinical data (conditions, meds, labs, encounters, imaging, pathology, allergies). Optional PDF via pandoc. Designed for bringing to doctor visits.

### Example Data Sources

Real EHR exports live in `~/github/personal/health_stats/dr-tan/`:
- `HealthSummary_Jan_30_2026/` — Epic MyChart IHE XDM format (79 CDA XML documents in `IHE_XDM/Alexander1/`)
- `MedicalRecord_AlexanderTowell/` — MEDITECH Expanse bulk export (UUID-named XML, NDJSON TOC, per-admission folders)
- `SIHF_01-31-26/` — athenahealth FHIR R4 ambulatory summary (single XML in `Document_XML/`)

**Expected input directory structures per source:**

```
Epic:      input_dir/DOC0001.XML, DOC0002.XML, ...  (DOC\d{4}\.XML pattern)
MEDITECH:  input_dir/US Core FHIR Resources.json
           input_dir/CCDA/<uuid>.xml                 (UUID-named CCDA files)
           input_dir/Table of Contents.ndjson
athena:    input_dir/Document_XML/*AmbulatorySummary*.xml  (or directly in input_dir)
```

## Key Conventions

- All dates stored as ISO `YYYY-MM-DD` strings throughout the codebase. Date normalization lives in `core/utils.py` (`normalize_date_to_iso`).
- Source parsers use `lxml` with optional `recover=True` for XML with encoding issues (MEDITECH).
- Deduplication happens at the adapter stage using `deduplicate_by_key` from `core/utils.py`.
- Tests use pytest fixtures from `tests/conftest.py` with `tmp_db`, `sample_unified_records`, `sample_epic_data`, `sample_meditech_data`, `sample_athena_data`, and `surgical_db`.
- Roundtrip tests (`test_roundtrip.py`) verify that record counts are preserved through all pipeline stages.
- Requires Python 3.11+ (`tomllib` from stdlib). No `pyproject.toml` or `requirements.txt` yet. Dependencies: `lxml`, `mcp` (FastMCP), `pytest`. Optional: `pandoc` for PDF export, `hugo` for static site generation. Run as `python -m chartfold`.

## Adding a New EHR Source

1. Create `sources/newsource.py` with a `process_*_export(input_dir)` function returning a dict
2. Create `adapters/newsource_adapter.py` with a `*_to_unified(data) -> UnifiedRecords` function and `_parser_counts(data)` helper
3. Add a `SourceConfig` in `sources/base.py`
4. Wire into `cli.py` (add subcommand, `_load_newsource` function)
5. Add fixtures in `tests/conftest.py` and tests in `test_newsource.py`, `test_adapters.py`, `test_roundtrip.py`
