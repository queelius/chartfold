"""Convert Epic parsed data (from sources.epic) into UnifiedRecords."""

from __future__ import annotations

import json

from chartfold.core.utils import derive_source_name, normalize_date_to_iso, try_parse_numeric
from chartfold.models import (
    AllergyRecord,
    ClinicalNote,
    ConditionRecord,
    DocumentRecord,
    EncounterRecord,
    FamilyHistoryRecord,
    ImagingReport,
    ImmunizationRecord,
    LabResult,
    MedicationRecord,
    PathologyReport,
    PatientRecord,
    ProcedureRecord,
    SocialHistoryRecord,
    UnifiedRecords,
    VitalRecord,
)
from chartfold.sources.assets import discover_source_assets
from chartfold.sources.epic import OID_SNOMED

# Keys explicitly consumed by the procedure adapter mapping.
# Everything else in the source dict gets captured as metadata JSON.
_PROC_MAPPED_KEYS = frozenset({"name", "code_value", "date", "status", "provider", "source_doc"})


def _is_valid_legacy_text(text: str, header_prefix: str) -> bool:
    """Check if a legacy text entry is valid (non-empty and not a header line)."""
    stripped = text.strip()
    return bool(stripped) and not stripped.startswith(header_prefix)


def _extract_snomed_code(proc: dict) -> str:
    """Extract SNOMED code from procedure if code system matches."""
    if proc.get("code_system", "") == OID_SNOMED:
        return str(proc.get("code_value", "") or "")
    return ""


def _format_provider_list(authors: list | str | None) -> str:
    """Format author list as comma-separated provider string."""
    if isinstance(authors, list):
        return ", ".join(authors)
    return ""


def _parser_counts(data: dict) -> dict[str, int]:
    """Count records in Epic parser output before adapter transformation."""
    lab_components = sum(len(p.get("components", [])) for p in data.get("lab_results", []))
    cea_count = len(data.get("cea_values", []))
    return {
        "patients": 1 if data.get("patient") else 0,
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
        "family_history": len(data.get("family_history", [])),
        "procedures": len(data.get("procedures", [])),
        "errors": len(data.get("errors", [])),
    }


