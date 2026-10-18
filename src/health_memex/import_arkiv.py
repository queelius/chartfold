"""Import health-memex clinical data from arkiv universal record format.

Reverses the export performed by export_arkiv.py: parses JSONL records,
remaps FK references, unfolds tags, and inserts into a fresh SQLite database
in topological (FK-dependency) order.

Accepted input layouts (C5b workspace contract, auto-detected by extension):

- directory containing ``README.md`` + ``schema.yaml`` + ``*.jsonl`` shards
- ``.zip`` bundle of the same layout
- ``.tar.gz`` / ``.tgz`` bundle of the same layout

Archive bundles are extracted into a process-scoped TemporaryDirectory and
the existing directory-based pipeline runs against the extracted tree. Any
``media/`` assets are resolved relative to that extracted root exactly like
they would be from a directory input.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterator

import yaml
from arkiv import bundle_format, unpack_bundle

from health_memex.db import (
    _UNIQUE_KEYS,
    HealthMemexDB,
    _build_upsert_sql,
    _discover_fk_graph,
    _discover_tables,
    _topological_sort,
)
from health_memex.export_arkiv import _FK_FIELDS, _TAG_CONFIG

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Reverse FK mapping: uri_key -> (fk_col, parent_table)
_REVERSE_FK: dict[str, tuple[str, str]] = {
    uri_key: (fk_col, parent_table) for fk_col, (parent_table, uri_key) in _FK_FIELDS.items()
}

_SYNTHETIC_KEYS = {"table"}

# URIs in modern arkiv exports use unique_id (16 hex chars). Older
# exports used autoincrement integers, and notes/analyses still do
# (no natural key). The pattern accepts both: \w+ matches digits,
# hex strings, and any reasonable id form. The handler dispatches on
# format at lookup time. Same pattern is matched for both
# health-memex: and the legacy chartfold: prefix.
_URI_PATTERN = re.compile(r"^health-memex:(\w[\w-]*)/(\w+)$")
_LEGACY_URI_PATTERN = re.compile(r"^chartfold:(\w[\w-]*)/(\w+)$")


def _match_uri(uri: str) -> re.Match | None:
    """Match a health-memex or legacy chartfold URI."""
    return _URI_PATTERN.match(uri) or _LEGACY_URI_PATTERN.match(uri)


# Reverse tag config: table -> (tag_table, tag_fk_col)
_REVERSE_TAG_CONFIG = _TAG_CONFIG  # same structure works for import


# ---------------------------------------------------------------------------
# _record_to_row
# ---------------------------------------------------------------------------


def _record_to_row(
    record: dict[str, Any],
) -> tuple[str, str | None, dict[str, Any]]:
    """Convert an arkiv record back to a DB row dict.

    Reverses _row_to_record():
    1. Extracts table name from metadata.table.
    2. Parses the URI's id portion (the row's stable identifier, which
       is unique_id for clinical tables and autoincrement string for
       notes/analyses).
    3. Reverses FK URIs (procedure_uri -> procedure_id, but storing
       the parent's unique_id string rather than an autoincrement int;
       the actual remap to autoincrement happens at insert time via
       _resolve_fk_unique_id).
    4. Reverses ref_id_uri for source_assets, same pattern.
    5. Extracts tags from metadata -> row["_tags"].
    6. Strips synthetic keys (table).

    Returns:
        (table_name, exported_id_or_None, row_dict)

        ``exported_id`` is whatever the URI carried — typically the
        unique_id (16-hex string) for clinical tables, the
        autoincrement-string for notes/analyses. The caller doesn't
        need to interpret it; it's just used as a stable key.
    """
    metadata = record.get("metadata", {})
    table = metadata["table"]

    # Parse the URI's id portion (no longer constrained to integer)
    exported_id: str | None = None
    uri = record.get("uri", "")
    m = _match_uri(uri)
    if m:
        exported_id = m.group(2)

    # Build row from metadata, reversing transformations
    row: dict[str, Any] = {}

    for key, val in metadata.items():
        # Skip synthetic keys
        if key in _SYNTHETIC_KEYS:
            continue

        # Reverse FK URIs -> FK column carrying the parent's unique_id
        # string. _resolve_fk_unique_id at insert time will translate
        # to the parent's autoincrement id.
        if key in _REVERSE_FK:
            fk_col, _parent_table = _REVERSE_FK[key]
            fk_match = _match_uri(val)
            if fk_match:
                row[fk_col] = fk_match.group(2)  # unique_id string
            continue

        # Reverse ref_id_uri for source_assets
        if key == "ref_id_uri":
            ref_match = _match_uri(val)
            if ref_match:
                row["ref_table"] = ref_match.group(1)
                row["ref_id"] = ref_match.group(2)  # unique_id string
            continue

        # Extract tags -> _tags (inserted separately)
        if key == "tags" and table in _TAG_CONFIG:
            row["_tags"] = val
            continue

        row[key] = val

    return table, exported_id, row


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_table_columns(db: HealthMemexDB, table: str) -> set[str]:
    """Get column names for a table (excluding 'id')."""
    rows = db.query(f"PRAGMA table_info({table})")
    return {r["name"] for r in rows if r["name"] != "id"}


def _lookup_id_by_unique(
    conn, table: str, unique_cols: tuple[str, ...], row: dict[str, Any]
) -> int | None:
    """Find the ``id`` of a row that matches *row* on every unique-key column.

    Used after an UPSERT to recover the surviving row's id for FK remapping,
    since ``lastrowid`` is undefined when ON CONFLICT DO UPDATE fires.
    Returns ``None`` if no row matches (e.g. the unique-key contained a
    NULL that SQLite treats as distinct and the INSERT branch fell through
    to a DO UPDATE that didn't happen).
    """
    conds: list[str] = []
    vals: list[Any] = []
    for col in unique_cols:
        val = row.get(col)
        if val is None:
            conds.append(f"{col} IS NULL")
        else:
            conds.append(f"{col} = ?")
            vals.append(val)
    where = " AND ".join(conds)
    cur = conn.execute(f"SELECT id FROM {table} WHERE {where}", vals)
    r = cur.fetchone()
    if r is None:
        return None
    # conn.row_factory may or may not be set; handle both tuple + Row.
    try:
        return int(r["id"])
    except (IndexError, TypeError, KeyError):
        return int(r[0])


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
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    # Valid YAML need not be a mapping (a bare scalar or list parses fine),
    # and every caller indexes the result as one.
    return data if isinstance(data, dict) else None


def _parse_source_asset_records(
    records: list[dict[str, Any]],
) -> list[tuple[str | None, dict[str, Any]]]:
    """Parse source_assets JSONL records into (exported_id, row) tuples.

    Source asset records have non-application/json mimetypes and different
    metadata structure than clinical records.
    """
    result = []
    for record in records:
        metadata = record.get("metadata", {})
        if metadata.get("table") != "source_assets":
            continue

        # Parse the source_asset's own id (autoincrement) from any
        # health-memex: URI present. source_assets has no unique_id
        # column (no natural key beyond source+file_path), so its
        # primary URI is file:// — the autoincrement string is only
        # used by the caller for tag/asset bookkeeping.
        exported_id: str | None = None
        uri = record.get("uri", "")
        uri_match = _match_uri(uri)
        if uri_match:
            exported_id = uri_match.group(2)

        row: dict[str, Any] = {}

        for key, val in metadata.items():
            if key in _SYNTHETIC_KEYS:
                continue
            # Reverse ref_id_uri: stash the parent's unique_id string;
            # _import_source_assets will translate via uid_map.
            if key == "ref_id_uri":
                ref_match = _match_uri(val)
                if ref_match:
                    row["ref_table"] = ref_match.group(1)
                    row["ref_id"] = ref_match.group(2)
                continue
            row[key] = val

        # Set content_type from the record's mimetype
        row["content_type"] = record.get("mimetype", "application/octet-stream")

        # Handle file_path: look for media file from URI
        if uri.startswith("file://media/"):
            media_name = uri[len("file://media/") :]
            row["_media_name"] = media_name
        elif record.get("content"):
            # base64-embedded content
            row["_base64_content"] = record["content"]

        # file_path will be set during import based on archive location
        # If not already set, initialize to empty
        if "file_path" not in row:
            row["file_path"] = ""

        result.append((exported_id, row))

    return result


def _import_source_assets(
    db: HealthMemexDB,
    asset_rows: list[tuple[str | None, dict[str, Any]]],
    archive_dir: str,
    uid_map: dict[str, dict[str, int]],
    table_columns: set[str],
) -> int:
    """Import source asset records into the database.

    Handles file_path resolution from archive's media/ directory,
    ref_id remapping through uid_map (parent.unique_id -> autoincrement
    id of just-inserted parent row), and base64 content restoration.

    Returns the number of imported records.
    """
    count = 0
    media_dir = os.path.join(archive_dir, "media")

    for exported_id, row in asset_rows:
        # Resolve file_path from media/
        media_name = row.pop("_media_name", None)
        base64_content = row.pop("_base64_content", None)

        if media_name and os.path.isdir(media_dir):
            media_path = os.path.realpath(os.path.join(media_dir, media_name))
            real_media_dir = os.path.realpath(media_dir)
            if media_path.startswith(real_media_dir + os.sep) and os.path.isfile(media_path):
                row["file_path"] = media_path

        if not row.get("file_path") and base64_content:
            # Write base64 content to media/ in the archive
            os.makedirs(media_dir, exist_ok=True)
            file_name = row.get("file_name", f"asset_{exported_id}")
            dest = os.path.realpath(os.path.join(media_dir, file_name))
            real_media_dir = os.path.realpath(media_dir)
            if not dest.startswith(real_media_dir + os.sep):
                continue  # skip path-traversal attempt
            with open(dest, "wb") as f:
                f.write(base64.b64decode(base64_content))
            row["file_path"] = dest

        if not row.get("file_path"):
            row["file_path"] = ""

        # Remap ref_id: row.ref_id holds the parent's unique_id string
        # (set by _parse_source_asset_records). Translate via uid_map
        # to the parent's just-inserted autoincrement id.
        ref_table = row.get("ref_table")
        ref_uid = row.get("ref_id")
        if ref_table and ref_uid is not None:
            parent_map = uid_map.get(ref_table, {})
            row["ref_id"] = parent_map.get(ref_uid)  # None if parent not imported

        # Filter to known columns only
        filtered = {k: v for k, v in row.items() if k in table_columns}

        if not filtered:
            continue

        cols = list(filtered.keys())
        col_names = ", ".join(cols)
        placeholders = ", ".join("?" for _ in cols)

        db.conn.execute(
            f"INSERT INTO source_assets ({col_names}) VALUES ({placeholders})",
            list(filtered.values()),
        )

        # source_assets isn't a parent table for any FK in the schema,
        # so we don't need to add it to uid_map. (Earlier versions did
        # that for completeness; it's never read.)

        count += 1

    return count


# ---------------------------------------------------------------------------
# Bundle detection and extraction (C5b)
# ---------------------------------------------------------------------------


def _contents_path(archive_dir: str, rel_path: str) -> str | None:
    """Resolve a README ``contents[].path`` against *archive_dir*.

    Returns the joined path, or None when it would land outside the
    archive root (``../outside.jsonl``, an absolute path, or a symlink
    pointing elsewhere). ``contents`` is untrusted bundle metadata, so a
    shard path must be confined to the archive the same way arkiv
    confines extracted members.
    """
    joined = Path(archive_dir, rel_path)
    try:
        joined.resolve().relative_to(Path(archive_dir).resolve())
    except ValueError:
        return None
    return str(joined)


def _find_archive_root(extracted_dir: str) -> str:
    """Locate the directory containing ``README.md`` after extraction.

    The exporter packs with ``arkiv.pack_bundle``, whose member names are
    relative to the staging directory, so README.md lives at the archive
    root. We still descend into a single
    top-level subdirectory when present so we tolerate bundles packed by
    other tools (or by a user who zipped the parent folder).
    """
    if os.path.isfile(os.path.join(extracted_dir, "README.md")):
        return extracted_dir
    entries = [e for e in os.listdir(extracted_dir) if not e.startswith(".")]
    if len(entries) == 1:
        child = os.path.join(extracted_dir, entries[0])
        if os.path.isdir(child) and os.path.isfile(os.path.join(child, "README.md")):
            return child
    return extracted_dir


@contextlib.contextmanager
def _resolve_archive_dir(archive_path: str) -> Iterator[str]:
    """Yield a directory path containing the arkiv layout.

    If *archive_path* is a directory, yields it unchanged. If it is a
    ``.zip`` / ``.tar.gz`` / ``.tgz`` bundle, extracts into a
    TemporaryDirectory and yields that. The temp dir is cleaned up on
    context exit.
    """
    if bundle_format(archive_path) not in ("zip", "tar.gz"):
        yield archive_path
        return

    with tempfile.TemporaryDirectory(prefix="health_memex_arkiv_import_") as tmp:
        # arkiv.unpack_bundle rejects path-escaping members and escaping
        # link targets, extracts tar with filter="data", and enforces
        # zip/tar bomb limits on entry count and uncompressed size.
        unpack_bundle(archive_path, tmp)
        yield _find_archive_root(tmp)


# ---------------------------------------------------------------------------
# validate_arkiv
# ---------------------------------------------------------------------------


def validate_arkiv(archive_dir: str) -> dict[str, Any]:
    """Validate an arkiv archive (directory or bundle) without importing.

    Accepts a directory path, ``.zip``, ``.tar.gz``, or ``.tgz``. Bundles
    are extracted to a temporary directory for the duration of validation.

    Checks:
    - README.md exists and has valid YAML frontmatter
    - schema.yaml parses (optional file)
    - Each JSONL file listed in frontmatter exists and contains valid JSON

    Returns:
        {"valid": bool, "errors": list[str], "summary": dict[str, int]}
    """
    try:
        with _resolve_archive_dir(archive_dir) as resolved:
            return _validate_arkiv_dir(resolved)
    except (zipfile.BadZipFile, tarfile.TarError, ValueError, OSError) as e:
        return {
            "valid": False,
            "errors": [f"Could not open archive {archive_dir!r}: {e}"],
            "summary": {},
        }


def _validate_arkiv_dir(archive_dir: str) -> dict[str, Any]:
    """Validate an already-extracted archive directory. See validate_arkiv."""
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
        jsonl_path = _contents_path(archive_dir, path)

        if jsonl_path is None:
            errors.append(f"Unsafe path in contents (escapes the archive root): {path!r}")
            continue
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
                    errors.append(f"Invalid JSON in {path} line {line_num}: {e}")

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
    merge: bool = False,
) -> dict[str, Any]:
    """Import an arkiv archive (directory or bundle) into a health-memex DB.

    Accepts a directory path, ``.zip``, ``.tar.gz``, or ``.tgz``. Bundles
    are extracted into a TemporaryDirectory for the duration of the import
    so ``media/`` assets resolve against a real filesystem path.

    Three mutually-exclusive modes govern how the target DB is treated:

    - default (all three flags false): refuse if the DB exists
    - ``overwrite=True``: unlink the existing DB and create fresh
    - ``merge=True``: open the existing DB (or create it), UPSERT records
      by natural key so re-importing the same archive is idempotent

    Args:
        archive_dir: Path to the arkiv archive (directory or bundle).
        db_path: Path for the target SQLite database.
        validate_only: If True, only validate without importing.
        overwrite: If True, unlink and recreate the target database.
        merge: If True, UPSERT records into the existing database using
            natural-key (_UNIQUE_KEYS) conflict detection. Safe to run
            repeatedly against the same DB.

    Returns:
        {"success": bool, "errors": list[str], "counts": dict[str, int]}
    """
    if overwrite and merge:
        return {
            "success": False,
            "errors": ["--overwrite and --merge are mutually exclusive."],
            "counts": {},
        }

    try:
        with _resolve_archive_dir(archive_dir) as resolved:
            return _import_arkiv_dir(
                resolved,
                db_path,
                validate_only=validate_only,
                overwrite=overwrite,
                merge=merge,
            )
    except (zipfile.BadZipFile, tarfile.TarError, ValueError, OSError) as e:
        return {
            "success": False,
            "errors": [f"Could not open archive {archive_dir!r}: {e}"],
            "counts": {},
        }


def _import_arkiv_dir(
    archive_dir: str,
    db_path: str,
    validate_only: bool = False,
    overwrite: bool = False,
    merge: bool = False,
) -> dict[str, Any]:
    """Import an already-extracted archive directory.

    Pipeline:
    1. Validate the archive
    2. Check if DB exists (refuse without overwrite=True)
    3. Parse JSONL records from all files
    4. Create fresh DB with init_schema()
    5. Topological sort tables by FK dependencies
    6. Insert rows in FK order with ID remapping
    7. Unfold tags from _tags -> tag table inserts
    8. Handle source_assets separately
    """
    # Step 1: Validate
    validation = _validate_arkiv_dir(archive_dir)
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
    if db_exists and not (overwrite or merge):
        return {
            "success": False,
            "errors": [
                f"Database already exists: {db_path}. "
                "Use --overwrite to replace or --merge to add records."
            ],
            "counts": {},
        }

    # Step 3: Parse all JSONL records, grouped by table
    readme_path = os.path.join(archive_dir, "README.md")
    with open(readme_path, "r", encoding="utf-8") as f:
        frontmatter = _parse_frontmatter(f.read())

    # Collect records by table
    table_records: dict[str, list[tuple[str | None, dict[str, Any]]]] = {}
    source_asset_raw_records: list[dict[str, Any]] = []

    contents = frontmatter.get("contents", []) if frontmatter else []
    for entry in contents:
        path = entry.get("path", "")
        jsonl_path = _contents_path(archive_dir, path)

        # Validation above already rejected unsafe paths; re-check here so
        # this loop never depends on that ordering.
        if jsonl_path is None or not os.path.isfile(jsonl_path):
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

    # Step 4: Prepare target DB
    # - overwrite: unlink existing so init_schema creates fresh
    # - merge: leave existing in place; init_schema is idempotent and no-ops
    #   on existing tables
    # - default (neither flag): db_exists is False at this point
    if db_exists and overwrite:
        Path(db_path).unlink()

    errors: list[str] = []
    counts: dict[str, int] = {}

    with HealthMemexDB(db_path) as db:
        db.init_schema()

        # Step 5: Topological sort
        schema_tables = _discover_tables(db)
        fk_graph = _discover_fk_graph(db, schema_tables)
        import_order = _topological_sort(schema_tables, fk_graph)

        # Track unique_id -> autoincrement id per parent table, populated
        # as parent rows are inserted so child rows can resolve FKs.
        # Children carry parent.unique_id (the durable URI form); we
        # translate to autoincrement id at insert time. This replaces
        # the old "id_map[parent_table][old_autoincrement]" scheme.
        uid_map: dict[str, dict[str, int]] = {}

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
            if table in _UNIQUE_KEYS:
                uid_map[table] = {}

            # Get valid columns for this table
            valid_columns = _get_table_columns(db, table)

            # Get FK columns for remapping
            table_fks = fk_graph.get(table, [])

            for exported_id, row in rows_for_table:
                # Extract tags before column filtering
                tags = row.pop("_tags", None)

                # Remap FK columns: row[fk_col] is the parent's
                # unique_id string (set by _record_to_row); look up
                # the parent's autoincrement id we just inserted.
                for fk_col, parent_table, _parent_col in table_fks:
                    parent_uid = row.get(fk_col)
                    if parent_uid is not None:
                        parent_map = uid_map.get(parent_table, {})
                        row[fk_col] = parent_map.get(parent_uid)
                        # None if parent not in this archive — leave
                        # the FK NULL rather than error, so partial
                        # imports stay loadable.

                # Filter to valid columns only
                filtered = {k: v for k, v in row.items() if k in valid_columns}

                if not filtered:
                    continue

                cols = list(filtered.keys())
                col_names = ", ".join(cols)
                placeholders = ", ".join("?" for _ in cols)

                if merge and table in _UNIQUE_KEYS:
                    # UPSERT by natural key. `lastrowid` is undefined for
                    # the DO UPDATE path in SQLite, so we look up the
                    # surviving row by its unique key afterward to get a
                    # stable id for FK remapping.
                    unique_cols = _UNIQUE_KEYS[table]
                    upsert_sql = _build_upsert_sql(table, cols, unique_cols)
                    db.conn.execute(upsert_sql, list(filtered.values()))
                    new_id = _lookup_id_by_unique(db.conn, table, unique_cols, filtered)
                else:
                    cursor = db.conn.execute(
                        f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                        list(filtered.values()),
                    )
                    new_id = cursor.lastrowid

                # Populate uid_map for any clinical table so child
                # rows in subsequent iterations can resolve FK URIs
                # via the parent's unique_id. ``exported_id`` is the
                # URI's id portion, which is the unique_id string for
                # tables in _UNIQUE_KEYS (the export side strips
                # unique_id from metadata since it's already in the
                # URI; we don't need to reconstruct it from filtered).
                if table in _UNIQUE_KEYS and new_id is not None and exported_id:
                    uid_map[table][exported_id] = new_id

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

        # Step 8: Handle source_assets — uses uid_map for ref_id
        # resolution (child carries parent.unique_id; we map to
        # parent.autoincrement_id).
        if source_asset_rows:
            sa_columns = _get_table_columns(db, "source_assets")
            sa_count = _import_source_assets(
                db, source_asset_rows, archive_dir, uid_map, sa_columns
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
