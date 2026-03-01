"""Full-fidelity export and import for chartfold databases.

JSON round-trip capable export that can recreate the SQLite database.
Exports the complete database contents for backup and portability.

Tables, foreign keys, and import ordering are auto-discovered from the
SQLite schema — adding new tables to schema.sql requires zero changes here.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from chartfold.db import (
    ChartfoldDB,
    _discover_fk_graph,
    _discover_tables,
    _topological_sort,
)

EXPORT_VERSION = "1.0"
SCHEMA_VERSION = 1

# Tables excluded from default export (opt-in only)
_EXCLUDE_BY_DEFAULT = {"load_log"}

# Tables excluded when --exclude-notes is used
_NOTE_TABLES = {"notes", "note_tags"}


def export_full_json(
    db: ChartfoldDB,
    output_path: str,
    include_notes: bool = True,
    include_load_log: bool = False,
) -> str:
    """Export entire database to JSON file.

    Args:
        db: Database connection.
        output_path: Where to write the JSON file.
        include_notes: Include personal notes (default True).
        include_load_log: Include audit log (default False).

    Returns the output file path.
    """
    all_tables = _discover_tables(db)

    # Apply exclusions
    exclude = set()
    if not include_notes:
        exclude |= _NOTE_TABLES
    if not include_load_log:
        exclude |= _EXCLUDE_BY_DEFAULT

    tables_to_export = [t for t in all_tables if t not in exclude]

    export_data = {
        "chartfold_export": {
            "version": EXPORT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        },
        "tables": {},
    }

    for table in tables_to_export:
        rows = db.query(f"SELECT * FROM {table}")
        export_data["tables"][table] = rows

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)

    return output_path


def validate_json_export(input_path: str) -> dict:
    """Validate a JSON export file without importing.

    Args:
        input_path: Path to the JSON export file.

    Returns a dict with validation results:
        - valid: bool
        - errors: list of error messages
        - summary: dict of table -> record count
    """
    errors = []
    summary = {}

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return {"valid": False, "errors": [f"Invalid JSON: {e}"], "summary": {}}
    except FileNotFoundError:
        return {"valid": False, "errors": [f"File not found: {input_path}"], "summary": {}}

    # Check structure
    if "chartfold_export" not in data:
        errors.append("Missing 'chartfold_export' metadata block")
    else:
        meta = data["chartfold_export"]
        if "version" not in meta:
            errors.append("Missing export version")
        if "schema_version" not in meta:
            errors.append("Missing schema version")

    if "tables" not in data:
        errors.append("Missing 'tables' block")
        return {"valid": False, "errors": errors, "summary": {}}

    tables = data["tables"]

    if not tables:
        errors.append("No tables found in export")

    # Build summary
    for table, rows in tables.items():
        if not isinstance(rows, list):
            errors.append(f"Table '{table}' is not a list")
            continue
        summary[table] = len(rows)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "summary": summary,
    }


def import_json(
    input_path: str,
    db_path: str,
    validate_only: bool = False,
    overwrite: bool = False,
) -> dict:
    """Import JSON export to recreate database.

    Uses auto-discovery to determine import order from the target schema's
    foreign key graph. FK columns are automatically remapped during import.

    Args:
        input_path: Path to the JSON export file.
        db_path: Path to the target SQLite database.
        validate_only: If True, only validate without importing.
        overwrite: If True, overwrite existing database.

    Returns a dict with import results:
        - success: bool
        - errors: list of error messages
        - counts: dict of table -> records imported
    """
    # Validate first
    validation = validate_json_export(input_path)
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
            "validated_only": True,
        }

    # Check if database exists
    db_exists = Path(db_path).exists()
    if db_exists and not overwrite:
        return {
            "success": False,
            "errors": [f"Database already exists: {db_path}. Use --overwrite to replace."],
            "counts": {},
        }

    # Load export data
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    tables_in_json = data["tables"]
    counts: dict[str, int] = {}
    errors: list[str] = []

    # If overwriting, delete the existing database
    if db_exists and overwrite:
        Path(db_path).unlink()

    # Create fresh database and discover its schema
    with ChartfoldDB(db_path) as db:
        db.init_schema()

        # Auto-discover table order from the fresh schema
        schema_tables = _discover_tables(db)
        fk_graph = _discover_fk_graph(db, schema_tables)
        import_order = _topological_sort(schema_tables, fk_graph)

        # Track ID remappings for FK resolution
        id_map: dict[str, dict[int, int]] = {}  # table -> {old_id: new_id}

        # Import tables in topological order
        for table in import_order:
            if table not in tables_in_json or not tables_in_json[table]:
                counts[table] = 0
                continue

            rows = tables_in_json[table]
            id_map[table] = {}

            # Get FK columns for this table so we can remap them
            table_fks = fk_graph.get(table, [])

            for row in rows:
                old_id = row.pop("id", None)

                # Remap any FK columns
                for fk_col, parent_table, _parent_col in table_fks:
                    old_fk = row.get(fk_col)
                    if old_fk is not None:
                        parent_map = id_map.get(parent_table, {})
                        if parent_map:
                            row[fk_col] = parent_map.get(old_fk, old_fk)

                cols = list(row.keys())
                placeholders = ", ".join("?" for _ in cols)
                col_names = ", ".join(cols)

                cursor = db.conn.execute(
                    f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                    list(row.values()),
                )

                if old_id is not None:
                    id_map[table][old_id] = cursor.lastrowid

            db.conn.commit()
            counts[table] = len(rows)

    return {
        "success": True,
        "errors": errors,
        "counts": counts,
    }
