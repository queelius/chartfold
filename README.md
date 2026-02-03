# chartfold

Collect and consolidate personal health data from multiple EHR (Electronic Health Record) systems into a single SQLite database. Query, analyze, and export your aggregated clinical data via CLI, MCP server (for LLM-assisted analysis), or Hugo/Markdown output.

## Install

```bash
pip install chartfold

# With MCP server support (for Claude integration)
pip install "chartfold[mcp]"
```

## Quick Start

```bash
# Load data from EHR exports
chartfold load epic ~/exports/epic/
chartfold load meditech ~/exports/meditech/
chartfold load athena ~/exports/athena/

# Or load all at once
chartfold load all --epic-dir ~/exports/epic/ --meditech-dir ~/exports/meditech/ --athena-dir ~/exports/athena/

# Query your data
chartfold query "SELECT test_name, value, result_date FROM lab_results ORDER BY result_date DESC LIMIT 10"

# Get a summary
chartfold summary

# What's new since your last visit
chartfold diff 2025-01-01

# Export a clinical summary for your doctor
chartfold export --output summary.md --lookback 6
```

## Supported EHR Sources

| Source | Format | Description |
|--------|--------|-------------|
| **Epic MyChart** | CDA R2 XML | IHE XDM exports from Epic MyChart |
| **MEDITECH Expanse** | CCDA XML + FHIR JSON | Dual-format bulk exports |
| **athenahealth** | FHIR R4 XML | Ambulatory summary exports |

## MCP Server

chartfold includes an MCP server with 22 tools for LLM-assisted health data analysis:

```bash
chartfold serve-mcp --db chartfold.db
```

This enables tools like lab trend queries, medication reconciliation, visit preparation, surgical timelines, and more through Claude or other MCP-compatible clients.

## Development

```bash
git clone https://github.com/queelius/chartfold.git
cd chartfold
pip install -e ".[dev,mcp]"

# Run tests
python -m pytest tests/

# Run tests with coverage
python -m pytest tests/ --cov=chartfold --cov-report=term-missing
```

## License

MIT
