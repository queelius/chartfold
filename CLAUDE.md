# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Structure

Package code lives in `src/chartfold/`. Tests in `tests/`.

```bash
# Development setup
pip install -e ".[dev,mcp]"
```

## What This Is

`chartfold` is a patient-facing Python tool for collecting personal health data from multiple EHR (Electronic Health Record) systems and consolidating it into a single SQLite database. Patients can then query, analyze, and export their aggregated clinical data via CLI, MCP server (for LLM-assisted analysis), or self-contained HTML SPA. The goal is patient empowerment through data ownership — enabling time-series analysis, intelligent querying with tools like Claude Code, and organized preparation for medical visits.

## Commands

```bash
# Run all tests (1000+ tests, pytest)
python -m pytest tests/

# Run a single test file
python -m pytest tests/test_adapters.py

# Run a single test class or method
python -m pytest tests/test_adapters.py::TestEpicAdapter::test_lab_panel_explosion

# Run tests with coverage
python -m pytest tests/ --cov=chartfold --cov-report=term-missing

# Lint (ruff configured in pyproject.toml)
ruff check src/ tests/
ruff format --check src/ tests/

# Load data from EHR exports
python -m chartfold load epic <dir>
python -m chartfold load meditech <dir>
python -m chartfold load athena <dir>
python -m chartfold load auto <dir-or-file>          # Auto-detect source type
python -m chartfold load mychart-visit <file.mhtml>   # MyChart visit page MHTML
python -m chartfold load mychart-test-result <file.mhtml>  # MyChart test result MHTML
python -m chartfold load all --epic-dir <> --meditech-dir <> --athena-dir <>
python -m chartfold load analyses <dir>               # Load analysis markdown files

# Query and inspect
python -m chartfold query "SELECT test_name, value, result_date FROM lab_results ORDER BY result_date DESC"
python -m chartfold summary

# What's new since a given date (visit diff)
python -m chartfold diff 2025-01-01

# Export formats: arkiv, html
python -m chartfold export arkiv --output ./arkiv/
python -m chartfold export arkiv --output ./arkiv/ --embed          # inline base64 assets
python -m chartfold export arkiv --output ./arkiv/ --exclude-notes
python -m chartfold export html --output summary.html
python -m chartfold export html --output summary.html --embed-images --config chartfold.toml

# Import from arkiv archive (round-trip capable)
python -m chartfold import ./arkiv/ --db new_chartfold.db
python -m chartfold import ./arkiv/ --validate-only
python -m chartfold import ./arkiv/ --db existing.db --overwrite

# Generate personalized config from your data
python -m chartfold init-config

# Personal notes
python -m chartfold notes list --limit 20
python -m chartfold notes search --tag oncology --query "CEA"
python -m chartfold notes show <note-id>

# Start MCP server for Claude integration
python -m chartfold serve-mcp --db chartfold.db
```

## Architecture

### Three-Stage Data Pipeline

Every EHR source goes through the same pipeline, and each stage is independently testable:

```
Raw EHR files (XML/FHIR/MHTML)
    ↓
[Source Parser]  → source-specific dict  (sources/*.py)
    ↓
[Adapter]        → UnifiedRecords        (adapters/*_adapter.py)
    ↓
[DB Loader]      → SQLite tables         (db.py using schema.sql)
```

- **Shared parsing infrastructure** in `core/cda.py` (CDA R2 XML: namespace handling, section extraction, date formatting) and `core/fhir.py` (FHIR R4 Bundle: resource extraction by type, base64 decode of presented forms). Source parsers build on these.
- **Source parsers** handle format-specific XML/FHIR/HTML parsing and return dicts with keys like `lab_results`, `medications`, `problems`, `clinical_notes`, etc.
- **Adapters** normalize dates to ISO 8601, parse numeric values, deduplicate records, and map everything into dataclass instances (`models.py`).
- **DB loader** uses UPSERT (INSERT...ON CONFLICT...DO UPDATE) for stable autoincrement IDs across re-imports. `replace=True` mode also cleans up stale records.

The CLI prints a **stage comparison table** after loading to verify no silent data loss (parser count → adapter count → DB count).

### Source Types

| Source | Format | Parser | Adapter |
|--------|--------|--------|---------|
| Epic MyChart | CDA R2 XML (IHE XDM) | `sources/epic.py` | `adapters/epic_adapter.py` |
| MEDITECH Expanse | CCDA XML + FHIR JSON (dual-format merge) | `sources/meditech.py` | `adapters/meditech_adapter.py` |
| athenahealth | FHIR R4 Bundle XML | `sources/athena.py` | `adapters/athena_adapter.py` |
| MyChart Visit MHTML | MIME HTML (visit notes, images) | `sources/mhtml_visit.py` | `adapters/mhtml_visit_adapter.py` |
| MyChart Test Result MHTML | MIME HTML (genomic panels) | `sources/mhtml_test_result.py` | `adapters/mhtml_test_result_adapter.py` |

### MEDITECH Dual-Format Merge

Unlike Epic (CDA-only) and athena (FHIR-only), the MEDITECH adapter merges two parallel data streams:

- **FHIR JSON** (`US Core FHIR Resources.json`) — structured coded data (LOINC, ICD-10, RxNorm) for encounters, conditions, medications, observations, immunizations
- **CCDA XML** (`CCDA/*.xml`, UUID-named files) — HTML-table-based extraction for labs, meds, notes, vitals, allergies, social/family/mental history

