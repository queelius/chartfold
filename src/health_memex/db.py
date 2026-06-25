"""SQLite database layer for health-memex.

HealthMemexDB wraps a SQLite database with:
- Schema initialization from schema.sql
- UPSERT-based source loading (stable IDs across re-imports)
- Read-only query helper returning list[dict]
- Load logging for audit trail
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from health_memex.models import (
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

# Tables that carry the archived_at soft-delete column.
# Every record table + marginalia (notes, analyses).
# Excludes: load_log (audit trail), note_tags / analysis_tags (join tables
# that cascade with parent).
_SOFT_DELETE_TABLES: frozenset[str] = frozenset({*_UNIQUE_KEYS.keys(), "notes", "analyses"})


class TableStats(TypedDict):
    """Per-table load statistics."""

    new: int  # Records whose natural key didn't exist before
    existing: int  # Records whose natural key already existed (upserted)
    removed: int  # Stale records deleted (only in replace=True mode)
    total: int  # Total records in the import


class LoadResult:  # noqa: PLW1641 (no need for __hash__)
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
    rows = conn.execute(f"SELECT {select_cols} FROM {table} WHERE source = ?", (source,)).fetchall()
    return {tuple(row[c] for c in natural_key_cols) for row in rows}


def _get_schema_sql() -> str:
    """Read the schema.sql file bundled with the package."""
    schema_path = Path(__file__).parent / "schema.sql"
    return schema_path.read_text()


def _record_to_row(record) -> dict:
    """Convert a dataclass record to a dict suitable for INSERT."""
    return asdict(record)


# Number of hex chars retained from sha256 output for unique_id values.
# 16 hex = 8 bytes = 64 bits → birthday collision after ~4 billion records,
# wildly safe for personal-archive scale. Matches the bookmark-memex
# convention (sha256(url)[:16]).
_UNIQUE_ID_HEX_LEN = 16


def _compute_unique_id(table: str, row: dict) -> str:
    """Content-hash a row's natural key into a durable unique_id.

    The natural key for *table* comes from :data:`_UNIQUE_KEYS`. Field
    values are joined with ``\\x00`` (null byte, which never appears in
    clinical text/date/number fields) so adjacent fields can't collide.
    NULL/missing fields serialise as the empty string, keeping the
    function total when a natural-key column is absent.

    Same natural key always yields the same hash, which is the whole
    point: re-importing the same source data produces stable URIs.

    Raises ``ValueError`` for unknown tables, since durable IDs only
    apply to tables that have a declared natural key.
    """
    if table not in _UNIQUE_KEYS:
        raise ValueError(f"no natural key declared for table {table!r}")
    parts: list[str] = []
    for col in _UNIQUE_KEYS[table]:
        val = row.get(col)
        parts.append("" if val is None else str(val))
    payload = "\x00".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:_UNIQUE_ID_HEX_LEN]


# Regex-like predicate for distinguishing unique_id strings from
# autoincrement integer ids in URI lookup. A unique_id is exactly
# _UNIQUE_ID_HEX_LEN lowercase hex chars; anything else is treated as
# either a numeric autoincrement id (digits only) or invalid input.
def _is_unique_id_format(s: str) -> bool:
    if len(s) != _UNIQUE_ID_HEX_LEN:
        return False
    return all(c in "0123456789abcdef" for c in s)


def _escape_like(s: str) -> str:
    """Escape LIKE wildcards so they match literally."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _build_upsert_sql(table: str, columns: list[str], unique_cols: tuple[str, ...]) -> str:
    """Build INSERT ... ON CONFLICT ... DO UPDATE SET SQL.

    For tables that support soft delete, the ON CONFLICT branch also clears
    archived_at. Rationale: if the source re-supplies a record whose natural
    key matches an archived row, the record is current again (resurrection).
    """
    col_names = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    conflict_cols = ", ".join(unique_cols)

    # Columns to update on conflict (everything not in the unique key)
    update_cols = [c for c in columns if c not in unique_cols]
    if not update_cols:
        # All columns are part of the unique key — just ignore duplicates
        return f"INSERT OR IGNORE INTO {table} ({col_names}) VALUES ({placeholders})"

    update_pairs = [f"{c} = excluded.{c}" for c in update_cols]
    # Resurrection: clear archived_at when a re-import matches by natural key.
    # archived_at isn't in the dataclass columns, so we hardcode the reset.
    if table in _SOFT_DELETE_TABLES:
        update_pairs.append("archived_at = NULL")
    update_clause = ", ".join(update_pairs)
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

    select_cols = ", ".join(["id", *natural_key_cols])
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
        conn.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", stale_ids)

    return len(stale_ids)


