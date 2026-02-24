"""SQLite database layer for chartfold.

ChartfoldDB wraps a SQLite database with:
- Schema initialization from schema.sql
- UPSERT-based source loading (stable IDs across re-imports)
- Read-only query helper returning list[dict]
- Load logging for audit trail
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from chartfold.models import (
    AllergyRecord,
    ClinicalNote,
    ConditionRecord,
    DocumentRecord,
    EncounterRecord,
    FamilyHistoryRecord,
    GeneticVariant,
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
    ("genetic_variants", "genetic_variants", GeneticVariant),
]

# Natural key UNIQUE constraints (as declared in schema.sql).
# Used for UPSERT conflict detection and stale-record cleanup.
_UNIQUE_KEYS: dict[str, tuple[str, ...]] = {
    "patients": ("source", "name", "date_of_birth"),
    "documents": ("source", "doc_id"),
    "encounters": ("source", "encounter_date", "encounter_type", "facility"),
    "lab_results": ("source", "test_name", "result_date", "value"),
    "vitals": ("source", "vital_type", "recorded_date", "value_text"),
    "medications": ("source", "name", "start_date"),
    "conditions": ("source", "condition_name", "icd10_code"),
    "procedures": ("source", "name", "procedure_date"),
    "pathology_reports": ("source", "report_date", "specimen"),
    "imaging_reports": ("source", "study_name", "study_date"),
    "clinical_notes": ("source", "note_date", "note_type", "author"),
    "immunizations": ("source", "vaccine_name", "admin_date"),
    "allergies": ("source", "allergen"),
    "social_history": ("source", "category", "recorded_date"),
    "family_history": ("source", "relation", "condition"),
    "mental_status": ("source", "instrument", "question", "recorded_date"),
    "source_assets": ("source", "file_path"),
    "genetic_variants": ("source", "gene", "dna_change", "test_name", "collection_date"),
}


class TableStats(TypedDict):
    """Per-table load statistics."""

    new: int  # Records whose natural key didn't exist before
    existing: int  # Records whose natural key already existed (upserted)
    removed: int  # Stale records deleted (only in replace=True mode)
    total: int  # Total records in the import


class LoadResult:
    """Result of a load_source operation.

    Supports dict-style access for backwards compatibility:
        result["lab_results"]  -> total count (int)
        result["tables"]       -> per-table stats dict
        result["content_hash"] -> SHA-256 hex string
        result["skipped"]      -> bool
    """

    def __init__(
        self,
        tables: dict[str, TableStats],
        content_hash: str,
        skipped: bool,
    ):
        self.tables = tables
        self.content_hash = content_hash
        self.skipped = skipped

    def __getitem__(self, key: str):
        if key == "tables":
            return self.tables
        if key == "content_hash":
            return self.content_hash
        if key == "skipped":
            return self.skipped
        # Backwards compat: result["lab_results"] -> total count
        if key in self.tables:
            return self.tables[key]["total"]
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return key in ("tables", "content_hash", "skipped") or key in self.tables

    def __iter__(self):
        return iter(self.tables)

    def __eq__(self, other):
        if isinstance(other, LoadResult):
            return self.tables == other.tables and self.content_hash == other.content_hash
        return NotImplemented

    def keys(self):
        """Return table names (backwards compat with dict[str, int])."""
        return self.tables.keys()

    def get(self, key: str, default=None):
        try:
            return self[key]
        except KeyError:
            return default


def _content_hash(records: UnifiedRecords) -> str:
    """Compute SHA-256 hash of serialized records for dedup/provenance.

    Produces a stable hash by sorting all record lists by their natural key
    columns before serializing.
    """
    h = hashlib.sha256()
    h.update(records.source.encode())

    if records.patient is not None:
        h.update(json.dumps(asdict(records.patient), sort_keys=True).encode())

    for attr, table, _dc_type in _TABLE_MAP:
        record_list = getattr(records, attr, [])
        if not record_list:
            continue
        # Sort by natural key columns for deterministic ordering
        unique_cols = _UNIQUE_KEYS[table]
        natural_key_cols = [c for c in unique_cols if c != "source"]
        rows = [asdict(r) for r in record_list]
        rows.sort(key=lambda row: tuple(str(row.get(c, "")) for c in natural_key_cols))
        h.update(json.dumps(rows, sort_keys=True).encode())

    return h.hexdigest()


def _get_existing_keys(
    conn: sqlite3.Connection, table: str, source: str, unique_cols: tuple[str, ...]
) -> set[tuple]:
    """Get the set of natural keys currently in the DB for this source/table."""
    natural_key_cols = [c for c in unique_cols if c != "source"]
    if not natural_key_cols:
        return set()
    select_cols = ", ".join(natural_key_cols)
    rows = conn.execute(
        f"SELECT {select_cols} FROM {table} WHERE source = ?", (source,)
    ).fetchall()
    return {tuple(row[c] for c in natural_key_cols) for row in rows}


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


def _build_upsert_sql(
    table: str, columns: list[str], unique_cols: tuple[str, ...]
) -> str:
    """Build INSERT ... ON CONFLICT ... DO UPDATE SET SQL."""
    col_names = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    conflict_cols = ", ".join(unique_cols)

    # Columns to update on conflict (everything not in the unique key)
    update_cols = [c for c in columns if c not in unique_cols]
    if not update_cols:
        # All columns are part of the unique key — just ignore duplicates
        return f"INSERT OR IGNORE INTO {table} ({col_names}) VALUES ({placeholders})"

    update_clause = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
    return (
        f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) "
        f"ON CONFLICT({conflict_cols}) DO UPDATE SET {update_clause}"
    )


def _cleanup_stale_records(
    conn: sqlite3.Connection,
    table: str,
    source: str,
    unique_cols: tuple[str, ...],
    imported_keys: set[tuple],
) -> int:
    """Delete records for this source whose natural key wasn't in the import.

    Returns the number of deleted rows.
    """
    natural_key_cols = [c for c in unique_cols if c != "source"]
    if not natural_key_cols:
        return 0

    select_cols = ", ".join(["id"] + natural_key_cols)
    existing = conn.execute(
        f"SELECT {select_cols} FROM {table} WHERE source = ?", (source,)
    ).fetchall()

    stale_ids = []
    for row in existing:
        key = tuple(row[c] for c in natural_key_cols)
        if key not in imported_keys:
            stale_ids.append(row["id"])

    if stale_ids:
        placeholders = ", ".join("?" for _ in stale_ids)
        conn.execute(
            f"DELETE FROM {table} WHERE id IN ({placeholders})", stale_ids
        )

    return len(stale_ids)


class ChartfoldDB:
    """SQLite-backed clinical data store."""

    def __init__(self, db_path: str = "chartfold.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def init_schema(self) -> None:
        """Create all tables from schema.sql (IF NOT EXISTS).

        Also migrates existing databases by adding any missing columns
        (e.g. metadata) via ALTER TABLE.
        """
        sql = _get_schema_sql()
        self.conn.executescript(sql)
        self._migrate_add_metadata_columns()

    def _migrate_add_metadata_columns(self) -> None:
        """Add metadata column to existing tables that lack it."""
        tables = ["patients"] + [t for _, t, _ in _TABLE_MAP]
        for table in tables:
            try:
                self.conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN metadata TEXT DEFAULT ''"
                )
            except sqlite3.OperationalError:
                pass  # Column already exists

    def load_source(
        self, records: UnifiedRecords, replace: bool = False
    ) -> LoadResult:
        """Load all records from a source into the database using UPSERT.

        UPSERT (INSERT ... ON CONFLICT ... DO UPDATE) preserves stable
        autoincrement IDs across re-imports, keeping FK references intact.

        Args:
            records: Unified records from a single source.
            replace: If True (bulk replace), also delete stale records for this
                     source that aren't in the import. If False (default,
                     additive), only add/update the provided records — never
                     deletes existing data.

        Returns:
            LoadResult with per-table diff stats and content hash.
        """
        source = records.source
        start = time.monotonic()
        chash = _content_hash(records)
        table_stats: dict[str, TableStats] = {}

        # Check if this exact data was already loaded
        last_load = self.conn.execute(
            "SELECT content_hash FROM load_log WHERE source = ? ORDER BY id DESC LIMIT 1",
            (source,),
        ).fetchone()
        if last_load and last_load["content_hash"] == chash:
            # Identical data — skip the load entirely
            return LoadResult(tables={}, content_hash=chash, skipped=True)

        with self.conn:
            # Upsert patient
            if records.patient is not None:
                unique_cols = _UNIQUE_KEYS["patients"]
                existing_keys = _get_existing_keys(self.conn, "patients", source, unique_cols)
                row = _record_to_row(records.patient)
                cols = list(row.keys())
                sql = _build_upsert_sql("patients", cols, unique_cols)
                self.conn.execute(sql, list(row.values()))

                natural_key_cols = [c for c in unique_cols if c != "source"]
                imported_key = tuple(row[c] for c in natural_key_cols)
                is_new = imported_key not in existing_keys

                removed = 0
                if replace:
                    removed = _cleanup_stale_records(
                        self.conn, "patients", source, unique_cols, {imported_key}
                    )

                table_stats["patients"] = TableStats(
                    new=1 if is_new else 0,
                    existing=0 if is_new else 1,
                    removed=removed,
                    total=1,
                )
            else:
                if replace:
                    cur = self.conn.execute(
                        "SELECT COUNT(*) AS n FROM patients WHERE source = ?", (source,)
                    )
                    removed = cur.fetchone()["n"]
                    if removed:
                        self.conn.execute(
                            "DELETE FROM patients WHERE source = ?", (source,)
                        )
                else:
                    removed = 0
                table_stats["patients"] = TableStats(
                    new=0, existing=0, removed=removed, total=0
                )

            # Upsert all record lists
            for attr, table, _dc_type in _TABLE_MAP:
                record_list = getattr(records, attr, [])
                unique_cols = _UNIQUE_KEYS[table]

                if not record_list:
                    removed = 0
                    if replace:
                        cur = self.conn.execute(
                            f"SELECT COUNT(*) AS n FROM {table} WHERE source = ?",
                            (source,),
                        )
                        removed = cur.fetchone()["n"]
                        if removed:
                            self.conn.execute(
                                f"DELETE FROM {table} WHERE source = ?", (source,)
                            )
                    table_stats[table] = TableStats(
                        new=0, existing=0, removed=removed, total=0
                    )
                    continue

                # Snapshot existing keys before upsert
                existing_keys = _get_existing_keys(
                    self.conn, table, source, unique_cols
                )

                # Build UPSERT SQL from first record's columns
                first_row = _record_to_row(record_list[0])
                cols = list(first_row.keys())
                sql = _build_upsert_sql(table, cols, unique_cols)

                # Build value rows and collect natural keys in one pass
                natural_key_cols = [c for c in unique_cols if c != "source"]
                rows = []
                imported_keys: set[tuple] = set()
                for r in record_list:
                    r_dict = _record_to_row(r)
                    rows.append(list(r_dict.values()))
                    key = tuple(r_dict[c] for c in natural_key_cols)
                    imported_keys.add(key)

                self.conn.executemany(sql, rows)

                new_keys = imported_keys - existing_keys
                existing_count = len(imported_keys) - len(new_keys)

                removed = 0
                if replace:
                    removed = _cleanup_stale_records(
                        self.conn, table, source, unique_cols, imported_keys
                    )

                table_stats[table] = TableStats(
                    new=len(new_keys),
                    existing=existing_count,
                    removed=removed,
                    total=len(record_list),
                )

            # Log the load with content hash
            duration = time.monotonic() - start
            now = datetime.now(timezone.utc).isoformat()
            counts = {t: s["total"] for t, s in table_stats.items()}
            self.conn.execute(
                """INSERT INTO load_log (
                    source, loaded_at, duration_seconds, content_hash,
                    patients_count, documents_count, encounters_count,
                    lab_results_count, vitals_count, medications_count,
                    conditions_count, procedures_count, pathology_reports_count,
                    imaging_reports_count, clinical_notes_count, immunizations_count,
                    allergies_count, social_history_count, family_history_count,
                    mental_status_count, source_assets_count, genetic_variants_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    source,
                    now,
                    duration,
                    chash,
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
                    counts.get("genetic_variants", 0),
                ),
            )

        return LoadResult(tables=table_stats, content_hash=chash, skipped=False)

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
            "genetic_variants": row.get("genetic_variants_count", 0),
        }

    # --- Tag helpers (shared by notes and analyses) ---

    def _save_tags(self, table: str, fk_col: str, fk_id: int, tags: list[str]) -> None:
        """Replace all tags for a record: delete existing, insert new."""
        self.conn.execute(f"DELETE FROM {table} WHERE {fk_col}=?", (fk_id,))
        for tag in tags:
            clean = tag.strip()
            if clean:
                self.conn.execute(
                    f"INSERT OR IGNORE INTO {table} ({fk_col}, tag) VALUES (?, ?)",
                    (fk_id, clean),
                )

    def _fetch_tags(self, table: str, fk_col: str, fk_id: int) -> list[str]:
        """Fetch sorted tags for a record."""
        rows = self.query(
            f"SELECT tag FROM {table} WHERE {fk_col} = ? ORDER BY tag",
            (fk_id,),
        )
        return [r["tag"] for r in rows]

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
            else:
                # Create new note
                cursor = self.conn.execute(
                    "INSERT INTO notes (title, content, created_at, updated_at, ref_table, ref_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (title, content, now, now, ref_table, ref_id),
                )
                # lastrowid is always int after INSERT
                note_id = cursor.lastrowid or 0

            self._save_tags("note_tags", "note_id", note_id, tags)

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
        note["tags"] = self._fetch_tags("note_tags", "note_id", note_id)
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

        for row in rows:
            row["tags"] = self._fetch_tags("note_tags", "note_id", row["id"])

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
            else:
                cursor = self.conn.execute(
                    "INSERT INTO analyses (slug, title, content, frontmatter, "
                    "category, summary, source, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (slug, title, content, frontmatter_json, category, summary, source, now, now),
                )
                analysis_id = cursor.lastrowid or 0

            self._save_tags("analysis_tags", "analysis_id", analysis_id, tags)

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
        analysis["tags"] = self._fetch_tags("analysis_tags", "analysis_id", analysis["id"])
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
            row["tags"] = self._fetch_tags("analysis_tags", "analysis_id", row["id"])

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
