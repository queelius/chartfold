# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

`health-memex` is a `*-memex` ecosystem archive for personal health data. It consolidates medical records from multiple EHR (Electronic Health Record) systems into a single queryable SQLite database, then exposes that data via MCP server, CLI, arkiv export, and self-contained HTML SPA.

Part of the `*-memex` family (see `~/github/memex/CLAUDE.md` for the ecosystem contract). Each archive covers one domain and satisfies a common contract: SQLite + FTS5 backend, MCP server, thin admin CLI, import pipelines, arkiv export, durable record IDs, and marginalia.

**Cross-archive URI prefix:** `health-memex://`

## Project Structure

Package code lives in `src/health_memex/`. Tests in `tests/`.

```bash
# Development setup
pip install -e ".[dev,mcp]"
```

## Commands

```bash
# Run all tests (pytest)
python -m pytest tests/

# Run a single test file
python -m pytest tests/test_adapters.py

# Run a single test class or method
python -m pytest tests/test_adapters.py::TestEpicAdapter::test_lab_panel_explosion

# Run tests with coverage
python -m pytest tests/ --cov=health_memex --cov-report=term-missing

# Lint (ruff configured in pyproject.toml)
ruff check src/ tests/
ruff format --check src/ tests/

# Type check (mypy, also runs in CI)
mypy src/health_memex/

# Load data from EHR exports
health-memex load epic <dir>
health-memex load meditech <dir>
health-memex load athena <dir>
health-memex load auto <dir-or-file>          # Auto-detect source type
health-memex load mychart-visit <file.mhtml>   # MyChart visit page MHTML
health-memex load mychart-test-result <file.mhtml>  # MyChart test result MHTML
health-memex load all --epic-dir <> --meditech-dir <> --athena-dir <>
health-memex load analyses <dir>               # Load analysis markdown files

# Query and inspect
health-memex query "SELECT test_name, value, result_date FROM lab_results ORDER BY result_date DESC"
health-memex summary

# What's new since a given date (visit diff)
health-memex diff 2025-01-01

# Export formats: arkiv, html
health-memex export arkiv --output ./arkiv/
health-memex export arkiv --output ./arkiv/ --embed          # inline base64 assets
health-memex export html --output summary.html
health-memex export html --output summary.html --embed-images --config health_memex.toml
health-memex export html --output summary.html --ai-chat --proxy-url https://proxy.example.com/v1/messages

# Import from arkiv archive (round-trip capable)
health-memex import ./arkiv/ --db new.db
health-memex import ./arkiv/ --validate-only

# Generate personalized config from your data
health-memex init-config

# Personal notes
health-memex notes list --limit 20
health-memex notes search --tag oncology --query "CEA"

# Start MCP server (matches ecosystem pattern: memex mcp, btk mcp)
health-memex mcp --db health_memex.db
```

## Architecture

### Three-Stage Data Pipeline

Every EHR source goes through the same pipeline, and each stage is independently testable:

```
Raw EHR files (XML/FHIR/MHTML)
    |
[Source Parser]  -> source-specific dict  (sources/*.py)
    |
[Adapter]        -> UnifiedRecords        (adapters/*_adapter.py)
    |
[DB Loader]      -> SQLite tables         (db.py using schema.sql)
```

- **Shared parsing infrastructure** in `core/cda.py` (CDA R2 XML: namespace handling, section extraction, date formatting) and `core/fhir.py` (FHIR R4 Bundle: resource extraction by type, base64 decode of presented forms). Source parsers build on these.
- **Source parsers** handle format-specific XML/FHIR/HTML parsing and return dicts with keys like `lab_results`, `medications`, `problems`, `clinical_notes`, etc.
- **Adapters** normalize dates to ISO 8601, parse numeric values, deduplicate records, and map everything into dataclass instances (`models.py`).
- **DB loader** uses UPSERT (INSERT...ON CONFLICT...DO UPDATE) for stable autoincrement IDs across re-imports. `replace=True` mode also cleans up stale records.

The CLI prints a **stage comparison table** after loading to verify no silent data loss (parser count -> adapter count -> DB count).

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

