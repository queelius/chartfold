"""Clinical summary — comprehensive patient snapshot in a single call."""
from __future__ import annotations

from chartfold.db import ChartfoldDB


def get_clinical_summary(
    db: ChartfoldDB,
    include_notes: bool = False,
    include_family_history: bool = True,
    recent_labs_days: int = 180,
) -> dict:
    """Return the full clinical picture in a single call.

    Returns:
        active_conditions, allergies, active_medications, recent_labs,
        recent_vitals, recent_imaging, recent_encounters, pathology_reports,
        procedures, family_history (optional), recent_notes (optional).
    """
    from datetime import date, timedelta

    cutoff = (date.today() - timedelta(days=recent_labs_days)).isoformat()

    summary = {
        "active_conditions": db.query(
            "SELECT condition_name, icd10_code, onset_date, category, source "
            "FROM conditions WHERE LOWER(clinical_status) = 'active' "
            "ORDER BY condition_name"
        ),
        "all_conditions": db.query(
            "SELECT condition_name, icd10_code, clinical_status, onset_date, "
            "resolved_date, category, source "
            "FROM conditions ORDER BY onset_date DESC"
        ),
        "allergies": db.query(
            "SELECT allergen, reaction, severity, status, source "
            "FROM allergies ORDER BY allergen"
        ),
        "active_medications": db.query(
            "SELECT name, sig, route, start_date, prescriber, source "
            "FROM medications WHERE LOWER(status) = 'active' "
            "ORDER BY name"
        ),
        "all_medications": db.query(
            "SELECT name, status, sig, route, start_date, stop_date, prescriber, source "
            "FROM medications ORDER BY CASE WHEN LOWER(status)='active' THEN 0 ELSE 1 END, name"
        ),
        "recent_labs": db.query(
            "SELECT test_name, value, value_numeric, unit, ref_range, "
            "interpretation, result_date, source "
            "FROM lab_results WHERE result_date >= ? "
            "ORDER BY result_date DESC",
            (cutoff,),
        ),
        "abnormal_labs": db.query(
            "SELECT test_name, value, value_numeric, unit, ref_range, "
            "interpretation, result_date, source "
            "FROM lab_results WHERE interpretation != '' AND interpretation IS NOT NULL "
            "AND result_date >= ? "
            "ORDER BY result_date DESC",
            (cutoff,),
        ),
        "recent_vitals": db.query(
            "SELECT vital_type, value, value_text, unit, recorded_date, source "
            "FROM vitals WHERE recorded_date >= ? "
            "ORDER BY recorded_date DESC",
            (cutoff,),
        ),
        "recent_imaging": db.query(
            "SELECT study_name, modality, study_date, impression, source "
            "FROM imaging_reports WHERE study_date >= ? "
            "ORDER BY study_date DESC",
            (cutoff,),
        ),
        "all_imaging": db.query(
            "SELECT study_name, modality, study_date, "
            "SUBSTR(impression, 1, 300) as impression_preview, source "
            "FROM imaging_reports ORDER BY study_date DESC"
        ),
        "recent_encounters": db.query(
            "SELECT encounter_date, encounter_type, facility, provider, reason, source "
            "FROM encounters WHERE encounter_date >= ? "
            "ORDER BY encounter_date DESC",
            (cutoff,),
        ),
        "procedures": db.query(
            "SELECT name, procedure_date, provider, facility, status, source "
            "FROM procedures ORDER BY procedure_date DESC"
        ),
        "pathology_reports": db.query(
            "SELECT report_date, specimen, diagnosis, staging, margins, "
            "lymph_nodes, source "
            "FROM pathology_reports ORDER BY report_date DESC"
        ),
    }

    if include_family_history:
        summary["family_history"] = db.query(
            "SELECT relation, condition, age_at_onset, deceased "
            "FROM family_history ORDER BY relation"
        )

    if include_notes:
        summary["recent_notes"] = db.query(
            "SELECT note_type, author, note_date, content, source "
            "FROM clinical_notes WHERE note_date >= ? "
            "ORDER BY note_date DESC",
            (cutoff,),
        )
    else:
        summary["recent_notes_preview"] = db.query(
            "SELECT note_type, author, note_date, "
            "SUBSTR(content, 1, 300) as preview, source "
            "FROM clinical_notes WHERE note_date >= ? "
            "ORDER BY note_date DESC",
            (cutoff,),
        )

    return summary
