"""MCP server for chartfold — Claude queries patient data via SQL tools.

Run with: python -m chartfold.mcp.server
Configure env: CHARTFOLD_DB=/path/to/chartfold.db
"""

from __future__ import annotations

import os
import re

from mcp.server.fastmcp import FastMCP

from chartfold.analysis.cross_source import match_encounters_by_date
from chartfold.analysis.data_quality import get_data_quality
from chartfold.analysis.lab_trends import (
    get_abnormal_labs,
    get_available_tests,
    get_lab_series,
    get_lab_trend,
)
from chartfold.analysis.medications import reconcile_medications
from chartfold.analysis.surgical_timeline import build_surgical_timeline
from chartfold.analysis.visit_diff import visit_diff
from chartfold.analysis.visit_prep import generate_visit_prep
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
        "- save_note / get_note / search_notes_personal / delete_note: "
        "Persist and retrieve personal analyses, observations, and visit prep summaries\n\n"
        "Start with get_database_summary or get_schema to understand available data. "
        "Use get_data_quality_report before cross-source analysis to understand duplicates. "
        "Use save_note to persist important analyses or observations for future reference."
    ),
)


def _get_db() -> ChartfoldDB:
    db = ChartfoldDB(DB_PATH)
    db.init_schema()
    return db


@mcp.tool()
def run_sql(query: str) -> list[dict] | str:
    """Execute a read-only SQL query against the chartfold database.

    Only SELECT statements are allowed. Returns results as a list of dicts.

    Key tables: patients, documents, encounters, lab_results, vitals,
    medications, conditions, procedures, pathology_reports, imaging_reports,
    clinical_notes, immunizations, allergies, social_history, family_history,
    mental_status, load_log.

    Lab results have both `value` (TEXT) and `value_numeric` (REAL, NULL if not parseable).
    Every table has `source` column for cross-source queries.
    """
    # Safety: only allow SELECT
    cleaned = query.strip().upper()
    if (
        not cleaned.startswith("SELECT")
        and not cleaned.startswith("PRAGMA")
        and not cleaned.startswith("WITH")
    ):
        return "Error: Only SELECT/WITH/PRAGMA statements are allowed."

    # Block dangerous patterns
    dangerous = re.search(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH)\b",
        cleaned,
    )
    if dangerous:
        return f"Error: {dangerous.group()} statements are not allowed."

    db = _get_db()
    try:
        return db.query(query)
    except Exception as e:
        return f"SQL Error: {e}"
    finally:
        db.close()


