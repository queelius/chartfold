"""MCP server for health-memex — Claude queries patient data via SQL tools.

Run with: python -m health_memex.mcp.server
Configure env: HEALTH_MEMEX_DB=/path/to/health_memex.db (default: XDG data home)
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from mcp.server.fastmcp import FastMCP

from health_memex.db import (
    _UNIQUE_KEYS,
    HealthMemexDB,
    _build_upsert_sql,
    _compute_unique_id,
    _is_unique_id_format,
    default_db_path,
)

# Same resolver as the CLI (env var, then XDG), never a cwd-relative default:
# the federation spawns this server from arbitrary working directories.
DB_PATH = default_db_path()

mcp = FastMCP(
    "health-memex",
    instructions=(
        "Patient clinical data server with unified SQLite database containing records "
        "from Epic, MEDITECH, and athenahealth sources.\n\n"
        "Key capabilities:\n"
        "- run_sql / get_schema: Direct SQL access (read-only)\n"
        "- query_labs / get_lab_series_tool: Lab results per-source or unified cross-source series\n"
        "- get_available_tests: Discover what tests exist in the database\n"
        "- get_abnormal_labs: All flagged-abnormal lab results\n"
        "- get_medications / reconcile_medications_tool: Medication list and cross-source reconciliation\n"
        "- get_visit_diff: Everything new since a given date (encounters, procedures, imaging, labs, pathology)\n"
        "- get_visit_prep: Pre-appointment summary\n"
        "- get_surgical_timeline: Procedures linked to pathology, imaging, and medications\n"
        "- match_cross_source_encounters: Same-day encounters across different EHR systems\n"
        "- get_data_quality_report: Duplicate labs and source coverage matrix\n"
        "- get_database_summary: Table counts and load history\n"
        "- search_notes / search_pathology_fts / search_imaging_fts: FTS5 full-text search over clinical notes, pathology reports, and imaging reports\n"
        "- get_pathology_report: Pathology report lookup by id/date/specimen\n"
        "- get_source_files / get_asset_summary: Find source files (PDFs, images) linked to records\n\n"
        "- save_note / get_note / search_notes_personal / delete_note: Persist and retrieve personal analyses, observations, and visit prep summaries\n"
        "- save_analysis / get_analysis / search_analyses / list_analyses / delete_analysis: Manage structured analysis documents with YAML frontmatter metadata\n\n"
        "Start with get_database_summary or get_schema to understand available data. "
        "Use get_data_quality_report before cross-source analysis to understand duplicates. "
        "Use save_note to persist important analyses or observations for future reference."
    ),
)


_db: HealthMemexDB | None = None


def _get_db() -> HealthMemexDB:
    """Return a shared HealthMemexDB instance (lazy singleton).

    MCP servers are single-process and handle one request at a time,
    so a shared connection is safe and avoids re-running init_schema()
    on every tool call.
    """
    global _db  # noqa: PLW0603
    if _db is None:
        _db = HealthMemexDB(DB_PATH)
        _db.init_schema()
    return _db


def _sqlite_authorizer(action: int, arg1, arg2, db_name, trigger_name) -> int:
    """SQLite authorizer that denies ATTACH/DETACH at the engine level.

    ATTACH/DETACH bypass read-only mode by opening new (potentially writable)
    databases. Blocking at the authorizer level is immune to SQL comment tricks
    and formatting that would defeat regex-based checks.
    """
    if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _readonly_query(query: str, params: tuple = ()) -> list[dict] | str:
    """Execute a query against a read-only SQLite connection.

    Uses SQLite's URI mode=ro for engine-level read-only enforcement
    plus an authorizer callback to block ATTACH/DETACH.

    *params* is forwarded to ``conn.execute`` as the standard sqlite3
    parameter substitution (``?`` placeholders in the query). Callers
    SHOULD use placeholders for any user-supplied value rather than
    interpolating into the SQL string; the format-check defenses in
    individual callers are then unnecessary.

    Why _get_db() runs first:

    * ``mode=ro`` cannot CREATE the database file. If DB_PATH points
      at a path that hasn't been initialised, ``mode=ro`` fails with
      "unable to open database file". Forcing the R/W singleton to
      instantiate first creates the file, runs init_schema (which is
      itself idempotent), and applies migrations — only then does the
      readonly connection attach.

    * The R/W singleton also opens in WAL journal mode, creating the
      ``-shm`` shadow-memory file. Modern sqlite3 (3.22+) handles
      WAL+ro+missing-shm gracefully when the WAL has been
      checkpointed, but older builds or DBs in inconsistent post-
      crash states benefit from -shm being present before a readonly
      attach.

    Net effect: the very first read against a fresh DB path Just
    Works, and we get migration-applied data instead of a confusing
    error.
    """
    _get_db()  # ensure file exists, schema initialised, -shm present
    conn = None
    MAX_ROWS = 5000
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.set_authorizer(_sqlite_authorizer)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        rows = cursor.fetchmany(MAX_ROWS)
        if len(rows) == MAX_ROWS and cursor.fetchone() is not None:
            return (
                f"Error: query returned more than {MAX_ROWS} rows. "
                f"Add a LIMIT clause or filter your query."
            )
        return [dict(r) for r in rows]
    except sqlite3.OperationalError as e:
        msg = str(e).lower()
        if "readonly" in msg or "attempt to write" in msg or "not authorized" in msg:
            return "Error: This connection is read-only. Write operations are not permitted."
        return f"SQL Error: {e}"
    except Exception as e:
        return f"SQL Error: {e}"
    finally:
        if conn:
            conn.close()


# ---------------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------------


@mcp.tool()
def run_sql(query: str) -> list[dict] | str:
    """Execute a read-only SQL query against the health-memex database.

    Only SELECT statements are allowed. Returns results as a list of dicts.

    The connection is opened in read-only mode at the SQLite engine level,
    so INSERT/UPDATE/DELETE/DROP will be rejected by the database itself.

    Key tables: patients, documents, encounters, lab_results, vitals,
    medications, conditions, procedures, pathology_reports, imaging_reports,
    clinical_notes, immunizations, allergies, social_history, family_history,
    mental_status, notes, note_tags, analyses, analysis_tags, source_assets,
    load_log.

    Lab results have both `value` (TEXT) and `value_numeric` (REAL, NULL if not parseable).
    Every clinical table has a `source` column for cross-source queries.
    The `analyses` table stores frontmatter as JSON — use json_extract() to query it.
    """
    return _readonly_query(query)


@mcp.tool()
def get_schema() -> str:
    """Get the database schema (CREATE TABLE statements) for query planning."""
    result = _readonly_query(
        "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL ORDER BY name"
    )
    if isinstance(result, str):
        return result
    return "\n\n".join(r["sql"] for r in result)


@mcp.tool()
def get_database_summary() -> dict:
    """Get an overview of what data is loaded in the database."""
    db = _get_db()
    return {"table_counts": db.summary(), "load_history": db.sources()}


# Tables that ``get_record`` can resolve, mapped to the column holding each
# record's durable id. Mirrors the arkiv export convention
# (``health-memex:{table}/{id}``) so URI kind == SQL table. Derived from
# ``_UNIQUE_KEYS`` (the canonical clinical-table list, keyed by unique_id)
# plus ``notes`` and ``analyses``, which carry their own ``archived_at`` but
# live outside the clinical-records pipeline and have no natural key, so
# their id is the autoincrement ``id``. Served by ``get_record_kinds``.
_RECORD_ID_COLUMNS: dict[str, str] = {
    **dict.fromkeys(_UNIQUE_KEYS, "unique_id"),
    "notes": "id",
    "analyses": "id",
}
_RECORD_KINDS: frozenset[str] = frozenset(_RECORD_ID_COLUMNS)


@mcp.tool()
def get_record_kinds() -> dict:
    """Declare the URI kinds this archive resolves (health-memex://<kind>/<id>)
    and the table and id column backing each. Part of the *-memex archive
    contract. Every kind is its SQL table."""
    return {
        "kinds": [
            {"kind": kind, "table": kind, "id_column": id_column}
            for kind, id_column in _RECORD_ID_COLUMNS.items()
        ]
    }


@mcp.tool()
def get_record(kind: str, id: str) -> dict:
    """Resolve a health-memex://{kind}/{id} URI to one record.

    The federation layer's ``LocalProcessResolver`` calls this tool to
    dereference cross-archive URIs. For ad-hoc use, prefer the kind-
    specific tools (``query_labs``, ``get_pathology_report``, etc.)
    which return richer, multi-row views.

    Two id formats are accepted (auto-detected by string shape):

      - **unique_id**: 16 hex chars (sha256 of the row's natural key,
        truncated). Stable across re-imports. The durable form for
        clinical tables in ``_UNIQUE_KEYS``.
      - **autoincrement id**: pure digits. The native form for
        ``notes`` and ``analyses`` (no natural key, no unique_id
        column). Also resolves clinical rows for legacy URIs that
        pre-date the unique_id migration; those URIs may break
        across DB rebuilds since autoincrement values churn.

    Both forms return the same response shape, so callers don't
    need to know which format they used.

    Args:
        kind: Table name (e.g. ``"lab_results"``, ``"encounters"``).
            Must match the arkiv URI convention.
        id: 16-hex unique_id OR digits-only autoincrement id, passed
            as a string. Other formats return ``invalid_id``.

    Returns:
        On success: ``{"kind": kind, "id": <id_used_for_lookup>,
            "record": {...row}}``. ``id`` echoes back exactly what was
            provided (preserving the format the caller chose).
        On invalid kind: ``{"error": "unknown_kind", "kind": kind, ...}``.
        On unrecognized id format: ``{"error": "invalid_id", "id": id}``.
        On missing row: ``{"error": "not_found", "kind": kind, "id": id}``.
    """
    if kind not in _RECORD_KINDS:
        return {
            "error": "unknown_kind",
            "kind": kind,
            "valid_kinds": sorted(_RECORD_KINDS),
        }

    # The notes/analyses tables have no natural key (and thus no
    # unique_id column), so we always look them up by autoincrement id.
    has_unique_id = _RECORD_ID_COLUMNS[kind] == "unique_id"

    # A URI fragment ("#page=3", an epubcfi, a message range, ...) addresses a
    # position *within* a record, not a different record, so strip it before
    # resolving: the base id selects the row. Mirrors mail-memex's parse_uri.
    base_id, _, fragment = id.partition("#")

    # `kind` is allowlisted via _RECORD_KINDS; `base_id` is parameterised, so
    # neither can carry a SQL injection. The format checks pick the
    # right column (durable unique_id vs autoincrement id) but no
    # longer guard against escape — the placeholder does.
    if has_unique_id and _is_unique_id_format(base_id):
        rows = _readonly_query(f"SELECT * FROM {kind} WHERE unique_id = ?", (base_id,))
    elif base_id.isdigit():
        rows = _readonly_query(f"SELECT * FROM {kind} WHERE id = ?", (base_id,))
    else:
        return {"error": "invalid_id", "id": id}

    # _readonly_query returns str on error, list[dict] on success
    if isinstance(rows, str):
        return {"error": "sql_error", "detail": rows}
    if not rows:
        return {"error": "not_found", "kind": kind, "id": id}
    record = rows[0]
    result: dict[str, Any] = {"kind": kind, "id": id, "record": record}
    # R4: surface archived state explicitly. Archived records stay resolvable
    # (cross-archive references must not break on soft-delete), but callers
    # should not have to dig the archived_at column out of the record.
    result["archived"] = bool(isinstance(record, dict) and record.get("archived_at"))
    if fragment:
        # Echo the fragment so callers can post-resolve the sub-position.
        result["fragment"] = fragment
    return result


# ---------------------------------------------------------------------------
# Clinical query tools
# ---------------------------------------------------------------------------


@mcp.tool()
def query_labs(
    test_name: str = "",
    loinc: str = "",
    start_date: str = "",
    end_date: str = "",
) -> list[dict]:
    """Query lab results by test name, LOINC code, and/or date range.

    Args:
        test_name: Partial match on test name (case-insensitive). E.g., "CEA", "hemoglobin".
        loinc: LOINC code for exact match. E.g., "2039-6" for CEA.
        start_date: ISO date, results on or after.
        end_date: ISO date, results on or before.
    """
    from health_memex.analysis.lab_trends import get_lab_trend

    return get_lab_trend(
        _get_db(),
        test_name=test_name or None,
        test_loinc=loinc or None,
        start_date=start_date or "",
        end_date=end_date or "",
    )


@mcp.tool()
def get_lab_series_tool(
    test_name: str = "",
    loinc: str = "",
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """Get a unified cross-source lab series for a test.

    Returns all results across all sources in chronological order, with source
    annotations and reference range discrepancy flags. Use this instead of
    query_labs when you need the full cross-source picture for a single test.

    Args:
        test_name: Partial match on test name (case-insensitive). E.g., "CEA", "hemoglobin".
        loinc: LOINC code for exact match. E.g., "2039-6" for CEA.
        start_date: ISO date, results on or after.
        end_date: ISO date, results on or before.
    """
    from health_memex.analysis.lab_trends import get_lab_series

    return get_lab_series(
        _get_db(),
        test_name=test_name or None,
        test_loinc=loinc or None,
        start_date=start_date,
        end_date=end_date,
    )


@mcp.tool()
def get_available_tests_tool() -> list[dict]:
    """List all lab tests in the database with frequency and date range.

    Returns each test's name, result count, which sources have it, and earliest/latest
    result dates. Use this to discover what tests are available before querying specific labs.
    """
    from health_memex.analysis.lab_trends import get_available_tests

    return get_available_tests(_get_db())


@mcp.tool()
def get_abnormal_labs_tool(
    start_date: str = "",
    end_date: str = "",
) -> list[dict]:
    """Get all lab results flagged as abnormal (H, L, HH, LL, A, etc.).

    Returns results with non-empty interpretation flags, useful for identifying
    out-of-range values across all tests and sources.

    Args:
        start_date: ISO date, results on or after.
        end_date: ISO date, results on or before.
    """
    from health_memex.analysis.lab_trends import get_abnormal_labs

    return get_abnormal_labs(
        _get_db(),
        start_date=start_date,
        end_date=end_date,
    )


@mcp.tool()
def get_medications(status: str = "") -> list[dict]:
    """Get medications, optionally filtered by status.

    Args:
        status: Filter by status: "active", "completed", "stopped", etc. Empty = all.
    """
    from health_memex.analysis.medications import get_medication_list

    return get_medication_list(_get_db(), status=status or None)


@mcp.tool()
def reconcile_medications_tool() -> dict:
    """Cross-source medication reconciliation.

    Compares medications across all sources and identifies discrepancies where the
    same medication has different statuses (e.g., "active" in Epic but "completed" in
    MEDITECH). Returns active medications and a list of discrepancies with per-source details.
    """
    from health_memex.analysis.medications import reconcile_medications

    return reconcile_medications(_get_db())


@mcp.tool()
def search_notes(
    query_text: str = "",
    note_type: str = "",
    start_date: str = "",
    end_date: str = "",
) -> list[dict]:
    """Search clinical notes by text content, type, and date range.

    When query_text is provided, uses FTS5 full-text matching (porter stemmer +
    unicode61 tokenizer). FTS5 query syntax is supported:
      - "diabetes" -> matches diabetic, diabetes, etc. (stemmed)
      - "left breast" -> phrase (token sequence)
      - "CEA AND elevated" -> boolean operators
      - "renal NEAR/5 function" -> proximity

    Without query_text, lists all notes matching the type/date filters.
    Archived notes are excluded.

    Args:
        query_text: FTS5 query. Empty = no text filter.
        note_type: Filter by note type (e.g., "Progress Notes", "H&P").
        start_date: ISO date, notes on or after.
        end_date: ISO date, notes on or before.
    """
    clauses = ["n.archived_at IS NULL"]
    params: list = []
    joins = ""

    if query_text:
        # FTS5 MATCH must reference the virtual table by its canonical name,
        # not an alias — SQLite does not resolve aliases inside MATCH.
        joins = " JOIN clinical_notes_fts ON n.id = clinical_notes_fts.rowid"
        clauses.append("clinical_notes_fts MATCH ?")
        params.append(query_text)

    if note_type:
        clauses.append("LOWER(n.note_type) LIKE ?")
        params.append(f"%{note_type.lower()}%")
    if start_date:
        clauses.append("n.note_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("n.note_date <= ?")
        params.append(end_date)

    where = " AND ".join(clauses)
    return _get_db().query(
        f"SELECT n.id, n.note_type, n.author, n.note_date, "
        f"SUBSTR(n.content, 1, 500) AS content_preview, n.source "
        f"FROM clinical_notes n{joins} WHERE {where} ORDER BY n.note_date DESC",
        tuple(params),
    )


@mcp.tool()
def get_pathology_report(
    report_id: int = 0,
    report_date: str = "",
    specimen: str = "",
) -> list[dict]:
    """Get pathology report(s) by ID, date, or specimen.

    Archived reports are excluded.

    Args:
        report_id: Specific report ID.
        report_date: ISO date to filter by.
        specimen: Partial match on specimen description.
    """
    clauses = ["archived_at IS NULL"]
    params: list = []
    if report_id:
        clauses.append("id = ?")
        params.append(report_id)
    if report_date:
        clauses.append("report_date = ?")
        params.append(report_date)
    if specimen:
        clauses.append("LOWER(specimen) LIKE ?")
        params.append(f"%{specimen.lower()}%")
    where = " AND ".join(clauses)
    return _get_db().query(
        f"SELECT * FROM pathology_reports WHERE {where} ORDER BY report_date DESC",
        tuple(params),
    )


@mcp.tool()
def search_pathology_fts(
    query: str,
    start_date: str = "",
    end_date: str = "",
    limit: int = 20,
) -> list[dict]:
    """Full-text search of pathology reports via FTS5.

    Indexed columns: diagnosis, gross_description, microscopic_description,
    staging, margins, lymph_nodes, full_text. Use column filters in the query
    to scope: 'diagnosis:adenocarcinoma', 'staging:pT3 OR staging:T3',
    'margins:positive NEAR/5 inked'.

    Archived reports are excluded. Results ordered by FTS5 rank (BM25).

    Args:
        query: FTS5 query (e.g., 'adenocarcinoma', '"signet ring"', 'her2 AND positive').
        start_date: ISO date, reports on or after.
        end_date: ISO date, reports on or before.
        limit: Max rows to return (default 20).
    """
    clauses = ["p.archived_at IS NULL", "pathology_fts MATCH ?"]
    params: list = [query]
    if start_date:
        clauses.append("p.report_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("p.report_date <= ?")
        params.append(end_date)
    params.append(limit)
    where = " AND ".join(clauses)
    return _get_db().query(
        f"SELECT p.id, p.source, p.report_date, p.specimen, p.diagnosis, "
        f"SUBSTR(p.full_text, 1, 500) AS full_text_preview, "
        f"bm25(pathology_fts) AS rank "
        f"FROM pathology_reports p JOIN pathology_fts ON p.id = pathology_fts.rowid "
        f"WHERE {where} ORDER BY rank LIMIT ?",
        tuple(params),
    )


@mcp.tool()
def search_imaging_fts(
    query: str,
    modality: str = "",
    start_date: str = "",
    end_date: str = "",
    limit: int = 20,
) -> list[dict]:
    """Full-text search of imaging reports via FTS5.

    Indexed columns: findings, impression, full_text. Scope with column
    filters: 'impression:nodule', 'findings:"no evidence of"'.

    Archived reports are excluded. Results ordered by FTS5 rank.

    Args:
        query: FTS5 query.
        modality: Optional modality filter (CT, MRI, US, etc.).
        start_date: ISO date, studies on or after.
        end_date: ISO date, studies on or before.
        limit: Max rows to return (default 20).
    """
    clauses = ["i.archived_at IS NULL", "imaging_fts MATCH ?"]
    params: list = [query]
    if modality:
        clauses.append("i.modality = ?")
        params.append(modality)
    if start_date:
        clauses.append("i.study_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("i.study_date <= ?")
        params.append(end_date)
    params.append(limit)
    where = " AND ".join(clauses)
    return _get_db().query(
        f"SELECT i.id, i.source, i.study_name, i.modality, i.study_date, "
        f"SUBSTR(i.impression, 1, 300) AS impression_preview, "
        f"SUBSTR(i.findings, 1, 300) AS findings_preview, "
        f"bm25(imaging_fts) AS rank "
        f"FROM imaging_reports i JOIN imaging_fts ON i.id = imaging_fts.rowid "
        f"WHERE {where} ORDER BY rank LIMIT ?",
        tuple(params),
    )


@mcp.tool()
def get_visit_diff(since_date: str) -> dict:
    """Get everything new since a given date across all clinical data types.

    Returns new labs, imaging, pathology, medication changes, notes, conditions,
    encounters, and procedures since the specified date. Useful for "what's changed
    since my last visit?" queries.

    Args:
        since_date: ISO date (YYYY-MM-DD). Returns records on or after this date.
    """
    from health_memex.analysis.visit_diff import visit_diff

    return visit_diff(_get_db(), since_date)


@mcp.tool()
def get_visit_prep(
    visit_date: str = "",
    lookback_months: int = 3,
) -> dict:
    """Generate a visit preparation summary with recent data and outstanding issues.

    Args:
        visit_date: Upcoming visit date (ISO). Defaults to today.
        lookback_months: How many months of history to include (default 3).
    """
    from health_memex.analysis.visit_prep import generate_visit_prep

    return generate_visit_prep(_get_db(), visit_date=visit_date, lookback_months=lookback_months)


@mcp.tool()
def get_visit_prep_bundle(
    visit_date: str = "",
    lookback_months: int = 6,
    key_test_readings: int = 8,
    include_analyses: bool = True,
    include_notes: bool = True,
) -> dict:
    """Get a comprehensive visit preparation context bundle in a single call.

    Returns a structured dict with all data sections for LLM-driven visit prep:
    lab_trends (key tests with last N readings), new_labs, recent_imaging (full
    impressions + findings), recent_notes (full content), active_medications,
    active_conditions, recent_procedures, saved_notes, saved_analyses, and
    treatment_context_note (auto-identified comprehensive oncology note).

    The LLM receives everything it needs for interactive visit preparation
    without follow-up queries. Health Memex assembles; the LLM reasons.

    Args:
        visit_date: Upcoming visit date (ISO). Defaults to today.
        lookback_months: Months of history to include (default 6).
        key_test_readings: Number of trend readings per key test (default 8).
        include_analyses: Include saved analysis documents (default True).
        include_notes: Include saved personal notes (default True).
    """
    from health_memex.analysis.visit_prep import generate_visit_prep_bundle

    config_path = os.environ.get("HEALTH_MEMEX_CONFIG", "")
    return generate_visit_prep_bundle(
        _get_db(),
        visit_date=visit_date,
        lookback_months=lookback_months,
        key_test_readings=key_test_readings,
        include_analyses=include_analyses,
        include_notes=include_notes,
        config_path=config_path,
    )


@mcp.tool()
def get_surgical_timeline(
    pre_op_imaging_days: int = 90,
    post_op_imaging_days: int = 30,
    limit: int = 10,
    offset: int = 0,
    include_full_text: bool = False,
) -> list[dict]:
    """Get the complete surgical timeline with linked pathology, imaging, and medications.

    Each procedure includes linked pathology report (within 30 days), related imaging
    (with pre-op/post-op timing annotation), and medications active around the procedure.

    Results are paginated by procedure. Use limit/offset to page through results.
    Set include_full_text=True to include full pathology report text (can be very large).

    Args:
        pre_op_imaging_days: Days before procedure to search for related imaging (default 90).
        post_op_imaging_days: Days after procedure to search for related imaging (default 30).
        limit: Max procedures to return (default 10, 0 = all).
        offset: Number of procedures to skip (default 0).
        include_full_text: Include full pathology report text (default False).
    """
    from health_memex.analysis.surgical_timeline import build_surgical_timeline

    return build_surgical_timeline(
        _get_db(),
        pre_op_imaging_days=pre_op_imaging_days,
        post_op_imaging_days=post_op_imaging_days,
        limit=limit,
        offset=offset,
        include_full_text=include_full_text,
    )


@mcp.tool()
def match_cross_source_encounters(tolerance_days: int = 0) -> list[dict]:
    """Find encounters that occurred on the same date across different EHR sources.

    Identifies cases where the same visit generated records in multiple systems
    (e.g., a surgery at Anderson with follow-up notes in athenahealth). Each match
    includes the date and the list of encounters from different sources.

    Args:
        tolerance_days: How many days apart encounters can be to count as a match.
            0 = exact same date (default), 1 = within 1 day, etc.
    """
    from health_memex.analysis.cross_source import match_encounters_by_date as _match

    return _match(_get_db(), tolerance_days=tolerance_days)


@mcp.tool()
def get_data_quality_report() -> dict:
    """Check data quality: cross-source duplicates, source coverage matrix.

    Returns potential duplicate labs (same test + same date + different source),
    a source coverage matrix showing which tables have data from which sources,
    and summary counts. Use this before analysis to understand data completeness
    and potential issues.
    """
    from health_memex.analysis.data_quality import get_data_quality

    return get_data_quality(_get_db())


@mcp.tool()
def get_clinical_summary_tool(
    include_notes: bool = False,
    include_family_history: bool = True,
    recent_days: int = 180,
) -> dict:
    """Get the complete clinical picture in a single call.

    Returns active conditions, all conditions history, allergies, active and
    historical medications, recent labs (with abnormal flagged separately),
    recent vitals, all imaging (recent with impressions, older with previews),
    procedures, pathology reports, and recent encounters.

    Set include_notes=True to get full clinical note text (can be large).
    Default returns note previews (300 chars) to save context space.

    Args:
        include_notes: Include full clinical note text (default False = 300-char preview).
        include_family_history: Include family history (default True).
        recent_days: How many days back for "recent" data (default 180).
    """
    from health_memex.analysis.clinical_summary import get_clinical_summary

    return get_clinical_summary(
        _get_db(),
        include_notes=include_notes,
        include_family_history=include_family_history,
        recent_labs_days=recent_days,
    )


@mcp.tool()
def get_timeline(
    start_date: str = "",
    end_date: str = "",
    include_notes: bool = False,
    include_labs: bool = True,
) -> list[dict]:
    """Get a unified chronological timeline of all clinical events.

    Merges encounters, procedures, imaging, pathology, labs, and notes into
    a single date-sorted list. Each event has: date, type, source, summary,
    and type-specific detail.

    Labs are grouped by (date, source) to avoid flooding — each group shows
    total count, abnormal count, and individual results.

    Args:
        start_date: ISO date, events on or after (default: all).
        end_date: ISO date, events on or before (default: all).
        include_notes: Include full clinical note text (default False = 300-char preview).
        include_labs: Include lab results in timeline (default True).
    """
    from health_memex.analysis.timeline import get_clinical_timeline

    return get_clinical_timeline(
        _get_db(),
        start_date=start_date or None,
        end_date=end_date or None,
        include_notes=include_notes,
        include_labs=include_labs,
    )


@mcp.tool()
def write_record(
    table: str,
    data: dict,
) -> dict:
    """Insert or update a clinical record (UPSERT by natural key).

    If a row with the same natural key already exists, it is updated. Otherwise
    a new row is inserted. The 'source' column is required. All natural-key
    columns for the target table must be present in data.

    Supported tables: encounters, lab_results, vitals, medications, conditions,
    procedures, pathology_reports, imaging_reports, clinical_notes, immunizations,
    allergies, social_history, family_history, mental_status, genetic_variants.

    Args:
        table: Target table name.
        data: Dict of column_name → value. Must include 'source' and all
            natural-key columns for the table.
    """
    WRITABLE_TABLES = {
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
        "genetic_variants",
        "mental_status",
    }
    if table not in WRITABLE_TABLES:
        return {"error": f"Table '{table}' is not writable. Allowed: {sorted(WRITABLE_TABLES)}"}
    if not data.get("source"):
        return {"error": "Record must include a 'source' field."}

    unique_cols = _UNIQUE_KEYS[table]
    missing_nk = [c for c in unique_cols if c not in data]
    if missing_nk:
        return {
            "error": (
                f"Record is missing natural-key columns for {table}: {missing_nk}. "
                f"UPSERT requires all of: {list(unique_cols)}"
            )
        }

    db = _get_db()
    try:
        # Validate column names against the live schema to prevent SQL injection.
        valid_cols = {row[1] for row in db.conn.execute(f"PRAGMA table_info({table})").fetchall()}
        bad_cols = set(data.keys()) - valid_cols
        if bad_cols:
            return {"error": f"Invalid column(s) for {table}: {sorted(bad_cols)}"}

        # Determine created vs updated by probing for an existing row by
        # natural key before the UPSERT fires.
        nk_where = " AND ".join(f"{c} = ?" for c in unique_cols)
        nk_values = tuple(data[c] for c in unique_cols)
        existing = db.conn.execute(f"SELECT id FROM {table} WHERE {nk_where}", nk_values).fetchone()

        # Inject the durable content-hash unique_id at write time, the same
        # way load_source does. Without it a write_record row gets unique_id
        # = NULL and is unresolvable by the federation's content-hash URI
        # until the next init_schema backfill (a whole-session window).
        data = {**data, "unique_id": _compute_unique_id(table, data)}

        columns = list(data.keys())
        values = [data[c] for c in columns]
        sql = _build_upsert_sql(table, columns, unique_cols)
        cursor = db.conn.execute(sql, values)
        db.conn.commit()

        if existing:
            return {"id": existing[0], "table": table, "status": "updated"}
        return {"id": cursor.lastrowid, "table": table, "status": "created"}
    except sqlite3.IntegrityError as e:
        return {"error": f"Integrity error: {e}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_source_files(
    table_name: str = "",
    record_id: int = 0,
    encounter_date: str = "",
    source: str = "",
    asset_type: str = "",
) -> list[dict]:
    """Find source files (PDFs, images, etc.) linked to clinical records.

    Returns source assets matching the criteria. You can search by:
    - table_name + record_id: Assets linked to a specific clinical record
    - encounter_date: Assets from a specific encounter date
    - source: Assets from a specific EHR source
    - asset_type: Filter by file type (pdf, png, html, etc.)

    Args:
        table_name: Clinical table name (e.g., "lab_results", "procedures").
        record_id: Record ID in the table.
        encounter_date: ISO date to filter by.
        source: Filter by source (e.g., "epic_anderson", "meditech_anderson").
        asset_type: Filter by asset type (e.g., "pdf", "png").
    """
    clauses = []
    params: list = []
    if table_name:
        clauses.append("ref_table = ?")
        params.append(table_name)
    if record_id:
        clauses.append("ref_id = ?")
        params.append(record_id)
    if encounter_date:
        clauses.append("encounter_date = ?")
        params.append(encounter_date)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if asset_type:
        clauses.append("asset_type = ?")
        params.append(asset_type)
    where = " AND ".join(clauses) if clauses else "1=1"
    return _get_db().query(
        f"SELECT id, source, ref_table, ref_id, encounter_date, "
        f"file_name, asset_type, file_size_kb "
        f"FROM source_assets WHERE {where} ORDER BY encounter_date DESC",
        tuple(params),
    )


@mcp.tool()
def get_asset_summary() -> list[dict]:
    """Get a summary of source assets (PDFs, images, etc.) by source and type.

    Returns counts and total sizes grouped by source and asset type, plus a
    grand total. Use this to understand what non-parsed source files are available
    in the database.
    """
    return _get_db().query(
        "SELECT source, asset_type, COUNT(*) as count, "
        "SUM(file_size_kb) as total_kb "
        "FROM source_assets GROUP BY source, asset_type ORDER BY source, asset_type"
    )


# ---------------------------------------------------------------------------
# Personal notes (CRUD)
# ---------------------------------------------------------------------------


@mcp.tool()
def save_note(
    title: str,
    content: str,
    tags: str = "",
    ref_table: str = "",
    ref_id: int = 0,
    note_id: int = 0,
) -> dict:
    """Save a personal note (analysis, observation, visit prep summary).

    Creates a new note if note_id is 0, or updates an existing note if note_id > 0.
    Notes can be tagged for easy retrieval and optionally linked to a clinical record.

    Args:
        title: Short descriptive title for the note.
        content: Full markdown content of the note.
        tags: Comma-separated tags, e.g. "visit-prep,oncology,cea-trend".
        ref_table: Optional clinical table to link to (e.g. "lab_results", "encounters").
        ref_id: Optional row ID in ref_table to link to.
        note_id: 0 to create new, or existing note ID to update.
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    saved_id = _get_db().save_note(
        title=title,
        content=content,
        tags=tag_list,
        ref_table=ref_table or None,
        ref_id=ref_id or None,
        note_id=note_id or None,
    )
    return {"id": saved_id, "status": "updated" if note_id else "created"}


@mcp.tool()
def search_notes_personal(
    query: str = "",
    tag: str = "",
    ref_table: str = "",
    ref_id: int = 0,
) -> list[dict]:
    """Search personal notes by text, tag, or linked clinical record.

    All parameters are optional and combined with AND when multiple are provided.

    Args:
        query: Text to search for in title and content (case-insensitive).
        tag: Filter by exact tag match.
        ref_table: Filter by linked clinical table name.
        ref_id: Filter by linked clinical record ID.
    """
    return _get_db().search_notes_personal(
        query=query or None,
        tag=tag or None,
        ref_table=ref_table or None,
        ref_id=ref_id or None,
    )


@mcp.tool()
def get_note(note_id: int) -> dict | str:
    """Retrieve a personal note by ID, including full content and tags.

    Args:
        note_id: The ID of the note to retrieve.
    """
    result = _get_db().get_note(note_id)
    if result is None:
        return f"Note {note_id} not found."
    return result


@mcp.tool()
def delete_note(note_id: int, hard: bool = False) -> dict:
    """Delete a personal note by ID.

    By default performs a soft delete (sets archived_at). The note is hidden
    from reads but URI references from clinical records and trails remain
    valid. Pass hard=True to permanently remove the row.

    Args:
        note_id: The ID of the note to delete.
        hard: If True, permanently delete instead of archiving (default False).
    """
    return {"deleted": _get_db().delete_note(note_id, hard=hard), "hard": hard}


# ---------------------------------------------------------------------------
# Structured analyses (CRUD)
# ---------------------------------------------------------------------------


@mcp.tool()
def save_analysis(
    slug: str,
    title: str,
    content: str,
    category: str = "",
    summary: str = "",
    tags: str = "",
    source: str = "claude",
    frontmatter_yaml: str = "",
) -> dict:
    """Save a structured analysis document (upsert by slug).

    Analyses are long-form medical analysis documents with optional YAML frontmatter
    metadata. If a slug already exists, it is updated. The frontmatter is stored as
    a JSON blob for json_extract() queries.

    Args:
        slug: Unique identifier derived from filename (e.g., "cancer-timeline").
        title: Display title for the analysis.
        content: Full markdown content of the analysis.
        category: Category for grouping (e.g., "oncology", "timeline").
        summary: Short description/summary.
        tags: Comma-separated tags, e.g. "cancer,CEA,surgery".
        source: Author source, e.g. "claude", "user".
        frontmatter_yaml: Optional YAML string with additional metadata fields.
            Will be parsed and stored as JSON for json_extract() queries.
    """
    db = _get_db()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    frontmatter_json = None
    if frontmatter_yaml:
        try:
            import yaml

            parsed = yaml.safe_load(frontmatter_yaml)
            frontmatter_json = json.dumps(parsed, default=str) if parsed else None
        except Exception:
            frontmatter_json = frontmatter_yaml  # Store as-is if not valid YAML

    existing_before = db.get_analysis(slug)
    saved_id = db.save_analysis(
        slug=slug,
        title=title,
        content=content,
        frontmatter_json=frontmatter_json,
        category=category or None,
        summary=summary or None,
        tags=tag_list,
        source=source,
    )

    return {"id": saved_id, "slug": slug, "status": "updated" if existing_before else "created"}


@mcp.tool()
def get_analysis(slug: str) -> dict | str:
    """Retrieve a structured analysis by slug, including full content and tags.

    Args:
        slug: The slug of the analysis to retrieve (e.g., "cancer-timeline").
    """
    result = _get_db().get_analysis(slug)
    if result is None:
        return f"Analysis '{slug}' not found."
    return result


@mcp.tool()
def search_analyses(
    query: str = "",
    tag: str = "",
    category: str = "",
) -> list[dict]:
    """Search structured analyses by text, tag, or category.

    All parameters are optional and combined with AND when multiple are provided.

    Args:
        query: Text to search for in title, content, and frontmatter (case-insensitive).
        tag: Filter by exact tag match.
        category: Filter by category (e.g., "oncology", "timeline").
    """
    return _get_db().search_analyses(
        query=query or None,
        tag=tag or None,
        category=category or None,
    )


@mcp.tool()
def list_analyses() -> list[dict]:
    """List all structured analyses with slug, title, category, tags, and dates."""
    return _get_db().list_analyses()


@mcp.tool()
def delete_analysis(slug: str, hard: bool = False) -> dict:
    """Delete a structured analysis by slug.

    By default performs a soft delete (sets archived_at). The analysis is
    hidden from reads but the slug remains reserved until purged. Re-saving
    an archived slug via save_analysis resurrects it. Pass hard=True to
    permanently remove the row (freeing the slug for new content).

    Args:
        slug: The slug of the analysis to delete (e.g., "cancer-timeline").
        hard: If True, permanently delete instead of archiving (default False).
    """
    return {"deleted": _get_db().delete_analysis(slug, hard=hard), "slug": slug, "hard": hard}


# ---------------------------------------------------------------------------
# Soft delete for clinical records
# ---------------------------------------------------------------------------


@mcp.tool()
def archive_record(table: str, record_id: int) -> dict:
    """Soft-delete a clinical record (sets archived_at, hides from reads).

    The row stays in the database so URI references from marginalia and trails
    stay valid. A re-import via load_source will resurrect it if the source
    still contains the record. Use unarchive_record to manually restore, or
    purge_record to permanently remove.

    Args:
        table: Clinical table name (e.g., "lab_results", "encounters").
        record_id: The id column of the row to archive.
    """
    try:
        affected = _get_db().archive_record(table, record_id)
    except ValueError as e:
        return {"error": str(e)}
    return {"archived": affected, "table": table, "id": record_id}


@mcp.tool()
def unarchive_record(table: str, record_id: int) -> dict:
    """Restore a soft-deleted clinical record (clears archived_at).

    Args:
        table: Clinical table name.
        record_id: The id of the previously archived row.
    """
    try:
        affected = _get_db().unarchive_record(table, record_id)
    except ValueError as e:
        return {"error": str(e)}
    return {"unarchived": affected, "table": table, "id": record_id}


@mcp.tool()
def purge_record(table: str, record_id: int) -> dict:
    """Permanently delete a clinical record (hard delete).

    Use with caution: this breaks URI references from marginalia and trails.
    Prefer archive_record for user-driven deletion. Typical use: permanently
    removing an erroneously loaded record.

    Args:
        table: Clinical table name.
        record_id: The id of the row to permanently delete.
    """
    try:
        affected = _get_db().purge_record(table, record_id)
    except ValueError as e:
        return {"error": str(e)}
    return {"purged": affected, "table": table, "id": record_id}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
