# arkiv Export Design

**Date:** 2026-02-17
**Status:** Approved

## Overview

Add `chartfold export arkiv` to export clinical data in the [arkiv universal record format](https://github.com/atowell/arkiv). This is a one-way export (no corresponding import — JSON export covers round-trip needs).

arkiv is a document-oriented personal data format: JSONL as canonical storage, one JSON object per record, with a manifest for schema discovery.

## Record Format

Each chartfold table row becomes one arkiv record:

```jsonl
{"mimetype": "application/json", "uri": "chartfold:lab_results/42", "timestamp": "2025-01-15", "metadata": {"table": "lab_results", "source": "epic_anderson", "test_name": "CEA", "test_loinc": "2039-6", "value": "2.3", "value_numeric": 2.3, "unit": "ng/mL", "ref_range": "0.0-3.0", "interpretation": "N", "panel_name": "Tumor Markers", "status": "final"}}
```

### Field Mapping

| arkiv field | Chartfold mapping |
|-------------|-------------------|
| `mimetype` | Always `application/json` |
| `uri` | `chartfold:{table}/{id}` — custom URI scheme, resolvable by chartfold CLI (future) |
| `timestamp` | Primary date field per table (see table below) |
| `content` | Omitted (metadata has everything) |
| `metadata` | All non-null fields from the row, plus `"table": "{table_name}"` |

### Timestamp Field per Table

| Table | Timestamp field |
|-------|----------------|
| lab_results | result_date |
| encounters | encounter_date |
| medications | start_date |
| procedures | procedure_date |
| imaging_reports | study_date |
| pathology_reports | report_date |
| clinical_notes | note_date |
| vitals | recorded_date |
| immunizations | admin_date |
| allergies | onset_date |
| conditions | onset_date |
| social_history | recorded_date |
| family_history | *(none — no date field)* |
| mental_status | recorded_date |
| patients | date_of_birth |
| notes | created_at |
| analyses | created_at |

### FK Denormalization

Foreign key references are converted to `chartfold:` URIs:

- `pathology_reports.procedure_id: 5` → `"procedure_uri": "chartfold:procedures/5"`
- `note_tags` rows folded into parent note as `"tags": ["oncology", "cea"]`
- `analysis_tags` rows folded into parent analysis as `"tags": ["cancer", "timeline"]`

### Null Handling

Null/empty fields are skipped in metadata. arkiv principle: no required fields.

## Collection Mapping

One `.jsonl` file per non-empty chartfold table:

```
chartfold-arkiv/
├── manifest.json
├── lab_results.jsonl
├── medications.jsonl
├── encounters.jsonl
├── conditions.jsonl
├── procedures.jsonl
├── pathology_reports.jsonl
├── imaging_reports.jsonl
├── clinical_notes.jsonl
├── vitals.jsonl
├── immunizations.jsonl
├── allergies.jsonl
├── social_history.jsonl
├── family_history.jsonl
├── mental_status.jsonl
├── patients.jsonl
├── notes.jsonl
└── analyses.jsonl
```

Empty tables are skipped (no file, no manifest entry).

### Tables Included

- All 16 clinical tables (patients through mental_status)
- Personal notes and analyses (opt-out via `--exclude-notes`)

### Tables Excluded

- `load_log` (operational metadata)
- `source_assets` (file references, not clinical data)
- `documents` (source document metadata)
- `note_tags`, `analysis_tags` (folded into parent records)

## Manifest

Auto-generated per arkiv spec with schema discovery:

```json
{
  "description": "Chartfold clinical data export",
  "created": "2026-02-17",
  "metadata": {
    "chartfold_version": "1.1",
    "source_tool": "chartfold"
  },
  "collections": [
    {
      "file": "lab_results.jsonl",
      "description": "Laboratory test results with values, reference ranges, and interpretations",
      "record_count": 847,
      "schema": {
        "metadata_keys": {
          "table": {"type": "string", "count": 847, "values": ["lab_results"]},
          "source": {"type": "string", "count": 847, "values": ["epic_anderson", "meditech_anderson"]},
          "test_name": {"type": "string", "count": 847, "example": "CEA"},
          "value_numeric": {"type": "number", "count": 720, "example": 2.3},
          "interpretation": {"type": "string", "count": 650, "values": ["N", "H", "L", "HH", "LL"]}
        }
      }
    }
  ]
}
```

Schema discovery: scan all records per collection, count non-null values per key, detect types, enumerate low-cardinality fields (< 20 unique values), sample one example for high-cardinality fields.

## CLI Interface

```bash
# Basic export
chartfold export arkiv --output ./chartfold-arkiv/

# Exclude personal notes/analyses
chartfold export arkiv --output ./chartfold-arkiv/ --exclude-notes
```

Output directory is created if it doesn't exist. Overwrites existing files.

## Module Structure

New file: `src/chartfold/export_arkiv.py`

Functions:
- `export_arkiv(db, output_dir, include_notes=True)` — main entry point
- `_table_to_records(db, table_name, timestamp_field)` — converts rows to arkiv records
- `_build_schema(records)` — scans records for metadata key stats
- `_build_manifest(collections)` — assembles manifest.json

No new dependencies (json stdlib only).

## Not In Scope

- arkiv import (JSON export covers round-trip)
- SQLite query layer generation (arkiv's job)
- Source assets / documents / load_log export

## Future Work

- **CLI URI resolver**: `chartfold show chartfold:lab_results/123` to look up and display a record by its chartfold URI. Could also support piping, e.g., `chartfold show < uri_list.txt`.
- **HTML SPA deep links**: Make `chartfold:` URIs resolve to anchors in the HTML export.
