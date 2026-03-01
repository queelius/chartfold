"""Export chartfold clinical data to arkiv universal record format.

Each clinical table is exported as a separate .jsonl file, with one arkiv record
per database row. Tags from note_tags and analysis_tags are folded into the
parent record's metadata.

The archive manifest is written as README.md (YAML frontmatter) + schema.yaml,
following the arkiv specification.
"""

from __future__ import annotations

import base64
import importlib.metadata
import json
import os
import shutil
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from chartfold.db import ChartfoldDB

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TIMESTAMP_FIELDS: dict[str, str | None] = {
    "lab_results": "result_date",
    "encounters": "encounter_date",
    "medications": "start_date",
    "procedures": "procedure_date",
    "imaging_reports": "study_date",
    "pathology_reports": "report_date",
    "clinical_notes": "note_date",
    "vitals": "recorded_date",
    "immunizations": "admin_date",
    "allergies": "onset_date",
    "conditions": "onset_date",
    "social_history": "recorded_date",
    "genetic_variants": "collection_date",
    "source_assets": "encounter_date",
    "family_history": None,
    "mental_status": "recorded_date",
    "patients": "date_of_birth",
    "notes": "created_at",
    "analyses": "created_at",
}

_FK_FIELDS: dict[str, tuple[str, str]] = {
    "procedure_id": ("procedures", "procedure_uri"),
}

_STRIP_COLS: set[str] = {"id"}

_MAX_ENUM_VALUES: int = 20

_NOTE_TABLES = {"notes", "analyses"}

_EXCLUDED_TABLES = {
    "load_log", "source_assets", "documents",
    "note_tags", "analysis_tags", "sqlite_sequence",
}

_TAG_CONFIG = {
    "notes": ("note_tags", "note_id"),
    "analyses": ("analysis_tags", "analysis_id"),
}

_COLLECTION_DESCRIPTIONS: dict[str, str] = {
    "patients": "Patient demographics",
    "encounters": "Clinical encounters and visits",
    "lab_results": "Laboratory test results with values, reference ranges, and interpretations",
    "vitals": "Vital sign measurements",
    "medications": "Medication orders and prescriptions",
    "conditions": "Diagnosed conditions and problems",
    "procedures": "Surgical and clinical procedures",
    "pathology_reports": "Pathology and histology reports linked to procedures",
    "imaging_reports": "Radiology and imaging study reports",
    "clinical_notes": "Progress notes, H&P, and other clinical documentation",
    "immunizations": "Vaccination records",
    "allergies": "Allergy and adverse reaction records",
    "social_history": "Social history (smoking, alcohol, etc.)",
    "family_history": "Family medical history",
    "mental_status": "Mental health screening instruments (PHQ-9, GAD-7, etc.)",
    "genetic_variants": "Genetic variants from genomic testing panels",
    "source_assets": "Source documents (PDFs, images) from EHR exports",
    "notes": "Personal notes and annotations",
    "analyses": "Structured analysis documents",
}


# ---------------------------------------------------------------------------
# Task 1: _row_to_record
# ---------------------------------------------------------------------------


def _row_to_record(
    row: dict[str, Any],
    table: str,
    timestamp_field: str | None,
) -> dict[str, Any]:
    """Convert a single DB row dict to an arkiv record.

    Args:
        row: Dict from db.query() with column names as keys.
        table: The clinical table name (e.g. "lab_results").
        timestamp_field: Column to use as timestamp, or None if no timestamp.

    Returns:
        An arkiv record dict with mimetype, uri, optional timestamp, and metadata.
    """
    record: dict[str, Any] = {
        "mimetype": "application/json",
        "uri": f"chartfold:{table}/{row['id']}",
    }

    # Add timestamp if the field exists and has a non-None value
    if timestamp_field is not None:
        ts_value = row.get(timestamp_field)
        if ts_value is not None:
            record["timestamp"] = ts_value

    # Build metadata: all non-null, non-empty fields, minus stripped cols
    metadata: dict[str, Any] = {"table": table}

    for col, val in row.items():
        # Skip stripped columns
        if col in _STRIP_COLS:
            continue

        # Handle FK fields: convert to URI
        if col in _FK_FIELDS:
            if val is not None:
                fk_table, uri_key = _FK_FIELDS[col]
                metadata[uri_key] = f"chartfold:{fk_table}/{val}"
            continue

        # Skip None and empty strings
        if val is None:
            continue
        if isinstance(val, str) and val == "":
            continue

        metadata[col] = val

    record["metadata"] = metadata
    return record


