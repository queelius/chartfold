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
        "Core tools:\n"
        "- run_sql: Read-only SQL access (connection is read-only at the engine level)\n"
        "- get_schema: CREATE TABLE statements for query planning\n"
        "- get_database_summary: Table counts and load history — start here\n\n"
        "Personal notes (CRUD):\n"
        "- save_note / get_note / search_notes_personal / delete_note\n\n"
        "Structured analyses (CRUD):\n"
        "- save_analysis / get_analysis / search_analyses / list_analyses / delete_analysis\n\n"
        "The database is read-only via run_sql. All writes go through the "
        "dedicated note/analysis tools. Start with get_database_summary to "
        "understand available data, then get_schema for column details."
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
