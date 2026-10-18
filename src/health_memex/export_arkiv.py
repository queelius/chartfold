"""Export health-memex clinical data to arkiv universal record format.

Each clinical table is exported as a separate .jsonl file, with one arkiv record
per database row. Tags from note_tags and analysis_tags are folded into the
parent record's metadata.

The archive manifest is written as README.md (YAML frontmatter) + schema.yaml,
following the arkiv specification.

Bundle formats (C5a workspace contract):
    Output path extension drives packaging:
      - ``.zip``              -> single-file zip archive
      - ``.tar.gz`` / ``.tgz`` -> single-file gzip tarball
      - anything else         -> directory (historical behavior)

All three layouts carry the same records.jsonl shards + README.md +
schema.yaml + any media/ assets.

Security notice for operators:
    Arkiv archives contain PHI in plaintext (JSONL + YAML). Keep them
    encrypted at rest (full-disk encryption, GPG, or a password-
    protected zip) and NEVER publish or email them without the
    recipient's understanding. The exporter does not encrypt; that is
    the operator's responsibility.
"""

from __future__ import annotations

import base64
import importlib.metadata
import json
import os
import shutil
import tarfile
import tempfile
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from arkiv import bundle_format, pack_bundle

if TYPE_CHECKING:
    from health_memex.db import HealthMemexDB

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
    "load_log",
    "source_assets",
    "documents",
    "note_tags",
    "analysis_tags",
    "sqlite_sequence",
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
    # URIs use unique_id (durable, content-hash from natural key)
    # for tables that have one. For notes/analyses (user-authored,
    # not re-imported), there's no natural key to hash, so we fall
    # back to autoincrement id. That's acceptable because these
    # tables aren't recreated by EHR re-imports — autoincrement is
    # stable for them in practice.
    uid = row.get("unique_id")
    if uid:
        uri_id = uid
    elif table in {"notes", "analyses"}:
        uri_id = str(row["id"])
    else:
        # Should never happen for clinical tables since load_source
        # auto-fills unique_id on every UPSERT; the migration
        # backfills any pre-existing rows. Surface as an error
        # rather than write a malformed URI.
        raise ValueError(
            f"row in {table!r} (id={row.get('id')!r}) has no unique_id; "
            "cannot export. Run init_schema() to backfill."
        )

    record: dict[str, Any] = {
        "mimetype": "application/json",
        "uri": f"health-memex:{table}/{uri_id}",
    }

    # Add timestamp if the field exists and has a non-None value
    if timestamp_field is not None:
        ts_value = row.get(timestamp_field)
        if ts_value is not None:
            record["timestamp"] = ts_value

    # Build metadata: all non-null, non-empty fields, minus stripped cols.
    # unique_id is also stripped from metadata since it's already in the URI.
    metadata: dict[str, Any] = {"table": table}
    skip_cols = _STRIP_COLS | {"unique_id"}

    for col, val in row.items():
        # Skip stripped columns
        if col in skip_cols:
            continue

        # Handle FK fields: convert to URI using parent's unique_id.
        # The parent table has unique_id (it's in _UNIQUE_KEYS); we
        # look it up via a small per-row JOIN. For personal-archive
        # scale this is fine; if it ever matters, _row_to_record
        # could accept a pre-built id-to-unique_id map.
        if col in _FK_FIELDS:
            if val is not None:
                fk_table, uri_key = _FK_FIELDS[col]
                metadata[uri_key] = f"health-memex:{fk_table}/{val}"
                # ↑ val is set by the caller _export_table to the
                # parent's unique_id, not its autoincrement id. This
                # is the upgrade from the old scheme.
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


# Per-export schema cache. Keyed by id(db.conn) so multiple concurrent
# exports against different databases don't see each other's caches.
# Cleared at the start of each export_arkiv() call (see _reset_caches
# in the export entry point).
_TABLE_COLS_CACHE: dict[int, dict[str, set[str]]] = {}


def _table_columns(db: HealthMemexDB, table: str) -> set[str]:
    """Column-name set for *table*, cached per export.

    PRAGMA table_info is cheap individually but pricey when called
    inside a per-row loop where ``db.query`` opens a fresh read-only
    connection each time. We cache the column set per (connection,
    table) pair so the second-and-later calls are O(1).

    The cache is cleared at the start of every ``export_arkiv()`` call
    so a long-running process (e.g. test suite) that exports against
    multiple DBs doesn't accumulate stale entries.
    """
    cache = _TABLE_COLS_CACHE.setdefault(id(db.conn), {})
    if table not in cache:
        cache[table] = {r["name"] for r in db.query(f"PRAGMA table_info({table})")}
    return cache[table]


