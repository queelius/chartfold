"""Import chartfold clinical data from arkiv universal record format.

Reverses the export performed by export_arkiv.py: parses JSONL records,
remaps FK references, unfolds tags, and inserts into a fresh SQLite database
in topological (FK-dependency) order.
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from chartfold.db import (
    ChartfoldDB,
    _discover_fk_graph,
    _discover_tables,
    _topological_sort,
)
from chartfold.export_arkiv import _FK_FIELDS, _TAG_CONFIG

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Reverse FK mapping: uri_key -> (fk_col, parent_table)
_REVERSE_FK: dict[str, tuple[str, str]] = {
    uri_key: (fk_col, parent_table)
    for fk_col, (parent_table, uri_key) in _FK_FIELDS.items()
}

_SYNTHETIC_KEYS = {"table"}

_URI_PATTERN = re.compile(r"^chartfold:(\w+)/(\d+)$")

# Reverse tag config: table -> (tag_table, tag_fk_col)
_REVERSE_TAG_CONFIG = _TAG_CONFIG  # same structure works for import


# ---------------------------------------------------------------------------
# _record_to_row
# ---------------------------------------------------------------------------


def _record_to_row(
    record: dict[str, Any],
) -> tuple[str, int | None, dict[str, Any]]:
    """Convert an arkiv record back to a DB row dict.

    Reverses _row_to_record():
    1. Extracts table name from metadata.table
    2. Parses old ID from the URI (chartfold:{table}/{id})
    3. Reverses FK URIs (procedure_uri -> procedure_id)
    4. Reverses ref_id_uri for source_assets
    5. Extracts tags from metadata -> row["_tags"]
    6. Strips synthetic keys (table)

    Returns:
        (table_name, old_id_or_None, row_dict)
    """
    metadata = record.get("metadata", {})
    table = metadata["table"]

    # Parse old ID from URI
    old_id: int | None = None
    uri = record.get("uri", "")
    m = _URI_PATTERN.match(uri)
    if m:
        old_id = int(m.group(2))

    # Build row from metadata, reversing transformations
    row: dict[str, Any] = {}

    for key, val in metadata.items():
        # Skip synthetic keys
        if key in _SYNTHETIC_KEYS:
            continue

        # Reverse FK URIs -> FK ID columns
        if key in _REVERSE_FK:
            fk_col, _parent_table = _REVERSE_FK[key]
            fk_match = _URI_PATTERN.match(val)
            if fk_match:
                row[fk_col] = int(fk_match.group(2))
            continue

        # Reverse ref_id_uri for source_assets
        if key == "ref_id_uri":
            ref_match = _URI_PATTERN.match(val)
            if ref_match:
                row["ref_table"] = ref_match.group(1)
                row["ref_id"] = int(ref_match.group(2))
            continue

        # Extract tags -> _tags (inserted separately)
        if key == "tags" and table in _TAG_CONFIG:
            row["_tags"] = val
            continue

        row[key] = val

    return table, old_id, row


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_table_columns(db: ChartfoldDB, table: str) -> set[str]:
    """Get column names for a table (excluding 'id')."""
    rows = db.query(f"PRAGMA table_info({table})")
    return {r["name"] for r in rows if r["name"] != "id"}


def _parse_frontmatter(readme_text: str) -> dict[str, Any] | None:
    """Parse YAML frontmatter from a README.md file.

    Returns the parsed YAML dict, or None if parsing fails.
    """
    if not readme_text.startswith("---\n"):
        return None

    parts = readme_text.split("---\n", 2)
    if len(parts) < 3:
        return None

    try:
        return yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None


def _parse_source_asset_records(
    records: list[dict[str, Any]],
) -> list[tuple[int | None, dict[str, Any]]]:
    """Parse source_assets JSONL records into (old_id, row) tuples.

    Source asset records have non-application/json mimetypes and different
    metadata structure than clinical records.
    """
    result = []
    for record in records:
        metadata = record.get("metadata", {})
        if metadata.get("table") != "source_assets":
            continue

        # Parse old ID from metadata or URI — source assets use file:// URIs
        # but may also have a regular chartfold: URI in some cases
        old_id: int | None = None
        uri = record.get("uri", "")
        chartfold_match = _URI_PATTERN.match(uri)
        if chartfold_match:
            old_id = int(chartfold_match.group(2))

        row: dict[str, Any] = {}

        for key, val in metadata.items():
            if key in _SYNTHETIC_KEYS:
                continue
            # Reverse ref_id_uri
            if key == "ref_id_uri":
                ref_match = _URI_PATTERN.match(val)
                if ref_match:
                    row["ref_table"] = ref_match.group(1)
                    row["ref_id"] = int(ref_match.group(2))
                continue
            row[key] = val

        # Set content_type from the record's mimetype
        row["content_type"] = record.get("mimetype", "application/octet-stream")

        # Handle file_path: look for media file from URI
        if uri.startswith("file://media/"):
            media_name = uri[len("file://media/"):]
            row["_media_name"] = media_name
        elif record.get("content"):
            # base64-embedded content
            row["_base64_content"] = record["content"]

        # file_path will be set during import based on archive location
        # If not already set, initialize to empty
        if "file_path" not in row:
            row["file_path"] = ""

        result.append((old_id, row))

    return result


def _import_source_assets(
    db: ChartfoldDB,
    asset_rows: list[tuple[int | None, dict[str, Any]]],
    archive_dir: str,
    id_map: dict[str, dict[int, int]],
    table_columns: set[str],
) -> int:
    """Import source asset records into the database.

    Handles file_path resolution from archive's media/ directory,
    ref_id remapping through id_map, and base64 content restoration.

    Returns the number of imported records.
    """
    count = 0
    media_dir = os.path.join(archive_dir, "media")

    for old_id, row in asset_rows:
        # Resolve file_path from media/
        media_name = row.pop("_media_name", None)
        base64_content = row.pop("_base64_content", None)

        if media_name and os.path.isdir(media_dir):
            media_path = os.path.join(media_dir, media_name)
            if os.path.isfile(media_path):
                row["file_path"] = os.path.abspath(media_path)

        if not row.get("file_path") and base64_content:
            # Write base64 content to media/ in the archive
            os.makedirs(media_dir, exist_ok=True)
            file_name = row.get("file_name", f"asset_{old_id}")
            dest = os.path.join(media_dir, file_name)
            with open(dest, "wb") as f:
                f.write(base64.b64decode(base64_content))
            row["file_path"] = os.path.abspath(dest)

        if not row.get("file_path"):
            row["file_path"] = ""

        # Remap ref_id through id_map
        ref_table = row.get("ref_table")
        ref_id = row.get("ref_id")
        if ref_table and ref_id is not None:
            parent_map = id_map.get(ref_table, {})
            if parent_map:
                row["ref_id"] = parent_map.get(ref_id, ref_id)

        # Filter to known columns only
        filtered = {k: v for k, v in row.items() if k in table_columns}

        if not filtered:
            continue

        cols = list(filtered.keys())
        col_names = ", ".join(cols)
        placeholders = ", ".join("?" for _ in cols)

        cursor = db.conn.execute(
            f"INSERT INTO source_assets ({col_names}) VALUES ({placeholders})",
            list(filtered.values()),
        )

        if old_id is not None:
            id_map.setdefault("source_assets", {})[old_id] = cursor.lastrowid

        count += 1

    return count


# ---------------------------------------------------------------------------
# validate_arkiv
# ---------------------------------------------------------------------------


def validate_arkiv(archive_dir: str) -> dict[str, Any]:
    """Validate an arkiv archive without importing.

    Checks:
    - README.md exists and has valid YAML frontmatter
    - schema.yaml parses (optional file)
    - Each JSONL file listed in frontmatter exists and contains valid JSON

    Returns:
        {"valid": bool, "errors": list[str], "summary": dict[str, int]}
    """
    errors: list[str] = []
    summary: dict[str, int] = {}

    readme_path = os.path.join(archive_dir, "README.md")
    if not os.path.isfile(readme_path):
        errors.append(f"Missing README.md in {archive_dir}")
        return {"valid": False, "errors": errors, "summary": summary}

    with open(readme_path, "r", encoding="utf-8") as f:
        readme_text = f.read()

    frontmatter = _parse_frontmatter(readme_text)
    if frontmatter is None:
        errors.append("Invalid or missing YAML frontmatter in README.md")
        return {"valid": False, "errors": errors, "summary": summary}

    # Check schema.yaml (optional but validated if present)
    schema_path = os.path.join(archive_dir, "schema.yaml")
    if os.path.isfile(schema_path):
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                yaml.safe_load(f)
        except yaml.YAMLError as e:
            errors.append(f"Invalid schema.yaml: {e}")

    # Validate each JSONL file listed in contents
    contents = frontmatter.get("contents", [])
    for entry in contents:
        path = entry.get("path", "")
        jsonl_path = os.path.join(archive_dir, path)

        if not os.path.isfile(jsonl_path):
            errors.append(f"Missing file listed in contents: {path}")
            continue

        # Parse table name from filename (e.g., "lab_results.jsonl" -> "lab_results")
        table_name = os.path.splitext(os.path.basename(path))[0]
        line_count = 0

        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line_num, raw_line in enumerate(f, 1):
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    json.loads(stripped)
                    line_count += 1
                except json.JSONDecodeError as e:
                    errors.append(
                        f"Invalid JSON in {path} line {line_num}: {e}"
                    )

        summary[table_name] = line_count

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# import_arkiv
# ---------------------------------------------------------------------------


def import_arkiv(
    archive_dir: str,
    db_path: str,
    validate_only: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Import an arkiv archive into a fresh chartfold database.

    Pipeline:
    1. Validate the archive
    2. Check if DB exists (refuse without overwrite=True)
    3. Parse JSONL records from all files
    4. Create fresh DB with init_schema()
    5. Topological sort tables by FK dependencies
    6. Insert rows in FK order with ID remapping
    7. Unfold tags from _tags -> tag table inserts
    8. Handle source_assets separately

    Args:
        archive_dir: Path to the arkiv archive directory.
        db_path: Path for the target SQLite database.
        validate_only: If True, only validate without importing.
        overwrite: If True, overwrite existing database.

    Returns:
        {"success": bool, "errors": list[str], "counts": dict[str, int]}
    """
    # Step 1: Validate
    validation = validate_arkiv(archive_dir)
    if not validation["valid"]:
        return {
            "success": False,
            "errors": validation["errors"],
            "counts": {},
        }

    if validate_only:
        return {
            "success": True,
            "errors": [],
            "counts": validation["summary"],
        }

    # Step 2: Check if DB exists
    db_exists = Path(db_path).exists()
    if db_exists and not overwrite:
        return {
            "success": False,
            "errors": [f"Database already exists: {db_path}. Use --overwrite to replace."],
            "counts": {},
        }

    # Step 3: Parse all JSONL records, grouped by table
    readme_path = os.path.join(archive_dir, "README.md")
    with open(readme_path, "r", encoding="utf-8") as f:
        frontmatter = _parse_frontmatter(f.read())

    # Collect records by table
    table_records: dict[str, list[tuple[int | None, dict[str, Any]]]] = {}
    source_asset_raw_records: list[dict[str, Any]] = []

    contents = frontmatter.get("contents", []) if frontmatter else []
    for entry in contents:
        path = entry.get("path", "")
        jsonl_path = os.path.join(archive_dir, path)

        if not os.path.isfile(jsonl_path):
            continue

        with open(jsonl_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                stripped = raw_line.strip()
                if not stripped:
                    continue
                record = json.loads(stripped)
                metadata = record.get("metadata", {})
                table = metadata.get("table")

                if not table:
                    continue

                # Source assets are handled separately
                if table == "source_assets":
                    source_asset_raw_records.append(record)
                    continue

                # Regular clinical records
                if record.get("mimetype") != "application/json":
                    continue

                tbl, old_id, row = _record_to_row(record)
                table_records.setdefault(tbl, []).append((old_id, row))

    # Parse source asset records
    source_asset_rows = _parse_source_asset_records(source_asset_raw_records)

    # Step 4: Create fresh DB
    if db_exists and overwrite:
        Path(db_path).unlink()

    errors: list[str] = []
    counts: dict[str, int] = {}

    with ChartfoldDB(db_path) as db:
        db.init_schema()

        # Step 5: Topological sort
        schema_tables = _discover_tables(db)
        fk_graph = _discover_fk_graph(db, schema_tables)
        import_order = _topological_sort(schema_tables, fk_graph)

        # Track ID remappings: table -> {old_id: new_id}
        id_map: dict[str, dict[int, int]] = {}

        # Tag tables to skip in main loop (handled after parent insert)
        tag_tables = set()
        for tag_table, _fk_col in _TAG_CONFIG.values():
            tag_tables.add(tag_table)

        # Step 6: Insert rows in FK order
        for table in import_order:
            # Skip tag tables (handled via _tags unfolding)
            if table in tag_tables:
                continue

            # Skip source_assets (handled separately)
            if table == "source_assets":
                continue

            if table not in table_records:
                counts[table] = 0
                continue

            rows_for_table = table_records[table]
            id_map[table] = {}

            # Get valid columns for this table
            valid_columns = _get_table_columns(db, table)

            # Get FK columns for remapping
            table_fks = fk_graph.get(table, [])

            for old_id, row in rows_for_table:
                # Extract tags before column filtering
                tags = row.pop("_tags", None)

                # Remap FK columns
                for fk_col, parent_table, _parent_col in table_fks:
                    old_fk = row.get(fk_col)
                    if old_fk is not None:
                        parent_map = id_map.get(parent_table, {})
                        if parent_map:
                            row[fk_col] = parent_map.get(old_fk, old_fk)

                # Filter to valid columns only
                filtered = {k: v for k, v in row.items() if k in valid_columns}

                if not filtered:
                    continue

                cols = list(filtered.keys())
                col_names = ", ".join(cols)
                placeholders = ", ".join("?" for _ in cols)

                cursor = db.conn.execute(
                    f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                    list(filtered.values()),
                )

                new_id = cursor.lastrowid
                if old_id is not None:
                    id_map[table][old_id] = new_id

                # Step 7: Unfold tags
                if tags and table in _TAG_CONFIG:
                    tag_table, tag_fk_col = _TAG_CONFIG[table]
                    for tag in tags:
                        clean = tag.strip()
                        if clean:
                            db.conn.execute(
                                f"INSERT OR IGNORE INTO {tag_table} ({tag_fk_col}, tag) "
                                f"VALUES (?, ?)",
                                (new_id, clean),
                            )

            db.conn.commit()
            counts[table] = len(rows_for_table)

        # Step 8: Handle source_assets
        if source_asset_rows:
            sa_columns = _get_table_columns(db, "source_assets")
            sa_count = _import_source_assets(
                db, source_asset_rows, archive_dir, id_map, sa_columns
            )
            db.conn.commit()
            counts["source_assets"] = sa_count
        else:
            counts["source_assets"] = 0

    return {
        "success": True,
        "errors": errors,
        "counts": counts,
    }