The adapter deduplicates across formats using composite keys (e.g., `(test.lower(), date_iso, value)` for labs, `name.lower()` for conditions). FHIR conditions override CCDA problems when names match. This dual-format merge is the most complex adapter path and is tested with dedicated fixtures.

### Unified Data Model (models.py)

17 dataclass types mapping 1:1 to SQLite tables (including `genetic_variants`). All dates are ISO `YYYY-MM-DD` strings. Every record carries a `source` field for provenance tracking. The `UnifiedRecords` container holds all records from a single source load.

Lab results have both `value` (text, handles `<0.5`, `positive`) and `value_numeric` (float, NULL when not parseable).

### Database (db.py, schema.sql)

SQLite with WAL mode and foreign keys enabled. 17 clinical tables + `load_log` audit trail + `notes`/`note_tags` + `analyses`/`analysis_tags` + `source_assets`. Key indexes on lab dates/test names/LOINC codes, vital types/dates, procedure/imaging dates. Pathology reports FK to procedures with CASCADE.

**UPSERT loading** (`_UNIQUE_KEYS` in `db.py`): Each table has a natural key used for conflict detection. `load_source(records, replace=True)` does UPSERT + stale cleanup (bulk import). `load_source(records, replace=False)` does UPSERT only (additive import, e.g., MHTML).

`db.query()` returns `list[dict]` (via `sqlite3.Row` factory).

### MCP Server (mcp/server.py)

FastMCP server with `CHARTFOLD_DB` env var for database path. Design principle: the LLM writes its own SQL for all reads via `run_sql` + `get_schema`. Write operations (notes, analyses) go through dedicated tools with controlled parameters.

### Data Access Modules (analysis/)

Parameterized query helpers that surface structured views of the data for LLMs (via MCP) and CLI:

- `lab_trends.py` — lab values by test/date/LOINC, flagged abnormals, cross-source series
- `medications.py` — active meds, history, cross-source grouping that surfaces status conflicts
- `surgical_timeline.py` — procedures with linked pathology/imaging/meds by date proximity
- `visit_prep.py` — bundle recent data for a given visit date
- `visit_diff.py` — everything new since date X across all clinical tables
- `data_quality.py` — cross-source duplicate detection, source coverage matrix
- `cross_source.py` — cross-source encounter matching by date

### Export Modules

- `spa/export.py` — Self-contained HTML SPA with embedded SQLite database via sql.js (WebAssembly). All data stays client-side with in-browser SQL queries. Supports `--embed-images` and `--config`.
- `export_arkiv.py` — Arkiv universal record format (JSONL + README.md + schema.yaml). Primary backup/restore format with full round-trip support. Source assets exported to `media/` or inline base64 via `--embed`.
- `import_arkiv.py` — Arkiv import with validation, FK remapping, tag unfolding, and source asset restoration.

### Configuration (config.py)

TOML config (`chartfold.toml`) for personalized settings. Key tests to chart, dashboard settings. Auto-generated from DB contents via `python -m chartfold init-config`.

## Key Conventions

- All dates stored as ISO `YYYY-MM-DD` strings. Date normalization in `core/utils.py` (`normalize_date_to_iso`).
- Source parsers use `lxml` with optional `recover=True` for XML with encoding issues (MEDITECH). MHTML parsers use Python stdlib `email` module + `lxml.html` XPath (NOT cssselect — `cssselect` requires an extra package).
- Deduplication happens at the adapter stage using `deduplicate_by_key` from `core/utils.py`.
- Tests use pytest fixtures from `tests/conftest.py` with `tmp_db`, `sample_unified_records`, `sample_epic_data`, `sample_meditech_data`, `sample_athena_data`, and `surgical_db`.
- Roundtrip tests (`test_roundtrip.py`) verify that record counts are preserved through all pipeline stages.
- Requires Python 3.11+ (`tomllib` from stdlib). Dependencies: `lxml`, `pyyaml`. Optional: `mcp` (FastMCP) for MCP server. Run as `python -m chartfold`.
- Ruff for linting (configured in `pyproject.toml`), line length 100, target Python 3.11.
- Coverage minimum: 68% (configured in `pyproject.toml`).

## Adding a New EHR Source

1. Create `sources/newsource.py` with a `process_*_export(input_dir)` function returning a dict
2. Create `adapters/newsource_adapter.py` with a `*_to_unified(data) -> UnifiedRecords` function and `_parser_counts(data)` helper
3. Add a `SourceConfig` in `sources/base.py` (if applicable)
4. Wire into `cli.py` (add subcommand, `_load_newsource` function)
5. Add fixtures in `tests/conftest.py` and tests in `test_newsource.py`, `test_adapters.py`, `test_roundtrip.py`

## Gotchas

- `mhtml_test_result.py`: The function `test_result_to_unified` starts with `test_` — pytest tries to collect it as a test. Import it with `from ... import test_result_to_unified as adapt_test_result` in tests.
- `source_assets` are inserted via raw SQL in tests (not through the adapter pipeline).
- `_UNIQUE_KEYS` in `db.py` must match the UNIQUE constraints declared in `schema.sql`.
- When adding a new table: update `_TABLE_MAP`, `_UNIQUE_KEYS`, `schema.sql`, `models.py`, `export_arkiv.py` (`_TIMESTAMP_FIELDS`, `_COLLECTION_DESCRIPTIONS`, `_FK_FIELDS` if applicable), and `analysis/visit_diff.py`.
