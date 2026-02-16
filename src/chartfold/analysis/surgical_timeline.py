"""Surgical timeline builder — links procedures with pathology and related records."""

from __future__ import annotations

from typing import Any

from chartfold.db import ChartfoldDB
from chartfold.extractors.pathology import link_pathology_to_procedures


def build_surgical_timeline(
    db: ChartfoldDB,
    pre_op_imaging_days: int = 90,
    post_op_imaging_days: int = 30,
    limit: int = 0,
    offset: int = 0,
    include_full_text: bool = True,
) -> list[dict]:
    """Build a unified surgical timeline with linked pathology reports.

    Returns a list sorted by date, each item containing:
    - procedure: dict with name, date, facility, provider, source
    - pathology: dict or None with diagnosis, staging, margins, lymph_nodes
    - related_imaging: list of imaging studies within the specified window
    - related_medications: list of medications active around the procedure date

    Args:
        db: Database connection.
        pre_op_imaging_days: Days before procedure to look for pre-op imaging (default 90).
        post_op_imaging_days: Days after procedure to look for post-op imaging (default 30).
        limit: Max procedures to return (0 = all).
        offset: Number of procedures to skip.
        include_full_text: Include full pathology report text (default True).
    """
    # Query all procedures for pathology linking, then paginate the result
    all_procedures = db.query(
        "SELECT id, name, procedure_date, provider, facility, source, operative_note "
        "FROM procedures ORDER BY procedure_date"
    )
    pathology = db.query(
        "SELECT id, report_date, specimen, diagnosis, staging, margins, "
        "lymph_nodes, full_text, source, procedure_id "
        "FROM pathology_reports ORDER BY report_date"
    )
    imaging = db.query(
        "SELECT id, study_name, modality, study_date, impression, source "
        "FROM imaging_reports ORDER BY study_date"
    )

    # Link unlinked pathology reports to procedures
    unlinked = [p for p in pathology if not p.get("procedure_id")]
    if unlinked and all_procedures:
        links = link_pathology_to_procedures(
            [
                {
                    "id": p["id"],
                    "report_date": p["report_date"],
                    "specimen": p.get("specimen", ""),
                    "diagnosis": p.get("diagnosis", ""),
                }
                for p in unlinked
            ],
            [
                {"id": p["id"], "procedure_date": p["procedure_date"], "name": p["name"]}
                for p in all_procedures
            ],
        )
        # Apply links
        for path_id, proc_id in links:
            db.conn.execute(
                "UPDATE pathology_reports SET procedure_id = ? WHERE id = ?",
                (proc_id, path_id),
            )
        db.conn.commit()

        # Re-query pathology to get updated procedure_id values
        pathology = db.query(
            "SELECT id, report_date, specimen, diagnosis, staging, margins, "
            "lymph_nodes, full_text, source, procedure_id "
            "FROM pathology_reports ORDER BY report_date"
        )

    # Paginate procedures
    procedures = all_procedures[offset:] if offset else all_procedures
    if limit > 0:
        procedures = procedures[:limit]

    # Build timeline entries
    timeline: list[dict[str, Any]] = []
    path_by_proc: dict[int, list[dict[str, Any]]] = {}
    for p in pathology:
        pid = p.get("procedure_id")
        if pid:
            path_by_proc.setdefault(pid, []).append(p)

    # Query medications for procedure-concurrent linking
    medications = db.query(
        "SELECT name, status, start_date, stop_date, source FROM medications ORDER BY name"
    )

    for proc in procedures:
        proc_date = proc.get("procedure_date", "")
        entry: dict[str, Any] = {
            "procedure": {
                "id": proc["id"],
                "name": proc["name"],
                "date": proc_date,
                "facility": proc.get("facility", ""),
                "provider": proc.get("provider", ""),
                "source": proc["source"],
            },
            "pathology": None,
            "related_imaging": [],
            "related_medications": [],
        }

        # Linked pathology
        linked_paths = path_by_proc.get(proc["id"], [])
        if linked_paths:
            p = linked_paths[0]  # Primary pathology report
            path_entry: dict[str, Any] = {
                "id": p["id"],
                "diagnosis": p.get("diagnosis", ""),
                "staging": p.get("staging", ""),
                "margins": p.get("margins", ""),
                "lymph_nodes": p.get("lymph_nodes", ""),
            }
            if include_full_text:
                path_entry["full_text"] = p.get("full_text", "")
            entry["pathology"] = path_entry

        # Related imaging (asymmetric: pre_op_imaging_days before, post_op_imaging_days after)
        if proc_date:
            try:
                from datetime import date

                pd = date.fromisoformat(proc_date)
            except ValueError:
                pd = None

            if pd:
                for img in imaging:
                    img_date = img.get("study_date", "")
                    if img_date:
                        try:
                            id_ = date.fromisoformat(img_date)
                            delta = (pd - id_).days
                            # delta > 0: imaging before procedure
                            # delta < 0: imaging after procedure
                            if -post_op_imaging_days <= delta <= pre_op_imaging_days:
                                entry["related_imaging"].append(
                                    {
                                        "id": img["id"],
                                        "study": img["study_name"],
                                        "modality": img["modality"],
                                        "date": img_date,
                                        "impression": img.get("impression", ""),
                                        "source": img.get("source", ""),
                                        "timing": "pre-op"
                                        if delta > 0
                                        else "post-op"
                                        if delta < 0
                                        else "same-day",
                                    }
                                )
                        except ValueError:
                            pass

                # Related medications (active around the procedure date)
                for med in medications:
                    start = med.get("start_date", "")
                    stop = med.get("stop_date", "")
                    status = (med.get("status") or "").lower()
                    # Include if: active with no stop date, or start <= proc_date <= stop
                    if status == "active" and not stop:
                        entry["related_medications"].append(
                            {
                                "name": med["name"],
                                "source": med["source"],
                            }
                        )
                    elif start and stop:
                        try:
                            sd = date.fromisoformat(start)
                            ed = date.fromisoformat(stop)
                            if sd <= pd <= ed:
                                entry["related_medications"].append(
                                    {
                                        "name": med["name"],
                                        "source": med["source"],
                                    }
                                )
                        except ValueError:
                            pass

        timeline.append(entry)

    return timeline
