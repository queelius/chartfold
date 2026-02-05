"""Lab trend analysis — query and track lab values over time."""

from __future__ import annotations

from chartfold.db import ChartfoldDB


def get_lab_trend(
    db: ChartfoldDB,
    test_name: str | None = None,
    test_loinc: str | None = None,
    test_names: list[str] | None = None,
    start_date: str = "",
    end_date: str = "",
) -> list[dict]:
    """Get chronological lab values for a specific test.

    Args:
        db: Database connection.
        test_name: Test name to search for (partial match, case-insensitive).
        test_loinc: LOINC code for exact match.
        test_names: Multiple test names to OR-match (for cross-source synonyms).
        start_date: Filter results on or after this ISO date.
        end_date: Filter results on or before this ISO date.
    """
    conditions = []
    params = []

    if test_loinc:
        conditions.append("test_loinc = ?")
        params.append(test_loinc)
    elif test_names:
        eq_clauses = " OR ".join("LOWER(test_name) = ?" for _ in test_names)
        conditions.append(f"({eq_clauses})")
        params.extend(n.lower() for n in test_names)
    elif test_name:
        conditions.append("LOWER(test_name) LIKE ?")
        params.append(f"%{test_name.lower()}%")
    else:
        return []

    if start_date:
        conditions.append("result_date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("result_date <= ?")
        params.append(end_date)

    where = " AND ".join(conditions)
    return db.query(
        f"SELECT test_name, value, value_numeric, unit, ref_range, "
        f"interpretation, result_date, source "
        f"FROM lab_results WHERE {where} "
        f"ORDER BY result_date",
        tuple(params),
    )


def get_abnormal_labs(
    db: ChartfoldDB,
    start_date: str = "",
    end_date: str = "",
) -> list[dict]:
    """Get lab results flagged as abnormal."""
    conditions = ["interpretation != '' AND interpretation IS NOT NULL"]
    params = []

    if start_date:
        conditions.append("result_date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("result_date <= ?")
        params.append(end_date)

    where = " AND ".join(conditions)
    return db.query(
        f"SELECT test_name, value, value_numeric, unit, ref_range, "
        f"interpretation, result_date, source "
        f"FROM lab_results WHERE {where} "
        f"ORDER BY result_date DESC",
        tuple(params),
    )


def get_latest_labs(db: ChartfoldDB, limit: int = 50) -> list[dict]:
    """Get the most recent result for each unique test name."""
    return db.query(
        "SELECT test_name, value, value_numeric, unit, ref_range, "
        "interpretation, result_date, source "
        "FROM lab_results "
        "WHERE result_date = ("
        "  SELECT MAX(lr2.result_date) FROM lab_results lr2 "
        "  WHERE lr2.test_name = lab_results.test_name"
        ") "
        "GROUP BY test_name "
        "ORDER BY result_date DESC "
        "LIMIT ?",
        (limit,),
    )


def get_lab_series(
    db: ChartfoldDB,
    test_name: str | None = None,
    test_loinc: str | None = None,
    test_names: list[str] | None = None,
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """Get a unified cross-source chronological series for a lab test.

    Returns all results across all sources for the given test, ordered by date,
    with source annotations and reference range discrepancy flags.

    Args:
        db: Database connection.
        test_name: Test name to search for (partial match, case-insensitive).
        test_loinc: LOINC code for exact match.
        test_names: Multiple test names to OR-match (for cross-source synonyms).
        start_date: Filter results on or after this ISO date.
        end_date: Filter results on or before this ISO date.

    Returns dict with:
    - test_name: Canonical test name
    - results: Chronological list of results with source annotations
    - sources: List of sources that contributed results
    - ref_ranges: Dict of source -> ref_range (flags discrepancies)
    - ref_range_discrepancy: True if sources report different reference ranges
    """
    results = get_lab_trend(db, test_name=test_name, test_loinc=test_loinc,
                            test_names=test_names,
                            start_date=start_date, end_date=end_date)
    if not results:
        return {
            "test_name": test_name or test_loinc or "",
            "results": [],
            "sources": [],
            "ref_ranges": {},
            "ref_range_discrepancy": False,
        }

    # Collect reference ranges per source
    ref_ranges: dict[str, set[str]] = {}
    for r in results:
        src = r.get("source", "")
        rr = r.get("ref_range", "")
        if src and rr:
            ref_ranges.setdefault(src, set()).add(rr)

    # Flatten: one ref_range per source (use most common if multiple)
    ref_range_map: dict[str, str] = {}
    for src, ranges in ref_ranges.items():
        ref_range_map[src] = max(ranges, key=lambda x: sum(
            1 for r in results if r.get("source") == src and r.get("ref_range") == x
        ))

    # Detect discrepancy: different non-empty ref ranges across sources
    unique_ranges = {rr for rr in ref_range_map.values() if rr}
    discrepancy = len(unique_ranges) > 1

    sources = sorted({r["source"] for r in results})
    canonical_name = results[0]["test_name"]

    return {
        "test_name": canonical_name,
        "results": results,
        "sources": sources,
        "ref_ranges": ref_range_map,
        "ref_range_discrepancy": discrepancy,
    }


def get_available_tests(db: ChartfoldDB) -> list[dict]:
    """Get all unique test names with their frequency and date range.

    Returns list of dicts with:
    - test_name: Test name
    - count: Number of results
    - sources: Comma-separated source list
    - first_date: Earliest result date
    - last_date: Most recent result date
    """
    return db.query(
        "SELECT test_name, COUNT(*) as count, "
        "GROUP_CONCAT(DISTINCT source) as sources, "
        "MIN(result_date) as first_date, "
        "MAX(result_date) as last_date "
        "FROM lab_results "
        "GROUP BY test_name "
        "ORDER BY count DESC"
    )