def epic_to_unified(data: dict, source_name: str | None = None) -> UnifiedRecords:
    """Transform Epic extraction output into UnifiedRecords.

    Args:
        data: Output from process_epic_documents().
        source_name: Optional source name override. If not provided, derived from input_dir.
    """
    input_dir = data.get("input_dir", "")
    if source_name:
        source = source_name
    elif input_dir:
        source = derive_source_name(input_dir, "epic")
    else:
        source = "epic"
    records = UnifiedRecords(source=source)

    # Patient demographics
    patient_data = data.get("patient")
    if patient_data:
        records.patient = PatientRecord(
            source=source,
            name=patient_data.get("name", ""),
            date_of_birth=normalize_date_to_iso(patient_data.get("date_of_birth", "")),
            gender=patient_data.get("gender", ""),
            mrn=patient_data.get("mrn", ""),
            address=patient_data.get("address", ""),
            phone=patient_data.get("phone", ""),
        )

    # Documents
    for inv in data.get("inventory", []):
        records.documents.append(
            DocumentRecord(
                source=source,
                doc_id=inv["doc_id"],
                doc_type="CDA",
                title=inv.get("title", ""),
                encounter_date=normalize_date_to_iso(inv.get("date", "")),
                file_path=inv.get("file_path", ""),
                file_size_kb=inv.get("size_kb", 0),
            )
        )

    # Encounters
    for enc in data.get("encounter_timeline", []):
        records.encounters.append(
            EncounterRecord(
                source=source,
                source_doc_id=enc.get("doc_id", ""),
                encounter_date=normalize_date_to_iso(enc.get("date", "")),
                encounter_end=normalize_date_to_iso(enc.get("end_date", "")),
                encounter_type=enc.get("encounter_type", ""),
                facility=enc.get("facility", ""),
                provider=_format_provider_list(enc.get("authors")),
                reason=enc.get("reason", ""),
            )
        )

    # Lab results — explode panels into individual rows
    for panel in data.get("lab_results", []):
        panel_name = panel.get("panel", "")
        panel_date = normalize_date_to_iso(panel.get("date", ""))
        source_doc = panel.get("source_doc", "")
        for comp in panel.get("components", []):
            val = comp.get("value", "")
            records.lab_results.append(
                LabResult(
                    source=source,
                    source_doc_id=source_doc,
                    test_name=comp.get("name", ""),
                    panel_name=panel_name,
                    value=val,
                    value_numeric=try_parse_numeric(val),
                    ref_range=comp.get("ref_range", ""),
                    result_date=panel_date,
                )
            )

    # CEA values (also lab results, but pre-extracted)
    for cea in data.get("cea_values", []):
        val = cea.get("value", "")
        records.lab_results.append(
            LabResult(
                source=source,
                source_doc_id="",
                test_name="CEA",
                panel_name="CEA",
                value=val,
                value_numeric=try_parse_numeric(val),
                ref_range=cea.get("ref_range", ""),
                result_date=normalize_date_to_iso(cea.get("date", "")),
            )
        )

    # Imaging reports
    for img in data.get("imaging_reports", []):
        records.imaging_reports.append(
            ImagingReport(
                source=source,
                study_name=img.get("study", ""),
                modality=_guess_modality(img.get("study", "")),
                study_date=normalize_date_to_iso(img.get("date", "")),
                findings=img.get("findings", ""),
                impression=img.get("impression", ""),
                full_text=img.get("full_text", ""),
            )
        )

    # Pathology reports
    for path in data.get("pathology_reports", []):
        records.pathology_reports.append(
            PathologyReport(
                source=source,
                report_date=normalize_date_to_iso(path.get("date", "")),
                specimen=path.get("panel", ""),
                diagnosis=path.get("diagnosis", ""),
                gross_description=path.get("gross", ""),
                microscopic_description=path.get("microscopic", ""),
                full_text=path.get("full_text", ""),
            )
        )

    # Clinical notes
    for note in data.get("clinical_notes", []):
        records.clinical_notes.append(
            ClinicalNote(
                source=source,
                source_doc_id=note.get("doc_id", ""),
                note_type=note.get("section", ""),
                note_date=normalize_date_to_iso(note.get("date", "")),
                content=note.get("text", ""),
            )
        )

    # Medications (structured)
    for med in data.get("medications", []):
        if isinstance(med, str):
            if _is_valid_legacy_text(med, "Medications"):
                records.medications.append(
                    MedicationRecord(source=source, name=med.strip(), status="active")
                )
            continue
        records.medications.append(
            MedicationRecord(
                source=source,
                name=med.get("name", ""),
                rxnorm_code=med.get("rxnorm", ""),
                status=med.get("status", ""),
                sig=med.get("sig", ""),
                route=med.get("route", ""),
                start_date=normalize_date_to_iso(med.get("start_date", "")),
                stop_date=normalize_date_to_iso(med.get("stop_date", "")),
            )
        )

    # Conditions (structured)
    for cond in data.get("problems", []):
        if isinstance(cond, str):
            if _is_valid_legacy_text(cond, "Active Problems"):
                records.conditions.append(
                    ConditionRecord(
                        source=source, condition_name=cond.strip(), clinical_status="active"
                    )
                )
            continue
        records.conditions.append(
            ConditionRecord(
                source=source,
                condition_name=cond.get("name", ""),
                icd10_code=cond.get("icd10", ""),
                snomed_code=cond.get("snomed", ""),
                clinical_status=cond.get("status", "active"),
                onset_date=normalize_date_to_iso(cond.get("onset_date", "")),
            )
        )

    # Vitals
    for vital in data.get("vitals", []):
        records.vitals.append(
            VitalRecord(
                source=source,
                vital_type=vital.get("type", ""),
                value=vital.get("value"),
                unit=vital.get("unit", ""),
                recorded_date=normalize_date_to_iso(vital.get("date", "")),
            )
        )

    # Immunizations
    for imm in data.get("immunizations", []):
        records.immunizations.append(
            ImmunizationRecord(
                source=source,
                vaccine_name=imm.get("name", ""),
                cvx_code=imm.get("cvx_code", ""),
                admin_date=normalize_date_to_iso(imm.get("date", "")),
                lot_number=imm.get("lot", ""),
                status=imm.get("status", ""),
            )
        )

    # Allergies
    for allergy in data.get("allergies", []):
        records.allergies.append(
            AllergyRecord(
                source=source,
                allergen=allergy.get("allergen", ""),
                reaction=allergy.get("reaction", ""),
                severity=allergy.get("severity", ""),
                status=allergy.get("status", "active"),
            )
        )

    # Social History
    for sh in data.get("social_history", []):
        records.social_history.append(
            SocialHistoryRecord(
                source=source,
                category=sh.get("category", ""),
                value=sh.get("value", ""),
                recorded_date=normalize_date_to_iso(sh.get("date", "")),
            )
        )

    # Procedures
    for proc in data.get("procedures", []):
        # Fall back to document encounter_date when procedure has no date
        proc_date = normalize_date_to_iso(
            proc.get("date") or proc.get("encounter_date", "")
        )
        # Capture unmapped keys in metadata, normalizing dates for consistency
        extras = {}
        for k, v in proc.items():
            if k not in _PROC_MAPPED_KEYS and v:
                extras[k] = normalize_date_to_iso(v) if k.endswith("_date") else v
        records.procedures.append(
            ProcedureRecord(
                source=source,
                source_doc_id=proc.get("source_doc", ""),
                name=proc.get("name", ""),
                snomed_code=_extract_snomed_code(proc),
                procedure_date=proc_date,
                provider=proc.get("provider", ""),
                status=proc.get("status", ""),
                metadata=json.dumps(extras) if extras else "",
            )
        )

    # Family History
    for fh in data.get("family_history", []):
        records.family_history.append(
            FamilyHistoryRecord(
                source=source,
                relation=fh.get("relation", ""),
                condition=fh.get("condition", ""),
            )
        )

    # Source assets (non-parsed files)
    input_dir = data.get("input_dir", "")
    if input_dir:
        records.source_assets = discover_source_assets(input_dir, source)

    return records


def _guess_modality(study_name: str) -> str:
    """Guess imaging modality from study name."""
    name = study_name.upper()

    # Check for patterns that map to each modality
    # Order matters: more specific patterns first
    modality_patterns = [
        ("PET", ["PET"]),
        ("MRI", ["MRI", "MR "]),
        ("CT", ["CT ", "CT/"]),
        ("US", ["US ", "ULTRASOUND"]),
        ("XR", ["XR ", "X-RAY", "XRAY", "CHEST"]),
        ("MG", ["MAMM"]),
    ]

    # Special case: CT at start of name
    if name.startswith("CT"):
        return "CT"

    for modality, patterns in modality_patterns:
        if any(pattern in name for pattern in patterns):
            return modality

    return ""
