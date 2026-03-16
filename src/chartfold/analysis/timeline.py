"""Unified clinical timeline — all events in chronological order."""
from __future__ import annotations

from chartfold.db import ChartfoldDB


def get_clinical_timeline(
    db: ChartfoldDB,
    start_date: str | None = None,
    end_date: str | None = None,
    include_notes: bool = False,
    include_labs: bool = True,
) -> list[dict]:
    """Return all clinical events merged into a single chronological timeline.

    Each event has: date, type, source, summary, and type-specific detail fields.
    Events are sorted by date descending (most recent first).
    """
    events: list[dict] = []

    date_filter = ""
    params: list = []
    if start_date:
        date_filter += " AND {col} >= ?"
        params.append(start_date)
    if end_date:
        date_filter += " AND {col} <= ?"
        params.append(end_date)

    def _params(col: str) -> tuple:
        """Build params with the date column name substituted."""
        filt = ""
        p = []
        if start_date:
            filt += f" AND {col} >= ?"
            p.append(start_date)
        if end_date:
            filt += f" AND {col} <= ?"
            p.append(end_date)
        return filt, tuple(p)

    # Encounters
    filt, p = _params("encounter_date")
    for r in db.query(
        f"SELECT encounter_date, encounter_type, facility, provider, reason, source "
        f"FROM encounters WHERE 1=1{filt} ORDER BY encounter_date DESC", p
    ):
        events.append({
            "date": r["encounter_date"], "type": "encounter", "source": r["source"],
            "summary": f"{r['encounter_type'] or 'Visit'} at {r['facility'] or 'unknown'}",
            "detail": r,
        })

    # Procedures
    filt, p = _params("procedure_date")
    for r in db.query(
        f"SELECT name, procedure_date, provider, facility, status, source "
        f"FROM procedures WHERE 1=1{filt} ORDER BY procedure_date DESC", p
    ):
        events.append({
            "date": r["procedure_date"], "type": "procedure", "source": r["source"],
            "summary": r["name"],
            "detail": r,
        })

    # Imaging
    filt, p = _params("study_date")
    for r in db.query(
        f"SELECT study_name, modality, study_date, impression, source "
        f"FROM imaging_reports WHERE 1=1{filt} ORDER BY study_date DESC", p
    ):
        events.append({
            "date": r["study_date"], "type": "imaging", "source": r["source"],
            "summary": f"{r['modality'] or ''} {r['study_name'] or ''}".strip(),
            "detail": r,
        })

    # Pathology
    filt, p = _params("report_date")
    for r in db.query(
        f"SELECT report_date, specimen, diagnosis, staging, margins, "
        f"lymph_nodes, source FROM pathology_reports WHERE 1=1{filt} "
        f"ORDER BY report_date DESC", p
    ):
        events.append({
            "date": r["report_date"], "type": "pathology", "source": r["source"],
            "summary": f"Pathology: {r['specimen'] or 'unknown specimen'}",
            "detail": r,
        })

    # Labs (grouped by date to avoid flooding)
    if include_labs:
        filt, p = _params("result_date")
        lab_rows = db.query(
            f"SELECT test_name, value, value_numeric, unit, ref_range, "
            f"interpretation, result_date, source "
            f"FROM lab_results WHERE 1=1{filt} ORDER BY result_date DESC", p
        )
        # Group by (date, source) to create one event per lab panel
        lab_groups: dict[tuple[str, str], list] = {}
        for r in lab_rows:
            key = (r["result_date"] or "", r["source"] or "")
            lab_groups.setdefault(key, []).append(r)

        for (lab_date, source), results in lab_groups.items():
            abnormal = [r for r in results if r.get("interpretation")]
            events.append({
                "date": lab_date, "type": "labs", "source": source,
                "summary": f"{len(results)} lab results ({len(abnormal)} abnormal)",
                "detail": {
                    "total": len(results),
                    "abnormal_count": len(abnormal),
                    "results": results,
                },
            })

    # Clinical notes
    if include_notes:
        filt, p = _params("note_date")
        for r in db.query(
            f"SELECT note_type, author, note_date, content, source "
            f"FROM clinical_notes WHERE 1=1{filt} ORDER BY note_date DESC", p
        ):
            events.append({
                "date": r["note_date"], "type": "note", "source": r["source"],
                "summary": f"{r['note_type'] or 'Note'} by {r['author'] or 'unknown'}",
                "detail": r,
            })
    else:
        filt, p = _params("note_date")
        for r in db.query(
            f"SELECT note_type, author, note_date, "
            f"SUBSTR(content, 1, 300) as preview, source "
            f"FROM clinical_notes WHERE 1=1{filt} ORDER BY note_date DESC", p
        ):
            events.append({
                "date": r["note_date"], "type": "note", "source": r["source"],
                "summary": f"{r['note_type'] or 'Note'} by {r['author'] or 'unknown'}",
                "detail": r,
            })

    # Sort all events by date descending
    events.sort(key=lambda e: e.get("date") or "", reverse=True)

    return events
