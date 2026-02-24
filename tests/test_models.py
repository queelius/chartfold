"""Tests for chartfold.models dataclasses."""

from dataclasses import asdict

from chartfold.models import (
    AllergyRecord,
    ClinicalNote,
    ConditionRecord,
    DocumentRecord,
    EncounterRecord,
    FamilyHistoryRecord,
    GeneticVariant,
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


class TestDataclassInstantiation:
    """Verify all dataclasses can be instantiated with minimal args."""

    def test_patient_record(self):
        p = PatientRecord(source="test")
        assert p.source == "test"
        assert p.name == ""
        assert p.gender == ""

    def test_document_record(self):
        d = DocumentRecord(source="test", doc_id="DOC001")
        assert d.doc_id == "DOC001"
        assert d.doc_type == ""

    def test_encounter_record(self):
        e = EncounterRecord(source="test")
        assert e.encounter_type == ""

    def test_lab_result(self):
        lr = LabResult(source="test", test_name="CEA", value="5.8", value_numeric=5.8)
        assert lr.value_numeric == 5.8
        assert lr.unit == ""

    def test_lab_result_null_numeric(self):
        lr = LabResult(source="test", test_name="Culture", value="positive")
        assert lr.value_numeric is None

    def test_vital_record(self):
        v = VitalRecord(source="test", vital_type="bp_systolic", value=120.0)
        assert v.value == 120.0

    def test_medication_record(self):
        m = MedicationRecord(source="test", name="Aspirin")
        assert m.status == ""

    def test_condition_record(self):
        c = ConditionRecord(source="test", condition_name="Diabetes")
        assert c.icd10_code == ""

    def test_procedure_record(self):
        p = ProcedureRecord(source="test", name="Colonoscopy")
        assert p.cpt_code == ""

    def test_pathology_report(self):
        pr = PathologyReport(source="test", diagnosis="Adenocarcinoma")
        assert pr.procedure_id is None

    def test_imaging_report(self):
        ir = ImagingReport(source="test", study_name="CT Chest")
        assert ir.modality == ""

    def test_clinical_note(self):
        cn = ClinicalNote(source="test", content="Patient doing well.")
        assert cn.content_format == "text"

    def test_immunization_record(self):
        i = ImmunizationRecord(source="test", vaccine_name="Flu")
        assert i.cvx_code == ""

    def test_allergy_record(self):
        a = AllergyRecord(source="test", allergen="Penicillin")
        assert a.severity == ""

    def test_social_history_record(self):
        sh = SocialHistoryRecord(source="test", category="smoking", value="never")
        assert sh.recorded_date == ""

    def test_family_history_record(self):
        fh = FamilyHistoryRecord(source="test", relation="father", condition="heart disease")
        assert fh.deceased is None

    def test_mental_status_record(self):
        ms = MentalStatusRecord(source="test", instrument="PHQ-9")
        assert ms.score is None
        assert ms.total_score is None

    def test_genetic_variant(self):
        gv = GeneticVariant(source="test", gene="TP53", dna_change="c.713G>A")
        assert gv.gene == "TP53"
        assert gv.vaf is None
        assert gv.classification == ""


class TestUnifiedRecords:
    def test_empty_container(self):
        ur = UnifiedRecords(source="test")
        assert ur.source == "test"
        assert ur.patient is None
        assert len(ur.lab_results) == 0
        assert len(ur.medications) == 0

    def test_with_patient(self):
        ur = UnifiedRecords(
            source="test",
            patient=PatientRecord(source="test", name="John"),
        )
        assert ur.patient.name == "John"

    def test_add_records(self):
        ur = UnifiedRecords(source="test")
        ur.lab_results.append(LabResult(source="test", test_name="WBC"))
        ur.medications.append(MedicationRecord(source="test", name="Aspirin"))
        assert len(ur.lab_results) == 1
        assert len(ur.medications) == 1

    def test_asdict_roundtrip(self):
        lr = LabResult(source="test", test_name="CEA", value="5.8", value_numeric=5.8)
        d = asdict(lr)
        assert d["source"] == "test"
        assert d["test_name"] == "CEA"
        assert d["value_numeric"] == 5.8


class TestMetadataField:
    """All clinical record dataclasses should have a metadata field."""

    CLINICAL_TYPES = [
        PatientRecord,
        DocumentRecord,
        EncounterRecord,
        LabResult,
        VitalRecord,
        MedicationRecord,
        ConditionRecord,
        ProcedureRecord,
        PathologyReport,
        ImagingReport,
        ClinicalNote,
        ImmunizationRecord,
        AllergyRecord,
        SocialHistoryRecord,
        FamilyHistoryRecord,
        MentalStatusRecord,
        GeneticVariant,
    ]

    def test_all_types_have_metadata_field(self):
        """Every clinical record type should have a metadata field."""
        from dataclasses import fields as dc_fields

        for cls in self.CLINICAL_TYPES:
            field_names = {f.name for f in dc_fields(cls)}
            assert "metadata" in field_names, f"{cls.__name__} missing metadata field"

    def test_metadata_defaults_to_empty_string(self):
        """Metadata should default to empty string (not None)."""
        p = ProcedureRecord(source="test", name="test")
        assert p.metadata == ""

    def test_metadata_accepts_json_string(self):
        """Metadata should accept a JSON string."""
        import json

        meta = json.dumps({"key": "value", "number": 42})
        p = ProcedureRecord(source="test", name="test", metadata=meta)
        parsed = json.loads(p.metadata)
        assert parsed["key"] == "value"
        assert parsed["number"] == 42
