"""Full-fidelity export and import for chartfold databases.

Supports two export formats:
- Markdown: Human-readable dump of all tables
- JSON: Round-trip capable export that can recreate the SQLite database

Unlike export.py (which is visit-focused with filtering), this module
exports the complete database contents for backup and portability.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from chartfold.db import ChartfoldDB
from chartfold.formatters.markdown import MarkdownWriter

EXPORT_VERSION = "1.0"
SCHEMA_VERSION = 1

# Tables to export by default (clinical data + personal notes)
CLINICAL_TABLES = [
    "patients",
    "documents",
    "encounters",
    "lab_results",
    "vitals",
    "medications",
    "conditions",
    "procedures",
    "pathology_reports",
    "imaging_reports",
    "clinical_notes",
    "immunizations",
    "allergies",
    "social_history",
    "family_history",
    "mental_status",
    "source_assets",
]

NOTE_TABLES = ["notes", "note_tags"]

AUDIT_TABLES = ["load_log"]

# Import order matters due to foreign keys:
# - pathology_reports.procedure_id -> procedures.id
# - note_tags.note_id -> notes.id
IMPORT_PHASE_1 = [
    "patients",
    "documents",
    "encounters",
    "lab_results",
    "vitals",
    "medications",
    "conditions",
    "procedures",
    "imaging_reports",
    "clinical_notes",
    "immunizations",
    "allergies",
    "social_history",
    "family_history",
    "mental_status",
    "source_assets",
]

IMPORT_PHASE_2_FK = [
    ("pathology_reports", "procedure_id", "procedures"),
]

IMPORT_PHASE_3_NOTES = ["notes", "note_tags"]


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
    tables_to_export = CLINICAL_TABLES.copy()
    if include_notes:
        tables_to_export.extend(NOTE_TABLES)
    if include_load_log:
        tables_to_export.extend(AUDIT_TABLES)

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


def export_full_markdown(db: ChartfoldDB, output_path: str) -> str:
    """Export entire database as markdown tables.

    Args:
        db: Database connection.
        output_path: Where to write the markdown file.

    Returns the output file path.
    """
    md = MarkdownWriter()
    now = datetime.now(timezone.utc).isoformat()

    md.heading("Chartfold Full Data Export", level=1)
    md.w(f"*Exported: {now}*")
    md.w()

    # Summary
    summary = db.summary()
    md.heading("Summary", level=2)
    for table, count in summary.items():
        if count > 0:
            md.w(f"- **{table}**: {count} records")
    md.w()

    # All tables
    all_tables = CLINICAL_TABLES + NOTE_TABLES
    for table in all_tables:
        rows = db.query(f"SELECT * FROM {table}")
        if not rows:
            continue

        md.separator()
        md.heading(f"{table} ({len(rows)} records)", level=2)

        # Get column headers from first row
        headers = list(rows[0].keys())

        # Build table rows, truncating long values
        table_rows = []
        for row in rows:
            table_row = []
            for h in headers:
                val = row[h]
                if val is None:
                    val = ""
                else:
                    val = str(val)
                    # Truncate long values for readability
                    if len(val) > 80:
                        val = val[:77] + "..."
                    # Escape pipe characters for markdown tables
                    val = val.replace("|", "\\|").replace("\n", " ")
                table_row.append(val)
            table_rows.append(table_row)

        md.table(headers, table_rows)

    md.write_to_file(output_path)
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

    # Check for required clinical tables
    missing_clinical = [t for t in CLINICAL_TABLES if t not in tables]
    if missing_clinical:
        errors.append(f"Missing clinical tables: {', '.join(missing_clinical)}")

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

    tables = data["tables"]
    counts = {}
    errors = []

    # If overwriting, delete the existing database
    if db_exists and overwrite:
        Path(db_path).unlink()

    # Create fresh database
    with ChartfoldDB(db_path) as db:
        db.init_schema()

        # Track ID remappings for FK resolution
        id_map = {}  # table -> {old_id: new_id}

        # Phase 1: Tables without FK dependencies
        for table in IMPORT_PHASE_1:
            if table not in tables or not tables[table]:
                counts[table] = 0
                continue

            rows = tables[table]
            id_map[table] = {}

            for row in rows:
                old_id = row.pop("id", None)
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

        # Phase 2: Tables with FK dependencies
        for table, fk_col, parent_table in IMPORT_PHASE_2_FK:
            if table not in tables or not tables[table]:
                counts[table] = 0
                continue

            rows = tables[table]
            parent_map = id_map.get(parent_table, {})
            id_map[table] = {}

            for row in rows:
                old_id = row.pop("id", None)

                # Remap FK
                old_fk = row.get(fk_col)
                if old_fk is not None and parent_map:
                    row[fk_col] = parent_map.get(old_fk)

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

        # Phase 3: Notes tables
        if tables.get("notes"):
            rows = tables["notes"]
            id_map["notes"] = {}

            for row in rows:
                old_id = row.pop("id", None)
                cols = list(row.keys())
                placeholders = ", ".join("?" for _ in cols)
                col_names = ", ".join(cols)

                cursor = db.conn.execute(
                    f"INSERT INTO notes ({col_names}) VALUES ({placeholders})",
                    list(row.values()),
                )

                if old_id is not None:
                    id_map["notes"][old_id] = cursor.lastrowid

            db.conn.commit()
            counts["notes"] = len(rows)

        if tables.get("note_tags"):
            rows = tables["note_tags"]
            notes_map = id_map.get("notes", {})

            for row in rows:
                # note_tags has no auto-increment id, just note_id FK
                old_note_id = row.get("note_id")
                if old_note_id is not None and notes_map:
                    row["note_id"] = notes_map.get(old_note_id, old_note_id)

                cols = list(row.keys())
                placeholders = ", ".join("?" for _ in cols)
                col_names = ", ".join(cols)

                db.conn.execute(
                    f"INSERT INTO note_tags ({col_names}) VALUES ({placeholders})",
                    list(row.values()),
                )

            db.conn.commit()
            counts["note_tags"] = len(rows)

        # Phase 4: load_log (optional, included if present)
        if tables.get("load_log"):
            rows = tables["load_log"]
            for row in rows:
                row.pop("id", None)  # Remove auto-increment id
                cols = list(row.keys())
                placeholders = ", ".join("?" for _ in cols)
                col_names = ", ".join(cols)

                db.conn.execute(
                    f"INSERT INTO load_log ({col_names}) VALUES ({placeholders})",
                    list(row.values()),
                )

            db.conn.commit()
            counts["load_log"] = len(rows)

    return {
        "success": True,
        "errors": errors,
        "counts": counts,
    }