- **FHIR JSON** (`US Core FHIR Resources.json`): structured coded data (LOINC, ICD-10, RxNorm) for encounters, conditions, medications, observations, immunizations
- **CCDA XML** (`CCDA/*.xml`, UUID-named files): HTML-table-based extraction for labs, meds, notes, vitals, allergies, social/family/mental history

The adapter deduplicates across formats using composite keys (e.g., `(test.lower(), date_iso, value)` for labs, `name.lower()` for conditions). FHIR conditions override CCDA problems when names match. This dual-format merge is the most complex adapter path and is tested with dedicated fixtures.

### Unified Data Model (models.py)

18 dataclass types mapping 1:1 to SQLite tables. 17 are in `_TABLE_MAP` (bulk-loaded via the adapter pipeline); `PatientRecord` is loaded separately. All dates are ISO `YYYY-MM-DD` strings. Every record carries a `source` field for provenance tracking. The `UnifiedRecords` container holds all records from a single source load.

Lab results have both `value` (text, handles `<0.5`, `positive`) and `value_numeric` (float, NULL when not parseable).

Note: `LabResult` is the only dataclass that doesn't follow the `*Record`/`*Report`/`*Variant` naming convention.

### Database (db.py, schema.sql)

SQLite with WAL mode and foreign keys enabled. 17 clinical tables + `load_log` audit trail + `notes`/`note_tags` + `analyses`/`analysis_tags` + `source_assets`. Key indexes on lab dates/test names/LOINC codes, vital types/dates, procedure/imaging dates. Pathology reports FK to procedures with `ON DELETE SET NULL`.

**UPSERT loading** (`_UNIQUE_KEYS` in `db.py`): Each table has a natural key used for conflict detection. `load_source(records, replace=True)` does UPSERT + stale cleanup (bulk import). `load_source(records, replace=False)` does UPSERT only (additive import, e.g., MHTML).

`db.query()` returns `list[dict]` (via `sqlite3.Row` factory).

The main class is `HealthMemexDB` (in `db.py`).

### MCP Server (mcp/server.py)

FastMCP server with `HEALTH_MEMEX_DB` env var for database path. 31 tools across four categories:

- **Read-only SQL**: `run_sql`, `get_schema`, `get_database_summary`
- **Clinical queries**: `query_labs`, `get_lab_series_tool`, `get_available_tests_tool`, `get_abnormal_labs_tool`, `get_medications`, `reconcile_medications_tool`, `search_notes`, `get_pathology_report`, `get_source_files`, `get_asset_summary`
- **Compound analysis**: `get_visit_diff`, `get_visit_prep`, `get_visit_prep_bundle`, `get_surgical_timeline`, `match_cross_source_encounters`, `get_data_quality_report`, `get_clinical_summary_tool`, `get_timeline`
- **Write operations**: `save_note`, `get_note`, `search_notes_personal`, `delete_note`, `save_analysis`, `get_analysis`, `search_analyses`, `list_analyses`, `delete_analysis`, `write_record`

Design principle: the LLM writes its own SQL for all reads via `run_sql` + `get_schema`. Write operations (notes, analyses) go through dedicated tools with controlled parameters. `write_record` allows inserting clinical records to any clinical table but requires `source` and validates column names against the schema.

Read-only SQL uses SQLite URI `mode=ro` for engine-level enforcement and blocks `ATTACH`/`DETACH` to prevent writable database bypass. Results capped at 5000 rows.

**`run_sql`'s parameter is named `query`, not `sql`.** This diverges from the ecosystem's `execute_sql(sql=...)` / `run_sql(sql=...)` convention. The federation accommodates this via a per-archive `sql_arg` override: health-memex's archive config must set `sql_arg: query` (the federation config loader supports and tests this, defaulting `sql_arg` to `sql` for every other archive). Do not rename the parameter without coordinating a matching change to the federation config, or federation SQL calls into this archive will fail with a missing-argument error.

### Data Access Modules (analysis/)

Parameterized query helpers that surface structured views of the data for LLMs (via MCP) and CLI:

