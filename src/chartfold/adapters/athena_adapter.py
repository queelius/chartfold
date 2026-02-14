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


def _derive_source(data: dict, source_name: str | None) -> str:
    """Derive source identifier from data or override."""
    if source_name:
        return source_name
    input_dir = data.get("input_dir", "")
    if input_dir:
        return derive_source_name(input_dir, "athena")
    return "athena"


def _convert_patient(patient: dict, source: str) -> PatientRecord:
    """Convert patient dict to PatientRecord."""
    return PatientRecord(
        source=source,
        name=patient.get("name", ""),
        date_of_birth=patient.get("dob", ""),
        gender=patient.get("gender", ""),
        mrn=patient.get("mrn", ""),
        address=patient.get("address", ""),
        phone=patient.get("phone", ""),
    )


def _convert_document(doc: dict, source: str) -> DocumentRecord:
    """Convert document dict to DocumentRecord."""
    return DocumentRecord(
        source=source,
        doc_id=doc.get("doc_id", ""),
        doc_type="CDA",
        title=doc.get("title", ""),
        encounter_date=normalize_date_to_iso(doc.get("encounter_date", "")),
        file_path=doc.get("file_path", ""),
    )


def _convert_encounter(enc: dict, source: str) -> EncounterRecord:
    """Convert encounter dict to EncounterRecord."""
    return EncounterRecord(
        source=source,
        encounter_date=normalize_date_to_iso(enc.get("date", "")),
        encounter_end=normalize_date_to_iso(enc.get("end_date", "")),
        encounter_type=enc.get("type", ""),
        facility=enc.get("facility", ""),
        provider=enc.get("provider", ""),
        reason=enc.get("reason", ""),
    )


def _convert_lab_result(lab: dict, source: str) -> LabResult:
    """Convert lab dict to LabResult."""
    val = lab.get("value", "")
    return LabResult(
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
    )


def _convert_vital(vital: dict, source: str) -> VitalRecord:
    """Convert vital dict to VitalRecord."""
    return VitalRecord(
        source=source,
        vital_type=vital.get("type", ""),
        value=vital.get("value"),
        value_text=vital.get("value_text", ""),
        unit=vital.get("unit", ""),
        recorded_date=normalize_date_to_iso(vital.get("date", "")),
    )


def _convert_medication(med: dict, source: str) -> MedicationRecord:
    """Convert medication dict to MedicationRecord."""
    return MedicationRecord(
        source=source,
        name=med.get("name", ""),
        rxnorm_code=med.get("rxnorm", ""),
        status=med.get("status", "active"),
        sig=med.get("sig", ""),
        route=med.get("route", ""),
        start_date=normalize_date_to_iso(med.get("start_date", "")),
        stop_date=normalize_date_to_iso(med.get("stop_date", "")),
    )


def _convert_condition(cond: dict, source: str) -> ConditionRecord:
    """Convert condition dict to ConditionRecord."""
    return ConditionRecord(
        source=source,
        condition_name=cond.get("name", ""),
        icd10_code=cond.get("icd10", ""),
        snomed_code=cond.get("snomed", ""),
        clinical_status=cond.get("status", ""),
        onset_date=normalize_date_to_iso(cond.get("onset", "")),
    )


def _convert_immunization(imm: dict, source: str) -> ImmunizationRecord:
    """Convert immunization dict to ImmunizationRecord."""
    return ImmunizationRecord(
        source=source,
        vaccine_name=imm.get("name", ""),
        cvx_code=imm.get("cvx", ""),
        admin_date=normalize_date_to_iso(imm.get("date", "")),
        lot_number=imm.get("lot", ""),
        status=imm.get("status", ""),
    )


def _convert_allergy(allergy: dict, source: str) -> AllergyRecord:
    """Convert allergy dict to AllergyRecord."""
    return AllergyRecord(
        source=source,
        allergen=allergy.get("allergen", ""),
        reaction=allergy.get("reaction", ""),
        severity=allergy.get("severity", ""),
        status=allergy.get("status", "active"),
    )


