"""MCP server for chartfold — Claude queries patient data via SQL tools.

Run with: python -m chartfold.mcp.server
Configure env: CHARTFOLD_DB=/path/to/chartfold.db
"""

from __future__ import annotations

import json
import os
import sqlite3

from mcp.server.fastmcp import FastMCP

from chartfold.db import ChartfoldDB

DB_PATH = os.environ.get("CHARTFOLD_DB", "chartfold.db")

mcp = FastMCP(
    "chartfold",
    instructions=(
        "Patient clinical data server with unified SQLite database containing records "
        "from Epic, MEDITECH, and athenahealth sources.\n\n"
        "Key capabilities:\n"
        "- run_sql / get_schema: Direct SQL access (read-only)\n"
        "- query_labs / get_lab_series_tool: Lab results per-source or unified cross-source series\n"
        "- get_available_tests: Discover what tests exist in the database\n"
        "- get_abnormal_labs: All flagged-abnormal lab results\n"
        "- get_medications / reconcile_medications_tool: Medication list and cross-source reconciliation\n"
        "- get_timeline: Unified event timeline (encounters, procedures, imaging, labs, pathology)\n"
        "- get_visit_diff: Everything new since a given date\n"
        "- get_visit_prep: Pre-appointment summary\n"
        "- get_surgical_timeline: Procedures linked to pathology, imaging, and medications\n"
        "- match_cross_source_encounters: Same-day encounters across different EHR systems\n"
        "- get_data_quality_report: Duplicate labs and source coverage matrix\n"
        "- get_database_summary: Table counts and load history\n"
        "- search_notes / get_pathology_report: Full-text clinical note search and pathology lookup\n"
        "- get_source_files / get_asset_summary: Find source files (PDFs, images) linked to records\n\n"
        "- save_note / get_note / search_notes_personal / delete_note: Persist and retrieve personal analyses, observations, and visit prep summaries\n"
        "- save_analysis / get_analysis / search_analyses / list_analyses / delete_analysis: Manage structured analysis documents with YAML frontmatter metadata\n\n"
        "Start with get_database_summary or get_schema to understand available data. "
        "Use get_data_quality_report before cross-source analysis to understand duplicates. "
        "Use save_note to persist important analyses or observations for future reference."
    ),
)


def _get_db() -> ChartfoldDB:
    db = ChartfoldDB(DB_PATH)
    db.init_schema()
    return db