def _reset_export_caches() -> None:
    """Clear the per-export caches. Called by export_arkiv()."""
    _TABLE_COLS_CACHE.clear()


def _select_rows_with_fk_uids(db: HealthMemexDB, table: str) -> list[dict[str, Any]]:
    """SELECT all rows from *table*, resolving each FK in _FK_FIELDS
    to the parent's unique_id.

    The arkiv URI format uses parent.unique_id (durable) rather than
    parent.id (autoincrement, churns on re-import). Resolving at SQL
    time via LEFT JOIN keeps _row_to_record simple — it just sees the
    FK column already populated with the parent's unique_id string
    instead of the autoincrement integer.
    """
    cols = _table_columns(db, table)
    fk_cols = [fk for fk in _FK_FIELDS if fk in cols]
    if not fk_cols:
        return db.query(f"SELECT * FROM {table}")

    # Build a SELECT that overrides each FK column with the parent's
    # unique_id (or NULL if FK is itself NULL). SQLite returns the
    # LAST same-named column when a SELECT yields duplicates, so the
    # alias-qualified ``unique_id AS <fk_col>`` wins over the original
    # FK integer column from ``{table}.*``.
    select_pieces = [f"{table}.*"]
    join_pieces = []
    for fk_col in fk_cols:
        parent_table, _uri_key = _FK_FIELDS[fk_col]
        alias = f"_p_{fk_col}"
        select_pieces.append(f"{alias}.unique_id AS {fk_col}")
        join_pieces.append(f"LEFT JOIN {parent_table} {alias} ON {alias}.id = {table}.{fk_col}")
    sql = f"SELECT {', '.join(select_pieces)} FROM {table} " + " ".join(join_pieces)
    return db.query(sql)


def _lookup_unique_id(db: HealthMemexDB, table: str, autoincrement_id: int) -> str | None:
    """Look up a row's unique_id given its autoincrement id.

    Used by source_assets export to translate ``ref_id`` (autoincrement)
    into the parent's durable unique_id for the ``ref_id_uri`` field.
    Returns None if the row doesn't exist, the table doesn't have a
    unique_id column, or unique_id is NULL on that row.
    """
    if "unique_id" not in _table_columns(db, table):
        return None
    rows = db.query(
        f"SELECT unique_id FROM {table} WHERE id = ?",
        (autoincrement_id,),
    )
    return rows[0]["unique_id"] if rows else None


def _export_table(
    db: HealthMemexDB,
    table: str,
    timestamp_field: str | None,
    output_dir: str,
) -> list[dict[str, Any]] | None:
    """Export all rows from one table as arkiv JSONL.

    Args:
        db: Open HealthMemexDB instance.
        table: Table name to export.
        timestamp_field: Column to use as timestamp, or None.
        output_dir: Directory to write the .jsonl file into.

    Returns:
        List of arkiv records, or None if the table is empty.
    """
    rows = _select_rows_with_fk_uids(db, table)
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
    db: HealthMemexDB,
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
        db: Open HealthMemexDB instance.
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
    """Return the installed health-memex version, or 'dev' if not installed."""
    try:
        return importlib.metadata.version("health-memex")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


# ---------------------------------------------------------------------------
# Source asset export
# ---------------------------------------------------------------------------