def _convert_social_history(sh: dict, source: str) -> SocialHistoryRecord:
    """Convert social history dict to SocialHistoryRecord."""
    return SocialHistoryRecord(
        source=source,
        category=sh.get("category", ""),
        value=sh.get("value", ""),
        recorded_date=normalize_date_to_iso(sh.get("date", "")),
    )


def _convert_family_history(fh: dict, source: str) -> FamilyHistoryRecord:
    """Convert family history dict to FamilyHistoryRecord."""
    return FamilyHistoryRecord(
        source=source,
        relation=fh.get("relation", ""),
        condition=fh.get("condition", ""),
    )


def _convert_mental_status(ms: dict, source: str) -> MentalStatusRecord:
    """Convert mental status dict to MentalStatusRecord."""
    return MentalStatusRecord(
        source=source,
        instrument=ms.get("instrument", ""),
        question=ms.get("question", ""),
        answer=ms.get("answer", ""),
        score=ms.get("score"),
        total_score=ms.get("total_score"),
        recorded_date=normalize_date_to_iso(ms.get("date", "")),
    )


def _convert_clinical_note(note: dict, source: str) -> ClinicalNote:
    """Convert clinical note dict to ClinicalNote."""
    return ClinicalNote(
        source=source,
        note_type=note.get("type", ""),
        author=note.get("author", ""),
        note_date=normalize_date_to_iso(note.get("date", "")),
        content=note.get("content", ""),
    )


def _convert_procedure(proc: dict, source: str) -> ProcedureRecord:
    """Convert procedure dict to ProcedureRecord."""
    return ProcedureRecord(
        source=source,
        name=proc.get("name", ""),
        snomed_code=proc.get("snomed", ""),
        cpt_code=proc.get("cpt", ""),
        procedure_date=normalize_date_to_iso(proc.get("date", "")),
        provider=proc.get("provider", ""),
        facility=proc.get("facility", ""),
    )


def athena_to_unified(data: dict, source_name: str | None = None) -> UnifiedRecords:
    """Transform athenahealth extraction output into UnifiedRecords.

    Args:
        data: Output from process_athena_export().
        source_name: Optional source name override. If not provided, derived from input_dir.
    """
    source = _derive_source(data, source_name)
    records = UnifiedRecords(source=source)

    # Patient
    patient = data.get("patient")
    if patient:
        records.patient = _convert_patient(patient, source)

    # Convert all record types using helper functions
    records.documents = [_convert_document(d, source) for d in data.get("documents", [])]
    records.encounters = [_convert_encounter(e, source) for e in data.get("encounters", [])]
    records.lab_results = [_convert_lab_result(lab, source) for lab in data.get("lab_results", [])]
    records.vitals = [_convert_vital(v, source) for v in data.get("vitals", [])]
    records.medications = [_convert_medication(m, source) for m in data.get("medications", [])]
    records.conditions = [_convert_condition(c, source) for c in data.get("conditions", [])]
    records.immunizations = [
        _convert_immunization(i, source) for i in data.get("immunizations", [])
    ]
    records.allergies = [_convert_allergy(a, source) for a in data.get("allergies", [])]
    records.social_history = [
        _convert_social_history(s, source) for s in data.get("social_history", [])
    ]
    records.family_history = [
        _convert_family_history(f, source) for f in data.get("family_history", [])
    ]
    records.mental_status = [
        _convert_mental_status(m, source) for m in data.get("mental_status", [])
    ]
    records.clinical_notes = [
        _convert_clinical_note(n, source) for n in data.get("clinical_notes", [])
    ]
    records.procedures = [_convert_procedure(p, source) for p in data.get("procedures", [])]

    # Source assets (non-parsed files)
    input_dir = data.get("input_dir", "")
    if input_dir:
        records.source_assets = discover_source_assets(input_dir, source)

    return records