- `lab_trends.py`: lab values by test/date/LOINC, flagged abnormals, cross-source series
- `medications.py`: active meds, history, cross-source grouping that surfaces status conflicts
- `surgical_timeline.py`: procedures with linked pathology/imaging/meds by date proximity
- `visit_prep.py`: `generate_visit_prep` (quick summary) and `generate_visit_prep_bundle` (comprehensive 10-section context for LLM-driven visit prep with key test trend resolution from config or frequency fallback)
- `visit_diff.py`: everything new since date X across all clinical tables
- `clinical_summary.py`: full clinical picture in one call (conditions, meds, labs, vitals, imaging, encounters, procedures, pathology)
- `timeline.py`: unified chronological timeline merging all event types, with labs grouped by (date, source) to avoid flooding
- `data_quality.py`: cross-source duplicate detection, source coverage matrix
- `cross_source.py`: cross-source encounter matching by date

### Extractors (extractors/)

Domain-specific extraction helpers used by adapters and analysis modules:

- `labs.py`: CEA extraction from FHIR observations and parsed lab results
- `pathology.py`: structured section parsing from pathology report text (diagnosis, gross, microscopic, staging, margins) and procedure linkage by date proximity + specimen similarity

### Export Modules

- `export_arkiv.py`: Arkiv universal record format (JSONL + README.md + schema.yaml). Primary backup/restore format with full round-trip support. Source assets exported to `media/` or inline base64 via `--embed`. Record URIs use `health-memex:{table}/{id}` prefix.
- `import_arkiv.py`: Arkiv import with validation, FK remapping, tag unfolding, and source asset restoration. Accepts both `health-memex:` and legacy `chartfold:` URI prefixes. Asset bytes are copied into the archive's media store (`<db dir>/media/<unique_id>.<ext>`, or `--media-dir`) and upserted by `unique_id`, so re-imports are idempotent.
- `media.py`: source-asset storage. `source_assets.file_path` is either absolute (EHR-loaded assets, pointing at the original export) or relative to the DB directory (arkiv-imported assets). `resolve_asset_path(db_path, file_path)` is the **only** way to turn a stored `file_path` into a filesystem path; every reader must use it. `store_media` writes atomically (temp + `os.replace`), skips identical bytes, overwrites different bytes, and refuses symlinks.

### SPA (spa/)

Self-contained HTML SPA with embedded SQLite database via sql.js (WebAssembly). All data stays client-side. Supports `--embed-images`, `--config`, `--ai-chat`, and `--proxy-url`.

- `spa/export.py`: HTML generation. Assembles JS/CSS/SQL data into a single-file SPA.
- `spa/chat_prompt.py`: System prompt generation for AI chat (schema + stats + current analyses). `_CLINICAL_TABLES` derived from `db.py`'s `_UNIQUE_KEYS` (not hardcoded).
- `spa/js/`: 8 modules: `app.js` (init/lifecycle), `db.js` (sql.js wrapper), `router.js` (hash-based navigation), `sections.js` (all content sections including `visit_prep` and `print_summary`), `chart.js` (line charts via `ChartRenderer`), `chat.js` (AI agent loop + chat UI, conditionally included), `ui.js` (shared UI helpers), `markdown.js` (markdown rendering).
- `spa/css/`: `styles.css` (main) + `chat.css` (chat panel, conditionally included).

AI chat (`--ai-chat`): Client-side agent loop with two tools: `run_sql` (SQL queries) and `render_chart` (inline line charts). Conversation persists across SPA navigation via DOM detach/reattach. Sliding window (`MAX_MESSAGES=40`) with pair-aware trimming.

### Analysis Parser (analysis_parser.py)

Parses analysis markdown files with optional YAML frontmatter (title, category, tags, summary). Files without frontmatter use the filename as title. Used by `health-memex load analyses <dir>` and the `save_analysis` MCP tool.

### Configuration (config.py)

TOML config (`health_memex.toml`) for personalized settings. Key tests to chart, dashboard settings. Auto-generated from DB contents via `health-memex init-config`.

## Ecosystem Alignment

This archive satisfies the `*-memex` contract (see `~/github/memex/CLAUDE.md`):