def _readonly_query(query: str) -> list[dict] | str:
    """Execute a query against a read-only SQLite connection.

    Uses SQLite's URI mode=ro for engine-level read-only enforcement.
    Also blocks ATTACH/DETACH since those can open writable databases
    even through a read-only connection.
    """
    # Block ATTACH/DETACH — these bypass read-only mode by opening new databases
    upper = query.strip().upper()
    if any(kw in upper for kw in ("ATTACH", "DETACH")):
        return "Error: ATTACH/DETACH statements are not allowed."

    db_path = DB_PATH
    conn = None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError as e:
        if "readonly" in str(e).lower() or "attempt to write" in str(e).lower():
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
    """Execute a read-only SQL query against the chartfold database.

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
    try:
        summary = db.summary()
        sources = db.sources()
        return {"table_counts": summary, "load_history": sources}
    finally:
        db.close()


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
    db = _get_db()
    try:
        from chartfold.analysis.lab_trends import query_lab_results

        return query_lab_results(
            db,
            test_name=test_name or None,
            loinc=loinc or None,
            start_date=start_date or None,
            end_date=end_date or None,
        )
    finally:
        db.close()


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
    db = _get_db()
    try:
        from chartfold.analysis.lab_trends import get_lab_series

        return get_lab_series(
            db,
            test_name=test_name or None,
            loinc=loinc or None,
            start_date=start_date or None,
            end_date=end_date or None,
        )
    finally:
        db.close()


@mcp.tool()
def get_available_tests_tool() -> list[dict]:
    """List all lab tests in the database with frequency and date range.

    Returns each test's name, result count, which sources have it, and earliest/latest
    result dates. Use this to discover what tests are available before querying specific labs.
    """
    db = _get_db()
    try:
        from chartfold.analysis.lab_trends import get_available_tests

        return get_available_tests(db)
    finally:
        db.close()


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
    db = _get_db()
    try:
        from chartfold.analysis.lab_trends import get_abnormal_labs

        return get_abnormal_labs(
            db,
            start_date=start_date or None,
            end_date=end_date or None,
        )
    finally:
        db.close()


@mcp.tool()
def get_medications(status: str = "") -> list[dict]:
    """Get medications, optionally filtered by status.

    Args:
        status: Filter by status: "active", "completed", "stopped", etc. Empty = all.
    """
    db = _get_db()
    try:
        from chartfold.analysis.medications import get_medications as _get_meds

        return _get_meds(db, status=status or None)
    finally:
        db.close()


@mcp.tool()
def reconcile_medications_tool() -> dict:
    """Cross-source medication reconciliation.

    Compares medications across all sources and identifies discrepancies where the
    same medication has different statuses (e.g., "active" in Epic but "completed" in
    MEDITECH). Returns active medications and a list of discrepancies with per-source details.
    """
    db = _get_db()
    try:
        from chartfold.analysis.medications import reconcile_medications

        return reconcile_medications(db)
    finally:
        db.close()


@mcp.tool()
def get_timeline(
    start_date: str = "",
    end_date: str = "",
    event_types: str = "",
) -> list[dict]:
    """Get a unified event timeline across all sources.

    Args:
        start_date: ISO date filter.
        end_date: ISO date filter.
        event_types: Comma-separated types to include: encounters, labs, procedures,
            imaging, pathology. Empty = all types.
    """
    db = _get_db()
    try:
        from chartfold.analysis.visit_diff import get_timeline as _get_timeline

        types = [t.strip() for t in event_types.split(",") if t.strip()] if event_types else None
        return _get_timeline(
            db,
            start_date=start_date or None,
            end_date=end_date or None,
            event_types=types,
        )
    finally:
        db.close()


@mcp.tool()
def search_notes(
    query_text: str = "",
    note_type: str = "",
    start_date: str = "",
    end_date: str = "",
) -> list[dict]:
    """Search clinical notes by text content, type, and date range.

    Args:
        query_text: Text to search for within note content (case-insensitive).
        note_type: Filter by note type (e.g., "Progress Notes", "H&P").
        start_date: ISO date, notes on or after.
        end_date: ISO date, notes on or before.
    """
    db = _get_db()
    try:
        clauses = []
        params: list = []
        if query_text:
            clauses.append("LOWER(content) LIKE ?")
            params.append(f"%{query_text.lower()}%")
        if note_type:
            clauses.append("LOWER(note_type) LIKE ?")
            params.append(f"%{note_type.lower()}%")
        if start_date:
            clauses.append("note_date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("note_date <= ?")
            params.append(end_date)
        where = " AND ".join(clauses) if clauses else "1=1"
        rows = db.query(
            f"SELECT id, note_type, author, note_date, "
            f"SUBSTR(content, 1, 500) AS content_preview, source "
            f"FROM clinical_notes WHERE {where} ORDER BY note_date DESC",
            tuple(params),
        )
        return rows
    finally:
        db.close()


@mcp.tool()
def get_pathology_report(
    report_id: int = 0,
    report_date: str = "",
    specimen: str = "",
) -> list[dict]:
    """Get pathology report(s) by ID, date, or specimen.

    Args:
        report_id: Specific report ID.
        report_date: ISO date to filter by.
        specimen: Partial match on specimen description.
    """
    db = _get_db()
    try:
        clauses = []
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
        where = " AND ".join(clauses) if clauses else "1=1"
        return db.query(
            f"SELECT * FROM pathology_reports WHERE {where} ORDER BY report_date DESC",
            tuple(params),
        )
    finally:
        db.close()


@mcp.tool()
def get_visit_diff(since_date: str) -> dict:
    """Get everything new since a given date across all clinical data types.

    Returns new labs, imaging, pathology, medication changes, notes, conditions,
    encounters, and procedures since the specified date. Useful for "what's changed
    since my last visit?" queries.

    Args:
        since_date: ISO date (YYYY-MM-DD). Returns records on or after this date.
    """
    db = _get_db()
    try:
        from chartfold.analysis.visit_diff import visit_diff

        return visit_diff(db, since_date)
    finally:
        db.close()


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
    db = _get_db()
    try:
        from chartfold.analysis.visit_prep import visit_prep

        return visit_prep(db, visit_date=visit_date or None, lookback_months=lookback_months)
    finally:
        db.close()


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
    db = _get_db()
    try:
        from chartfold.analysis.surgical_timeline import build_surgical_timeline

        return build_surgical_timeline(
            db,
            pre_op_imaging_days=pre_op_imaging_days,
            post_op_imaging_days=post_op_imaging_days,
            limit=limit,
            offset=offset,
            include_full_text=include_full_text,
        )
    finally:
        db.close()


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
    db = _get_db()
    try:
        from chartfold.analysis.cross_source import match_cross_source_encounters as _match

        return _match(db, tolerance_days=tolerance_days)
    finally:
        db.close()


@mcp.tool()
def get_data_quality_report() -> dict:
    """Check data quality: cross-source duplicates, source coverage matrix.

    Returns potential duplicate labs (same test + same date + different source),
    a source coverage matrix showing which tables have data from which sources,
    and summary counts. Use this before analysis to understand data completeness
    and potential issues.
    """
    db = _get_db()
    try:
        from chartfold.analysis.data_quality import data_quality_report

        return data_quality_report(db)
    finally:
        db.close()


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
    db = _get_db()
    try:
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
        return db.query(
            f"SELECT id, source, ref_table, ref_id, encounter_date, "
            f"filename, asset_type, LENGTH(data) as size_bytes "
            f"FROM source_assets WHERE {where} ORDER BY encounter_date DESC",
            tuple(params),
        )
    finally:
        db.close()


@mcp.tool()
def get_asset_summary() -> list[dict]:
    """Get a summary of source assets (PDFs, images, etc.) by source and type.

    Returns counts and total sizes grouped by source and asset type, plus a
    grand total. Use this to understand what non-parsed source files are available
    in the database.
    """
    db = _get_db()
    try:
        return db.query(
            "SELECT source, asset_type, COUNT(*) as count, "
            "SUM(LENGTH(data)) as total_bytes "
            "FROM source_assets GROUP BY source, asset_type ORDER BY source, asset_type"
        )
    finally:
        db.close()


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
    db = _get_db()
    try:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        saved_id = db.save_note(
            title=title,
            content=content,
            tags=tag_list,
            ref_table=ref_table or None,
            ref_id=ref_id or None,
            note_id=note_id or None,
        )
        return {"id": saved_id, "status": "updated" if note_id else "created"}
    finally:
        db.close()


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
    db = _get_db()
    try:
        return db.search_notes_personal(
            query=query or None,
            tag=tag or None,
            ref_table=ref_table or None,
            ref_id=ref_id or None,
        )
    finally:
        db.close()


@mcp.tool()
def get_note(note_id: int) -> dict | str:
    """Retrieve a personal note by ID, including full content and tags.

    Args:
        note_id: The ID of the note to retrieve.
    """
    db = _get_db()
    try:
        result = db.get_note(note_id)
        if result is None:
            return f"Note {note_id} not found."
        return result
    finally:
        db.close()


@mcp.tool()
def delete_note(note_id: int) -> dict:
    """Delete a personal note by ID.

    Args:
        note_id: The ID of the note to delete.
    """
    db = _get_db()
    try:
        deleted = db.delete_note(note_id)
        return {"deleted": deleted}
    finally:
        db.close()


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
    try:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        frontmatter_json = None
        if frontmatter_yaml:
            try:
                import yaml

                parsed = yaml.safe_load(frontmatter_yaml)
                # json.dumps with default=str handles YAML date objects
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
    finally:
        db.close()


@mcp.tool()
def get_analysis(slug: str) -> dict | str:
    """Retrieve a structured analysis by slug, including full content and tags.

    Args:
        slug: The slug of the analysis to retrieve (e.g., "cancer-timeline").
    """
    db = _get_db()
    try:
        result = db.get_analysis(slug)
        if result is None:
            return f"Analysis '{slug}' not found."
        return result
    finally:
        db.close()


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
    db = _get_db()
    try:
        return db.search_analyses(
            query=query or None,
            tag=tag or None,
            category=category or None,
        )
    finally:
        db.close()


@mcp.tool()
def list_analyses() -> list[dict]:
    """List all structured analyses with slug, title, category, tags, and dates."""
    db = _get_db()
    try:
        return db.list_analyses()
    finally:
        db.close()


@mcp.tool()
def delete_analysis(slug: str) -> dict:
    """Delete a structured analysis by slug.

    Args:
        slug: The slug of the analysis to delete (e.g., "cancer-timeline").
    """
    db = _get_db()
    try:
        deleted = db.delete_analysis(slug)
        return {"deleted": deleted, "slug": slug}
    finally:
        db.close()


def main():
    mcp.run()


if __name__ == "__main__":
    main()
