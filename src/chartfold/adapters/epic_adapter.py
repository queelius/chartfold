"""Convert Epic parsed data (from sources.epic) into UnifiedRecords."""

from __future__ import annotations

import re

from chartfold.core.utils import normalize_date_to_iso, try_parse_numeric
from chartfold.models import (
    AllergyRecord,
    ClinicalNote,
    ConditionRecord,
    DocumentRecord,
    EncounterRecord,
    ImagingReport,
    ImmunizationRecord,
    LabResult,
    MedicationRecord,
    PathologyReport,
    ProcedureRecord,
    SocialHistoryRecord,
    UnifiedRecords,
    VitalRecord,
)
from chartfold.sources.epic import _classify_result


def _parser_counts(data: dict) -> dict[str, int]:
    """Count records in Epic parser output before adapter transformation."""
    lab_components = sum(len(p.get("components", [])) for p in data.get("lab_results", []))
    cea_count = len(data.get("cea_values", []))
    return {
        "documents": len(data.get("inventory", [])),
        "encounters": len(data.get("encounter_timeline", [])),
        "lab_results": lab_components + cea_count,
        "imaging_reports": len(data.get("imaging_reports", [])),
        "pathology_reports": len(data.get("pathology_reports", [])),
        "clinical_notes": len(data.get("clinical_notes", [])),
        "medications": len(data.get("medications", [])),
        "conditions": len(data.get("problems", [])),
        "vitals": len(data.get("vitals", [])),
        "immunizations": len(data.get("immunizations", [])),
        "allergies": len(data.get("allergies", [])),
        "social_history": len(data.get("social_history", [])),
        "procedures": len(data.get("procedures", [])),
        "errors": len(data.get("errors", [])),
    }