| Contract Item | Implementation |
|---------------|----------------|
| SQLite + FTS5 backend | `db.py` + `schema.sql` (WAL mode, foreign keys) |
| MCP server | `mcp/server.py` (FastMCP, 31 tools, `health-memex mcp`) |
| Thin admin CLI | `cli.py` (load, export, import, query, summary, notes) |
| Import pipelines | 5 source types (Epic, MEDITECH, athena, MyChart MHTML x2) |
| Export: arkiv | `export_arkiv.py` (JSONL + schema.yaml + README.md) |
| Export: HTML SPA | `spa/export.py` (sql.js, optional AI chat) |
| Durable record IDs | UPSERT with natural keys (`_UNIQUE_KEYS` in `db.py`) |
| Marginalia | `notes`/`note_tags` tables, linked to any clinical record |

**Cross-archive URI scheme:** Records are addressable as `health-memex://{kind}/{id}`. Arkiv exports use `health-memex:{table}/{id}` URIs.

## Key Conventions

- All dates stored as ISO `YYYY-MM-DD` strings. Date normalization in `core/utils.py` (`normalize_date_to_iso`).
- Source parsers use `lxml` with optional `recover=True` for XML with encoding issues (MEDITECH). MHTML parsers use Python stdlib `email` module + `lxml.html` XPath (NOT cssselect, which requires an extra package).
- Deduplication happens at the adapter stage using `deduplicate_by_key` from `core/utils.py`.
- Tests use pytest fixtures from `tests/conftest.py` with `tmp_db`, `sample_unified_records`, `sample_epic_data`, `sample_meditech_data`, `sample_athena_data`, and `surgical_db`.
- Roundtrip tests (`test_roundtrip.py`) verify that record counts are preserved through all pipeline stages.
- Requires Python 3.11+ (`tomllib` from stdlib). Dependencies: `lxml`, `pyyaml`. Optional: `mcp` (FastMCP) for MCP server.
- CI tests on Python 3.11 and 3.12. Lint and typecheck run on 3.11 only.
- Ruff for linting (configured in `pyproject.toml`), line length 100, target Python 3.11.
- Coverage minimum: 68% (configured in `pyproject.toml`).

## Adding a New EHR Source

1. Create `sources/newsource.py` with a `process_*_export(input_dir)` function returning a dict
2. Create `adapters/newsource_adapter.py` with a `*_to_unified(data) -> UnifiedRecords` function and `_parser_counts(data)` helper
3. Add a `SourceConfig` in `sources/base.py` (if applicable)
4. Wire into `cli.py` (add subcommand, `_load_newsource` function)
5. Add fixtures in `tests/conftest.py` and tests in `test_newsource.py`, `test_adapters.py`, `test_roundtrip.py`

## Gotchas

- `mhtml_test_result.py`: The function `test_result_to_unified` starts with `test_`, so pytest tries to collect it as a test. Import it with `from ... import test_result_to_unified as adapt_test_result` in tests.
- `source_assets` are inserted via raw SQL in tests (not through the adapter pipeline).
- Imported `source_assets` rows must keep the `unique_id` carried in the bundle: the natural key is `(source, file_path)`, so recomputing it from the new relative path would change every asset URI. Media files are named by `unique_id` (not content hash) because `UNIQUE(source, file_path)` forbids two same-source rows sharing a path; identical bytes on distinct rows are stored per row by design.
- Never read `source_assets.file_path` as a path directly; go through `media.resolve_asset_path`. Relative paths are anchored at the DB directory, not the CWD.
- `_UNIQUE_KEYS` in `db.py` must match the UNIQUE constraints declared in `schema.sql`.
- When adding a new table: update `_TABLE_MAP`, `_UNIQUE_KEYS`, `schema.sql`, `models.py`, `export_arkiv.py` (`_TIMESTAMP_FIELDS`, `_COLLECTION_DESCRIPTIONS`, `_FK_FIELDS` if applicable), `analysis/visit_diff.py`, and if it's a non-clinical table add it to `_NON_CLINICAL_TABLES` in `spa/chat_prompt.py`.
- Legacy arkiv archives exported under the old `chartfold` name use `chartfold:` URI prefixes. The importer (`import_arkiv.py`) accepts both `health-memex:` and `chartfold:` URIs for backwards compatibility.
