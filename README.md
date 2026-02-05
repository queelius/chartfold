# chartfold

Patient-facing tool for consolidating personal health data from multiple EHR (Electronic Health Record) systems into a single SQLite database. Query, analyze, and export your aggregated clinical data via CLI, MCP server (for LLM-assisted analysis), or export to Markdown, HTML, or Hugo static sites.

**Goal:** Patient empowerment through data ownership — enabling time-series analysis, intelligent querying with tools like Claude Code, and organized preparation for medical visits.

## Features

- **Multi-EHR data consolidation** — Import from Epic MyChart, MEDITECH Expanse, and athenahealth
- **SQLite database** — 16 clinical tables with full audit trail
- **MCP server** — 22 tools for LLM-assisted analysis with Claude
- **Export formats** — Markdown, self-contained HTML with charts, Hugo static sites, JSON
- **Personal notes** — Tag and annotate any clinical record
- **Visit preparation** — Generate visit diffs and clinical summaries

## Installation

```bash
pip install chartfold

# With MCP server support (for Claude integration)
pip install "chartfold[mcp]"
```

### Development Setup

```bash
git clone https://github.com/queelius/chartfold.git
cd chartfold
pip install -e ".[dev,mcp]"
```

## Quick Start

### Load Data from EHR Exports

```bash
# Load from individual sources
chartfold load epic ~/exports/epic/
chartfold load meditech ~/exports/meditech/
chartfold load athena ~/exports/athena/

# Or load all at once
chartfold load all \
  --epic-dir ~/exports/epic/ \
  --meditech-dir ~/exports/meditech/ \
  --athena-dir ~/exports/athena/
```

### Query and Inspect

```bash
# View database summary
chartfold summary

# Run SQL queries
chartfold query "SELECT test_name, value, result_date FROM lab_results ORDER BY result_date DESC LIMIT 10"

# What's new since your last visit
chartfold diff 2025-01-01
```

### Export Your Data

```bash
# Markdown summary for your doctor (last 6 months)
chartfold export markdown --output summary.md --lookback 6

# PDF via pandoc
chartfold export markdown --output summary.pdf --pdf

# Self-contained HTML with charts
chartfold export html --output summary.html --lookback 6

# Full HTML export (all data)
chartfold export html --full --output full.html

# JSON for backup/restore
chartfold export json --output data.json

# Hugo static site
chartfold export hugo --output ./site
```

### Personal Notes

```bash
# List recent notes
chartfold notes list --limit 20

# Search by tag or query
chartfold notes search --tag oncology --query "CEA"

# Search by reference (notes linked to specific records)
chartfold notes search --ref-table lab_results
```

## Supported EHR Sources

| Source | Format | Description |
|--------|--------|-------------|
| **Epic MyChart** | CDA R2 XML | IHE XDM exports from Epic MyChart |
| **MEDITECH Expanse** | CCDA XML + FHIR JSON | Dual-format bulk exports (merged and deduplicated) |
| **athenahealth** | FHIR R4 XML | Ambulatory summary exports |

### Expected Input Directory Structures

```
Epic:      input_dir/DOC0001.XML, DOC0002.XML, ...
MEDITECH:  input_dir/US Core FHIR Resources.json
           input_dir/CCDA/<uuid>.xml
athena:    input_dir/Document_XML/*AmbulatorySummary*.xml
```

## Database Schema

chartfold stores data in 16 clinical tables:

| Category | Tables |
|----------|--------|
| **Core** | `patients`, `documents`, `encounters` |
| **Labs & Vitals** | `lab_results`, `vitals` |
| **Medications** | `medications`, `allergies` |
| **Conditions** | `conditions` |
| **Procedures** | `procedures`, `pathology_reports`, `imaging_reports` |
| **Notes** | `clinical_notes` |
| **History** | `immunizations`, `social_history`, `family_history`, `mental_status` |
| **System** | `load_log` (audit), `notes`, `note_tags` (personal), `source_assets` |

