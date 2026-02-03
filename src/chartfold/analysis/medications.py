"""Medication analysis — active meds, history, cross-source reconciliation."""

from __future__ import annotations

from chartfold.db import ChartfoldDB


def get_active_medications(db: ChartfoldDB) -> list[dict]:
    """Get currently active medications across all sources."""
    return db.query(
        "SELECT name, rxnorm_code, sig, route, start_date, prescriber, source "
        "FROM medications "
        "WHERE LOWER(status) = 'active' "
        "ORDER BY name"
    )


def get_medication_history(db: ChartfoldDB, med_name: str = "") -> list[dict]:
    """Get all medications, optionally filtered by name."""
    if med_name:
        return db.query(
            "SELECT name, rxnorm_code, status, sig, route, start_date, stop_date, "
            "prescriber, source "
            "FROM medications "
            "WHERE LOWER(name) LIKE ? "
            "ORDER BY start_date DESC",
            (f"%{med_name.lower()}%",),
        )
    return db.query(
        "SELECT name, rxnorm_code, status, sig, route, start_date, stop_date, "
        "prescriber, source "
        "FROM medications "
        "ORDER BY status, name"
    )


def reconcile_medications(db: ChartfoldDB) -> dict:
    """Cross-source medication reconciliation.

    Returns dict with:
    - active: medications active in at least one source
    - discrepancies: medications with conflicting status across sources
    """
    all_meds = db.query(
        "SELECT name, status, sig, source FROM medications ORDER BY name"
    )

    # Group by normalized name
    by_name: dict[str, list[dict]] = {}
    for med in all_meds:
        key = med["name"].lower().strip().split(" ")[0]  # Normalize by first word
        by_name.setdefault(key, []).append(med)

    active = []
    discrepancies = []

    for key, entries in by_name.items():
        statuses = {e.get("status", "").lower() for e in entries}
        sources = {e["source"] for e in entries}

        if "active" in statuses:
            active.append({
                "name": entries[0]["name"],
                "sources": list(sources),
                "statuses": list(statuses),
            })

        if len(statuses) > 1:
            discrepancies.append({
                "name": entries[0]["name"],
                "entries": entries,
            })

    return {"active": active, "discrepancies": discrepancies}
