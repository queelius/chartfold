"""Convert MEDITECH parsed data (from sources.meditech + core.fhir) into UnifiedRecords."""

from __future__ import annotations

from chartfold.core.utils import (
    derive_source_name,
    normalize_date_to_iso,
    parse_iso_date,
    try_parse_numeric,
)
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
    MentalStatusRecord,
    PathologyReport,
    PatientRecord,
    ProcedureRecord,
    SocialHistoryRecord,
    UnifiedRecords,
    VitalRecord,
)
from chartfold.sources.assets import discover_source_assets, enrich_assets_from_meditech_toc
from chartfold.sources.meditech import (
    deduplicate_allergies,
    deduplicate_family_history,
    deduplicate_immunizations,
    deduplicate_labs,
    deduplicate_medications,
    deduplicate_mental_status,
    deduplicate_notes,
    deduplicate_problems,
    deduplicate_procedures,
    deduplicate_social_history,
    deduplicate_vitals,
)


def _parser_counts(data: dict) -> dict[str, int]:
    """Count records in MEDITECH parser output before adapter transformation.

    Returns combined FHIR + CCDA counts (pre-dedup) using the same keys
    as UnifiedRecords.counts(), so the stage comparison table works correctly.
    """
    fhir = data.get("fhir_data") or {}
    ccda = data.get("ccda_data") or {}

    observations = fhir.get("observations", [])
    fhir_lab_obs = sum(1 for o in observations if o.get("category") == "laboratory")
    fhir_vital_obs = sum(1 for o in observations if o.get("category") == "vital-signs")
    fhir_social_obs = sum(1 for o in observations if o.get("category") == "social-history")
    fhir_survey_obs = sum(1 for o in observations if o.get("category") == "survey")

    # Classify diagnostic reports by category for accurate counting
    diag_reports = fhir.get("diagnostic_reports", [])
    fhir_pathology = sum(
        1 for dr in diag_reports if "pathology" in dr.get("category", "").lower()
    )
    fhir_imaging = sum(
        1
        for dr in diag_reports
        if "radiology" in dr.get("category", "").lower()
        or "imaging" in dr.get("category", "").lower()
    )
    fhir_diag_notes = len(diag_reports) - fhir_pathology - fhir_imaging

    return {
        "patients": 1 if fhir.get("patient") else 0,
        "documents": len(ccda.get("documents", [])),
        "encounters": len(fhir.get("encounters", [])),
        "lab_results": fhir_lab_obs + len(ccda.get("all_labs", [])),
        "conditions": len(fhir.get("conditions", [])) + len(ccda.get("all_problems", [])),
        "medications": len(fhir.get("medication_requests", []))
        + len(ccda.get("all_medications", [])),
        "procedures": len(fhir.get("procedures", [])) + len(ccda.get("all_procedures", [])),
        "pathology_reports": fhir_pathology,
        "imaging_reports": fhir_imaging,
        "clinical_notes": fhir_diag_notes + len(ccda.get("all_notes", [])),
        "vitals": fhir_vital_obs + len(ccda.get("all_vitals", [])),
        "immunizations": len(fhir.get("immunizations", []))
        + len(ccda.get("all_immunizations", [])),
        "allergies": len(fhir.get("allergy_intolerances", []))
        + len(ccda.get("all_allergies", [])),
        "social_history": fhir_social_obs + len(ccda.get("all_social_history", [])),
        "family_history": len(ccda.get("all_family_history", [])),
        "mental_status": fhir_survey_obs + len(ccda.get("all_mental_status", [])),
    }


