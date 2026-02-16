"""SQLite database layer for chartfold.

ChartfoldDB wraps a SQLite database with:
- Schema initialization from schema.sql
- Idempotent source loading (DELETE + INSERT per source)
- Read-only query helper returning list[dict]
- Load logging for audit trail
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path

from chartfold.models import (
    AllergyRecord,
    ClinicalNote,
    ConditionRecord,
    DocumentRecord,
    EncounterRecord,
    FamilyHistoryRecord,
    ImagingReport,
    ImmunizationRecord,
    LabResult,
    MedicationRecord,
    MentalStatusRecord,
    PathologyReport,
    ProcedureRecord,
    SocialHistoryRecord,
    SourceAsset,
    UnifiedRecords,
    VitalRecord,
)

# Mapping: (record list attr on UnifiedRecords, SQLite table name, dataclass type)
_TABLE_MAP: list[tuple[str, str, type]] = [
    ("documents", "documents", DocumentRecord),
    ("encounters", "encounters", EncounterRecord),
    ("lab_results", "lab_results", LabResult),
    ("vitals", "vitals", VitalRecord),
    ("medications", "medications", MedicationRecord),
    ("conditions", "conditions", ConditionRecord),
    ("procedures", "procedures", ProcedureRecord),
    ("pathology_reports", "pathology_reports", PathologyReport),
    ("imaging_reports", "imaging_reports", ImagingReport),
    ("clinical_notes", "clinical_notes", ClinicalNote),
    ("immunizations", "immunizations", ImmunizationRecord),
    ("allergies", "allergies", AllergyRecord),
    ("social_history", "social_history", SocialHistoryRecord),
    ("family_history", "family_history", FamilyHistoryRecord),
    ("mental_status", "mental_status", MentalStatusRecord),
    ("source_assets", "source_assets", SourceAsset),
]


def _get_schema_sql() -> str:
    """Read the schema.sql file bundled with the package."""
    schema_path = Path(__file__).parent / "schema.sql"
    return schema_path.read_text()


def _columns_for(dc_type: type) -> list[str]:
    """Get column names for a dataclass, excluding 'id' (auto-generated)."""
    return [f.name for f in fields(dc_type)]


def _record_to_row(record) -> dict:
    """Convert a dataclass record to a dict suitable for INSERT."""
    return asdict(record)


class ChartfoldDB:
    """SQLite-backed clinical data store."""

    def __init__(self, db_path: str = "chartfold.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def init_schema(self) -> None:
        """Create all tables from schema.sql (IF NOT EXISTS)."""
        sql = _get_schema_sql()
        self.conn.executescript(sql)

    def load_source(self, records: UnifiedRecords) -> dict[str, int]:
        """Load all records from a source into the database.

        Idempotent: DELETEs all existing rows for this source, then INSERTs.
        Returns a dict of table_name -> row_count inserted.
        """
        source = records.source
        start = time.monotonic()
        counts: dict[str, int] = {}

        with self.conn:
            # Delete existing data for this source
            self.conn.execute("DELETE FROM patients WHERE source = ?", (source,))
            for _, table, _ in _TABLE_MAP:
                self.conn.execute(f"DELETE FROM {table} WHERE source = ?", (source,))

            # Insert patient
            if records.patient is not None:
                row = _record_to_row(records.patient)
                cols = list(row.keys())
                placeholders = ", ".join("?" for _ in cols)
                col_names = ", ".join(cols)
                self.conn.execute(
                    f"INSERT INTO patients ({col_names}) VALUES ({placeholders})",
                    list(row.values()),
                )
                counts["patients"] = 1
            else:
                counts["patients"] = 0

            # Insert all record lists
            for attr, table, _dc_type in _TABLE_MAP:
                record_list = getattr(records, attr, [])
                if not record_list:
                    counts[table] = 0
                    continue
                # Get column names from first record
                row = _record_to_row(record_list[0])
                cols = list(row.keys())
                col_names = ", ".join(cols)
                placeholders = ", ".join("?" for _ in cols)
                sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"

                rows = [list(_record_to_row(r).values()) for r in record_list]
                self.conn.executemany(sql, rows)
                counts[table] = len(record_list)

            # Log the load
            duration = time.monotonic() - start
            now = datetime.now(timezone.utc).isoformat()
            self.conn.execute(
                """INSERT INTO load_log (
                    source, loaded_at, duration_seconds,
                    patients_count, documents_count, encounters_count,
                    lab_results_count, vitals_count, medications_count,
                    conditions_count, procedures_count, pathology_reports_count,
                    imaging_reports_count, clinical_notes_count, immunizations_count,
                    allergies_count, social_history_count, family_history_count,
                    mental_status_count, source_assets_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    source,
                    now,
                    duration,
                    counts.get("patients", 0),
                    counts.get("documents", 0),
                    counts.get("encounters", 0),
                    counts.get("lab_results", 0),
                    counts.get("vitals", 0),
                    counts.get("medications", 0),
                    counts.get("conditions", 0),
                    counts.get("procedures", 0),
                    counts.get("pathology_reports", 0),
                    counts.get("imaging_reports", 0),
                    counts.get("clinical_notes", 0),
                    counts.get("immunizations", 0),
                    counts.get("allergies", 0),
                    counts.get("social_history", 0),
                    counts.get("family_history", 0),
                    counts.get("mental_status", 0),
                    counts.get("source_assets", 0),
                ),
            )

        return counts

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        """Execute a read-only SQL query and return results as list of dicts."""
        cursor = self.conn.execute(sql, params)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]

    def summary(self) -> dict[str, int]:
        """Return row counts for all main tables (auto-discovered from schema)."""
        rows = self.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
        result = {}
        for r in rows:
            table = r["name"]
            if table == "load_log":
                continue  # Exclude audit log from summary display
            row = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            result[table] = row[0]
        return result

    def sources(self) -> list[dict]:
        """Return load history for all sources."""
        return self.query(
            "SELECT source, loaded_at, duration_seconds, "
            "lab_results_count, medications_count, conditions_count "
            "FROM load_log ORDER BY loaded_at DESC"
        )

    def last_load_counts(self, source: str) -> dict[str, int] | None:
        """Return record counts from the most recent load for a source."""
        rows = self.query(
            "SELECT * FROM load_log WHERE source = ? ORDER BY loaded_at DESC LIMIT 1",
            (source,),
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "patients": row["patients_count"],
            "documents": row["documents_count"],
            "encounters": row["encounters_count"],
            "lab_results": row["lab_results_count"],
            "vitals": row["vitals_count"],
            "medications": row["medications_count"],
            "conditions": row["conditions_count"],
            "procedures": row["procedures_count"],
            "pathology_reports": row["pathology_reports_count"],
            "imaging_reports": row["imaging_reports_count"],
            "clinical_notes": row["clinical_notes_count"],
            "immunizations": row["immunizations_count"],
            "allergies": row["allergies_count"],
            "social_history": row["social_history_count"],
            "family_history": row["family_history_count"],
            "mental_status": row["mental_status_count"],
            "source_assets": row.get("source_assets_count", 0),
        }

    # --- Personal notes CRUD ---

    def save_note(
        self,
        title: str,
        content: str,
        tags: list[str] | None = None,
        ref_table: str | None = None,
        ref_id: int | None = None,
        note_id: int | None = None,
    ) -> int:
        """Create or update a personal note. Returns the note ID."""
        now = datetime.now(timezone.utc).isoformat()
        tags = tags or []

        with self.conn:
            if note_id:
                # Update existing note
                self.conn.execute(
                    "UPDATE notes SET title=?, content=?, updated_at=?, ref_table=?, ref_id=? "
                    "WHERE id=?",
                    (title, content, now, ref_table, ref_id, note_id),
                )
                self.conn.execute("DELETE FROM note_tags WHERE note_id=?", (note_id,))
            else:
                # Create new note
                cursor = self.conn.execute(
                    "INSERT INTO notes (title, content, created_at, updated_at, ref_table, ref_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (title, content, now, now, ref_table, ref_id),
                )
                # lastrowid is always int after INSERT
                note_id = cursor.lastrowid or 0

            for tag in tags:
                clean_tag = tag.strip()
                if clean_tag:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO note_tags (note_id, tag) VALUES (?, ?)",
                        (note_id, clean_tag),
                    )

        return note_id

    def get_note(self, note_id: int) -> dict | None:
        """Retrieve a note by ID, including its tags. Returns None if not found."""
        rows = self.query(
            "SELECT id, title, content, created_at, updated_at, ref_table, ref_id "
            "FROM notes WHERE id = ?",
            (note_id,),
        )
        if not rows:
            return None
        note = rows[0]
        tag_rows = self.query(
            "SELECT tag FROM note_tags WHERE note_id = ? ORDER BY tag",
            (note_id,),
        )
        note["tags"] = [r["tag"] for r in tag_rows]
        return note

    def search_notes_personal(
        self,
        query: str | None = None,
        tag: str | None = None,
        ref_table: str | None = None,
        ref_id: int | None = None,
    ) -> list[dict]:
        """Search personal notes with optional filters (AND-combined).

        Returns notes ordered by updated_at DESC with a 300-char content preview.
        """
        conditions: list[str] = []
        params: list = []
        joins = ""

        if tag:
            joins = " JOIN note_tags nt ON n.id = nt.note_id"
            conditions.append("nt.tag = ?")
            params.append(tag)

        if query:
            conditions.append("(LOWER(n.title) LIKE ? OR LOWER(n.content) LIKE ?)")
            params.extend([f"%{query.lower()}%", f"%{query.lower()}%"])

        if ref_table:
            conditions.append("n.ref_table = ?")
            params.append(ref_table)

        if ref_id is not None:
            conditions.append("n.ref_id = ?")
            params.append(ref_id)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        rows = self.query(
            f"SELECT DISTINCT n.id, n.title, n.created_at, n.updated_at, "
            f"n.ref_table, n.ref_id, SUBSTR(n.content, 1, 300) as content_preview "
            f"FROM notes n{joins}{where} ORDER BY n.updated_at DESC",
            tuple(params),
        )

        # Attach tags to each result
        for row in rows:
            tag_rows = self.query(
                "SELECT tag FROM note_tags WHERE note_id = ? ORDER BY tag",
                (row["id"],),
            )
            row["tags"] = [r["tag"] for r in tag_rows]

        return rows

    def delete_note(self, note_id: int) -> bool:
        """Delete a note by ID. Returns True if a row was deleted."""
        with self.conn:
            cursor = self.conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        return cursor.rowcount > 0

    # --- Structured analyses CRUD ---

    def save_analysis(
        self,
        slug: str,
        title: str,
        content: str,
        frontmatter_json: str | None = None,
        category: str | None = None,
        summary: str | None = None,
        tags: list[str] | None = None,
        source: str = "user",
    ) -> int:
        """Create or update an analysis by slug (upsert). Returns the analysis ID."""
        now = datetime.now(timezone.utc).isoformat()
        tags = tags or []

        with self.conn:
            # Check if slug exists
            existing = self.query(
                "SELECT id FROM analyses WHERE slug = ?", (slug,)
            )

            if existing:
                analysis_id = existing[0]["id"]
                self.conn.execute(
                    "UPDATE analyses SET title=?, content=?, frontmatter=?, "
                    "category=?, summary=?, source=?, updated_at=? WHERE id=?",
                    (title, content, frontmatter_json, category, summary, source, now, analysis_id),
                )
                self.conn.execute("DELETE FROM analysis_tags WHERE analysis_id=?", (analysis_id,))
            else:
                cursor = self.conn.execute(
                    "INSERT INTO analyses (slug, title, content, frontmatter, "
                    "category, summary, source, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (slug, title, content, frontmatter_json, category, summary, source, now, now),
                )
                analysis_id = cursor.lastrowid or 0

            for tag in tags:
                clean_tag = tag.strip()
                if clean_tag:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO analysis_tags (analysis_id, tag) VALUES (?, ?)",
                        (analysis_id, clean_tag),
                    )

        return analysis_id

    def get_analysis(self, slug_or_id: str | int) -> dict | None:
        """Retrieve an analysis by slug (str) or id (int). Returns None if not found."""
        if isinstance(slug_or_id, int):
            rows = self.query("SELECT * FROM analyses WHERE id = ?", (slug_or_id,))
        else:
            rows = self.query("SELECT * FROM analyses WHERE slug = ?", (slug_or_id,))

        if not rows:
            return None
        analysis = rows[0]
        tag_rows = self.query(
            "SELECT tag FROM analysis_tags WHERE analysis_id = ? ORDER BY tag",
            (analysis["id"],),
        )
        analysis["tags"] = [r["tag"] for r in tag_rows]
        return analysis

    def search_analyses(
        self,
        query: str | None = None,
        tag: str | None = None,
        category: str | None = None,
    ) -> list[dict]:
        """Search analyses with optional filters (AND-combined).

        Returns analyses ordered by updated_at DESC with a 300-char content preview.
        """
        conditions: list[str] = []
        params: list = []
        joins = ""

        if tag:
            joins = " JOIN analysis_tags at ON a.id = at.analysis_id"
            conditions.append("at.tag = ?")
            params.append(tag)

        if query:
            conditions.append(
                "(LOWER(a.title) LIKE ? OR LOWER(a.content) LIKE ? "
                "OR LOWER(a.frontmatter) LIKE ?)"
            )
            q = f"%{query.lower()}%"
            params.extend([q, q, q])

        if category:
            conditions.append("a.category = ?")
            params.append(category)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        rows = self.query(
            f"SELECT DISTINCT a.id, a.slug, a.title, a.category, a.summary, "
            f"a.source, a.created_at, a.updated_at, "
            f"SUBSTR(a.content, 1, 300) as content_preview "
            f"FROM analyses a{joins}{where} ORDER BY a.updated_at DESC",
            tuple(params),
        )

        for row in rows:
            tag_rows = self.query(
                "SELECT tag FROM analysis_tags WHERE analysis_id = ? ORDER BY tag",
                (row["id"],),
            )
            row["tags"] = [r["tag"] for r in tag_rows]

        return rows

    def list_analyses(self) -> list[dict]:
        """List all analyses with tags, ordered by updated_at DESC."""
        return self.search_analyses()

    def delete_analysis(self, slug_or_id: str | int) -> bool:
        """Delete an analysis by slug (str) or id (int). Returns True if deleted."""
        with self.conn:
            if isinstance(slug_or_id, int):
                cursor = self.conn.execute("DELETE FROM analyses WHERE id = ?", (slug_or_id,))
            else:
                cursor = self.conn.execute("DELETE FROM analyses WHERE slug = ?", (slug_or_id,))
        return cursor.rowcount > 0

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
