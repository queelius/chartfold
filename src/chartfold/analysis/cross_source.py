"""Cross-source data matching — find same-day encounters, linked records."""

from __future__ import annotations

from chartfold.db import ChartfoldDB


def match_encounters_by_date(db: ChartfoldDB, tolerance_days: int = 0) -> list[dict]:
    """Find encounters that occurred on the same date across different sources.

    This helps identify cases where the same visit generated records in
    multiple EHR systems (e.g., a surgery at one hospital with follow-up
    notes in another system).

    Args:
        db: Database connection.
        tolerance_days: How many days apart encounters can be to be considered
            a match. 0 = exact same date, 1 = within 1 day, etc.

    Returns list of dicts, each with:
    - date: The encounter date
    - encounters: List of encounter dicts from different sources
    """
    encounters = db.query(
        "SELECT id, encounter_date, encounter_type, facility, provider, "
        "reason, source FROM encounters "
        "WHERE encounter_date IS NOT NULL AND encounter_date != '' "
        "ORDER BY encounter_date"
    )

    if not encounters:
        return []

    # Group by date (or date range if tolerance > 0)
    by_date: dict[str, list[dict]] = {}
    for enc in encounters:
        date = enc["encounter_date"]
        by_date.setdefault(date, []).append(enc)

    if tolerance_days == 0:
        # Simple exact-date matching
        matches = []
        for date, encs in sorted(by_date.items()):
            sources = {e["source"] for e in encs}
            if len(sources) > 1:
                matches.append({
                    "date": date,
                    "encounters": encs,
                    "sources": sorted(sources),
                })
        return matches

    # Date-range matching
    from datetime import date as dt_date, timedelta

    matched = []
    dates = sorted(by_date.keys())
    used = set()

    for i, d1 in enumerate(dates):
        if d1 in used:
            continue
        try:
            date1 = dt_date.fromisoformat(d1)
        except ValueError:
            continue

        group = list(by_date[d1])
        group_sources = {e["source"] for e in group}

        for d2 in dates[i + 1:]:
            if d2 in used:
                continue
            try:
                date2 = dt_date.fromisoformat(d2)
            except ValueError:
                continue
            if abs((date2 - date1).days) <= tolerance_days:
                new_sources = {e["source"] for e in by_date[d2]}
                if new_sources - group_sources:
                    group.extend(by_date[d2])
                    group_sources |= new_sources
                    used.add(d2)

        if len(group_sources) > 1:
            matched.append({
                "date": d1,
                "encounters": group,
                "sources": sorted(group_sources),
            })
            used.add(d1)

    return matched