All dates are stored as ISO `YYYY-MM-DD` strings. Every record carries a `source` field for provenance tracking.

## MCP Server

chartfold includes an MCP (Model Context Protocol) server with 22 tools for LLM-assisted health data analysis:

```bash
chartfold serve-mcp --db chartfold.db
```

### Available Tools

| Category | Tools |
|----------|-------|
| **SQL & Schema** | `run_sql`, `get_schema` |
| **Labs** | `query_labs`, `get_lab_series_tool`, `get_available_tests_tool`, `get_abnormal_labs_tool` |
| **Medications** | `get_medications`, `reconcile_medications_tool` |
| **Clinical** | `get_timeline`, `search_notes`, `get_pathology_report` |
| **Analysis** | `get_visit_diff`, `get_visit_prep`, `get_surgical_timeline` |
| **Cross-source** | `match_cross_source_encounters`, `get_data_quality_report` |
| **Summary** | `get_database_summary` |
| **Personal Notes** | `save_note`, `get_note`, `search_notes_personal`, `delete_note` |

### Claude Desktop Configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "chartfold": {
      "command": "python",
      "args": ["-m", "chartfold", "serve-mcp", "--db", "/path/to/chartfold.db"]
    }
  }
}
```

## Configuration

Generate a personalized config from your data:

```bash
chartfold init-config
```

This creates `chartfold.toml` with lab tests to chart based on what's in your database:

```toml
[[lab_tests]]
name = "CEA"
match = ["CEA", "Carcinoembryonic Antigen"]

[[lab_tests]]
name = "Hemoglobin"
match = ["Hemoglobin", "Hgb", "HGB"]

[hugo]
dashboard_recent_labs = 10
```

## Architecture

chartfold uses a three-stage pipeline for each EHR source:

```
Raw EHR files (XML/FHIR)
    ↓
[Source Parser]  → source-specific dict
    ↓
[Adapter]        → UnifiedRecords (normalized dataclasses)
    ↓
[DB Loader]      → SQLite tables
```

### Key Design Decisions

- **Idempotent loading** — Re-running `load` for a source replaces its data
- **Cross-source deduplication** — Adapters deduplicate records using composite keys
- **Date normalization** — All dates normalized to ISO format at adapter stage
- **Provenance tracking** — Every record tracks its source for cross-source analysis

## Testing

```bash
# Run all tests (700+ tests)
python -m pytest tests/

# Run a single test file
python -m pytest tests/test_adapters.py

# Run with coverage
python -m pytest tests/ --cov=chartfold --cov-report=term-missing
```

## Project Structure

```
src/chartfold/
├── sources/        # EHR-specific parsers (epic.py, meditech.py, athena.py)
├── adapters/       # Normalize to UnifiedRecords (epic_adapter.py, etc.)
├── analysis/       # Query helpers (lab_trends.py, medications.py, etc.)
├── extractors/     # Specialized parsers (labs.py, pathology.py)
├── core/           # Shared utilities (cda.py, fhir.py, utils.py)
├── formatters/     # Output formatters (markdown.py)
├── hugo/           # Hugo site generator (generate.py)
├── mcp/            # MCP server (server.py)
├── db.py           # Database interface
├── models.py       # Dataclass models
├── config.py       # Configuration management
├── cli.py          # Command-line interface
├── export.py       # Markdown export
├── export_html.py  # HTML export with Chart.js
└── export_full.py  # Full JSON/markdown export
```

## Adding a New EHR Source

1. Create `sources/newsource.py` with `process_*_export(input_dir)` returning a dict
2. Create `adapters/newsource_adapter.py` with `*_to_unified(data) -> UnifiedRecords`
3. Add a `SourceConfig` in `sources/base.py`
4. Wire into `cli.py` (add subcommand)
5. Add tests in `tests/`

## Requirements

- Python 3.11+ (uses `tomllib` from stdlib)
- Dependencies: `lxml`, `mcp` (optional)
- Optional: `pandoc` for PDF export, `hugo` for static site generation

## License

MIT