# ---------------------------------------------------------------------------
# Task 2: _export_table
# ---------------------------------------------------------------------------


def _export_table(
    db: ChartfoldDB,
    table: str,
    timestamp_field: str | None,
    output_dir: str,
) -> list[dict[str, Any]] | None:
    """Export all rows from one table as arkiv JSONL.

    Args:
        db: Open ChartfoldDB instance.
        table: Table name to export.
        timestamp_field: Column to use as timestamp, or None.
        output_dir: Directory to write the .jsonl file into.

    Returns:
        List of arkiv records, or None if the table is empty.
    """
    rows = db.query(f"SELECT * FROM {table}")
    if not rows:
        return None

    records = [_row_to_record(row, table, timestamp_field) for row in rows]

    jsonl_path = os.path.join(output_dir, f"{table}.jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    return records


# ---------------------------------------------------------------------------
# Task 3: _export_table_with_tags
# ---------------------------------------------------------------------------


def _export_table_with_tags(
    db: ChartfoldDB,
    table: str,
    tag_table: str,
    tag_fk_col: str,
    timestamp_field: str | None,
    output_dir: str,
) -> list[dict[str, Any]] | None:
    """Export a table with tags folded from a related tag table.

    Like _export_table but also queries the tag table and adds a sorted
    "tags" list to each record's metadata when tags exist.

    Args:
        db: Open ChartfoldDB instance.
        table: Main table name (e.g. "notes" or "analyses").
        tag_table: Tag table name (e.g. "note_tags" or "analysis_tags").
        tag_fk_col: FK column in tag_table pointing to parent (e.g. "note_id").
        timestamp_field: Column to use as timestamp, or None.
        output_dir: Directory to write the .jsonl file into.

    Returns:
        List of arkiv records, or None if the table is empty.
    """
    rows = db.query(f"SELECT * FROM {table}")
    if not rows:
        return None

    # Build tag lookup: parent_id -> sorted list of tags
    tag_rows = db.query(f"SELECT {tag_fk_col}, tag FROM {tag_table}")
    tag_lookup: dict[int, list[str]] = defaultdict(list)
    for trow in tag_rows:
        tag_lookup[trow[tag_fk_col]].append(trow["tag"])

    records = []
    for row in rows:
        rec = _row_to_record(row, table, timestamp_field)
        tags = tag_lookup.get(row["id"])
        if tags:
            rec["metadata"]["tags"] = sorted(tags)
        records.append(rec)

    jsonl_path = os.path.join(output_dir, f"{table}.jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    return records


# ---------------------------------------------------------------------------
# Task 4: _build_schema
# ---------------------------------------------------------------------------


def _build_schema(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Discover schema from a list of arkiv records.

    Scans all records' metadata keys and for each key:
    - Detects the JSON type (string/number/boolean/array/object)
    - Counts occurrences
    - If unique values < _MAX_ENUM_VALUES: includes "values" (sorted list)
    - If unique values >= _MAX_ENUM_VALUES: includes "example" (one sample)

    Args:
        records: List of arkiv record dicts.

    Returns:
        Schema dict: {"metadata_keys": {key: {type, count, values|example}, ...}}
    """
    if not records:
        return {"metadata_keys": {}}

    # Track per-key: type, count, unique values (as hashable for tracking),
    # and actual sample values
    key_types: dict[str, str] = {}
    key_counts: dict[str, int] = defaultdict(int)
    key_unique_hashable: dict[str, set[Any]] = defaultdict(set)
    key_sample: dict[str, Any] = {}

    for rec in records:
        metadata = rec.get("metadata", {})
        for key, val in metadata.items():
            key_counts[key] += 1

            # Detect type from first occurrence
            if key not in key_types:
                key_types[key] = _detect_json_type(val)

            # Store sample value (first seen)
            if key not in key_sample:
                key_sample[key] = val

            # Track unique values - use str() for unhashable types
            try:
                key_unique_hashable[key].add(val)
            except TypeError:
                # Unhashable (list, dict) - use string repr for tracking
                key_unique_hashable[key].add(str(val))

    # Build schema output
    metadata_keys: dict[str, Any] = {}
    for key in sorted(key_types):
        entry: dict[str, Any] = {
            "type": key_types[key],
            "count": key_counts[key],
        }

        unique_count = len(key_unique_hashable[key])
        if unique_count < _MAX_ENUM_VALUES:
            # Collect actual values for sorted output
            actual_values = _collect_actual_values(key, records)
            entry["values"] = _sort_values(actual_values)
        else:
            entry["example"] = key_sample[key]

        metadata_keys[key] = entry

    return {"metadata_keys": metadata_keys}


def _detect_json_type(val: Any) -> str:
    """Detect JSON type name for a Python value."""
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, (int, float)):
        return "number"
    if isinstance(val, str):
        return "string"
    if isinstance(val, list):
        return "array"
    if isinstance(val, dict):
        return "object"
    return "string"  # fallback


def _collect_actual_values(key: str, records: list[dict[str, Any]]) -> list[Any]:
    """Collect all unique actual values for a metadata key across records."""
    seen_hashable: set[Any] = set()
    values: list[Any] = []

    for rec in records:
        val = rec.get("metadata", {}).get(key)
        if val is None:
            continue

        # For unhashable types, use str repr for dedup
        try:
            hashable = val
            hash(hashable)
        except TypeError:
            hashable = str(val)

        if hashable not in seen_hashable:
            seen_hashable.add(hashable)
            values.append(val)

    return values


def _sort_values(values: list[Any]) -> list[Any]:
    """Sort a list of mixed-type values for schema output."""
    try:
        return sorted(values)
    except TypeError:
        # Mixed types that can't be compared - sort by string representation
        return sorted(values, key=str)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_version() -> str:
    """Return the installed chartfold version, or 'dev' if not installed."""
    try:
        return importlib.metadata.version("chartfold")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


# ---------------------------------------------------------------------------
# Source asset export
# ---------------------------------------------------------------------------


def _export_source_assets(
    db: ChartfoldDB,
    output_dir: str,
    embed: bool = False,
) -> list[dict[str, Any]] | None:
    """Export source_assets as arkiv records with actual MIME types.

    Default mode: copy files to media/ subdirectory, use file://media/ URIs.
    Embed mode: also base64-encode content inline per arkiv spec.
    """
    rows = db.query("SELECT * FROM source_assets")
    if not rows:
        return None

    media_dir = os.path.join(output_dir, "media")
    os.makedirs(media_dir, exist_ok=True)

    records: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for row in rows:
        file_name = row["file_name"]
        file_path = row["file_path"]
        mime = row.get("content_type") or "application/octet-stream"

        # Skip assets whose source files don't exist
        src_path = Path(file_path)
        if not src_path.is_file():
            continue

        # Disambiguate colliding file names with row ID prefix
        media_name = file_name
        if media_name in seen_names:
            media_name = f"{row['id']}_{file_name}"
        seen_names.add(media_name)

        record: dict[str, Any] = {
            "mimetype": mime,
            "uri": f"file://media/{media_name}",
        }

        # Timestamp
        ts = row.get("encounter_date")
        if ts:
            record["timestamp"] = ts

        # Copy file to media/
        dest = os.path.join(media_dir, media_name)
        shutil.copy2(str(src_path), dest)

        # Embed mode: base64 inline
        if embed:
            with open(str(src_path), "rb") as bf:
                record["content"] = base64.b64encode(bf.read()).decode("ascii")

        # Build metadata (skip file_path — replaced by URI;
        # skip ref_id — replaced by ref_id_uri below)
        metadata: dict[str, Any] = {"table": "source_assets"}
        skip_keys = {"id", "file_path", "content_type", "ref_id"}
        for col, val in row.items():
            if col in skip_keys:
                continue
            if val is None or (isinstance(val, str) and val == ""):
                continue
            metadata[col] = val

        # Add ref_id_uri if ref_table and ref_id present
        if row.get("ref_table") and row.get("ref_id"):
            metadata["ref_id_uri"] = f"chartfold:{row['ref_table']}/{row['ref_id']}"

        record["metadata"] = metadata
        records.append(record)

    if not records:
        return None

    jsonl_path = os.path.join(output_dir, "source_assets.jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    return records


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def export_arkiv(
    db: ChartfoldDB,
    output_dir: str,
    include_notes: bool = True,
    embed: bool = False,
) -> str:
    """Export database to arkiv format (JSONL + README.md + schema.yaml).

    Args:
        db: Database connection.
        output_dir: Directory to write output files.
        include_notes: Include personal notes and analyses.
        embed: Base64-encode source asset content inline in arkiv records.

    Returns the output directory path.
    """
    os.makedirs(output_dir, exist_ok=True)

    tables_to_export = [
        t for t in _TIMESTAMP_FIELDS
        if t not in _EXCLUDED_TABLES
        and (include_notes or t not in _NOTE_TABLES)
    ]

    # Per-collection data for README contents and schema.yaml
    contents: list[dict[str, str]] = []
    schema_data: dict[str, Any] = {}

    for table in tables_to_export:
        ts_field = _TIMESTAMP_FIELDS[table]

        if table in _TAG_CONFIG:
            tag_table, tag_fk = _TAG_CONFIG[table]
            records = _export_table_with_tags(
                db, table, tag_table, tag_fk, ts_field, output_dir
            )
        else:
            records = _export_table(db, table, ts_field, output_dir)

        if records is None:
            continue

        schema = _build_schema(records)
        description = _COLLECTION_DESCRIPTIONS.get(table, table)
        contents.append({
            "path": f"{table}.jsonl",
            "description": description,
        })
        schema_data[table] = {
            "record_count": len(records),
            **schema,
        }

    # Export source assets separately (different record format)
    asset_records = _export_source_assets(db, output_dir, embed=embed)
    if asset_records is not None:
        schema = _build_schema(asset_records)
        contents.append({
            "path": "source_assets.jsonl",
            "description": _COLLECTION_DESCRIPTIONS.get(
                "source_assets", "Source assets"
            ),
        })
        schema_data["source_assets"] = {
            "record_count": len(asset_records),
            **schema,
        }

    # Write README.md with YAML frontmatter
    today = date.today().isoformat()
    version = _get_version()

    frontmatter = {
        "name": "Chartfold clinical data export",
        "description": "Clinical records from Epic, MEDITECH, and athenahealth",
        "datetime": today,
        "generator": f"chartfold v{version}",
        "contents": contents,
    }
    frontmatter_yaml = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)

    readme_path = os.path.join(output_dir, "README.md")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("---\n")
        f.write(frontmatter_yaml)
        f.write("---\n\n")
        f.write("# Chartfold Clinical Data Export\n\n")
        f.write(f"Exported from chartfold database on {today}.\n")

    # Write schema.yaml
    schema_path = os.path.join(output_dir, "schema.yaml")
    with open(schema_path, "w", encoding="utf-8") as f:
        yaml.dump(schema_data, f, default_flow_style=False, sort_keys=False)

    return output_dir