def meditech_to_unified(data: dict, source_name: str | None = None) -> UnifiedRecords:
    """Transform MEDITECH extraction output into UnifiedRecords.

    Args:
        data: Output from process_meditech_export().
        source_name: Optional source name override. If not provided, derived from input_dir.
    """
    input_dir = data.get("input_dir", "")
    if source_name:
        source = source_name
    elif input_dir:
        source = derive_source_name(input_dir, "meditech")
    else:
        source = "meditech"
    records = UnifiedRecords(source=source)

    fhir = data.get("fhir_data") or {}
    ccda = data.get("ccda_data") or {}

    # Patient from FHIR
    patient_data = fhir.get("patient")
    if patient_data:
        records.patient = PatientRecord(
            source=source,
            name=patient_data.get("name", ""),
            date_of_birth=patient_data.get("dob", ""),
            gender=patient_data.get("gender", ""),
            mrn=patient_data.get("id", ""),
        )

    # Documents from CCDA inventory
    for doc in ccda.get("documents", []):
        records.documents.append(
            DocumentRecord(
                source=source,
                doc_id=doc.get("filename", ""),
                doc_type="CCDA",
                title=doc.get("title", ""),
                encounter_date=normalize_date_to_iso(doc.get("encounter_date", "")),
                file_path=doc.get("file_path", ""),
            )
        )

    # Encounters from FHIR (with practitioner resolution)
    practitioners = fhir.get("practitioners", {})
    for enc in fhir.get("encounters", []):
        # Resolve provider from participant references
        provider = ""
        for ref in enc.get("participants", []):
            if ref in practitioners:
                provider = practitioners[ref]
                break
        records.encounters.append(
            EncounterRecord(
                source=source,
                encounter_date=enc.get("start_iso", ""),
                encounter_end=parse_iso_date(enc.get("end", "")),
                encounter_type=enc.get("type", ""),
                provider=provider,
            )
        )

    # Lab results — merge FHIR observations + CCDA labs, deduplicate
    _add_fhir_labs(records, fhir.get("observations", []), source)
    _add_ccda_labs(records, ccda.get("all_labs", []), source)

    # Conditions from FHIR
    for cond in fhir.get("conditions", []):
        records.conditions.append(
            ConditionRecord(
                source=source,
                condition_name=cond.get("text", ""),
                icd10_code=cond.get("icd_code", ""),
                clinical_status=cond.get("clinical_status", ""),
                onset_date=normalize_date_to_iso(cond.get("onset", "")),
            )
        )

    # Problems from CCDA (deduplicated)
    for prob in deduplicate_problems(ccda.get("all_problems", [])):
        # Only add if not already covered by a FHIR condition
        name_lower = prob["name"].lower().strip()
        existing = {c.condition_name.lower().strip() for c in records.conditions}
        if name_lower not in existing:
            records.conditions.append(
                ConditionRecord(
                    source=source,
                    condition_name=prob["name"],
                    clinical_status=prob.get("status", ""),
                )
            )

    # Medications from FHIR (with RxNorm)
    for med in fhir.get("medication_requests", []):
        records.medications.append(
            MedicationRecord(
                source=source,
                name=med.get("text", ""),
                rxnorm_code=med.get("rxnorm", ""),
                status=med.get("status", ""),
                sig="; ".join(med.get("dosage", [])),
                start_date=med.get("authored_iso", ""),
            )
        )

    # Medications from CCDA (deduplicated, add only new ones)
    existing_meds = {m.name.lower().strip() for m in records.medications}
    for med in deduplicate_medications(ccda.get("all_medications", [])):
        if med["name"].lower().strip() not in existing_meds:
            records.medications.append(
                MedicationRecord(
                    source=source,
                    name=med["name"],
                    sig=med.get("instructions", ""),
                    route=med.get("route", ""),
                    status=med.get("status", ""),
                )
            )

    # Procedures from FHIR
    for proc in fhir.get("procedures", []):
        records.procedures.append(
            ProcedureRecord(
                source=source,
                name=proc.get("name", ""),
                snomed_code=proc.get("snomed", ""),
                procedure_date=proc.get("date_iso", ""),
                status=proc.get("status", ""),
            )
        )

    # Procedures from CCDA (deduplicated, add only new ones)
    existing_procs = {
        (p.name.lower().strip(), p.procedure_date) for p in records.procedures
    }
    for proc in deduplicate_procedures(ccda.get("all_procedures", [])):
        key = (proc.get("name", "").lower().strip(), normalize_date_to_iso(proc.get("date_iso", "")))
        if key not in existing_procs:
            records.procedures.append(
                ProcedureRecord(
                    source=source,
                    name=proc.get("name", ""),
                    procedure_date=normalize_date_to_iso(proc.get("date_iso", "")),
                    provider=proc.get("provider", ""),
                    status=proc.get("status", ""),
                )
            )

    # Clinical notes from CCDA (deduplicated)
    for note in deduplicate_notes(ccda.get("all_notes", [])):
        records.clinical_notes.append(
            ClinicalNote(
                source=source,
                source_doc_id=note.get("source_file", ""),
                note_type=note.get("type", ""),
                note_date=normalize_date_to_iso(note.get("encounter_date", "")),
                content=note.get("text", ""),
            )
        )

    # Vitals — FHIR + CCDA
    _add_fhir_vitals(records, fhir.get("observations", []), source)
    for vital in deduplicate_vitals(ccda.get("all_vitals", [])):
        records.vitals.append(
            VitalRecord(
                source=source,
                vital_type=vital.get("type", ""),
                value=vital.get("value"),
                unit=vital.get("unit", ""),
                recorded_date=vital.get("date_iso", ""),
            )
        )

    # Immunizations — FHIR + CCDA
    _add_fhir_immunizations(records, fhir.get("immunizations", []), source)
    existing_imms = {(i.vaccine_name.lower(), i.admin_date) for i in records.immunizations}
    for imm in deduplicate_immunizations(ccda.get("all_immunizations", [])):
        key = (imm.get("name", "").lower(), imm.get("date_iso", ""))
        if key not in existing_imms:
            records.immunizations.append(
                ImmunizationRecord(
                    source=source,
                    vaccine_name=imm.get("name", ""),
                    admin_date=imm.get("date_iso", ""),
                    lot_number=imm.get("lot", ""),
                    status="completed",
                )
            )

    # DiagnosticReports from FHIR — classify by category
    _add_fhir_diagnostic_reports(records, fhir.get("diagnostic_reports", []), source)

    # Allergies from FHIR (first)
    _add_fhir_allergies(records, fhir.get("allergy_intolerances", []), source)

    # Allergies from CCDA (add only new ones)
    existing_allergens = {a.allergen.lower().strip() for a in records.allergies}
    for allergy in deduplicate_allergies(ccda.get("all_allergies", [])):
        if allergy.get("allergen", "").lower().strip() not in existing_allergens:
            records.allergies.append(
                AllergyRecord(
                    source=source,
                    allergen=allergy.get("allergen", ""),
                    reaction=allergy.get("reaction", ""),
                    severity=allergy.get("severity", ""),
                    status=allergy.get("status", "active"),
                )
            )

    # Social-history observations from FHIR
    _add_fhir_social_history_observations(records, fhir.get("observations", []), source)

    # Social History from CCDA
    for sh in deduplicate_social_history(ccda.get("all_social_history", [])):
        records.social_history.append(
            SocialHistoryRecord(
                source=source,
                category=sh.get("category", ""),
                value=sh.get("value", ""),
                recorded_date=sh.get("date_iso", ""),
            )
        )

    # Family History from CCDA
    for fh in deduplicate_family_history(ccda.get("all_family_history", [])):
        records.family_history.append(
            FamilyHistoryRecord(
                source=source,
                relation=fh.get("relation", ""),
                condition=fh.get("condition", ""),
            )
        )

    # Survey observations from FHIR (PHQ-9, etc.)
    _add_fhir_survey_observations(records, fhir.get("observations", []), source)

    # Mental Status from CCDA
    for ms in deduplicate_mental_status(ccda.get("all_mental_status", [])):
        records.mental_status.append(
            MentalStatusRecord(
                source=source,
                question=ms.get("observation", ""),
                answer=ms.get("response", ""),
                recorded_date=ms.get("date_iso", ""),
            )
        )

    # Source assets (non-parsed files like PDFs)
    input_dir = data.get("input_dir", "")
    if input_dir:
        records.source_assets = discover_source_assets(input_dir, source)
        # Enrich with MEDITECH TOC metadata
        toc_data = data.get("toc_data", [])
        if toc_data:
            records.source_assets = enrich_assets_from_meditech_toc(
                records.source_assets, toc_data, input_dir
            )
        # Enrich encounter_date from FHIR encounters using V-number mapping
        _enrich_asset_dates_from_fhir(records.source_assets, fhir.get("encounters", []))

    return records


