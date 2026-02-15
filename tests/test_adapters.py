"""Tests for chartfold.adapters — source-to-UnifiedRecords bridges."""

from chartfold.adapters.athena_adapter import athena_to_unified
from chartfold.adapters.epic_adapter import epic_to_unified, _guess_modality
from chartfold.adapters.meditech_adapter import meditech_to_unified, _is_imaging_report_name


class TestEpicAdapter:
    def test_source_name_fallback(self, sample_epic_data):
        """Without input_dir, fallback to generic source name."""
        records = epic_to_unified(sample_epic_data)
        assert records.source == "epic"

    def test_source_name_from_directory(self, sample_epic_data, tmp_path):
        """Source name derived from input_dir when present."""
        sample_epic_data["input_dir"] = str(tmp_path / "anderson")
        records = epic_to_unified(sample_epic_data)
        assert records.source == "epic_anderson"

    def test_source_name_override(self, sample_epic_data):
        """Explicit source_name overrides derived name."""
        records = epic_to_unified(sample_epic_data, source_name="epic_custom")
        assert records.source == "epic_custom"

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


    def test_patient_demographics(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        assert records.patient is not None
        assert records.patient.name == "John Doe"
        assert records.patient.date_of_birth == "1975-06-15"
        assert records.patient.gender == "Male"
        assert records.patient.mrn == "123456"

    def test_family_history(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        assert len(records.family_history) == 2
        relations = {fh.relation for fh in records.family_history}
        assert "Father" in relations
        assert "Mother" in relations
        father = next(fh for fh in records.family_history if fh.relation == "Father")
        assert "cancer" in father.condition.lower()

    def test_encounter_end_date(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        assert len(records.encounters) == 1
        assert records.encounters[0].encounter_end == "2025-01-15"

    def test_encounter_type(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        assert records.encounters[0].encounter_type == "office visit"

    def test_encounter_reason(self, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        assert records.encounters[0].reason == "Follow-up for colon cancer"


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
    def test_source_name_fallback(self, sample_meditech_data):
        """Without input_dir, fallback to generic source name."""
        records = meditech_to_unified(sample_meditech_data)
        assert records.source == "meditech"

    def test_source_name_from_directory(self, sample_meditech_data, tmp_path):
        """Source name derived from input_dir when present."""
        sample_meditech_data["input_dir"] = str(tmp_path / "siteman")
        records = meditech_to_unified(sample_meditech_data)
        assert records.source == "meditech_siteman"

    def test_source_name_override(self, sample_meditech_data):
        """Explicit source_name overrides derived name."""
        records = meditech_to_unified(sample_meditech_data, source_name="meditech_custom")
        assert records.source == "meditech_custom"

    def test_patient_from_fhir(self, sample_meditech_data):
        records = meditech_to_unified(sample_meditech_data)
        assert records.patient is not None
        assert records.patient.name == "Alexander Towell"
        assert records.patient.gender == "male"

    def test_fhir_labs(self, sample_meditech_data):
        records = meditech_to_unified(sample_meditech_data)
        cea = next(
            (
                lr
                for lr in records.lab_results
                if "CEA" in lr.test_name.upper() or "carcinoembryonic" in lr.test_name.lower()
            ),
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
        htn = next(
            (c for c in records.conditions if "hypertension" in c.condition_name.lower()), None
        )
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
        smoking = next(
            (s for s in records.social_history if s.category == "tobacco_smoking_status"), None
        )
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
        ccda_ms = next(
            (ms for ms in records.mental_status if "interest" in ms.question.lower() or "pleasure" in ms.question.lower()),
            None,
        )
        assert ccda_ms is not None
        assert ccda_ms.answer == "Not at all"

    def test_fhir_diagnostic_reports_imaging(self, sample_meditech_data):
        """FHIR DiagnosticReports with Radiology category become imaging reports."""
        records = meditech_to_unified(sample_meditech_data)
        assert len(records.imaging_reports) >= 1
        ct = next(
            (r for r in records.imaging_reports if "CT" in r.study_name.upper()), None
        )
        assert ct is not None
        assert ct.study_date == "2025-01-10"

    def test_fhir_allergy_intolerances(self, sample_meditech_data):
        """FHIR AllergyIntolerance resources become allergy records."""
        records = meditech_to_unified(sample_meditech_data)
        sulfa = next(
            (a for a in records.allergies if "sulfa" in a.allergen.lower()), None
        )
        assert sulfa is not None
        assert sulfa.reaction == "Hives"
        assert sulfa.severity == "moderate"

    def test_fhir_procedures(self, sample_meditech_data):
        """FHIR Procedure resources become procedure records."""
        records = meditech_to_unified(sample_meditech_data)
        hemi = next(
            (p for p in records.procedures if "hemicolectomy" in p.name.lower()), None
        )
        assert hemi is not None
        assert hemi.snomed_code == "44441009"
        assert hemi.procedure_date == "2024-07-01"

    def test_fhir_medication_rxnorm(self, sample_meditech_data):
        """FHIR MedicationRequest RxNorm codes should flow through."""
        records = meditech_to_unified(sample_meditech_data)
        cap = next((m for m in records.medications if "Capecitabine" in m.name), None)
        assert cap is not None
        assert cap.rxnorm_code == "200328"

    def test_fhir_social_history_obs(self, sample_meditech_data):
        """FHIR social-history observations become social history records."""
        records = meditech_to_unified(sample_meditech_data)
        fhir_sh = next(
            (s for s in records.social_history if "tobacco" in s.category.lower()),
            None,
        )
        assert fhir_sh is not None
        assert "smoker" in fhir_sh.value.lower()

    def test_fhir_survey_obs(self, sample_meditech_data):
        """FHIR survey observations (PHQ-9) become mental status records."""
        records = meditech_to_unified(sample_meditech_data)
        phq = next(
            (ms for ms in records.mental_status if "phq" in ms.instrument.lower()),
            None,
        )
        assert phq is not None
        assert phq.score == 3

    def test_fhir_practitioner_resolution(self, sample_meditech_data):
        """FHIR encounter participants should resolve to provider names."""
        records = meditech_to_unified(sample_meditech_data)
        assert len(records.encounters) >= 1
        assert records.encounters[0].provider == "Dr. Oncologist"

    def test_fhir_vitals_from_observations(self, sample_meditech_data):
        """FHIR vital-signs category observations should be mapped to vitals."""
        sample_meditech_data["fhir_data"]["observations"].append(
            {
                "text": "Heart Rate",
                "display": "Heart Rate",
                "loinc": "8867-4",
                "value": 72,
                "unit": "bpm",
                "date_iso": "2025-01-15",
                "category": "vital-signs",
                "status": "final",
            }
        )
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
    def test_source_name_fallback(self, sample_athena_data):
        """Without input_dir, fallback to generic source name."""
        records = athena_to_unified(sample_athena_data)
        assert records.source == "athena"

    def test_source_name_from_directory(self, sample_athena_data, tmp_path):
        """Source name derived from input_dir when present."""
        sample_athena_data["input_dir"] = str(tmp_path / "sihf_jan26")
        records = athena_to_unified(sample_athena_data)
        assert records.source == "athena_sihf_jan26"

    def test_source_name_override(self, sample_athena_data):
        """Explicit source_name overrides derived name."""
        records = athena_to_unified(sample_athena_data, source_name="athena_custom")
        assert records.source == "athena_custom"

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

    def test_encounter_end_date(self, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        assert len(records.encounters) == 1
        assert records.encounters[0].encounter_end == "2025-01-20"

    def test_empty_data(self):
        records = athena_to_unified({})
        assert records.source == "athena"  # Fallback without input_dir
        assert records.patient is None
        assert len(records.lab_results) == 0


class TestMeditechAdapterCCDAMerge:
    """Tests for CCDA data merging with FHIR — covers dedup branches."""

    def test_ccda_allergies_merge_with_fhir(self, sample_meditech_data):
        """CCDA allergies not in FHIR are added; duplicates are skipped."""
        sample_meditech_data["ccda_data"]["all_allergies"] = [
            {"allergen": "Penicillin", "reaction": "Rash", "severity": "mild"},
            {"allergen": "Sulfa drugs", "reaction": "Hives"},  # duplicate of FHIR
        ]
        records = meditech_to_unified(sample_meditech_data)
        allergens = [a.allergen for a in records.allergies]
        assert "Penicillin" in allergens
        assert allergens.count("Sulfa drugs") == 1  # not duplicated

    def test_ccda_procedures_merge_with_fhir(self, sample_meditech_data):
        """CCDA procedures not in FHIR are added; dedup by name+date."""
        sample_meditech_data["ccda_data"]["all_procedures"] = [
            {"name": "Appendectomy", "date_iso": "2024-03-15", "provider": "Dr. Smith"},
            {"name": "Right hemicolectomy", "date_iso": "2024-07-01"},  # dup of FHIR
        ]
        records = meditech_to_unified(sample_meditech_data)
        names = [p.name for p in records.procedures]
        assert "Appendectomy" in names
        assert names.count("Right hemicolectomy") == 1

    def test_ccda_medications_merge_with_fhir(self, sample_meditech_data):
        """CCDA medications not in FHIR are added; dedup by name."""
        sample_meditech_data["ccda_data"]["all_medications"] = [
            {"name": "Aspirin 81mg", "status": "active", "sig": "Once daily", "instructions": "Once daily"},
            {"name": "Capecitabine 500mg", "status": "active", "sig": "", "instructions": ""},  # dup
        ]
        records = meditech_to_unified(sample_meditech_data)
        med_names = [m.name for m in records.medications]
        assert "Aspirin 81mg" in med_names
        assert med_names.count("Capecitabine 500mg") == 1

    def test_fhir_diagnostic_report_pathology(self, sample_meditech_data):
        """Pathology-category DiagnosticReports become pathology_reports."""
        sample_meditech_data["fhir_data"]["diagnostic_reports"].append({
            "text": "Colon biopsy",
            "category": "Pathology",
            "date_iso": "2024-07-01",
            "full_text": "Adenocarcinoma, moderately differentiated.",
        })
        records = meditech_to_unified(sample_meditech_data)
        path = next(
            (p for p in records.pathology_reports if "Colon" in (p.specimen or "")), None
        )
        assert path is not None
        assert "Adenocarcinoma" in path.full_text

    def test_fhir_diagnostic_report_clinical_note_fallback(self, sample_meditech_data):
        """DiagnosticReports without known category fall back to clinical notes."""
        sample_meditech_data["fhir_data"]["diagnostic_reports"].append({
            "text": "Consult Note",
            "category": "other",
            "date_iso": "2025-01-12",
            "full_text": "Patient discussed treatment options.",
        })
        records = meditech_to_unified(sample_meditech_data)
        cn = next(
            (n for n in records.clinical_notes if "Consult" in n.note_type), None
        )
        assert cn is not None
        assert "treatment options" in cn.content

    def test_fhir_diagnostic_report_lab_skipped(self, sample_meditech_data):
        """LAB-category DiagnosticReports are skipped (results come from Observations)."""
        baseline = meditech_to_unified(sample_meditech_data)
        baseline_notes = len(baseline.clinical_notes)

        sample_meditech_data["fhir_data"]["diagnostic_reports"].append({
            "text": "CBC",
            "category": "LAB",
            "date_iso": "2024-06-01",
            "full_text": "",
        })
        sample_meditech_data["fhir_data"]["diagnostic_reports"].append({
            "text": "Comprehensive Metabolic Panel",
            "category": "lab",
            "date_iso": "2024-06-01",
            "full_text": "",
        })
        records = meditech_to_unified(sample_meditech_data)
        # LAB reports should not appear as clinical notes
        assert len(records.clinical_notes) == baseline_notes

    def test_fhir_diagnostic_report_radiology_non_imaging_becomes_note(self, sample_meditech_data):
        """Non-imaging reports categorized as 'Radiology' become clinical notes, not imaging."""
        sample_meditech_data["fhir_data"]["diagnostic_reports"].append({
            "text": "Office Visit",
            "category": "Radiology",
            "date_iso": "2025-01-12",
            "full_text": "Follow-up visit, patient doing well.",
        })
        records = meditech_to_unified(sample_meditech_data)
        # Should NOT appear as imaging
        assert not any(
            r.study_name == "Office Visit" for r in records.imaging_reports
        )
        # Should appear as a clinical note instead
        cn = next(
            (n for n in records.clinical_notes if "Office Visit" in n.note_type), None
        )
        assert cn is not None
        assert cn.content == "Follow-up visit, patient doing well."

    def test_fhir_diagnostic_report_radiology_imaging_stays_imaging(self, sample_meditech_data):
        """Actual imaging reports with 'Radiology' category remain as imaging reports."""
        sample_meditech_data["fhir_data"]["diagnostic_reports"].append({
            "text": "MRI Brain",
            "category": "Radiology",
            "date_iso": "2025-01-13",
            "full_text": "No acute intracranial abnormality.",
        })
        records = meditech_to_unified(sample_meditech_data)
        mri = next(
            (r for r in records.imaging_reports if r.study_name == "MRI Brain"), None
        )
        assert mri is not None
        assert "No acute" in mri.full_text

    def test_fhir_allergy_empty_allergen_skipped(self, sample_meditech_data):
        """Allergy records with empty allergen are skipped."""
        sample_meditech_data["fhir_data"]["allergy_intolerances"].append({
            "allergen": "",
            "reaction": "Unknown",
        })
        records = meditech_to_unified(sample_meditech_data)
        # Should only have the original Sulfa drugs, not the empty one
        assert all(a.allergen for a in records.allergies)


class TestIsImagingReportName:
    """Unit tests for _is_imaging_report_name helper."""

    def test_ct_scan(self):
        assert _is_imaging_report_name("ct abdomen pelvis") is True

    def test_mri(self):
        assert _is_imaging_report_name("mri brain with contrast") is True

    def test_xray(self):
        assert _is_imaging_report_name("x-ray chest pa and lateral") is True

    def test_ultrasound(self):
        assert _is_imaging_report_name("ultrasound abdomen") is True

    def test_office_visit_not_imaging(self):
        assert _is_imaging_report_name("office visit") is False

    def test_history_physical_not_imaging(self):
        assert _is_imaging_report_name("history and physical") is False

    def test_operative_note_not_imaging(self):
        assert _is_imaging_report_name("operative note") is False

    def test_empty_string(self):
        assert _is_imaging_report_name("") is False


class TestEpicAdapterEdgeCases:
    """Tests for Epic adapter edge cases — legacy text paths and helpers."""

    def test_legacy_text_medications(self, sample_epic_data):
        """String medications (legacy text) are added as active medications."""
        sample_epic_data["medications"] = [
            "Lisinopril 10mg daily",
            "  Medications  ",  # header line, should be skipped
            "",  # empty, should be skipped
            {"name": "Aspirin", "status": "active", "sig": ""},
        ]
        records = epic_to_unified(sample_epic_data)
        med_names = [m.name for m in records.medications]
        assert "Lisinopril 10mg daily" in med_names
        assert "Medications" not in med_names
        aspirin = next((m for m in records.medications if m.name == "Aspirin"), None)
        assert aspirin is not None

    def test_legacy_text_conditions(self, sample_epic_data):
        """String conditions (legacy text) are added as active conditions."""
        sample_epic_data["problems"] = [
            "Essential hypertension",
            "  Active Problems  ",  # header line, should be skipped
            "",  # empty, should be skipped
            {"name": "Diabetes", "status": "active"},
        ]
        records = epic_to_unified(sample_epic_data)
        cond_names = [c.condition_name for c in records.conditions]
        assert "Essential hypertension" in cond_names
        assert "Active Problems" not in cond_names
        diabetes = next((c for c in records.conditions if c.condition_name == "Diabetes"), None)
        assert diabetes is not None

    def test_extract_snomed_code_non_snomed(self, sample_epic_data):
        """Procedures with non-SNOMED code system return empty snomed_code."""
        from chartfold.adapters.epic_adapter import _extract_snomed_code
        assert _extract_snomed_code({"code_system": "2.16.840.1.113883.6.12", "code_value": "99213"}) == ""

    def test_format_provider_list_non_list(self):
        """Non-list authors return empty string."""
        from chartfold.adapters.epic_adapter import _format_provider_list
        assert _format_provider_list("Dr. Smith") == ""
        assert _format_provider_list(None) == ""