@mcp.tool()
def get_schema() -> str:
    """Get the database schema (CREATE TABLE statements) for query planning."""
    db = _get_db()
    try:
        rows = db.query(
            "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL ORDER BY name"
        )
        return "\n\n".join(r["sql"] for r in rows)
    finally:
        db.close()


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
        return get_lab_trend(
            db,
            test_name=test_name or None,
            test_loinc=loinc or None,
            start_date=start_date,
            end_date=end_date,
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
        return get_lab_series(
            db,
            test_name=test_name or None,
            test_loinc=loinc or None,
            start_date=start_date,
            end_date=end_date,
        )
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
        events = []
        types = [t.strip().lower() for t in event_types.split(",")] if event_types else []

        if not types or "encounters" in types:
            conditions = []
            params = []
            if start_date:
                conditions.append("encounter_date >= ?")
                params.append(start_date)
            if end_date:
                conditions.append("encounter_date <= ?")
                params.append(end_date)
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            for row in db.query(
                f"SELECT encounter_date as date, 'encounter' as type, "
                f"encounter_type as detail, facility, provider, source "
                f"FROM encounters{where} ORDER BY encounter_date",
                tuple(params),
            ):
                events.append(row)

        if not types or "procedures" in types:
            conditions = []
            params = []
            if start_date:
                conditions.append("procedure_date >= ?")
                params.append(start_date)
            if end_date:
                conditions.append("procedure_date <= ?")
                params.append(end_date)
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            for row in db.query(
                f"SELECT procedure_date as date, 'procedure' as type, "
                f"name as detail, facility, provider, source "
                f"FROM procedures{where} ORDER BY procedure_date",
                tuple(params),
            ):
                events.append(row)

        if not types or "imaging" in types:
            conditions = []
            params = []
            if start_date:
                conditions.append("study_date >= ?")
                params.append(start_date)
            if end_date:
                conditions.append("study_date <= ?")
                params.append(end_date)
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            for row in db.query(
                f"SELECT study_date as date, 'imaging' as type, "
                f"study_name as detail, modality as facility, '' as provider, source "
                f"FROM imaging_reports{where} ORDER BY study_date",
                tuple(params),
            ):
                events.append(row)

        if not types or "labs" in types:
            conditions = []
            params = []
            if start_date:
                conditions.append("result_date >= ?")
                params.append(start_date)
            if end_date:
                conditions.append("result_date <= ?")
                params.append(end_date)
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            for row in db.query(
                f"SELECT result_date as date, 'lab' as type, "
                f"test_name || ': ' || value || ' ' || COALESCE(unit, '') as detail, "
                f"'' as facility, '' as provider, source "
                f"FROM lab_results{where} ORDER BY result_date",
                tuple(params),
            ):
                events.append(row)

        if not types or "pathology" in types:
            conditions = []
            params = []
            if start_date:
                conditions.append("report_date >= ?")
                params.append(start_date)
            if end_date:
                conditions.append("report_date <= ?")
                params.append(end_date)
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            for row in db.query(
                f"SELECT report_date as date, 'pathology' as type, "
                f"COALESCE(specimen, '') || ': ' || COALESCE(diagnosis, '') as detail, "
                f"'' as facility, '' as provider, source "
                f"FROM pathology_reports{where} ORDER BY report_date",
                tuple(params),
            ):
                events.append(row)

        events.sort(key=lambda e: e.get("date", ""))
        return events
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
        if report_id:
            return db.query("SELECT * FROM pathology_reports WHERE id = ?", (report_id,))
        conditions = []
        params = []
        if report_date:
            conditions.append("report_date = ?")
            params.append(report_date)
        if specimen:
            conditions.append("LOWER(specimen) LIKE ?")
            params.append(f"%{specimen.lower()}%")
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        return db.query(
            f"SELECT * FROM pathology_reports{where} ORDER BY report_date", tuple(params)
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
        conditions = []
        params = []
        if query_text:
            conditions.append("LOWER(content) LIKE ?")
            params.append(f"%{query_text.lower()}%")
        if note_type:
            conditions.append("LOWER(note_type) LIKE ?")
            params.append(f"%{note_type.lower()}%")
        if start_date:
            conditions.append("note_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("note_date <= ?")
            params.append(end_date)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        return db.query(
            f"SELECT id, note_type, author, note_date, "
            f"SUBSTR(content, 1, 500) as content_preview, source "
            f"FROM clinical_notes{where} ORDER BY note_date DESC",
            tuple(params),
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
        if status:
            return db.query(
                "SELECT name, rxnorm_code, status, sig, route, start_date, stop_date, "
                "prescriber, source FROM medications WHERE LOWER(status) = ? ORDER BY name",
                (status.lower(),),
            )
        return db.query(
            "SELECT name, rxnorm_code, status, sig, route, start_date, stop_date, "
            "prescriber, source FROM medications ORDER BY status, name"
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
        return visit_diff(db, since_date=since_date)
    finally:
        db.close()


@mcp.tool()
def get_visit_prep(visit_date: str = "", lookback_months: int = 3) -> dict:
    """Generate a visit preparation summary with recent data and outstanding issues.

    Args:
        visit_date: Upcoming visit date (ISO). Defaults to today.
        lookback_months: How many months of history to include (default 3).
    """
    db = _get_db()
    try:
        return generate_visit_prep(db, visit_date=visit_date, lookback_months=lookback_months)
    finally:
        db.close()


@mcp.tool()
def get_surgical_timeline(
    pre_op_imaging_days: int = 90,
    post_op_imaging_days: int = 30,
) -> list[dict]:
    """Get the complete surgical timeline with linked pathology, imaging, and medications.

    Each procedure includes linked pathology report (within 30 days), related imaging
    (with pre-op/post-op timing annotation), and medications active around the procedure.

    Args:
        pre_op_imaging_days: Days before procedure to search for related imaging (default 90).
        post_op_imaging_days: Days after procedure to search for related imaging (default 30).
    """
    db = _get_db()
    try:
        return build_surgical_timeline(
            db,
            pre_op_imaging_days=pre_op_imaging_days,
            post_op_imaging_days=post_op_imaging_days,
        )
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
        return get_data_quality(db)
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
        return get_abnormal_labs(db, start_date=start_date, end_date=end_date)
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
        return reconcile_medications(db)
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
        return match_encounters_by_date(db, tolerance_days=tolerance_days)
    finally:
        db.close()


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
        conditions = []
        params = []

        if table_name and record_id:
            conditions.append("(ref_table = ? AND ref_id = ?)")
            params.extend([table_name, record_id])
        if encounter_date:
            conditions.append("encounter_date = ?")
            params.append(encounter_date)
        if source:
            conditions.append("source = ?")
            params.append(source)
        if asset_type:
            conditions.append("asset_type = ?")
            params.append(asset_type)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        return db.query(
            f"SELECT id, source, asset_type, file_path, file_name, file_size_kb, "
            f"title, encounter_date, encounter_id, doc_id "
            f"FROM source_assets{where} ORDER BY encounter_date DESC, file_name",
            tuple(params),
        )
    finally:
        db.close()


@mcp.tool()
def get_asset_summary() -> dict:
    """Get a summary of source assets (PDFs, images, etc.) by source and type.

    Returns counts and total sizes grouped by source and asset type, plus a
    grand total. Use this to understand what non-parsed source files are available
    in the database.
    """
    db = _get_db()
    try:
        by_source_type = db.query("""
            SELECT source, asset_type, COUNT(*) as count, SUM(file_size_kb) as total_kb
            FROM source_assets
            GROUP BY source, asset_type
            ORDER BY source, count DESC
        """)

        total = db.query(
            "SELECT COUNT(*) as count, SUM(file_size_kb) as total_kb FROM source_assets"
        )[0]

        return {
            "by_source_and_type": by_source_type,
            "total_count": total["count"],
            "total_size_kb": total["total_kb"] or 0,
        }
    finally:
        db.close()


def main():
    mcp.run()


if __name__ == "__main__":
    main()