def _enrich_asset_dates_from_fhir(assets: list, fhir_encounters: list[dict]) -> None:
    """Enrich source asset encounter_date from FHIR encounter identifiers.

    MEDITECH FHIR encounters have identifier.value = V-number (e.g., V00003676858)
    and period.start = encounter date. Source assets have encounter_id from directory
    names. This function populates encounter_date on assets by looking up the V-number.

    Modifies assets in place.
    """
    # Build V-number -> date mapping from FHIR encounters
    enc_id_to_date: dict[str, str] = {}
    for enc in fhir_encounters:
        enc_id = enc.get("encounter_id", "")
        date = enc.get("start_iso", "")
        if enc_id and date:
            enc_id_to_date[enc_id] = date

    if not enc_id_to_date:
        return

    # Enrich assets
    for asset in assets:
        if asset.encounter_date:
            continue  # Already has a date
        enc_id = asset.encounter_id
        if enc_id and enc_id in enc_id_to_date:
            asset.encounter_date = enc_id_to_date[enc_id]


def _add_fhir_labs(records: UnifiedRecords, observations: list[dict], source: str) -> None:
    """Add lab observations from FHIR data."""
    for obs in observations:
        # Only include lab-category observations
        if obs.get("category") != "laboratory":
            continue
        val = obs.get("value")
        val_str = str(val) if val is not None else ""
        val_numeric = None
        if isinstance(val, (int, float)):
            val_numeric = float(val)
        elif isinstance(val, str):
            val_numeric = try_parse_numeric(val)

        records.lab_results.append(
            LabResult(
                source=source,
                test_name=obs.get("text", ""),
                test_loinc=obs.get("loinc", ""),
                value=val_str,
                value_numeric=val_numeric,
                unit=obs.get("unit", ""),
                ref_range=obs.get("ref_range", ""),
                interpretation=obs.get("interpretation", ""),
                result_date=obs.get("date_iso", ""),
                status=obs.get("status", ""),
            )
        )