def _export_source_assets(
    db: HealthMemexDB,
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

        # Add ref_id_uri if ref_table and ref_id present.
        # Translate the autoincrement ref_id into the parent's
        # unique_id so the URI is durable across re-imports. Skip
        # silently if the parent row doesn't exist (orphan source
        # asset) or doesn't have a unique_id (legacy data not yet
        # backfilled — though init_schema should have handled it).
        if row.get("ref_table") and row.get("ref_id") is not None:
            ref_table = row["ref_table"]
            parent_uid = _lookup_unique_id(db, ref_table, row["ref_id"])
            if parent_uid:
                metadata["ref_id_uri"] = f"health-memex:{ref_table}/{parent_uid}"

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


def _staged_files(directory: str) -> set[str]:
    """Archive-relative POSIX paths of every regular file under *directory*."""
    root = Path(directory)
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _bundle_members(bundle: str, fmt: str) -> set[str]:
    """Member names of a packed ``.zip`` / ``.tar.gz`` bundle."""
    if fmt == "zip":
        with zipfile.ZipFile(bundle) as zf:
            return set(zf.namelist())
    with tarfile.open(bundle, "r:gz") as tf:
        return set(tf.getnames())


def _pack_staging(staging: str, archive_path: str, fmt: str) -> None:
    """Pack *staging* into *archive_path* via ``arkiv.pack_bundle``.

    ``pack_bundle`` deliberately omits dot-prefixed entries and the derived
    database at the archive root (``*.db`` / ``*.sqlite`` beside
    README.md). Every file health-memex stages is real payload (a source
    asset can arrive as ``media/.something``), so after packing we compare
    the bundle's members against the staged tree and refuse to leave a
    lossy bundle behind rather than drop data silently.
    """
    pack_bundle(staging, archive_path)
    dropped = sorted(_staged_files(staging) - _bundle_members(archive_path, fmt))
    if dropped:
        os.unlink(archive_path)
        raise ValueError(
            f"arkiv bundle packing would omit {len(dropped)} exported file(s) "
            f"({', '.join(dropped)}); export to a directory instead"
        )


def export_arkiv(
    db: HealthMemexDB,
    output_dir: str,
    include_notes: bool = True,
    embed: bool = False,
) -> str:
    """Export database to arkiv bundle (directory / .zip / .tar.gz).

    Args:
        db: Database connection.
        output_dir: Destination path. If it ends in ``.zip`` or
            ``.tar.gz``/``.tgz``, a single-file archive is written
            containing records.jsonl + README.md + schema.yaml + media/.
            Any other path is treated as a directory (historical
            behavior).
        include_notes: Include personal notes and analyses.
        embed: Base64-encode source asset content inline in arkiv records.

    Returns the output path (the archive file or the directory, depending
    on the format inferred from the extension).
    """
    _reset_export_caches()
    fmt = bundle_format(output_dir)

    if fmt not in ("zip", "tar.gz"):
        work_dir = output_dir
        os.makedirs(work_dir, exist_ok=True)
        _write_bundle_contents(db, work_dir, include_notes=include_notes, embed=embed)
        return work_dir

    # Archive path: write to a staging dir, then pack.
    archive_path = output_dir
    os.makedirs(os.path.dirname(os.path.abspath(archive_path)) or ".", exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="health_memex_arkiv_") as staging:
        _write_bundle_contents(db, staging, include_notes=include_notes, embed=embed)
        _pack_staging(staging, archive_path, fmt)
    return archive_path


def _write_bundle_contents(
    db: HealthMemexDB,
    output_dir: str,
    include_notes: bool,
    embed: bool,
) -> None:
    """Fill *output_dir* with records.jsonl + README.md + schema.yaml + media/.

    Pulled out of ``export_arkiv`` so both the direct-to-directory and
    pack-and-archive paths share the same body.
    """
    os.makedirs(output_dir, exist_ok=True)

    tables_to_export = [
        t
        for t in _TIMESTAMP_FIELDS
        if t not in _EXCLUDED_TABLES and (include_notes or t not in _NOTE_TABLES)
    ]

    # Per-collection data for README contents and schema.yaml
    contents: list[dict[str, str]] = []
    schema_data: dict[str, Any] = {}

    for table in tables_to_export:
        ts_field = _TIMESTAMP_FIELDS[table]

        if table in _TAG_CONFIG:
            tag_table, tag_fk = _TAG_CONFIG[table]
            records = _export_table_with_tags(db, table, tag_table, tag_fk, ts_field, output_dir)
        else:
            records = _export_table(db, table, ts_field, output_dir)

        if records is None:
            continue

        schema = _build_schema(records)
        description = _COLLECTION_DESCRIPTIONS.get(table, table)
        contents.append(
            {
                "path": f"{table}.jsonl",
                "description": description,
            }
        )
        schema_data[table] = {
            "record_count": len(records),
            **schema,
        }

    # Export source assets separately (different record format)
    asset_records = _export_source_assets(db, output_dir, embed=embed)
    if asset_records is not None:
        schema = _build_schema(asset_records)
        contents.append(
            {
                "path": "source_assets.jsonl",
                "description": _COLLECTION_DESCRIPTIONS.get("source_assets", "Source assets"),
            }
        )
        schema_data["source_assets"] = {
            "record_count": len(asset_records),
            **schema,
        }

    # Write README.md with YAML frontmatter
    today = date.today().isoformat()
    version = _get_version()

    frontmatter = {
        "name": "Health Memex clinical data export",
        "description": "Clinical records from Epic, MEDITECH, and athenahealth",
        "datetime": today,
        "generator": f"health-memex v{version}",
        "contents": contents,
    }
    frontmatter_yaml = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)

    readme_path = os.path.join(output_dir, "README.md")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("---\n")
        f.write(frontmatter_yaml)
        f.write("---\n\n")
        f.write("# Health Memex Clinical Data Export\n\n")
        f.write(f"Exported from health_memex database on {today}.\n")

    # Write schema.yaml
    schema_path = os.path.join(output_dir, "schema.yaml")
    with open(schema_path, "w", encoding="utf-8") as f:
        yaml.dump(schema_data, f, default_flow_style=False, sort_keys=False)
