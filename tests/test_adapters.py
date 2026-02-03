"""Tests for chartfold.adapters — source-to-UnifiedRecords bridges."""

import pytest

from chartfold.adapters.athena_adapter import athena_to_unified
from chartfold.adapters.epic_adapter import epic_to_unified, _guess_modality
from chartfold.adapters.meditech_adapter import meditech_to_unified


class TestEpicAdapter:
    def test_source_name(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        assert records.source == "epic_anderson"

    def test_documents(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        assert len(records.documents) == 2
        assert records.documents[0].doc_id == "DOC0001"

    def test_encounters(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        assert len(records.encounters) == 1
        assert records.encounters[0].facility == "Anderson Hospital"

    def test_lab_panel_explosion(self, sample_epic_data):
        """Panels should be exploded into individual lab result rows."""
        records = epic_to_unified(sample_epic_data)
        # 2 from panel components (WBC, Hemoglobin) + 1 from CEA values
        lab_names = [lr.test_name for lr in records.lab_results]
        assert "WBC" in lab_names
        assert "Hemoglobin" in lab_names
        assert "CEA" in lab_names

    def test_lab_numeric_parsing(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        cea = next(lr for lr in records.lab_results if lr.test_name == "CEA")
        assert cea.value_numeric == 5.8
        assert cea.value == "5.8"

    def test_lab_date_conversion(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        cea = next(lr for lr in records.lab_results if lr.test_name == "CEA")
        assert cea.result_date == "2025-01-15"  # Converted from MM/DD/YYYY

    def test_imaging_reports(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        assert len(records.imaging_reports) == 1
        assert records.imaging_reports[0].modality == "CT"

    def test_pathology_reports(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        assert len(records.pathology_reports) == 1
        assert "margins" in records.pathology_reports[0].diagnosis.lower()

    def test_clinical_notes(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        assert len(records.clinical_notes) == 1
        assert records.clinical_notes[0].note_type == "Progress Notes"

    def test_medications_from_text(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        med_names = [m.name for m in records.medications]
        assert "Capecitabine 500mg" in med_names
        assert "Ondansetron 8mg" in med_names

    def test_problems_to_conditions(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        cond_names = [c.condition_name for c in records.conditions]
        assert "Colon cancer" in cond_names
        assert "Hypertension" in cond_names

    def test_vitals(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        assert len(records.vitals) == 1
        assert records.vitals[0].vital_type == "bp_systolic"
        assert records.vitals[0].value == 130.0

    def test_immunizations(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        assert len(records.immunizations) == 1
        assert records.immunizations[0].vaccine_name == "Influenza"
        assert records.immunizations[0].cvx_code == "158"

    def test_allergies(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        assert len(records.allergies) == 1
        assert records.allergies[0].allergen == "Penicillin"

    def test_social_history(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        assert len(records.social_history) == 1
        assert records.social_history[0].category == "tobacco_smoking_status"

    def test_procedures(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        assert len(records.procedures) == 1
        assert "Colonoscopy" in records.procedures[0].name
        assert records.procedures[0].snomed_code == "73761001"


class TestGuessModality:
    def test_ct(self):
        assert _guess_modality("CT CHEST ABDOMEN PELVIS W CONTRAST") == "CT"

    def test_mri(self):
        assert _guess_modality("MRI BRAIN W/WO CONTRAST") == "MRI"

    def test_pet(self):
        assert _guess_modality("PET/CT WHOLE BODY") == "PET"

    def test_xray(self):
        assert _guess_modality("XR CHEST 2 VIEW") == "XR"

    def test_us(self):
        assert _guess_modality("US ABDOMEN COMPLETE") == "US"

    def test_unknown(self):
        assert _guess_modality("SOME OTHER STUDY") == ""


class TestMeditechAdapter:
    def test_source_name(self, sample_meditech_data):
        records = meditech_to_unified(sample_meditech_data)
        assert records.source == "meditech_anderson"

    def test_patient_from_fhir(self, sample_meditech_data):
        records = meditech_to_unified(sample_meditech_data)
        assert records.patient is not None
        assert records.patient.name == "Alexander Towell"
        assert records.patient.gender == "male"

    def test_fhir_labs(self, sample_meditech_data):
        records = meditech_to_unified(sample_meditech_data)
        cea = next(
            (lr for lr in records.lab_results if "CEA" in lr.test_name.upper() or "carcinoembryonic" in lr.test_name.lower()),
            None,
        )
        assert cea is not None
        assert cea.value_numeric == 5.8
        assert cea.test_loinc == "2039-6"

    def test_ccda_labs_merged(self, sample_meditech_data):
        records = meditech_to_unified(sample_meditech_data)
        wbc = next((lr for lr in records.lab_results if lr.test_name == "WBC"), None)
        assert wbc is not None
        assert wbc.value == "6.2"

    def test_fhir_conditions(self, sample_meditech_data):
        records = meditech_to_unified(sample_meditech_data)
        cancer = next((c for c in records.conditions if "cancer" in c.condition_name.lower()), None)
        assert cancer is not None
        assert cancer.icd10_code == "C18.9"
        assert cancer.clinical_status == "active"

    def test_ccda_problems_merged(self, sample_meditech_data):
        records = meditech_to_unified(sample_meditech_data)
        htn = next((c for c in records.conditions if "hypertension" in c.condition_name.lower()), None)
        assert htn is not None

    def test_medications(self, sample_meditech_data):
        records = meditech_to_unified(sample_meditech_data)
        assert len(records.medications) >= 1
        cap = next((m for m in records.medications if "Capecitabine" in m.name), None)
        assert cap is not None
        assert cap.status == "active"

    def test_encounters(self, sample_meditech_data):
        records = meditech_to_unified(sample_meditech_data)
        assert len(records.encounters) == 1
        assert records.encounters[0].encounter_date == "2025-01-15"

    def test_documents(self, sample_meditech_data):
        records = meditech_to_unified(sample_meditech_data)
        assert len(records.documents) == 1
        assert records.documents[0].doc_type == "CCDA"

    def test_ccda_vitals(self, sample_meditech_data):
        records = meditech_to_unified(sample_meditech_data)
        assert len(records.vitals) >= 2
        weight = next((v for v in records.vitals if v.vital_type == "weight"), None)
        assert weight is not None
        assert weight.value == 105.7
        assert weight.unit == "kg"

    def test_ccda_immunizations(self, sample_meditech_data):
        records = meditech_to_unified(sample_meditech_data)
        assert len(records.immunizations) >= 1
        flu = next((i for i in records.immunizations if "Influenza" in i.vaccine_name), None)
        assert flu is not None
        assert flu.admin_date == "2024-10-15"

    def test_ccda_social_history(self, sample_meditech_data):
        records = meditech_to_unified(sample_meditech_data)
        assert len(records.social_history) >= 1
        smoking = next((s for s in records.social_history if s.category == "tobacco_smoking_status"), None)
        assert smoking is not None
        assert smoking.value == "Never smoker"

    def test_ccda_family_history(self, sample_meditech_data):
        records = meditech_to_unified(sample_meditech_data)
        assert len(records.family_history) >= 1
        father = next((f for f in records.family_history if f.relation == "Father"), None)
        assert father is not None
        assert father.condition == "Colon Cancer"

    def test_ccda_mental_status(self, sample_meditech_data):
        records = meditech_to_unified(sample_meditech_data)
        assert len(records.mental_status) >= 1
        ms = records.mental_status[0]
        assert "interest" in ms.question.lower() or "pleasure" in ms.question.lower()
        assert ms.answer == "Not at all"

    def test_fhir_vitals_from_observations(self, sample_meditech_data):
        """FHIR vital-signs category observations should be mapped to vitals."""
        sample_meditech_data["fhir_data"]["observations"].append({
            "text": "Heart Rate",
            "display": "Heart Rate",
            "loinc": "8867-4",
            "value": 72,
            "unit": "bpm",
            "date_iso": "2025-01-15",
            "category": "vital-signs",
            "status": "final",
        })
        records = meditech_to_unified(sample_meditech_data)
        hr = next((v for v in records.vitals if v.vital_type == "heart_rate"), None)
        assert hr is not None
        assert hr.value == 72.0
        assert hr.unit == "bpm"

    def test_fhir_immunizations(self, sample_meditech_data):
        """FHIR immunizations should be added."""
        sample_meditech_data["fhir_data"]["immunizations"] = [
            {
                "name": "Tdap",
                "cvx_code": "115",
                "date_iso": "2022-05-01",
                "lot": "LOT555",
                "status": "completed",
            },
        ]
        records = meditech_to_unified(sample_meditech_data)
        tdap = next((i for i in records.immunizations if i.vaccine_name == "Tdap"), None)
        assert tdap is not None
        assert tdap.cvx_code == "115"
        assert tdap.lot_number == "LOT555"


class TestDateNormalization:
    """Test that adapters correctly normalize dates to ISO format."""

    def test_epic_mm_dd_yyyy(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        # Lab dates from Epic panels come as MM/DD/YYYY
        wbc = next((lr for lr in records.lab_results if lr.test_name == "WBC"), None)
        assert wbc is not None
        assert wbc.result_date == "2025-01-15"

    def test_meditech_fhir_iso(self, sample_meditech_data):
        records = meditech_to_unified(sample_meditech_data)
        enc = records.encounters[0]
        assert enc.encounter_date == "2025-01-15"

    def test_athena_mm_dd_yyyy(self, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        enc = records.encounters[0]
        assert enc.encounter_date == "2025-01-20"


class TestAthenaAdapter:
    def test_source_name(self, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        assert records.source == "athena_sihf"

    def test_patient(self, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        assert records.patient.name == "Alexander Towell"
        assert records.patient.gender == "male"
        assert records.patient.mrn == "99999"

    def test_documents(self, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        assert len(records.documents) == 1
        assert records.documents[0].encounter_date == "2025-01-20"

    def test_encounters(self, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        assert len(records.encounters) == 1
        assert records.encounters[0].facility == "SIHF Healthcare"
        assert records.encounters[0].provider == "Dr. PCP"

    def test_lab_results(self, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        assert len(records.lab_results) == 2
        glucose = next(lr for lr in records.lab_results if lr.test_name == "Glucose")
        assert glucose.value_numeric == 105.0
        assert glucose.unit == "mg/dL"
        assert glucose.test_loinc == "2345-7"
        assert glucose.interpretation == "H"
        assert glucose.result_date == "2025-01-20"

    def test_vitals(self, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        assert len(records.vitals) == 2
        weight = next(v for v in records.vitals if v.vital_type == "weight")
        assert weight.value == 82.5

    def test_medications(self, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        assert len(records.medications) == 1
        met = records.medications[0]
        assert "Metformin" in met.name
        assert met.rxnorm_code == "860975"
        assert met.status == "active"
        assert met.start_date == "2024-01-01"

    def test_conditions(self, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        assert len(records.conditions) == 1
        diab = records.conditions[0]
        assert "Diabetes" in diab.condition_name
        assert diab.icd10_code == "E11.9"
        assert diab.snomed_code == "44054006"

    def test_immunizations(self, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        assert len(records.immunizations) == 1
        flu = records.immunizations[0]
        assert flu.vaccine_name == "Influenza"
        assert flu.admin_date == "2024-10-15"

    def test_allergies(self, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        assert len(records.allergies) == 1
        assert records.allergies[0].allergen == "Penicillin"

    def test_social_history(self, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        assert len(records.social_history) == 1
        assert records.social_history[0].category == "smoking"

    def test_family_history(self, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        assert len(records.family_history) == 1
        assert records.family_history[0].relation == "Father"

    def test_mental_status(self, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        assert len(records.mental_status) == 1
        ms = records.mental_status[0]
        assert ms.instrument == "PHQ-9"
        assert ms.score == 0
        assert ms.total_score == 3

    def test_clinical_notes(self, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        assert len(records.clinical_notes) == 1
        assert records.clinical_notes[0].note_type == "Assessment"

    def test_procedures(self, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        assert len(records.procedures) == 1
        proc = records.procedures[0]
        assert "Colonoscopy" in proc.name
        assert proc.cpt_code == "45378"
        assert proc.procedure_date == "2021-11-22"

    def test_empty_data(self):
        records = athena_to_unified({})
        assert records.source == "athena_sihf"
        assert records.patient is None
        assert len(records.lab_results) == 0