def epic_to_unified(data: dict) -> UnifiedRecords:
    """Transform Epic extraction output into UnifiedRecords.

    Args:
        data: Output from process_epic_documents().
    """
    source = "epic_anderson"
    records = UnifiedRecords(source=source)

    # Documents
    for inv in data.get("inventory", []):
        records.documents.append(DocumentRecord(
            source=source,
            doc_id=inv["doc_id"],
            doc_type="CDA",
            title=inv.get("title", ""),
            encounter_date=normalize_date_to_iso(inv.get("date", "")),
            file_path="",
            file_size_kb=inv.get("size_kb", 0),
        ))

    # Encounters
    for enc in data.get("encounter_timeline", []):
        records.encounters.append(EncounterRecord(
            source=source,
            source_doc_id=enc.get("doc_id", ""),
            encounter_date=normalize_date_to_iso(enc.get("date", "")),
            encounter_type="",
            facility=enc.get("facility", ""),
            provider=", ".join(enc.get("authors", [])) if isinstance(enc.get("authors"), list) else "",
        ))

    # Lab results — explode panels into individual rows
    for panel in data.get("lab_results", []):
        panel_name = panel.get("panel", "")
        panel_date = normalize_date_to_iso(panel.get("date", ""))
        source_doc = panel.get("source_doc", "")
        for comp in panel.get("components", []):
            val = comp.get("value", "")
            records.lab_results.append(LabResult(
                source=source,
                source_doc_id=source_doc,
                test_name=comp.get("name", ""),
                panel_name=panel_name,
                value=val,
                value_numeric=try_parse_numeric(val),
                ref_range=comp.get("ref_range", ""),
                result_date=panel_date,
            ))

    # CEA values (also lab results, but pre-extracted)
    for cea in data.get("cea_values", []):
        val = cea.get("value", "")
        records.lab_results.append(LabResult(
            source=source,
            source_doc_id="",
            test_name="CEA",
            panel_name="CEA",
            value=val,
            value_numeric=try_parse_numeric(val),
            ref_range=cea.get("ref_range", ""),
            result_date=normalize_date_to_iso(cea.get("date", "")),
        ))

    # Imaging reports
    for img in data.get("imaging_reports", []):
        records.imaging_reports.append(ImagingReport(
            source=source,
            study_name=img.get("study", ""),
            modality=_guess_modality(img.get("study", "")),
            study_date=normalize_date_to_iso(img.get("date", "")),
            findings=img.get("findings", ""),
            impression=img.get("impression", ""),
            full_text=img.get("full_text", ""),
        ))

    # Pathology reports
    for path in data.get("pathology_reports", []):
        records.pathology_reports.append(PathologyReport(
            source=source,
            report_date=normalize_date_to_iso(path.get("date", "")),
            specimen=path.get("panel", ""),
            diagnosis=path.get("diagnosis", ""),
            gross_description=path.get("gross", ""),
            microscopic_description=path.get("microscopic", ""),
            full_text=path.get("full_text", ""),
        ))

    # Clinical notes
    for note in data.get("clinical_notes", []):
        records.clinical_notes.append(ClinicalNote(
            source=source,
            source_doc_id=note.get("doc_id", ""),
            note_type=note.get("section", ""),
            note_date=normalize_date_to_iso(note.get("date", "")),
            content=note.get("text", ""),
        ))

    # Medications (structured)
    for med in data.get("medications", []):
        if isinstance(med, str):
            # Legacy text format fallback
            if med.strip() and not med.startswith("Medications"):
                records.medications.append(MedicationRecord(source=source, name=med.strip(), status="active"))
            continue
        records.medications.append(MedicationRecord(
            source=source,
            name=med.get("name", ""),
            rxnorm_code=med.get("rxnorm", ""),
            status=med.get("status", ""),
            sig=med.get("sig", ""),
            route=med.get("route", ""),
            start_date=normalize_date_to_iso(med.get("start_date", "")),
            stop_date=normalize_date_to_iso(med.get("stop_date", "")),
        ))

    # Conditions (structured)
    for cond in data.get("problems", []):
        if isinstance(cond, str):
            # Legacy text format fallback
            if cond.strip() and not cond.startswith("Active Problems"):
                records.conditions.append(ConditionRecord(source=source, condition_name=cond.strip(), clinical_status="active"))
            continue
        records.conditions.append(ConditionRecord(
            source=source,
            condition_name=cond.get("name", ""),
            icd10_code=cond.get("icd10", ""),
            snomed_code=cond.get("snomed", ""),
            clinical_status=cond.get("status", "active"),
            onset_date=normalize_date_to_iso(cond.get("onset_date", "")),
        ))

    # Vitals
    for vital in data.get("vitals", []):
        records.vitals.append(VitalRecord(
            source=source,
            vital_type=vital.get("type", ""),
            value=vital.get("value"),
            unit=vital.get("unit", ""),
            recorded_date=normalize_date_to_iso(vital.get("date", "")),
        ))

    # Immunizations
    for imm in data.get("immunizations", []):
        records.immunizations.append(ImmunizationRecord(
            source=source,
            vaccine_name=imm.get("name", ""),
            cvx_code=imm.get("cvx_code", ""),
            admin_date=normalize_date_to_iso(imm.get("date", "")),
            lot_number=imm.get("lot", ""),
            status=imm.get("status", ""),
        ))

    # Allergies
    for allergy in data.get("allergies", []):
        records.allergies.append(AllergyRecord(
            source=source,
            allergen=allergy.get("allergen", ""),
            reaction=allergy.get("reaction", ""),
            severity=allergy.get("severity", ""),
            status=allergy.get("status", "active"),
        ))

    # Social History
    for sh in data.get("social_history", []):
        records.social_history.append(SocialHistoryRecord(
            source=source,
            category=sh.get("category", ""),
            value=sh.get("value", ""),
            recorded_date=normalize_date_to_iso(sh.get("date", "")),
        ))

    # Procedures
    from chartfold.sources.epic import OID_SNOMED
    for proc in data.get("procedures", []):
        records.procedures.append(ProcedureRecord(
            source=source,
            source_doc_id=proc.get("source_doc", ""),
            name=proc.get("name", ""),
            snomed_code=proc.get("code_value", "") if proc.get("code_system", "") == OID_SNOMED else "",
            procedure_date=normalize_date_to_iso(proc.get("date", "")),
            provider=proc.get("provider", ""),
            status=proc.get("status", ""),
        ))

    return records


def _guess_modality(study_name: str) -> str:
    """Guess imaging modality from study name."""
    name = study_name.upper()
    if "PET" in name:
        return "PET"
    if "MRI" in name or "MR " in name:
        return "MRI"
    if "CT " in name or "CT/" in name or name.startswith("CT"):
        return "CT"
    if "US " in name or "ULTRASOUND" in name:
        return "US"
    if "XR " in name or "X-RAY" in name or "XRAY" in name:
        return "XR"
    if "CHEST" in name:
        return "XR"
    if "MAMM" in name:
        return "MG"
    return ""
