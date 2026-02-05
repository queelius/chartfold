"""Data quality analysis — duplicates, coverage, and cross-source consistency."""

from __future__ import annotations

from chartfold.db import ChartfoldDB


def find_duplicate_labs(db: ChartfoldDB) -> list[dict]:
    """Find lab results that appear to be duplicates across sources.

    A potential duplicate: same test_name + same result_date from different sources.
    Includes both records so an analyst can determine if they're true duplicates
    (same assay) or different assays with the same name.

    Returns list of dicts, each with:
    - test_name: The test name
    - result_date: The date
    - records: List of matching records from different sources
    - value_match: True if all values are identical
    """
    dupes = db.query(
        "SELECT test_name, result_date, COUNT(DISTINCT source) as source_count "
        "FROM lab_results "
        "WHERE result_date IS NOT NULL AND result_date != '' "
        "GROUP BY test_name, result_date "
        "HAVING COUNT(DISTINCT source) > 1 "
        "ORDER BY result_date DESC, test_name"
    )

    results = []
    for d in dupes:
        records = db.query(
            "SELECT test_name, value, value_numeric, unit, ref_range, "
            "interpretation, result_date, source "
            "FROM lab_results "
            "WHERE test_name = ? AND result_date = ? "
            "ORDER BY source",
            (d["test_name"], d["result_date"]),
        )
        values = {r["value"] for r in records}
        results.append(
            {
                "test_name": d["test_name"],
                "result_date": d["result_date"],
                "records": records,
                "value_match": len(values) == 1,
            }
        )

    return results


def source_coverage_matrix(db: ChartfoldDB) -> dict:
    """Build a matrix showing which tables have data from which sources.

    Returns dict with:
    - sources: List of all source names
    - tables: Dict of table_name -> {source_name: count}
    - summary: Dict of source_name -> total records
    """
    tables = [
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
    ]

    # Get all sources
    sources_rows = db.query("SELECT DISTINCT source FROM load_log ORDER BY source")
    sources = [r["source"] for r in sources_rows]

    # If no load_log entries, try to discover sources from tables
    if not sources:
        for table in tables:
            rows = db.query(f"SELECT DISTINCT source FROM {table}")
            for r in rows:
                if r["source"] and r["source"] not in sources:
                    sources.append(r["source"])
        sources.sort()

    matrix: dict[str, dict[str, int]] = {}
    source_totals: dict[str, int] = dict.fromkeys(sources, 0)

    for table in tables:
        counts = db.query(f"SELECT source, COUNT(*) as count FROM {table} GROUP BY source")
        table_counts = {}
        for c in counts:
            src = c["source"]
            cnt = c["count"]
            table_counts[src] = cnt
            if src in source_totals:
                source_totals[src] += cnt
        matrix[table] = table_counts

    return {
        "sources": sources,
        "tables": matrix,
        "summary": source_totals,
    }


def get_data_quality(db: ChartfoldDB) -> dict:
    """Run all data quality checks and return a summary.

    Returns dict with:
    - duplicate_labs: Potential cross-source lab duplicates
    - coverage: Source coverage matrix
    - duplicate_count: Total number of potential duplicate groups
    - sources_count: Number of data sources loaded
    """
    dupes = find_duplicate_labs(db)
    coverage = source_coverage_matrix(db)

    return {
        "duplicate_labs": dupes,
        "coverage": coverage,
        "duplicate_count": len(dupes),
        "sources_count": len(coverage["sources"]),
    }
