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
health-memex import ./arkiv.zip --db new.db --media-dir ./assets  # custom media store
```

Import copies each source asset (PDF, image, ...) out of the archive into the
database's own media store, `<db dir>/media/<unique_id>.<ext>` by default, and
records the path relative to the database directory, so the imported database
keeps working after the archive is deleted and can be moved together with its
`media/` directory. Assets loaded directly from EHR exports keep their
absolute paths to the original files. Files are named by each asset's durable
`unique_id`, so byte-identical assets on distinct rows are stored once per row.

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

## Upgrading from 2.x

3.0 changes two things you may notice:

- **Arkiv exports from 2.x cannot be imported.** Record URIs now use a
  durable content-hash `unique_id` instead of autoincrement row ids, so
  references survive database rebuilds. Your existing database is upgraded
  in place the first time 3.0 opens it; after that, run
  `health-memex export arkiv` again to replace any 2.x backup bundles.
- **The default database moved** from `./health_memex.db` (relative to the
  current directory) to `~/.local/share/health-memex/health_memex.db`
  (or `$XDG_DATA_HOME/health-memex/`), for the CLI and the MCP server alike.
  Set `HEALTH_MEMEX_DB` or pass `--db` to keep using an existing file.

## Requirements

- Python 3.11+
- Dependencies: `lxml`, `pyyaml`
- Optional: `mcp` (FastMCP) for MCP server

## Handling PHI responsibly

health-memex is a **personal** archive. The SQLite database, the arkiv
bundle (`records.jsonl` plus `README.md`, `schema.yaml`, and `media/`), and
the HTML SPA all contain Protected Health Information (PHI) in plaintext.
Treat every exported artifact like a password file.

**Minimum precautions:**

- Keep the primary database on an encrypted volume (FileVault, LUKS,
  BitLocker, or similar).
- When sharing an arkiv bundle or an HTML SPA, wrap it in a
  password-protected `.zip` or GPG-encrypt it. `health-memex export` does
  **not** encrypt. That is the operator's responsibility.
- Never email a raw export, upload it to a generic file-sharing site,
  publish it on a public web server, or paste its contents into an
  arbitrary chat service.
- If you enable the `--ai-chat` feature in the SPA, remember that the
  chat routes your questions (which may quote lab values, diagnoses,
  and medication lists) through whatever proxy URL you configured. Use a
  proxy you control.
- When you no longer need an export, shred or secure-delete it rather
  than dropping it in the trash.

`health-memex` prints a PHI reminder to stderr after every export. The
reminder is deliberate; please do not suppress it in scripts unless you
know the destination path is already protected.

## License

MIT
