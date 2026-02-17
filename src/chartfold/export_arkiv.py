"""Export chartfold clinical data to arkiv universal record format (JSONL + manifest).

Each clinical table is exported as a separate .jsonl file, with one arkiv record
per database row. Tags from note_tags and analysis_tags are folded into the
parent record's metadata.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date
from typing import TYPE_CHECKING, Any

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
    rows = db.query(f"SELECT * FROM {table}")  # noqa: S608
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
    rows = db.query(f"SELECT * FROM {table}")  # noqa: S608
    if not rows:
        return None

    # Build tag lookup: parent_id -> sorted list of tags
    tag_rows = db.query(f"SELECT {tag_fk_col}, tag FROM {tag_table}")  # noqa: S608
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
# Main entry point
# ---------------------------------------------------------------------------


def export_arkiv(
    db: ChartfoldDB,
    output_dir: str,
    include_notes: bool = True,
) -> str:
    """Export database to arkiv format (JSONL + manifest).

    Args:
        db: Database connection.
        output_dir: Directory to write output files.
        include_notes: Include personal notes and analyses.

    Returns the output directory path.
    """
    os.makedirs(output_dir, exist_ok=True)

    tables_to_export = [
        t for t in _TIMESTAMP_FIELDS
        if t not in _EXCLUDED_TABLES
        and (include_notes or t not in _NOTE_TABLES)
    ]

    collections = []
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
        collections.append({
            "file": f"{table}.jsonl",
            "description": _COLLECTION_DESCRIPTIONS.get(table, table),
            "record_count": len(records),
            "schema": schema,
        })

    manifest = {
        "description": "Chartfold clinical data export",
        "created": date.today().isoformat(),
        "metadata": {"source_tool": "chartfold"},
        "collections": collections,
    }
    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return output_dir