class HealthMemexDB:
    """SQLite-backed clinical data store."""

    def __init__(self, db_path: str = "health_memex.db"):
        self.db_path = db_path
        # Ensure parent dir exists. The XDG default
        # (~/.local/share/health-memex/health_memex.db) won't be there on
        # a fresh install; sqlite3 raises a confusing "unable to open
        # database file" if we don't create it. Skip for ":memory:" or
        # other special paths that don't have a meaningful parent.
        parent = os.path.dirname(db_path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def init_schema(self) -> None:
        """Create all tables from schema.sql (IF NOT EXISTS) and run
        the forward migrations on any pre-existing database.
        """
        sql = _get_schema_sql()
        self.conn.executescript(sql)
        self._run_migrations()

    def _run_migrations(self) -> None:
        """Bring a possibly-old database up to the current schema.

        Each migration step uses ``ALTER TABLE ADD COLUMN`` (cheap,
        idempotent — raises OperationalError if the column already
        exists, which we suppress) plus targeted backfill helpers.
        Called from ``init_schema`` after the IF-NOT-EXISTS DDL runs.
        Steps:
          1. ``metadata`` JSON column on every record table.
          2. ``genetic_variants_count`` on ``load_log``.
          3. ``archived_at`` on every soft-delete table.
          4. ``unique_id`` (V2b durable IDs) on every clinical table,
             with a partial UNIQUE INDEX, and a backfill pass.
          5. FTS5 index rebuild for any rows missing from the index.
        """
        record_tables = ["patients"] + [t for _, t, _ in _TABLE_MAP]
        for table in record_tables:
            with contextlib.suppress(sqlite3.OperationalError):
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN metadata TEXT DEFAULT ''")

        # Add load_log columns introduced after initial schema
        with contextlib.suppress(sqlite3.OperationalError):
            self.conn.execute(
                "ALTER TABLE load_log ADD COLUMN genetic_variants_count INTEGER DEFAULT 0"
            )

        # archived_at soft-delete column on every record table + marginalia
        soft_delete_tables = [*record_tables, "notes", "analyses"]
        for table in soft_delete_tables:
            with contextlib.suppress(sqlite3.OperationalError):
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN archived_at TEXT")

        # archived_at indexes for notes/analyses are created HERE, not in
        # schema.sql, so they run only after the column above exists. On a
        # legacy DB whose notes/analyses tables predate archived_at, building
        # these in the schema.sql executescript would raise "no such column"
        # and abort the whole script before this migration could add it — a
        # chicken-and-egg deadlock that bricked every tool/CLI against the
        # deployed legacy database.
        for table in ("notes", "analyses"):
            with contextlib.suppress(sqlite3.OperationalError):
                self.conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_archived "
                    f"ON {table}(archived_at)"
                )

        # Durable IDs (V2b): every clinical table gains a content-hash
        # unique_id derived from its natural key. Stable across re-imports
        # so trail steps and arkiv URIs survive DB rebuilds.
        for table in _UNIQUE_KEYS:
            with contextlib.suppress(sqlite3.OperationalError):
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN unique_id TEXT")
            with contextlib.suppress(sqlite3.OperationalError):
                self.conn.execute(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_unique_id "
                    f"ON {table}(unique_id) WHERE unique_id IS NOT NULL"
                )
        self._backfill_unique_ids()

        # Backfill FTS5 indexes for existing rows. Triggers keep them in sync
        # from now on, but rows loaded before the FTS tables existed need to
        # be indexed once. Safe to rerun: only rows missing from FTS are added.
        self._backfill_fts_indexes()

    def _backfill_unique_ids(self) -> None:
        """Compute unique_id for any rows where it's still NULL.

        Runs after the ALTER TABLE migrations. For each table in
        ``_UNIQUE_KEYS``, fetch rows missing a unique_id, compute the
        natural-key hash, and UPDATE. Idempotent: a fresh DB has no
        rows to backfill (load_source already populates unique_id).
        """
        any_updates = False
        for table, unique_cols in _UNIQUE_KEYS.items():
            select_cols = ", ".join(["id", *unique_cols])
            try:
                rows = self.conn.execute(
                    f"SELECT {select_cols} FROM {table} "
                    f"WHERE unique_id IS NULL"
                ).fetchall()
            except sqlite3.OperationalError:
                # Column missing on a much older DB that for some
                # reason didn't pick up the ALTER above. Skip.
                continue
            if not rows:
                continue
            updates: list[tuple[str, int]] = []
            for row in rows:
                row_dict = {c: row[c] for c in unique_cols}
                uid = _compute_unique_id(table, row_dict)
                updates.append((uid, row["id"]))
            self.conn.executemany(
                f"UPDATE {table} SET unique_id = ? WHERE id = ?", updates
            )
            any_updates = True
        # ``executemany`` of UPDATE starts an implicit transaction in
        # Python's sqlite3 module. Commit so the backfill survives the
        # connection close. (DDL ALTER TABLE earlier in this migration
        # path is auto-committed; DML is not.)
        if any_updates:
            self.conn.commit()

    def _backfill_fts_indexes(self) -> None:
        """Rebuild FTS5 indexes when they have fewer docs than the parent.

        External-content FTS5 can't be probed with SELECT because rowids proxy
        the parent table. Instead we check the FTS5 _docsize shadow table,
        which stores one row per indexed document. If fewer docs are indexed
        than exist in the parent, we issue the canonical 'rebuild' command.
        Idempotent and fast when already in sync.
        """
        for fts, parent in (
            ("clinical_notes_fts", "clinical_notes"),
            ("pathology_fts", "pathology_reports"),
            ("imaging_fts", "imaging_reports"),
        ):
            parent_count = self.conn.execute(f"SELECT COUNT(*) FROM {parent}").fetchone()[0]
            if parent_count == 0:
                continue
            fts_count = self.conn.execute(f"SELECT COUNT(*) FROM {fts}_docsize").fetchone()[0]
            if fts_count < parent_count:
                self.conn.execute(f"INSERT INTO {fts}({fts}) VALUES('rebuild')")

    def load_source(self, records: UnifiedRecords, replace: bool = False) -> LoadResult:
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

        # Check if this exact data was already loaded. We can short-circuit only
        # if no records from this source are currently archived — otherwise we
        # need the UPSERT to fire so resurrection (archived_at = NULL) happens.
        last_load = self.conn.execute(
            "SELECT content_hash FROM load_log WHERE source = ? ORDER BY id DESC LIMIT 1",
            (source,),
        ).fetchone()
        if (
            last_load
            and last_load["content_hash"] == chash
            and not self._has_archived_records(source)
        ):
            # Identical data, no archived rows — skip the load entirely.
            # If archived rows exist, we fall through so UPSERT resurrects them.
            return LoadResult(tables={}, content_hash=chash, skipped=True)

        with self.conn:
            # Upsert patient
            if records.patient is not None:
                unique_cols = _UNIQUE_KEYS["patients"]
                existing_keys = _get_existing_keys(self.conn, "patients", source, unique_cols)
                row = _record_to_row(records.patient)
                row["unique_id"] = _compute_unique_id("patients", row)
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
                        self.conn.execute("DELETE FROM patients WHERE source = ?", (source,))
                else:
                    removed = 0
                table_stats["patients"] = TableStats(new=0, existing=0, removed=removed, total=0)

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
                            self.conn.execute(f"DELETE FROM {table} WHERE source = ?", (source,))
                    table_stats[table] = TableStats(new=0, existing=0, removed=removed, total=0)
                    continue

                # Snapshot existing keys before upsert
                existing_keys = _get_existing_keys(self.conn, table, source, unique_cols)

                # Build UPSERT SQL from first record's columns + unique_id
                first_row = _record_to_row(record_list[0])
                first_row["unique_id"] = _compute_unique_id(table, first_row)
                cols = list(first_row.keys())
                sql = _build_upsert_sql(table, cols, unique_cols)

                # Build value rows and collect natural keys in one pass
                natural_key_cols = [c for c in unique_cols if c != "source"]
                rows = []
                imported_keys: set[tuple] = set()
                for r in record_list:
                    r_dict = _record_to_row(r)
                    r_dict["unique_id"] = _compute_unique_id(table, r_dict)
                    rows.append([r_dict[c] for c in cols])
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

            # Derive count columns from _TABLE_MAP (+ patients)
            table_names = ["patients"] + [table for _, table, _ in _TABLE_MAP]
            count_cols = [f"{t}_count" for t in table_names]
            count_vals = [counts.get(t, 0) for t in table_names]

            col_str = ", ".join(
                ["source", "loaded_at", "duration_seconds", "content_hash", *count_cols]
            )
            placeholders = ", ".join("?" for _ in range(4 + len(count_cols)))
            self.conn.execute(
                f"INSERT INTO load_log ({col_str}) VALUES ({placeholders})",
                (source, now, duration, chash, *count_vals),
            )

        return LoadResult(tables=table_stats, content_hash=chash, skipped=False)

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        """Execute a read-only SQL query and return results as list of dicts.

        Uses a separate read-only connection to prevent accidental writes.
        """
        import sqlite3 as _sqlite3

        conn = _sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            cursor = conn.execute(sql, params)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def summary(self) -> dict[str, int]:
        """Return active (non-archived) row counts for all main tables.

        Auto-discovered from schema. Soft-delete tables are counted with
        WHERE archived_at IS NULL so archived records do not inflate the
        summary; tables without an archived_at column (e.g. join tables) are
        counted in full.
        """
        rows = self.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
        result = {}
        for r in rows:
            table = r["name"]
            if table == "load_log":
                continue  # Exclude audit log from summary display
            if table in _SOFT_DELETE_TABLES:
                row = self.conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE archived_at IS NULL"
                ).fetchone()
            else:
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
        # Derive table list from _TABLE_MAP + patients (loaded separately)
        tables = ["patients"] + [table for _, table, _ in _TABLE_MAP]
        return {table: row.get(f"{table}_count", 0) for table in tables}

    def _has_archived_records(self, source: str) -> bool:
        """True if any record in any clinical table for this source is archived.

        Used by load_source to decide whether it's safe to short-circuit an
        identical re-import: if archived records exist, we must run the UPSERT
        so natural-key matches resurrect them.
        """
        clinical = ["patients", *(t for _, t, _ in _TABLE_MAP)]
        for table in clinical:
            row = self.conn.execute(
                f"SELECT 1 FROM {table} WHERE source = ? AND archived_at IS NOT NULL LIMIT 1",
                (source,),
            ).fetchone()
            if row is not None:
                return True
        return False

    # --- Soft-delete primitives ---

    def _validate_soft_delete_table(self, table: str) -> None:
        """Raise ValueError if table doesn't support archived_at.

        Centralizes the allowlist so archive/unarchive/purge callers can't
        spray raw table names into SQL. Tables without archived_at (load_log,
        note_tags, analysis_tags) are explicitly rejected.
        """
        if table not in _SOFT_DELETE_TABLES:
            raise ValueError(
                f"Table {table!r} does not support soft delete. "
                f"Allowed: {sorted(_SOFT_DELETE_TABLES)}"
            )

    def archive_record(self, table: str, record_id: int) -> bool:
        """Mark a record as archived (soft delete). Returns True if a row was touched."""
        self._validate_soft_delete_table(table)
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            f"UPDATE {table} SET archived_at = ? WHERE id = ? AND archived_at IS NULL",
            (now, record_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def unarchive_record(self, table: str, record_id: int) -> bool:
        """Restore an archived record. Returns True if a row was touched."""
        self._validate_soft_delete_table(table)
        cursor = self.conn.execute(
            f"UPDATE {table} SET archived_at = NULL WHERE id = ? AND archived_at IS NOT NULL",
            (record_id,),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def purge_record(self, table: str, record_id: int) -> bool:
        """Hard-delete a record. Returns True if a row was deleted.

        Use with caution: this breaks URI references in marginalia and trails.
        Prefer archive_record for user-driven deletion.
        """
        self._validate_soft_delete_table(table)
        cursor = self.conn.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))
        self.conn.commit()
        return cursor.rowcount > 0

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

    def get_note_tags(self, note_id: int) -> list[str]:
        """Fetch sorted tags for a note."""
        return self._fetch_tags("note_tags", "note_id", note_id)

    def get_analysis_tags(self, analysis_id: int) -> list[str]:
        """Fetch sorted tags for an analysis."""
        return self._fetch_tags("analysis_tags", "analysis_id", analysis_id)

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
                # Update existing note. Resurrection: clear archived_at so
                # re-saving a soft-deleted note brings it back.
                cursor = self.conn.execute(
                    "UPDATE notes SET title=?, content=?, updated_at=?, ref_table=?, ref_id=?, "
                    "archived_at=NULL WHERE id=?",
                    (title, content, now, ref_table, ref_id, note_id),
                )
                if cursor.rowcount == 0:
                    raise ValueError(f"Note {note_id} not found")
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

    def get_note(self, note_id: int, include_archived: bool = False) -> dict | None:
        """Retrieve a note by ID, including its tags. Returns None if not found.

        Archived notes are hidden by default; pass include_archived=True to
        retrieve a soft-deleted note (e.g. for restore workflows).
        """
        filt = "" if include_archived else " AND archived_at IS NULL"
        rows = self.query(
            "SELECT id, title, content, created_at, updated_at, ref_table, ref_id, archived_at "
            f"FROM notes WHERE id = ?{filt}",
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
        include_archived: bool = False,
    ) -> list[dict]:
        """Search personal notes with optional filters (AND-combined).

        Returns notes ordered by updated_at DESC with a 300-char content preview.
        Archived notes are hidden by default; pass include_archived=True to show them.
        """
        conditions: list[str] = []
        params: list = []
        joins = ""

        if not include_archived:
            conditions.append("n.archived_at IS NULL")

        if tag:
            joins = " JOIN note_tags nt ON n.id = nt.note_id"
            conditions.append("nt.tag = ?")
            params.append(tag)

        if query:
            conditions.append(
                "(LOWER(n.title) LIKE ? ESCAPE '\\' OR LOWER(n.content) LIKE ? ESCAPE '\\')"
            )
            escaped = _escape_like(query.lower())
            params.extend([f"%{escaped}%", f"%{escaped}%"])

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

    def delete_note(self, note_id: int, hard: bool = False) -> bool:
        """Delete a note by ID. Returns True if a row was affected.

        Default is soft delete (sets archived_at) to preserve URI references
        from marginalia and trails. Pass hard=True to permanently remove.
        """
        if hard:
            return self.purge_record("notes", note_id)
        return self.archive_record("notes", note_id)

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
            existing = self.query("SELECT id FROM analyses WHERE slug = ?", (slug,))

            if existing:
                analysis_id = existing[0]["id"]
                # Resurrection: saving an existing slug clears archived_at
                # so users who re-save a soft-deleted analysis get it back.
                self.conn.execute(
                    "UPDATE analyses SET title=?, content=?, frontmatter=?, "
                    "category=?, summary=?, source=?, updated_at=?, "
                    "archived_at=NULL WHERE id=?",
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

    def get_analysis(self, slug_or_id: str | int, include_archived: bool = False) -> dict | None:
        """Retrieve an analysis by slug (str) or id (int). Returns None if not found.

        Archived analyses are hidden by default; pass include_archived=True to
        retrieve a soft-deleted analysis (e.g. for restore workflows).
        """
        filt = "" if include_archived else " AND archived_at IS NULL"
        if isinstance(slug_or_id, int):
            rows = self.query(f"SELECT * FROM analyses WHERE id = ?{filt}", (slug_or_id,))
        else:
            rows = self.query(f"SELECT * FROM analyses WHERE slug = ?{filt}", (slug_or_id,))

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
        include_archived: bool = False,
    ) -> list[dict]:
        """Search analyses with optional filters (AND-combined).

        Returns analyses ordered by updated_at DESC with a 300-char content preview.
        Archived analyses are hidden by default; pass include_archived=True to show them.
        """
        conditions: list[str] = []
        params: list = []
        joins = ""

        if not include_archived:
            conditions.append("a.archived_at IS NULL")

        if tag:
            joins = " JOIN analysis_tags at ON a.id = at.analysis_id"
            conditions.append("at.tag = ?")
            params.append(tag)

        if query:
            conditions.append(
                "(LOWER(a.title) LIKE ? ESCAPE '\\' OR LOWER(a.content) LIKE ? ESCAPE '\\' "
                "OR LOWER(a.frontmatter) LIKE ? ESCAPE '\\')"
            )
            q = f"%{_escape_like(query.lower())}%"
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

    def delete_analysis(self, slug_or_id: str | int, hard: bool = False) -> bool:
        """Delete an analysis by slug (str) or id (int). Returns True if affected.

        Default is soft delete (sets archived_at). Pass hard=True to permanently
        remove.
        """
        # Resolve slug -> id so we can reuse archive/purge primitives
        if isinstance(slug_or_id, int):
            analysis_id: int | None = slug_or_id
        else:
            rows = self.query("SELECT id FROM analyses WHERE slug = ?", (slug_or_id,))
            analysis_id = rows[0]["id"] if rows else None
        if analysis_id is None:
            return False
        if hard:
            return self.purge_record("analyses", analysis_id)
        return self.archive_record("analyses", analysis_id)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def _discover_tables(db: HealthMemexDB) -> list[str]:
    """All user tables from sqlite_master, excluding sqlite_ internals."""
    rows = db.query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    )
    return [r["name"] for r in rows]