def _add_ccda_labs(records: UnifiedRecords, all_labs: list[dict], source: str) -> None:
    """Add lab results from CCDA data (deduplicated)."""
    deduped = deduplicate_labs(all_labs)
    # Build set of existing (test, date, value) to avoid FHIR duplicates
    existing = {
        (lr.test_name.lower().strip(), lr.result_date, lr.value) for lr in records.lab_results
    }

    for lab in deduped:
        key = (lab["test"].lower().strip(), lab.get("date_iso", ""), lab.get("value", ""))
        if key in existing:
            continue
        existing.add(key)

        val = lab.get("value", "")
        records.lab_results.append(
            LabResult(
                source=source,
                source_doc_id=lab.get("source_file", ""),
                test_name=lab.get("test", ""),
                value=val,
                value_numeric=try_parse_numeric(val),
                unit=lab.get("unit", ""),
                ref_range=lab.get("ref_range", ""),
                interpretation=lab.get("interpretation", ""),
                result_date=lab.get("date_iso", ""),
            )
        )


def _add_fhir_vitals(records: UnifiedRecords, observations: list[dict], source: str) -> None:
    """Add vital-signs observations from FHIR data."""
    LOINC_VITAL_MAP = {
        "8480-6": "bp_systolic",
        "8462-4": "bp_diastolic",
        "8867-4": "heart_rate",
        "8310-5": "temperature",
        "9279-1": "respiratory_rate",
        "59408-5": "spo2",
        "3141-9": "weight",
        "29463-7": "weight",
        "8302-2": "height",
        "39156-5": "bmi",
    }
    for obs in observations:
        if obs.get("category") != "vital-signs":
            continue
        loinc = obs.get("loinc", "")
        vital_type = LOINC_VITAL_MAP.get(loinc, "")
        if not vital_type:
            continue
        val = obs.get("value")
        if val is None:
            continue
        records.vitals.append(
            VitalRecord(
                source=source,
                vital_type=vital_type,
                value=float(val) if isinstance(val, (int, float)) else None,
                value_text=str(val),
                unit=obs.get("unit", ""),
                recorded_date=obs.get("date_iso", ""),
            )
        )


def _add_fhir_immunizations(
    records: UnifiedRecords, immunizations: list[dict], source: str
) -> None:
    """Add immunizations from FHIR data."""
    for imm in immunizations:
        records.immunizations.append(
            ImmunizationRecord(
                source=source,
                vaccine_name=imm.get("name", ""),
                cvx_code=imm.get("cvx_code", ""),
                admin_date=imm.get("date_iso", ""),
                lot_number=imm.get("lot", ""),
                status=imm.get("status", ""),
            )
        )


