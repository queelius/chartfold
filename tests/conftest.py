"""Shared test fixtures for chartfold tests."""

import pytest

from chartfold.db import ChartfoldDB
from chartfold.models import (
    ConditionRecord,
    DocumentRecord,
    EncounterRecord,
    ImagingReport,
    LabResult,
    MedicationRecord,
    PathologyReport,
    PatientRecord,
    ProcedureRecord,
    UnifiedRecords,
)


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite database with schema initialized."""
    db_path = str(tmp_path / "test.db")
    db = ChartfoldDB(db_path)
    db.init_schema()
    yield db
    db.close()


@pytest.fixture
def sample_unified_records():
    """Create a minimal UnifiedRecords for testing."""
    return UnifiedRecords(
        source="test_source",
        patient=PatientRecord(
            source="test_source",
            name="John Doe",
            date_of_birth="1975-06-15",
            gender="male",
        ),
        documents=[
            DocumentRecord(
                source="test_source",
                doc_id="DOC0001",
                doc_type="CDA",
                title="Test Document",
                encounter_date="2025-01-15",
            ),
        ],
        encounters=[
            EncounterRecord(
                source="test_source",
                source_doc_id="DOC0001",
                encounter_date="2025-01-15",
                encounter_type="office visit",
                facility="Test Hospital",
                provider="Dr. Smith",
            ),
        ],
        lab_results=[
            LabResult(
                source="test_source",
                test_name="CEA",
                test_loinc="2039-6",
                panel_name="CEA",
                value="5.8",
                value_numeric=5.8,
                unit="ng/mL",
                ref_range="0.0-3.0",
                interpretation="H",
                result_date="2025-01-15",
                status="final",
            ),
            LabResult(
                source="test_source",
                test_name="Hemoglobin",
                value="12.5",
                value_numeric=12.5,
                unit="g/dL",
                ref_range="13.0-17.0",
                interpretation="L",
                result_date="2025-01-15",
            ),
        ],
        medications=[
            MedicationRecord(
                source="test_source",
                name="Capecitabine 500mg",
                status="active",
                sig="2 tablets twice daily",
            ),
        ],
        conditions=[
            ConditionRecord(
                source="test_source",
                condition_name="Colon cancer",
                icd10_code="C18.9",
                clinical_status="active",
            ),
        ],
    )


@pytest.fixture
def loaded_db(tmp_db, sample_unified_records):
    """A database with sample data loaded."""
    tmp_db.load_source(sample_unified_records)
    return tmp_db


@pytest.fixture
def sample_epic_data():
    """Minimal Epic extraction output dict."""
    return {
        "source": "Epic",
        "patient": {
            "name": "John Doe",
            "date_of_birth": "19750615",
            "gender": "Male",
            "mrn": "123456",
            "address": "123 Main St, Springfield, IL, 62701",
            "phone": "555-0100",
        },
        "inventory": [
            {
                "doc_id": "DOC0001",
                "date": "N/A (cumulative)",
                "title": "Continuity of Care Document",
                "size_kb": 150,
                "sections": ["Results", "Active Problems"],
                "authors": [],
                "facility": "",
            },
            {
                "doc_id": "DOC0003",
                "date": "20250115",
                "title": "Visit Summary",
                "size_kb": 50,
                "sections": ["Progress Notes"],
                "authors": ["Dr. Smith"],
                "facility": "Anderson Hospital",
            },
        ],
        "cea_values": [
            {"date": "01/15/2025", "value": "5.8", "ref_range": "0.0-3.0"},
        ],
        "lab_results": [
            {
                "panel": "CBC w Diff",
                "date": "01/15/2025",
                "time": "10:30 AM CST",
                "components": [
                    {"name": "WBC", "value": "6.2", "ref_range": "4.5-11.0"},
                    {"name": "Hemoglobin", "value": "12.5", "ref_range": "13.0-17.0"},
                ],
                "result_type": "LAB CBC",
                "source_doc": "DOC0001",
            },
        ],
        "imaging_reports": [
            {
                "study": "CT CHEST ABDOMEN PELVIS W CONTRAST",
                "date": "01/10/2025",
                "time": "2:00 PM CST",
                "impression": "No evidence of recurrence.",
                "findings": "Normal exam.",
                "full_text": "CT CHEST...",
            },
        ],
        "pathology_reports": [
            {
                "panel": "SURGICAL PATHOLOGY",
                "date": "12/18/2025",
                "diagnosis": "Negative margins",
                "gross": "Liver segment",
                "microscopic": "No viable tumor",
                "full_text": "PATHOLOGY REPORT...",
            },
        ],
        "clinical_notes": [
            {
                "doc_id": "DOC0003",
                "date": "01/15/2025",
                "section": "Progress Notes",
                "text": "Patient seen for follow-up.",
            },
        ],
        "medications": [
            {
                "name": "Capecitabine 500mg",
                "rxnorm": "200328",
                "status": "active",
                "route": "oral",
                "dose": "1 {tbl}",
                "sig": "1 {tbl}, oral",
                "start_date": "",
                "stop_date": "",
            },
            {
                "name": "Ondansetron 8mg",
                "rxnorm": "312087",
                "status": "active",
                "route": "oral",
                "dose": "1 {tbl}",
                "sig": "1 {tbl}, oral",
                "start_date": "",
                "stop_date": "",
            },
        ],
        "problems": [
            {
                "name": "Colon cancer",
                "icd10": "C18.9",
                "snomed": "363406005",
                "status": "Active",
                "onset_date": "20211122",
            },
            {
                "name": "Hypertension",
                "icd10": "I10",
                "snomed": "38341003",
                "status": "Active",
                "onset_date": "20200101",
            },
        ],
        "vitals": [
            {"type": "bp_systolic", "value": 130.0, "unit": "mmHg", "date": "20250115"},
        ],
        "immunizations": [
            {
                "name": "Influenza",
                "cvx_code": "158",
                "date": "20241015",
                "status": "completed",
                "lot": "ABC123",
            },
        ],
        "allergies": [
            {
                "allergen": "Penicillin",
                "reaction": "Rash",
                "severity": "moderate",
                "status": "active",
            },
        ],
        "social_history": [
            {
                "category": "tobacco_smoking_status",
                "value": "Never smoker",
                "loinc": "72166-2",
                "date": "20250115",
            },
        ],
        "procedures": [
            {
                "name": "Colonoscopy",
                "code_value": "73761001",
                "code_system": "2.16.840.1.113883.6.96",
                "date": "20211122",
                "status": "completed",
                "provider": "John Smith",
                "source_doc": "DOC0003",
            },
        ],
        "family_history": [
            {
                "relation": "Father",
                "condition": "Colon cancer",
            },
            {
                "relation": "Mother",
                "condition": "Hypertension",
            },
        ],
        "encounter_timeline": [
            {
                "date": "20250115",
                "end_date": "20250115",
                "date_fmt": "01/15/2025",
                "doc_id": "DOC0003",
                "title": "Visit Summary",
                "encounter_type": "office visit",
                "reason": "Follow-up for colon cancer",
                "key_sections": ["Progress Notes"],
                "facility": "Anderson Hospital",
                "authors": ["Dr. Smith"],
            },
        ],
        "errors": [],
    }


@pytest.fixture
def sample_meditech_data():
    """Minimal MEDITECH extraction output dict."""
    return {
        "source": "MEDITECH",
        "fhir_data": {
            "patient": {
                "name": "Alexander Towell",
                "dob": "1975-06-15",
                "gender": "male",
                "id": "12345",
            },
            "observations": [
                {
                    "text": "Carcinoembryonic Antigen",
                    "display": "CEA",
                    "loinc": "2039-6",
                    "value": 5.8,
                    "unit": "ng/mL",
                    "ref_range": "0.0-3.0",
                    "date": "2025-06-30T13:25:00+00:00",
                    "date_iso": "2025-06-30",
                    "category": "laboratory",
                    "interpretation": "H",
                    "status": "final",
                    "notes": [],
                },
                {
                    "text": "Tobacco smoking status",
                    "display": "Tobacco smoking status",
                    "loinc": "72166-2",
                    "value": "Never smoker",
                    "unit": "",
                    "ref_range": "",
                    "date_iso": "2025-01-15",
                    "category": "social-history",
                    "status": "final",
                },
                {
                    "text": "PHQ-9 total score",
                    "display": "PHQ-9",
                    "loinc": "44261-6",
                    "value": 3,
                    "unit": "{score}",
                    "ref_range": "",
                    "date_iso": "2025-01-15",
                    "category": "survey",
                    "status": "final",
                },
            ],
            "conditions": [
                {
                    "text": "Colon cancer",
                    "icd_code": "C18.9",
                    "icd_system": "http://hl7.org/fhir/sid/icd-10-cm",
                    "clinical_status": "active",
                    "onset": "2021-11-22",
                },
            ],
            "medication_requests": [
                {
                    "text": "Capecitabine 500mg",
                    "rxnorm": "200328",
                    "status": "active",
                    "intent": "order",
                    "authored_on": "2025-01-15",
                    "authored_iso": "2025-01-15",
                    "dosage": ["Take 2 tablets twice daily"],
                },
            ],
            "encounters": [
                {
                    "type": "Office Visit",
                    "start": "2025-01-15T08:00:00+00:00",
                    "end": "2025-01-15T09:00:00+00:00",
                    "status": "finished",
                    "start_iso": "2025-01-15",
                    "participants": ["Practitioner/prac-123"],
                },
            ],
            "practitioners": {
                "Practitioner/prac-123": "Dr. Oncologist",
            },
            "resource_counts": {"Patient": 1, "Observation": 1, "Condition": 1},
            "diagnostic_reports": [
                {
                    "text": "CT Abdomen Pelvis",
                    "category": "Radiology",
                    "date": "2025-01-10",
                    "date_iso": "2025-01-10",
                    "status": "final",
                    "result_refs": [],
                    "presented_form": [],
                    "full_text": "No evidence of recurrence.",
                },
            ],
            "allergy_intolerances": [
                {
                    "allergen": "Sulfa drugs",
                    "reaction": "Hives",
                    "severity": "moderate",
                    "clinical_status": "active",
                    "onset": "",
                    "onset_iso": "",
                },
            ],
            "procedures": [
                {
                    "name": "Right hemicolectomy",
                    "snomed": "44441009",
                    "date": "2024-07-01",
                    "date_iso": "2024-07-01",
                    "status": "completed",
                },
            ],
        },
        "ccda_data": {
            "documents": [
                {
                    "filename": "abc123.xml",
                    "title": "Discharge Summary",
                    "encounter_date": "20250115",
                    "encounter_date_fmt": "01/15/2025",
                    "section_names": ["Labs"],
                    "lab_count": 1,
                    "note_count": 0,
                },
            ],
            "all_labs": [
                {
                    "test": "WBC",
                    "date_raw": "January 15, 2025",
                    "date_iso": "2025-01-15",
                    "value": "6.2",
                    "unit": "K/mm3",
                    "result_raw": "6.2 K/mm3",
                    "interpretation": "",
                    "ref_range": "4.5-11.0",
                    "comment": "",
                    "site": "",
                    "source_file": "abc123.xml",
                },
            ],
            "all_procedures": [],
            "all_problems": [{"name": "Hypertension", "source_file": "abc123.xml"}],
            "all_medications": [],
            "all_notes": [],
            "all_vitals": [
                {
                    "type": "weight",
                    "value": 105.7,
                    "unit": "kg",
                    "date_iso": "2021-11-22",
                    "ref_range": "",
                    "source_file": "abc123.xml",
                    "encounter_date": "20250115",
                },
                {
                    "type": "bp_systolic",
                    "value": 130.0,
                    "unit": "mmHg",
                    "date_iso": "2021-11-22",
                    "ref_range": "",
                    "source_file": "abc123.xml",
                    "encounter_date": "20250115",
                },
            ],
            "all_immunizations": [
                {
                    "name": "Influenza",
                    "date_raw": "October 15th, 2024",
                    "date_iso": "2024-10-15",
                    "lot": "ABC123",
                    "manufacturer": "Sanofi",
                    "source_file": "abc123.xml",
                },
            ],
            "all_allergies": [],
            "all_social_history": [
                {
                    "category": "tobacco_smoking_status",
                    "value": "Never smoker",
                    "loinc": "72166-2",
                    "date_iso": "2021-11-22",
                    "source_file": "abc123.xml",
                },
            ],
            "all_family_history": [
                {
                    "relation": "Father",
                    "condition": "Colon Cancer",
                    "source_file": "abc123.xml",
                },
            ],
            "all_mental_status": [
                {
                    "observation": "Little interest or pleasure",
                    "response": "Not at all",
                    "date_iso": "2021-11-22",
                    "source_file": "abc123.xml",
                    "encounter_date": "20250115",
                },
            ],
            "errors": [],
        },
        "toc_data": [],
    }


@pytest.fixture
def sample_athena_data():
    """Minimal athenahealth extraction output dict."""
    return {
        "patient": {
            "name": "Alexander Towell",
            "dob": "1975-06-15",
            "gender": "male",
            "mrn": "99999",
            "address": "123 Main St",
            "phone": "555-0100",
        },
        "documents": [
            {
                "doc_id": "ATHENA001",
                "title": "Ambulatory Summary",
                "encounter_date": "20250120",
            },
        ],
        "encounters": [
            {
                "date": "01/20/2025",
                "end_date": "01/20/2025",
                "type": "Office Visit",
                "facility": "SIHF Healthcare",
                "provider": "Dr. PCP",
                "reason": "Follow-up",
            },
        ],
        "lab_results": [
            {
                "test_name": "Glucose",
                "loinc": "2345-7",
                "panel_name": "Basic Metabolic Panel",
                "value": "105",
                "unit": "mg/dL",
                "ref_range": "70-100",
                "interpretation": "H",
                "date": "01/20/2025",
            },
            {
                "test_name": "Creatinine",
                "loinc": "2160-0",
                "panel_name": "Basic Metabolic Panel",
                "value": "0.9",
                "unit": "mg/dL",
                "ref_range": "0.7-1.3",
                "interpretation": "",
                "date": "01/20/2025",
            },
        ],
        "vitals": [
            {
                "type": "weight",
                "value": 82.5,
                "value_text": "82.5",
                "unit": "kg",
                "date": "01/20/2025",
            },
            {
                "type": "bp_systolic",
                "value": 130,
                "value_text": "130",
                "unit": "mmHg",
                "date": "01/20/2025",
            },
        ],
        "medications": [
            {
                "name": "Metformin 500mg",
                "rxnorm": "860975",
                "status": "active",
                "sig": "Take 1 tablet twice daily",
                "route": "oral",
                "start_date": "01/01/2024",
                "stop_date": "",
            },
        ],
        "conditions": [
            {
                "name": "Type 2 Diabetes",
                "icd10": "E11.9",
                "snomed": "44054006",
                "status": "active",
                "onset": "01/01/2024",
            },
        ],
        "immunizations": [
            {
                "name": "Influenza",
                "cvx": "158",
                "date": "10/15/2024",
                "lot": "ABC123",
                "status": "completed",
            },
        ],
        "allergies": [
            {
                "allergen": "Penicillin",
                "reaction": "Rash",
                "severity": "moderate",
                "status": "active",
            },
        ],
        "social_history": [
            {"category": "smoking", "value": "Never smoker", "date": "01/20/2025"},
        ],
        "family_history": [
            {"relation": "Father", "condition": "Heart Disease"},
        ],
        "mental_status": [
            {
                "instrument": "PHQ-9",
                "question": "Little interest",
                "answer": "Not at all",
                "score": 0,
                "total_score": 3,
                "date": "01/20/2025",
            },
        ],
        "clinical_notes": [
            {
                "type": "Assessment",
                "author": "Dr. PCP",
                "date": "01/20/2025",
                "content": "Diabetes stable.",
            },
        ],
        "procedures": [
            {
                "name": "Colonoscopy",
                "snomed": "",
                "cpt": "45378",
                "date": "11/22/2021",
                "provider": "Dr. GI",
                "facility": "Anderson",
            },
        ],
        "imaging_reports": [
            {"name": "CT, abdomen + pelvis, w/ contrast", "date": "12/08/2021"},
            {"name": "XR, chest", "date": "02/08/2022"},
        ],
    }


@pytest.fixture
def surgical_db(tmp_db):
    """A database with procedures, pathology, and imaging for surgical timeline testing."""
    records = UnifiedRecords(
        source="test_surgical",
        procedures=[
            ProcedureRecord(
                source="test_surgical",
                name="Right hemicolectomy",
                procedure_date="2024-07-01",
                provider="Dr. Surgeon",
                facility="Anderson Hospital",
            ),
            ProcedureRecord(
                source="test_surgical",
                name="Liver resection",
                procedure_date="2025-05-14",
                provider="Dr. Hepato",
                facility="Siteman Cancer Center",
            ),
        ],
        pathology_reports=[
            PathologyReport(
                source="test_surgical",
                report_date="2024-07-03",
                specimen="Right colon",
                diagnosis="Invasive adenocarcinoma, PNI, 4/14 LN+",
                staging="pT3N2a",
                margins="Positive deep/radial margin",
                lymph_nodes="4 of 14 positive",
            ),
            PathologyReport(
                source="test_surgical",
                report_date="2025-05-16",
                specimen="Liver segment 2",
                diagnosis="Metastatic adenocarcinoma, PNI",
                staging="",
                margins="Positive cauterized margin",
                lymph_nodes="",
            ),
        ],
        imaging_reports=[
            ImagingReport(
                source="test_surgical",
                study_name="CT Chest Abdomen Pelvis",
                modality="CT",
                study_date="2024-06-25",
                impression="Mass in right colon, suspicious.",
            ),
            ImagingReport(
                source="test_surgical",
                study_name="PET/CT Whole Body",
                modality="PET",
                study_date="2025-06-01",
                impression="Post-surgical changes in liver.",
            ),
        ],
    )
    tmp_db.load_source(records)
    return tmp_db