def _discover_fk_graph(
    db: HealthMemexDB,
    tables: list[str],
) -> dict[str, list[tuple[str, str, str]]]:
    """FK graph via PRAGMA foreign_key_list().

    Returns {child_table: [(fk_col, parent_table, parent_col), ...]}.
    Only includes relationships where both tables are in the provided list.
    """
    table_set = set(tables)
    graph: dict[str, list[tuple[str, str, str]]] = {}
    for table in tables:
        fks = db.query(f"PRAGMA foreign_key_list({table})")
        for fk in fks:
            parent = fk["table"]
            if parent in table_set:
                graph.setdefault(table, []).append((fk["from"], parent, fk["to"]))
    return graph


def _topological_sort(
    tables: list[str], fk_graph: dict[str, list[tuple[str, str, str]]]
) -> list[str]:
    """Sort tables so parents come before children.

    Uses Kahn's algorithm. Handles cycles gracefully by appending remaining
    tables at the end (cycle shouldn't happen in a well-formed schema).
    """
    # Build adjacency: parent -> set of children
    in_degree: dict[str, int] = dict.fromkeys(tables, 0)
    children: dict[str, list[str]] = {t: [] for t in tables}

    for child, fk_list in fk_graph.items():
        parents = {fk[1] for fk in fk_list}  # unique parent tables
        for parent in parents:
            if parent != child and parent in in_degree:  # skip self-references
                in_degree[child] = in_degree.get(child, 0) + 1
                children.setdefault(parent, []).append(child)

    # Start with nodes that have no dependencies
    queue = [t for t in tables if in_degree[t] == 0]
    result = []

    while queue:
        # Sort for deterministic ordering
        queue.sort()
        node = queue.pop(0)
        result.append(node)
        for child in children.get(node, []):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    # Append any remaining (cycle) tables
    remaining = [t for t in tables if t not in set(result)]
    remaining.sort()
    result.extend(remaining)

    return result
