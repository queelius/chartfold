# Arkiv Round-Trip + Spec Compliance

**Date:** 2026-02-28
**Status:** Approved

## Overview

Make arkiv the primary backup/restore format for chartfold by:

1. Migrating export to the arkiv spec (README.md + schema.yaml instead of manifest.json)
2. Adding source asset export with optional base64 embedding (`--embed`)
3. Adding `chartfold import <dir>` for arkiv archives
4. Removing the JSON export/import path (`export_full.py`)

## arkiv Spec Summary (from ../arkiv/SPEC.md)

arkiv is a universal personal data format:

- **JSONL is canonical** — durable, human-readable, git-diffable source of truth
- **All fields optional** — `mimetype`, `uri`, `content`, `timestamp`, `metadata`
- **One record = one resource = one mimetype**
- **`content`** — inline content: text for text types, base64 for binary
- **`uri`** — where the resource lives (`file://`, `http://`, etc.)
- **Archive** — `README.md` (YAML frontmatter) + `schema.yaml` + `*.jsonl` + optional `media/`
- **SQLite** — derived query layer, regenerable from JSONL

## Export Changes (`export_arkiv.py`)

### Archive Format Migration

Replace `manifest.json` with spec-compliant archive format:

**README.md** (YAML frontmatter + markdown):
```yaml
---
name: Chartfold clinical data export
description: Clinical records from Epic, MEDITECH, and athenahealth
datetime: 2026-02-28
generator: chartfold v1.1.0
contents:
  - path: lab_results.jsonl
    description: Laboratory test results with values, reference ranges, and interpretations
  - path: medications.jsonl
    description: Medication orders and prescriptions
---

# Chartfold Clinical Data Export

Exported from chartfold database on 2026-02-28.
```

**schema.yaml** (auto-generated, curatable):
```yaml
lab_results:
  record_count: 847
  metadata_keys:
    source:
      type: string
      count: 847
      values: [epic_anderson, meditech_anderson]
    test_name:
      type: string
      count: 847
      example: CEA
```

### Source Assets (No Longer Excluded)

Source assets become proper arkiv records with their actual MIME types:

**Default mode** — files copied to `media/` subdirectory:
```jsonl
{"mimetype": "image/png", "uri": "file://media/abc123.png", "timestamp": "2025-01-15", "metadata": {"table": "source_assets", "source": "epic_anderson", "file_name": "abc123.png", "title": "CT Abdomen", "ref_table": "imaging_reports", "ref_id_uri": "chartfold:imaging_reports/7"}}
```

**`--embed` mode** — base64 content inlined (per arkiv spec: "base64 for binary"):
```jsonl
{"mimetype": "image/png", "uri": "file://media/abc123.png", "content": "iVBORw0KGgo...", "timestamp": "2025-01-15", "metadata": {"table": "source_assets", ...}}
```

### Record Format (Unchanged)

Clinical records keep `mimetype: application/json` with all metadata fields:
```jsonl
{"mimetype": "application/json", "uri": "chartfold:lab_results/42", "timestamp": "2025-01-15", "metadata": {"table": "lab_results", "source": "epic_anderson", "test_name": "CEA", "value": "2.3", "value_numeric": 2.3}}
```

### FK Denormalization (Unchanged)

- `procedure_id: 5` → `procedure_uri: "chartfold:procedures/5"`
- Tags folded: `"tags": ["oncology", "cea"]`

### Null Handling (Unchanged)

Null/empty fields skipped in metadata.

## New Module: `import_arkiv.py`

### Main Entry Point

```python
def import_arkiv(
    input_dir: str,
    db_path: str,
    validate_only: bool = False,
    overwrite: bool = False,
) -> dict:
    """Import an arkiv archive to recreate a chartfold database.

    Returns dict with success, errors, and per-table counts.
    """
```

### Import Pipeline

```
README.md frontmatter  →  discover collections (JSONL files)
        ↓
schema.yaml            →  preserve descriptions (optional, for export fidelity)
        ↓
*.jsonl files           →  parse records, reverse _row_to_record()
        ↓
topological sort        →  order tables by FK dependencies (from fresh schema)
        ↓
INSERT with ID remap    →  resolve chartfold: URIs to new autoincrement IDs
        ↓
unfold tags             →  metadata.tags → note_tags / analysis_tags rows
        ↓
source_assets           →  decode base64 content → write to media/ or verify uri exists
```

### Record-to-Row Reversal (`_record_to_row`)

The reverse of `_row_to_record()`:

1. Extract all fields from `metadata` to flat dict
2. Remove synthetic fields: `table` (derived from collection name)
3. Reverse FK URIs: `procedure_uri: "chartfold:procedures/5"` → `procedure_id: 5` (old ID, remapped later)
4. Extract `tags` from metadata → separate insert into tag tables
5. For source assets: `content` (base64) → decoded file bytes written to disk

### FK Resolution

Same pattern as the JSON importer:

```python
id_map: dict[str, dict[int, int]]  # table -> {old_id: new_id}
```

Parse `chartfold:{table}/{old_id}` URIs. Import in topological order (parents first). Remap old IDs to new autoincrement IDs in child rows.

### Source Asset Restoration

For source_assets records:
- If `content` field present: decode base64, write to file at `file_path` from metadata
- If `uri` starts with `file://media/`: check if file exists in `media/` subdirectory of the archive
- Update `file_path` in DB to the actual written path

### Validation

```python
def validate_arkiv(input_dir: str) -> dict:
    """Validate an arkiv archive without importing.

    Checks: README.md exists, frontmatter parses, JSONL files exist
    and contain valid JSON, schema.yaml parses.
    """
```

## CLI Changes

### New/Modified Commands

```bash
# Export (now writes README.md + schema.yaml instead of manifest.json)
chartfold export arkiv --output ./archive/
chartfold export arkiv --output ./archive/ --embed          # inline base64 assets
chartfold export arkiv --output ./archive/ --exclude-notes

# Import (replaces JSON import)
chartfold import <dir> [--db chartfold.db] [--validate-only] [--overwrite]
```

### Removed Commands

```bash
# These are deleted:
chartfold export json ...
chartfold import <file.json> ...
```

## Files to Delete

- `src/chartfold/export_full.py` — JSON export/import
- `tests/test_export_full.py` — JSON export/import tests

## Files to Create

- `src/chartfold/import_arkiv.py` — arkiv import logic

## Files to Modify

- `src/chartfold/export_arkiv.py` — README.md + schema.yaml output, source asset export, `--embed`
- `src/chartfold/cli.py` — rewire import command, add `--embed`, remove JSON commands
- `CLAUDE.md` — update export/import docs
- `README.md` — update export/import docs

## Directory Structure After Export

```
archive/
├── README.md              # YAML frontmatter (collection list) + markdown
├── schema.yaml            # Auto-generated metadata schema
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
├── genetic_variants.jsonl
├── patients.jsonl
├── source_assets.jsonl
├── notes.jsonl
├── analyses.jsonl
└── media/                 # Source asset files (images, PDFs)
    ├── abc123.png
    └── report.pdf
```

## What's Not Preserved in Round-Trip

- `load_log` — operational audit trail, regenerated on next data load
- `documents` — source document inventory, regenerated on next data load
- `note_tags` / `analysis_tags` — folded into parent records, unfolded on import
- Autoincrement IDs — new IDs assigned on import (FK relationships preserved via remapping)

## Not In Scope

- arkiv's own SQLite query layer (arkiv handles that itself)
- FTS5 indexing
- Incremental/streaming import
