"""Convert athenahealth/SIHF parsed data into UnifiedRecords."""

from __future__ import annotations

from chartfold.core.utils import derive_source_name, normalize_date_to_iso, try_parse_numeric
from chartfold.models import (
    AllergyRecord,
    ClinicalNote,
    ConditionRecord,
    DocumentRecord,
    EncounterRecord,
    FamilyHistoryRecord,
    ImmunizationRecord,
    LabResult,
    MedicationRecord,
    MentalStatusRecord,
    PatientRecord,
    ProcedureRecord,
    SocialHistoryRecord,
    UnifiedRecords,
    VitalRecord,
)
from chartfold.sources.assets import discover_source_assets


def _parser_counts(data: dict) -> dict[str, int]:
    """Count records in athenahealth parser output before adapter transformation."""
    return {
        "patients": 1 if data.get("patient") else 0,
        "documents": len(data.get("documents", [])),
        "encounters": len(data.get("encounters", [])),
        "lab_results": len(data.get("lab_results", [])),
        "vitals": len(data.get("vitals", [])),
        "medications": len(data.get("medications", [])),
        "conditions": len(data.get("conditions", [])),
        "immunizations": len(data.get("immunizations", [])),
        "allergies": len(data.get("allergies", [])),
        "social_history": len(data.get("social_history", [])),
        "family_history": len(data.get("family_history", [])),
        "mental_status": len(data.get("mental_status", [])),
        "clinical_notes": len(data.get("clinical_notes", [])),
        "procedures": len(data.get("procedures", [])),
    }


def athena_to_unified(data: dict, source_name: str | None = None) -> UnifiedRecords:
    """Transform athenahealth extraction output into UnifiedRecords.

    Args:
        data: Output from process_athena_export().
        source_name: Optional source name override. If not provided, derived from input_dir.
    """
    input_dir = data.get("input_dir", "")
    if source_name:
        source = source_name
    elif input_dir:
        source = derive_source_name(input_dir, "athena")
    else:
        source = "athena"
    records = UnifiedRecords(source=source)

    # Patient
    patient = data.get("patient")
    if patient:
        records.patient = PatientRecord(
            source=source,
            name=patient.get("name", ""),
            date_of_birth=patient.get("dob", ""),
            gender=patient.get("gender", ""),
            mrn=patient.get("mrn", ""),
            address=patient.get("address", ""),
            phone=patient.get("phone", ""),
        )

    # Documents
    for doc in data.get("documents", []):
        records.documents.append(DocumentRecord(
            source=source,
            doc_id=doc.get("doc_id", ""),
            doc_type="CDA",
            title=doc.get("title", ""),
            encounter_date=normalize_date_to_iso(doc.get("encounter_date", "")),
            file_path=doc.get("file_path", ""),
        ))

    # Encounters
    for enc in data.get("encounters", []):
        records.encounters.append(EncounterRecord(
            source=source,
            encounter_date=normalize_date_to_iso(enc.get("date", "")),
            encounter_type=enc.get("type", ""),
            facility=enc.get("facility", ""),
            provider=enc.get("provider", ""),
            reason=enc.get("reason", ""),
        ))

    # Lab results
    for lab in data.get("lab_results", []):
        val = lab.get("value", "")
        records.lab_results.append(LabResult(
            source=source,
            test_name=lab.get("test_name", ""),
            test_loinc=lab.get("loinc", ""),
            panel_name=lab.get("panel_name", ""),
            value=val,
            value_numeric=try_parse_numeric(val),
            unit=lab.get("unit", ""),
            ref_range=lab.get("ref_range", ""),
            interpretation=lab.get("interpretation", ""),
            result_date=normalize_date_to_iso(lab.get("date", "")),
        ))

    # Vitals
    for vital in data.get("vitals", []):
        records.vitals.append(VitalRecord(
            source=source,
            vital_type=vital.get("type", ""),
            value=vital.get("value"),
            value_text=vital.get("value_text", ""),
            unit=vital.get("unit", ""),
            recorded_date=normalize_date_to_iso(vital.get("date", "")),
        ))

    # Medications
    for med in data.get("medications", []):
        records.medications.append(MedicationRecord(
            source=source,
            name=med.get("name", ""),
            rxnorm_code=med.get("rxnorm", ""),
            status=med.get("status", "active"),
            sig=med.get("sig", ""),
            route=med.get("route", ""),
            start_date=normalize_date_to_iso(med.get("start_date", "")),
            stop_date=normalize_date_to_iso(med.get("stop_date", "")),
        ))

    # Conditions
    for cond in data.get("conditions", []):
        records.conditions.append(ConditionRecord(
            source=source,
            condition_name=cond.get("name", ""),
            icd10_code=cond.get("icd10", ""),
            snomed_code=cond.get("snomed", ""),
            clinical_status=cond.get("status", ""),
            onset_date=normalize_date_to_iso(cond.get("onset", "")),
        ))

    # Immunizations
    for imm in data.get("immunizations", []):
        records.immunizations.append(ImmunizationRecord(
            source=source,
            vaccine_name=imm.get("name", ""),
            cvx_code=imm.get("cvx", ""),
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

    # Social history
    for sh in data.get("social_history", []):
        records.social_history.append(SocialHistoryRecord(
            source=source,
            category=sh.get("category", ""),
            value=sh.get("value", ""),
            recorded_date=normalize_date_to_iso(sh.get("date", "")),
        ))

    # Family history
    for fh in data.get("family_history", []):
        records.family_history.append(FamilyHistoryRecord(
            source=source,
            relation=fh.get("relation", ""),
            condition=fh.get("condition", ""),
        ))

    # Mental status
    for ms in data.get("mental_status", []):
        records.mental_status.append(MentalStatusRecord(
            source=source,
            instrument=ms.get("instrument", ""),
            question=ms.get("question", ""),
            answer=ms.get("answer", ""),
            score=ms.get("score"),
            total_score=ms.get("total_score"),
            recorded_date=normalize_date_to_iso(ms.get("date", "")),
        ))

    # Clinical notes
    for note in data.get("clinical_notes", []):
        records.clinical_notes.append(ClinicalNote(
            source=source,
            note_type=note.get("type", ""),
            author=note.get("author", ""),
            note_date=normalize_date_to_iso(note.get("date", "")),
            content=note.get("content", ""),
        ))

    # Procedures
    for proc in data.get("procedures", []):
        records.procedures.append(ProcedureRecord(
            source=source,
            name=proc.get("name", ""),
            snomed_code=proc.get("snomed", ""),
            cpt_code=proc.get("cpt", ""),
            procedure_date=normalize_date_to_iso(proc.get("date", "")),
            provider=proc.get("provider", ""),
            facility=proc.get("facility", ""),
        ))

    # Source assets (non-parsed files)
    if input_dir:
        records.source_assets = discover_source_assets(input_dir, source)

    return records
