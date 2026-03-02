"""Generate the system prompt for the AI chat interface embedded in the HTML SPA.

The prompt combines role instructions, the full database schema, summary statistics
queried from the DB, and any current analyses. It is generated at export time and
embedded into the HTML so the LLM has full context about the patient's data.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

# Tables to report record counts for in the summary stats section.
_CLINICAL_TABLES = [
    "patients",
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
    "genetic_variants",
]


def generate_system_prompt(db_path: str) -> str:
    """Generate the full system prompt for the AI chat interface.

    Args:
        db_path: Path to the chartfold SQLite database.

    Returns:
        A multi-section system prompt string with role instructions, schema,
        summary statistics, and current analyses.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        sections = [
            _get_role_instructions(),
            _get_schema_section(),
            _get_summary_stats_section(conn),
            _get_current_analyses_section(conn),
        ]
    finally:
        conn.close()
    return "\n\n".join(s for s in sections if s)


def _get_role_instructions() -> str:
    """Return the role and behavior instructions for the LLM."""
    return (
        "## Role\n\n"
        "You are a medical data analyst helping a patient understand their health records. "
        "You have access to the patient's complete clinical database and can run SQL queries "
        "to answer questions.\n\n"
        "## Guidelines\n\n"
        "- Use only SELECT statements to query the database. Never modify data.\n"
        "- Always cite specific data points (dates, values, sources) in your answers.\n"
        "- Do not provide diagnostic advice or clinical interpretations beyond what is "
        "documented in the records.\n"
        "- When comparing data across sources, note which source each data point comes from.\n"
        "- Present lab trends chronologically and flag any values outside reference ranges.\n"
        "- If asked about something not in the database, say so clearly."
    )


def _get_schema() -> str:
    """Read the database schema SQL from the bundled schema.sql file."""
    schema_path = Path(__file__).parent.parent / "schema.sql"
    return schema_path.read_text()


def _get_schema_section() -> str:
    """Return the schema section of the prompt."""
    schema = _get_schema()
    return f"## Database Schema\n\n```sql\n{schema}\n```"


def _get_summary_stats_section(conn: sqlite3.Connection) -> str:
    """Query the DB for sources, record counts, and date ranges.

    Tries load_log first for source names (most reliable), then falls back
    to scanning clinical tables directly.
    """
    sources = _get_sources(conn)
    counts = _get_table_counts(conn)
    date_range = _get_lab_date_range(conn)

    if not sources and not any(counts.values()):
        return ""

    lines = ["## Data Summary\n"]

    if sources:
        lines.append("### Sources")
        for src in sources:
            lines.append(f"- {src}")
        lines.append("")

    lines.append("### Record Counts")
    for table, count in counts.items():
        if count > 0:
            label = table.replace("_", " ").title()
            lines.append(f"- {label}: {count}")
    lines.append("")

    if date_range:
        earliest, latest = date_range
        lines.append(f"### Lab Results Date Range\n- Earliest: {earliest}\n- Latest: {latest}")

    return "\n".join(lines)


def _get_sources(conn: sqlite3.Connection) -> list[str]:
    """Get distinct data source names, preferring load_log."""
    # Try load_log first (always populated on load)
    rows = conn.execute("SELECT DISTINCT source FROM load_log ORDER BY source").fetchall()
    if rows:
        return [row["source"] for row in rows]

    # Fallback: scan clinical tables for distinct source values
    all_sources: set[str] = set()
    for table in _CLINICAL_TABLES:
        try:
            src_rows = conn.execute(f"SELECT DISTINCT source FROM {table}").fetchall()
            all_sources.update(row["source"] for row in src_rows)
        except sqlite3.OperationalError:
            continue
    return sorted(all_sources)


def _get_table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Get row counts for all clinical tables."""
    counts: dict[str, int] = {}
    for table in _CLINICAL_TABLES:
        try:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            counts[table] = row["n"] if row else 0
        except sqlite3.OperationalError:
            counts[table] = 0
    return counts


def _get_lab_date_range(conn: sqlite3.Connection) -> tuple[str, str] | None:
    """Get the earliest and latest lab result dates."""
    row = conn.execute(
        "SELECT MIN(result_date) AS earliest, MAX(result_date) AS latest "
        "FROM lab_results WHERE result_date IS NOT NULL AND result_date != ''"
    ).fetchone()
    if row and row["earliest"] and row["latest"]:
        return (row["earliest"], row["latest"])
    return None


def _get_current_analyses_section(conn: sqlite3.Connection) -> str:
    """Fetch analyses with status 'current' in their frontmatter JSON."""
    try:
        rows = conn.execute(
            "SELECT title, content, frontmatter FROM analyses ORDER BY updated_at DESC"
        ).fetchall()
    except sqlite3.OperationalError:
        return ""

    current_analyses: list[tuple[str, str]] = []
    for row in rows:
        frontmatter_str = row["frontmatter"]
        if not frontmatter_str:
            continue
        try:
            fm = json.loads(frontmatter_str)
        except (json.JSONDecodeError, TypeError):
            continue
        if fm.get("status") == "current":
            current_analyses.append((row["title"], row["content"]))

    if not current_analyses:
        return ""

    lines = ["## Current Analyses\n"]
    for title, content in current_analyses:
        lines.append(f"### {title}\n")
        lines.append(content)
        lines.append("")

    return "\n".join(lines)
