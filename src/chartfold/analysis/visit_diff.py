"""Visit diff — what's new since a given date across all data types."""

from __future__ import annotations

from chartfold.db import ChartfoldDB


def visit_diff(db: ChartfoldDB, since_date: str) -> dict:
    """Return everything new since a given date, across all clinical tables.

    Args:
        db: Database connection.
        since_date: ISO date (YYYY-MM-DD). Returns records on or after this date.

    Returns dict with:
    - since_date: The cutoff date used
    - new_labs: Lab results since the date
    - new_imaging: Imaging studies since the date
    - new_pathology: Pathology reports since the date
    - medication_changes: Medications with start or stop dates since the date
    - new_notes: Clinical notes since the date
    - new_conditions: Conditions with onset since the date
    - new_encounters: Encounters since the date
    - new_procedures: Procedures since the date
    - summary: Count per category
    """
    if not since_date:
        return {"error": "since_date is required"}

    new_labs = db.query(
        "SELECT test_name, value, value_numeric, unit, ref_range, "
        "interpretation, result_date, source "
        "FROM lab_results WHERE result_date >= ? "
        "ORDER BY result_date DESC",
        (since_date,),
    )

    new_imaging = db.query(
        "SELECT study_name, modality, study_date, impression, source "
        "FROM imaging_reports WHERE study_date >= ? "
        "ORDER BY study_date DESC",
        (since_date,),
    )

    new_pathology = db.query(
        "SELECT p.report_date, p.specimen, p.diagnosis, p.staging, p.margins, "
        "p.source, pr.name as procedure_name "
        "FROM pathology_reports p "
        "LEFT JOIN procedures pr ON p.procedure_id = pr.id "
        "WHERE p.report_date >= ? "
        "ORDER BY p.report_date DESC",
        (since_date,),
    )

    medication_changes = db.query(
        "SELECT name, status, sig, start_date, stop_date, prescriber, source "
        "FROM medications "
        "WHERE start_date >= ? OR stop_date >= ? "
        "ORDER BY COALESCE(start_date, stop_date) DESC",
        (since_date, since_date),
    )

    new_notes = db.query(
        "SELECT note_type, author, note_date, "
        "SUBSTR(content, 1, 500) as content_preview, source "
        "FROM clinical_notes WHERE note_date >= ? "
        "ORDER BY note_date DESC",
        (since_date,),
    )

    new_conditions = db.query(
        "SELECT condition_name, icd10_code, clinical_status, onset_date, source "
        "FROM conditions WHERE onset_date >= ? "
        "ORDER BY onset_date DESC",
        (since_date,),
    )

    new_encounters = db.query(
        "SELECT encounter_date, encounter_type, facility, provider, reason, source "
        "FROM encounters WHERE encounter_date >= ? "
        "ORDER BY encounter_date DESC",
        (since_date,),
    )

    new_procedures = db.query(
        "SELECT name, procedure_date, provider, facility, source "
        "FROM procedures WHERE procedure_date >= ? "
        "ORDER BY procedure_date DESC",
        (since_date,),
    )

    new_genetic_variants = db.query(
        "SELECT gene, variant_type, classification, vaf, dna_change, "
        "protein_change, test_name, collection_date, result_date, source "
        "FROM genetic_variants WHERE collection_date >= ? "
        "ORDER BY collection_date DESC",
        (since_date,),
    )

    result = {
        "since_date": since_date,
        "new_labs": new_labs,
        "new_imaging": new_imaging,
        "new_pathology": new_pathology,
        "medication_changes": medication_changes,
        "new_notes": new_notes,
        "new_conditions": new_conditions,
        "new_encounters": new_encounters,
        "new_procedures": new_procedures,
        "new_genetic_variants": new_genetic_variants,
        "summary": {
            "labs": len(new_labs),
            "imaging": len(new_imaging),
            "pathology": len(new_pathology),
            "medication_changes": len(medication_changes),
            "notes": len(new_notes),
            "conditions": len(new_conditions),
            "encounters": len(new_encounters),
            "procedures": len(new_procedures),
            "genetic_variants": len(new_genetic_variants),
        },
    }
    return result
