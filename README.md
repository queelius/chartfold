# health-memex

Personal health data archive: consolidate medical records from multiple EHR systems into a single queryable SQLite database. Part of the [`*-memex` ecosystem](https://github.com/queelius/memex).

Query, analyze, and export your aggregated clinical data via CLI, MCP server (for LLM-assisted analysis), or self-contained HTML SPA.

## Features

- **Multi-EHR data consolidation**: Import from Epic MyChart, MEDITECH Expanse, and athenahealth
- **SQLite database**: 17 clinical tables with full audit trail
- **MCP server**: 31 tools for LLM-assisted analysis with Claude
- **Export formats**: Self-contained HTML SPA, Arkiv (JSONL + README.md + schema.yaml)
- **AI chat**: Ask questions about your record in the HTML SPA via Claude, with inline charts (optional, requires proxy)
- **Visit prep**: See what's new since your last visit, directly in the SPA
- **Print summary**: One-page printable view for your doctor
- **Personal notes**: Tag and annotate any clinical record

## Installation

```bash
pip install health-memex

# With MCP server support (for Claude integration)
pip install "health-memex[mcp]"
```

### Development Setup

```bash
git clone https://github.com/queelius/health-memex.git
cd health-memex
pip install -e ".[dev,mcp]"
```

## Quick Start

### Load Data from EHR Exports

```bash
# Load from individual sources
health-memex load epic ~/exports/epic/
health-memex load meditech ~/exports/meditech/
health-memex load athena ~/exports/athena/

# Or load all at once
health-memex load all \
  --epic-dir ~/exports/epic/ \
  --meditech-dir ~/exports/meditech/ \
  --athena-dir ~/exports/athena/
```

### Query and Inspect

```bash
# View database summary
health-memex summary

# Run SQL queries
health-memex query "SELECT test_name, value, result_date FROM lab_results ORDER BY result_date DESC LIMIT 10"

# What's new since your last visit
health-memex diff 2025-01-01
```

### Export Your Data

```bash
# Self-contained HTML SPA with embedded SQLite (all data stays client-side)
health-memex export html --output summary.html
health-memex export html --output summary.html --embed-images --config health_memex.toml
health-memex export html --output summary.html --ai-chat --proxy-url https://proxy.example.com/v1/messages

# Arkiv universal record format (primary backup/restore, round-trip capable)
health-memex export arkiv --output ./arkiv/
health-memex export arkiv --output ./arkiv/ --embed

# Import from arkiv archive
health-memex import ./arkiv/ --db new.db
health-memex import ./arkiv/ --validate-only
```

### MCP Server

```bash
# Start MCP server (matches ecosystem pattern: memex mcp, btk mcp)
health-memex mcp --db health_memex.db
```

### Claude Code Configuration

```json
{
  "mcpServers": {
    "health-memex": {
      "command": "python",
      "args": ["-m", "health_memex", "mcp", "--db", "/path/to/health_memex.db"]
    }
  }
}
```

### Personal Notes

```bash
health-memex notes list --limit 20
health-memex notes search --tag oncology --query "CEA"
```

## Supported EHR Sources

| Source | Format | Description |
|--------|--------|-------------|
| **Epic MyChart** | CDA R2 XML | IHE XDM exports from Epic MyChart |
| **Epic MyChart (MHTML)** | MHTML | Visit notes and genomic test results (e.g., Tempus XF) |
| **MEDITECH Expanse** | CCDA XML + FHIR JSON | Dual-format bulk exports (merged and deduplicated) |
| **athenahealth** | FHIR R4 XML | Ambulatory summary exports |

## Database Schema

17 clinical tables, all dates ISO `YYYY-MM-DD`, every record carries a `source` field:

| Category | Tables |
|----------|--------|
| **Core** | `patients`, `documents`, `encounters` |
| **Labs & Vitals** | `lab_results`, `vitals` |
| **Medications** | `medications`, `allergies` |
| **Conditions** | `conditions` |
| **Procedures** | `procedures`, `pathology_reports`, `imaging_reports` |
| **Genomics** | `genetic_variants` |
| **Notes** | `clinical_notes` |
| **History** | `immunizations`, `social_history`, `family_history`, `mental_status` |
| **System** | `load_log`, `notes`/`note_tags`, `analyses`/`analysis_tags`, `source_assets` |

## Configuration

```bash
health-memex init-config
```

Generates `health_memex.toml` with lab tests to chart based on what's in your database.

## Requirements

- Python 3.11+
- Dependencies: `lxml`, `pyyaml`
- Optional: `mcp` (FastMCP) for MCP server

## License

MIT
