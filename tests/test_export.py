"""Tests for chartfold.export module."""

import pytest

from chartfold.db import ChartfoldDB
from chartfold.export import export_markdown
from chartfold.models import (
    AllergyRecord,
    ConditionRecord,
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
def export_db(tmp_path):
    """Database with clinical data for export testing."""
    db = ChartfoldDB(str(tmp_path / "export.db"))
    db.init_schema()

    records = UnifiedRecords(
        source="test_source",
        patient=PatientRecord(source="test_source", name="Test Patient",
                              date_of_birth="1975-06-15", gender="male"),
        lab_results=[
            LabResult(source="test_source", test_name="CEA", value="5.8", value_numeric=5.8,
                      unit="ng/mL", ref_range="0.0-3.0", interpretation="H",
                      result_date="2025-12-15"),
            LabResult(source="test_source", test_name="Hemoglobin", value="12.5", value_numeric=12.5,
                      unit="g/dL", ref_range="13.0-17.0", interpretation="L",
                      result_date="2025-12-15"),
        ],
        medications=[
            MedicationRecord(source="test_source", name="Capecitabine 500mg", status="active",
                             sig="2 tabs twice daily", route="oral"),
        ],
        conditions=[
            ConditionRecord(source="test_source", condition_name="Colon cancer",
                            icd10_code="C18.9", clinical_status="active",
                            onset_date="2021-11-22"),
        ],
        encounters=[
            EncounterRecord(source="test_source", encounter_date="2025-12-15",
                            encounter_type="office visit", facility="Anderson",
                            provider="Dr. Smith"),
        ],
        imaging_reports=[
            ImagingReport(source="test_source", study_name="CT Abdomen", modality="CT",
                          study_date="2025-12-01", impression="No recurrence."),
        ],
        pathology_reports=[
            PathologyReport(source="test_source", report_date="2024-07-03",
                            specimen="Right colon", diagnosis="Adenocarcinoma",
                            staging="pT3N2a", margins="Negative"),
        ],
        allergies=[
            AllergyRecord(source="test_source", allergen="Penicillin",
                          reaction="Rash", severity="moderate", status="active"),
        ],
    )
    db.load_source(records)
    yield db
    db.close()


class TestExportMarkdown:
    def test_generates_file(self, export_db, tmp_path):
        output = str(tmp_path / "test_export.md")
        result = export_markdown(export_db, output_path=output)
        assert result == output
        assert (tmp_path / "test_export.md").exists()

    def test_includes_header(self, export_db, tmp_path):
        output = str(tmp_path / "export.md")
        export_markdown(export_db, output_path=output)
        content = (tmp_path / "export.md").read_text()
        assert "Clinical Records Summary" in content

    def test_includes_conditions(self, export_db, tmp_path):
        output = str(tmp_path / "export.md")
        export_markdown(export_db, output_path=output)
        content = (tmp_path / "export.md").read_text()
        assert "Colon cancer" in content
        assert "Active Conditions" in content

    def test_includes_medications(self, export_db, tmp_path):
        output = str(tmp_path / "export.md")
        export_markdown(export_db, output_path=output)
        content = (tmp_path / "export.md").read_text()
        assert "Capecitabine" in content
        assert "Active Medications" in content

    def test_includes_labs(self, export_db, tmp_path):
        output = str(tmp_path / "export.md")
        export_markdown(export_db, output_path=output, lookback_months=24)
        content = (tmp_path / "export.md").read_text()
        assert "CEA" in content
        assert "5.8" in content

    def test_includes_encounters(self, export_db, tmp_path):
        output = str(tmp_path / "export.md")
        export_markdown(export_db, output_path=output, lookback_months=24)
        content = (tmp_path / "export.md").read_text()
        assert "Recent Encounters" in content

    def test_includes_imaging(self, export_db, tmp_path):
        output = str(tmp_path / "export.md")
        export_markdown(export_db, output_path=output, lookback_months=24)
        content = (tmp_path / "export.md").read_text()
        assert "CT Abdomen" in content

    def test_includes_pathology(self, export_db, tmp_path):
        output = str(tmp_path / "export.md")
        export_markdown(export_db, output_path=output)
        content = (tmp_path / "export.md").read_text()
        assert "Pathology Reports" in content
        assert "Adenocarcinoma" in content

    def test_includes_allergies(self, export_db, tmp_path):
        output = str(tmp_path / "export.md")
        export_markdown(export_db, output_path=output)
        content = (tmp_path / "export.md").read_text()
        assert "Allergies" in content
        assert "Penicillin" in content

    def test_includes_data_overview(self, export_db, tmp_path):
        output = str(tmp_path / "export.md")
        export_markdown(export_db, output_path=output)
        content = (tmp_path / "export.md").read_text()
        assert "Data Overview" in content

    def test_empty_db(self, tmp_path):
        db = ChartfoldDB(str(tmp_path / "empty.db"))
        db.init_schema()
        output = str(tmp_path / "empty_export.md")
        export_markdown(db, output_path=output)
        content = (tmp_path / "empty_export.md").read_text()
        assert "Clinical Records Summary" in content
        db.close()
