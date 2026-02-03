"""Unified data model for clinical records from all EHR sources.

Each dataclass maps 1:1 to a SQLite table. The UnifiedRecords container
holds all records from a single source load, ready for insertion.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PatientRecord:
    """Patient demographics."""

    source: str
    name: str = ""
    date_of_birth: str = ""  # ISO YYYY-MM-DD
    gender: str = ""
    mrn: str = ""
    address: str = ""
    phone: str = ""


@dataclass
class DocumentRecord:
    """Source file inventory — one row per parsed document."""

    source: str
    doc_id: str  # Unique within source (filename, UUID, etc.)
    doc_type: str = ""  # CDA, FHIR, NDJSON, PDF
    title: str = ""
    encounter_date: str = ""  # ISO YYYY-MM-DD
    file_path: str = ""
    file_size_kb: int = 0


@dataclass
class EncounterRecord:
    """A clinical encounter (visit, admission, etc.)."""

    source: str
    source_doc_id: str = ""
    encounter_date: str = ""  # ISO YYYY-MM-DD
    encounter_end: str = ""  # ISO YYYY-MM-DD
    encounter_type: str = ""  # office visit, inpatient, ED, etc.
    facility: str = ""
    provider: str = ""
    reason: str = ""
    discharge_disposition: str = ""


@dataclass
class LabResult:
    """A single lab test result."""

    source: str
    source_doc_id: str = ""
    test_name: str = ""
    test_loinc: str = ""
    panel_name: str = ""
    value: str = ""  # Original text (handles "<0.5", "positive", etc.)
    value_numeric: float | None = None  # Parsed numeric (NULL when not parseable)
    unit: str = ""
    ref_range: str = ""
    interpretation: str = ""  # H, L, N, A, etc.
    result_date: str = ""  # ISO YYYY-MM-DD
    status: str = ""  # final, preliminary, etc.


@dataclass
class VitalRecord:
    """A single vital sign reading."""

    source: str
    source_doc_id: str = ""
    vital_type: str = ""  # bp_systolic, bp_diastolic, weight, height, temp, hr, rr, spo2, bmi
    value: float | None = None
    value_text: str = ""  # Original text for non-numeric
    unit: str = ""
    recorded_date: str = ""  # ISO YYYY-MM-DD


@dataclass
class MedicationRecord:
    """A medication entry (active, historical, or discharge)."""

    source: str
    source_doc_id: str = ""
    name: str = ""
    rxnorm_code: str = ""
    status: str = ""  # active, completed, stopped, etc.
    sig: str = ""  # Dosage instructions
    route: str = ""
    start_date: str = ""  # ISO YYYY-MM-DD
    stop_date: str = ""  # ISO YYYY-MM-DD
    prescriber: str = ""


@dataclass
class ConditionRecord:
    """A clinical condition / diagnosis."""

    source: str
    source_doc_id: str = ""
    condition_name: str = ""
    icd10_code: str = ""
    snomed_code: str = ""
    clinical_status: str = ""  # active, resolved, inactive
    onset_date: str = ""  # ISO YYYY-MM-DD
    resolved_date: str = ""  # ISO YYYY-MM-DD
    category: str = ""  # problem-list-item, encounter-diagnosis


@dataclass
class ProcedureRecord:
    """A clinical procedure."""

    source: str
    source_doc_id: str = ""
    name: str = ""
    snomed_code: str = ""
    cpt_code: str = ""
    procedure_date: str = ""  # ISO YYYY-MM-DD
    provider: str = ""
    facility: str = ""
    operative_note: str = ""
    status: str = ""


@dataclass
class PathologyReport:
    """A pathology report, optionally linked to a procedure."""

    source: str
    source_doc_id: str = ""
    procedure_id: int | None = None  # FK to procedures table
    report_date: str = ""  # ISO YYYY-MM-DD
    specimen: str = ""
    diagnosis: str = ""
    gross_description: str = ""
    microscopic_description: str = ""
    staging: str = ""
    margins: str = ""
    lymph_nodes: str = ""
    full_text: str = ""


@dataclass
class ImagingReport:
    """An imaging study report."""

    source: str
    source_doc_id: str = ""
    study_name: str = ""
    modality: str = ""  # CT, MRI, US, XR, PET, etc.
    study_date: str = ""  # ISO YYYY-MM-DD
    ordering_provider: str = ""
    findings: str = ""
    impression: str = ""
    full_text: str = ""


@dataclass
class ClinicalNote:
    """A clinical note (progress note, H&P, discharge summary, etc.)."""

    source: str
    source_doc_id: str = ""
    note_type: str = ""  # progress, h_and_p, discharge, consult, etc.
    author: str = ""
    note_date: str = ""  # ISO YYYY-MM-DD
    content: str = ""
    content_format: str = "text"  # text, html


@dataclass
class ImmunizationRecord:
    """A vaccination record."""

    source: str
    source_doc_id: str = ""
    vaccine_name: str = ""
    cvx_code: str = ""
    admin_date: str = ""  # ISO YYYY-MM-DD
    lot_number: str = ""
    site: str = ""
    status: str = ""


@dataclass
class AllergyRecord:
    """An allergy or adverse reaction."""

    source: str
    source_doc_id: str = ""
    allergen: str = ""
    reaction: str = ""
    severity: str = ""  # mild, moderate, severe
    status: str = ""  # active, inactive
    onset_date: str = ""  # ISO YYYY-MM-DD


@dataclass
class SocialHistoryRecord:
    """A social history entry (smoking, alcohol, occupation, etc.)."""

    source: str
    source_doc_id: str = ""
    category: str = ""  # smoking, alcohol, drug_use, occupation, etc.
    value: str = ""
    recorded_date: str = ""  # ISO YYYY-MM-DD


@dataclass
class FamilyHistoryRecord:
    """A family history entry."""

    source: str
    source_doc_id: str = ""
    relation: str = ""  # mother, father, sibling, etc.
    condition: str = ""
    age_at_onset: str = ""
    deceased: bool | None = None


@dataclass
class MentalStatusRecord:
    """A mental health screening result (PHQ-9, PHQ-2, GAD-7, etc.)."""

    source: str
    source_doc_id: str = ""
    instrument: str = ""  # PHQ-9, PHQ-2, GAD-7, etc.
    question: str = ""
    answer: str = ""
    score: int | None = None
    total_score: int | None = None
    recorded_date: str = ""  # ISO YYYY-MM-DD


@dataclass
class UnifiedRecords:
    """Container for all records from a single source load.

    Pass to ChartfoldDB.load_source() to insert into the database.
    """

    source: str  # e.g., "epic_anderson", "meditech_anderson", "athena_sihf"
    patient: PatientRecord | None = None
    documents: list[DocumentRecord] = field(default_factory=list)
    encounters: list[EncounterRecord] = field(default_factory=list)
    lab_results: list[LabResult] = field(default_factory=list)
    vitals: list[VitalRecord] = field(default_factory=list)
    medications: list[MedicationRecord] = field(default_factory=list)
    conditions: list[ConditionRecord] = field(default_factory=list)
    procedures: list[ProcedureRecord] = field(default_factory=list)
    pathology_reports: list[PathologyReport] = field(default_factory=list)
    imaging_reports: list[ImagingReport] = field(default_factory=list)
    clinical_notes: list[ClinicalNote] = field(default_factory=list)
    immunizations: list[ImmunizationRecord] = field(default_factory=list)
    allergies: list[AllergyRecord] = field(default_factory=list)
    social_history: list[SocialHistoryRecord] = field(default_factory=list)
    family_history: list[FamilyHistoryRecord] = field(default_factory=list)
    mental_status: list[MentalStatusRecord] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """Return record counts per table, matching the keys from db.load_source()."""
        return {
            "patients": 1 if self.patient else 0,
            "documents": len(self.documents),
            "encounters": len(self.encounters),
            "lab_results": len(self.lab_results),
            "vitals": len(self.vitals),
            "medications": len(self.medications),
            "conditions": len(self.conditions),
            "procedures": len(self.procedures),
            "pathology_reports": len(self.pathology_reports),
            "imaging_reports": len(self.imaging_reports),
            "clinical_notes": len(self.clinical_notes),
            "immunizations": len(self.immunizations),
            "allergies": len(self.allergies),
            "social_history": len(self.social_history),
            "family_history": len(self.family_history),
            "mental_status": len(self.mental_status),
        }