_IMAGING_TERMS = frozenset([
    "x-ray", "ct ", "computed tomography", "mri ", "magnetic resonance",
    "pet ", "positron emission", "ultrasound", "nuclear medicine",
    "mammogra", "fluoroscop", "angiogra", "echocardiogra",
])


def _is_imaging_report_name(name_lower: str) -> bool:
    """Check if a DiagnosticReport name refers to an actual imaging study."""
    return any(term in name_lower for term in _IMAGING_TERMS)


def _add_fhir_diagnostic_reports(
    records: UnifiedRecords, diagnostic_reports: list[dict], source: str
) -> None:
    """Classify FHIR DiagnosticReports by category into PathologyReport, ImagingReport, or ClinicalNote.

    LAB reports are skipped — their individual results are already captured via
    FHIR Observations parsed as lab_results. Cardiology and other categories
    are stored as clinical notes only if they have meaningful content.
    """
    for dr in diagnostic_reports:
        cat = dr.get("category", "").lower()
        name = dr.get("text", "")
        date = dr.get("date_iso", "")
        full_text = dr.get("full_text", "")

        if "pathology" in cat:
            records.pathology_reports.append(
                PathologyReport(
                    source=source,
                    report_date=date,
                    specimen=name,
                    full_text=full_text,
                )
            )
        elif "radiology" in cat or "imaging" in cat:
            # MEDITECH labels ALL non-lab/non-pathology reports as "Radiology",
            # including office visits, H&Ps, op notes, etc. Use code.text to
            # distinguish actual imaging from non-imaging reports.
            name_lower = name.lower()
            if _is_imaging_report_name(name_lower):
                records.imaging_reports.append(
                    ImagingReport(
                        source=source,
                        study_name=name,
                        study_date=date,
                        full_text=full_text,
                    )
                )
            elif full_text or name:
                records.clinical_notes.append(
                    ClinicalNote(
                        source=source,
                        note_type=name or "Diagnostic Report",
                        note_date=date,
                        content=full_text,
                    )
                )
        elif cat == "lab":
            # LAB DiagnosticReports are reference containers — individual results
            # are already captured via FHIR Observations as lab_results.
            continue
        else:
            # Cardiology, other categories: treat as clinical note
            if full_text or name:
                records.clinical_notes.append(
                    ClinicalNote(
                        source=source,
                        note_type=name or "Diagnostic Report",
                        note_date=date,
                        content=full_text,
                    )
                )


def _add_fhir_allergies(
    records: UnifiedRecords, allergy_intolerances: list[dict], source: str
) -> None:
    """Add FHIR AllergyIntolerance resources as AllergyRecords."""
    for ai in allergy_intolerances:
        allergen = ai.get("allergen", "")
        if not allergen:
            continue
        records.allergies.append(
            AllergyRecord(
                source=source,
                allergen=allergen,
                reaction=ai.get("reaction", ""),
                severity=ai.get("severity", ""),
                status=ai.get("clinical_status", "active"),
                onset_date=ai.get("onset_iso", ""),
            )
        )


def _add_fhir_social_history_observations(
    records: UnifiedRecords, observations: list[dict], source: str
) -> None:
    """Add social-history category FHIR observations as SocialHistoryRecords."""
    for obs in observations:
        if obs.get("category") != "social-history":
            continue
        val = obs.get("value")
        records.social_history.append(
            SocialHistoryRecord(
                source=source,
                category=obs.get("text", ""),
                value=str(val) if val is not None else "",
                recorded_date=obs.get("date_iso", ""),
            )
        )


def _add_fhir_survey_observations(
    records: UnifiedRecords, observations: list[dict], source: str
) -> None:
    """Add survey category FHIR observations (PHQ-9, etc.) as MentalStatusRecords."""
    for obs in observations:
        if obs.get("category") != "survey":
            continue
        val = obs.get("value")
        score = None
        if isinstance(val, (int, float)):
            score = int(val)
        records.mental_status.append(
            MentalStatusRecord(
                source=source,
                instrument=obs.get("text", ""),
                question=obs.get("display", ""),
                answer=str(val) if val is not None else "",
                score=score,
                recorded_date=obs.get("date_iso", ""),
            )
        )
