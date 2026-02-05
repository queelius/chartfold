# MCP Server

chartfold includes a Model Context Protocol (MCP) server that exposes your health data to LLM assistants like Claude.

## Starting the Server

```bash
chartfold serve-mcp --db chartfold.db
```

The server runs on stdio, compatible with MCP clients.

## Claude Desktop Integration

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

After restarting Claude Desktop, you can ask questions like:
- "What were my CEA levels over the past year?"
- "Show me all abnormal lab results"
- "Prepare a summary for my oncology visit next week"
- "What medications am I currently taking?"

## Available Tools

### SQL & Schema

| Tool | Description |
|------|-------------|
| `run_sql` | Execute SELECT/WITH/PRAGMA queries |
| `get_schema` | Get database schema information |

### Lab Results

| Tool | Description |
|------|-------------|
| `query_labs` | Search lab results by test name, date range, LOINC |
| `get_lab_series_tool` | Get time-series data for specific tests |
| `get_available_tests_tool` | List all test names in the database |
| `get_abnormal_labs_tool` | Get all flagged abnormal results |

### Medications

| Tool | Description |
|------|-------------|
| `get_medications` | List medications by status |
| `reconcile_medications_tool` | Cross-source medication reconciliation |

### Clinical Data

| Tool | Description |
|------|-------------|
| `get_timeline` | Chronological view of all clinical events |
| `search_notes` | Search clinical notes by content |
| `get_pathology_report` | Retrieve pathology reports |

### Visit & Timeline Analysis

| Tool | Description |
|------|-------------|
| `get_visit_diff` | Everything new since a given date |
| `get_visit_prep` | Bundle recent data for a visit |
| `get_surgical_timeline` | Procedures with linked pathology/imaging |

### Cross-Source Analysis

| Tool | Description |
|------|-------------|
| `match_cross_source_encounters` | Find matching encounters across sources |
| `get_data_quality_report` | Identify duplicates and coverage gaps |

### Summary

| Tool | Description |
|------|-------------|
| `get_database_summary` | Record counts by table |

### Personal Notes

| Tool | Description |
|------|-------------|
| `save_note` | Create or update a personal note |
| `get_note` | Retrieve a note by ID |
| `search_notes_personal` | Search personal notes |
| `delete_note` | Delete a note |

## Example Conversations

### Lab Trend Analysis

**You:** "Show me my CEA trend over the past 2 years"

Claude will use `get_lab_series_tool` with `test_names=["CEA"]` and present a summary of values with dates, highlighting any abnormals.

### Visit Preparation

**You:** "I have an oncology appointment on March 15. What's changed since my last visit on January 10?"

Claude will use `get_visit_diff` with the January date to show:
- New lab results
- Medication changes
- New imaging/pathology
- Recent clinical notes

### Medication Reconciliation

**You:** "Are my medication lists consistent across sources?"

Claude will use `reconcile_medications_tool` to identify:
- Status conflicts (active in one source, discontinued in another)
- Missing medications
- Dosage differences

## Security Notes

- The MCP server only allows SELECT queries (no INSERT/UPDATE/DELETE)
- WITH and PRAGMA statements are allowed for complex queries and metadata
- The database file must be readable by the server process
- Personal notes are included in queries — consider this when sharing
