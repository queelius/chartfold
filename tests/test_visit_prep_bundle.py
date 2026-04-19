"""Tests for the visit prep bundle feature."""

from __future__ import annotations

import pytest

from health_memex.config import LabTestConfig
from health_memex.db import HealthMemexDB
from health_memex.models import (
    ClinicalNote,
    ConditionRecord,
    EncounterRecord,
    ImagingReport,
    LabResult,
    MedicationRecord,
    ProcedureRecord,
    UnifiedRecords,
)


@pytest.fixture
def prep_db(tmp_path):
    """Database with enough data for visit prep bundle tests."""
    db = HealthMemexDB(str(tmp_path / "prep.db"))
    db.init_schema()

    records = UnifiedRecords(
        source="test_source",
        lab_results=[
            LabResult(
                source="test_source",
                test_name="CEA",
                value="5.8",
                value_numeric=5.8,
                ref_range="<=5.0",
                result_date="2025-07-08",
            ),
            LabResult(
                source="test_source",
                test_name="CEA",
                value="4.6",
                value_numeric=4.6,
                ref_range="<=5.0",
                result_date="2025-07-31",
            ),
            LabResult(
                source="test_source",
                test_name="CEA",
                value="3.9",
                value_numeric=3.9,
                ref_range="<=5.0",
                result_date="2025-08-14",
            ),
            LabResult(
                source="test_source",
                test_name="CEA",
                value="2.9",
                value_numeric=2.9,
                ref_range="<=5.0",
                result_date="2025-11-06",
            ),
            LabResult(
                source="test_source",
                test_name="CEA",
                value="1.8",
                value_numeric=1.8,
                ref_range="<=5.0",
                result_date="2026-01-15",
            ),
            LabResult(
                source="test_source",
                test_name="CEA",
                value="1.7",
                value_numeric=1.7,
                ref_range="<=5.0",
                result_date="2026-02-05",
            ),
            LabResult(
                source="test_source",
                test_name="CEA",
                value="1.8",
                value_numeric=1.8,
                ref_range="<=5.0",
                result_date="2026-03-05",
            ),
            LabResult(
                source="test_source",
                test_name="CEA",
                value="2.3",
                value_numeric=2.3,
                ref_range="<=5.0",
                result_date="2026-03-19",
            ),
            LabResult(
                source="test_source",
                test_name="Hemoglobin",
                value="15.8",
                value_numeric=15.8,
                result_date="2026-01-15",
            ),
            LabResult(
                source="test_source",
                test_name="Hemoglobin",
                value="14.3",
                value_numeric=14.3,
                result_date="2026-03-19",
            ),
            LabResult(
                source="test_source",
                test_name="Hemoglobin",
                value="16.1",
                value_numeric=16.1,
                result_date="2026-02-19",
            ),
            LabResult(
                source="test_source",
                test_name="WBC",
                value="4.57",
                value_numeric=4.57,
                result_date="2026-03-05",
            ),
            LabResult(
                source="test_source",
                test_name="WBC",
                value="4.32",
                value_numeric=4.32,
                result_date="2026-03-19",
            ),
            LabResult(
                source="test_source",
                test_name="Glucose",
                value="103",
                value_numeric=103.0,
                result_date="2026-03-19",
            ),
        ],
        encounters=[
            EncounterRecord(
                source="test_source",
                encounter_date="2026-03-05",
                encounter_type="Office Visit",
                provider="Dr. Tan",
                facility="Siteman Cancer Center",
                reason="Oncology follow-up",
            ),
            EncounterRecord(
                source="test_source",
                encounter_date="2026-03-19",
                encounter_type="Office Visit",
                provider="Amy Ngo, NP",
                facility="Siteman Cancer Center",
                reason="Chemo day 1 cycle 4",
            ),
        ],
        imaging_reports=[
            ImagingReport(
                source="test_source",
                study_name="MRI Abdomen Pelvis",
                modality="MRI",
                study_date="2026-03-31",
                impression="No evidence of disease progression. Stable hepatic changes.",
                findings="Liver: no new lesions. Spleen normal. Kidneys unremarkable.",
            ),
        ],
        clinical_notes=[
            ClinicalNote(
                source="test_source",
                note_type="Progress Notes",
                author="Dr. Tan",
                note_date="2026-03-05",
                content=("Oncology Return Visit. Treatment history reviewed. " + "x" * 2000),
            ),
            ClinicalNote(
                source="test_source",
                note_type="Progress Notes",
                author="Amy Ngo, NP",
                note_date="2026-03-19",
                content="Pt presenting for C4 FOLFOX.",
            ),
        ],
        medications=[
            MedicationRecord(
                source="test_source",
                name="levothyroxine 125 mcg",
                status="active",
                sig="Take 1 tablet daily",
                route="oral",
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
        procedures=[
            ProcedureRecord(
                source="test_source",
                name="Liver resection",
                procedure_date="2025-12-18",
                provider="Dr. Tan",
                facility="Barnes-Jewish Hospital",
            ),
        ],
    )
    db.load_source(records)

    db.save_note(
        "Trial Research", "Bot/Bal and BNT122 options...", tags=["oncology", "clinical-trials"]
    )
    db.save_analysis(
        slug="cancer-timeline",
        title="Cancer Timeline",
        content="Full chronological narrative...",
        category="oncology",
        summary="Timeline from diagnosis to present",
        tags=["oncology"],
    )

    yield db
    db.close()


class TestScoreTreatmentContextNote:
    """Test the heuristic that identifies the most comprehensive clinical note."""

    def test_oncology_keyword_scores_highest(self):
        from health_memex.analysis.visit_prep import _score_treatment_context_note

        note = {
            "note_date": "2026-03-05",
            "note_type": "Progress Notes",
            "author": "Dr. Tan",
            "content": "Oncology Return/Follow Up Visit. Treatment history reviewed.",
            "source": "epic",
        }
        score = _score_treatment_context_note(note)
        assert score >= 6

    def test_short_note_without_keywords_scores_zero(self):
        from health_memex.analysis.visit_prep import _score_treatment_context_note

        note = {
            "note_date": "2026-03-01",
            "note_type": "Vitals",
            "author": "",
            "content": "BP 120/80",
            "source": "epic",
        }
        assert _score_treatment_context_note(note) == 0

    def test_long_note_scores_by_length(self):
        from health_memex.analysis.visit_prep import _score_treatment_context_note

        note = {
            "note_date": "2026-03-05",
            "note_type": "H&P Notes",
            "author": "",
            "content": "x" * 5000,
            "source": "epic",
        }
        score = _score_treatment_context_note(note)
        assert score == 5

    def test_progress_note_type_adds_one(self):
        from health_memex.analysis.visit_prep import _score_treatment_context_note

        note = {
            "note_date": "2026-03-05",
            "note_type": "Progress Notes",
            "author": "",
            "content": "Short note.",
            "source": "epic",
        }
        assert _score_treatment_context_note(note) == 1


class TestResolveKeyTestTrends:
    def test_with_config(self, prep_db):
        from health_memex.analysis.visit_prep import _resolve_key_test_trends

        config_tests = [
            LabTestConfig(name="CEA", match=["CEA"]),
            LabTestConfig(name="Hemoglobin", match=["Hemoglobin"]),
        ]
        trends = _resolve_key_test_trends(prep_db, config_tests, max_readings=8)
        assert "CEA" in trends
        assert "Hemoglobin" in trends
        assert len(trends["CEA"]) == 8
        assert len(trends["Hemoglobin"]) == 3
        # Verify chronological order (oldest first)
        dates = [r["date"] for r in trends["CEA"]]
        assert dates == sorted(dates)

    def test_fallback_without_config(self, prep_db):
        from health_memex.analysis.visit_prep import _resolve_key_test_trends

        trends = _resolve_key_test_trends(prep_db, config_tests=[], max_readings=8)
        assert "CEA" in trends
        assert "Hemoglobin" in trends
        assert "WBC" in trends
        assert "Glucose" in trends

    def test_max_readings_limits_output(self, prep_db):
        from health_memex.analysis.visit_prep import _resolve_key_test_trends

        config_tests = [LabTestConfig(name="CEA", match=["CEA"])]
        trends = _resolve_key_test_trends(prep_db, config_tests, max_readings=3)
        assert len(trends["CEA"]) == 3
        assert trends["CEA"][-1]["date"] == "2026-03-19"

    def test_match_aliases(self, prep_db):
        from health_memex.analysis.visit_prep import _resolve_key_test_trends

        config_tests = [LabTestConfig(name="Hgb", match=["Hemoglobin", "Hgb"])]
        trends = _resolve_key_test_trends(prep_db, config_tests, max_readings=8)
        assert "Hgb" in trends
        assert len(trends["Hgb"]) == 3


class TestGenerateVisitPrepBundle:
    def test_returns_all_sections(self, prep_db):
        from health_memex.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02")
        expected_keys = {
            "visit_date",
            "lookback_start",
            "provider",
            "lab_trends",
            "new_labs",
            "recent_imaging",
            "recent_notes",
            "active_medications",
            "active_conditions",
            "recent_procedures",
            "saved_notes",
            "saved_analyses",
            "treatment_context_note",
        }
        assert set(bundle.keys()) == expected_keys

    def test_visit_date_defaults_to_today(self, prep_db):
        from health_memex.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db)
        assert bundle["visit_date"]  # non-empty

    def test_provider_from_recent_encounter(self, prep_db):
        from health_memex.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02")
        assert bundle["provider"] == "Amy Ngo, NP"

    def test_lab_trends_populated(self, prep_db):
        from health_memex.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02")
        # Fallback mode (no config_path), should still populate from frequent tests
        assert len(bundle["lab_trends"]) > 0

    def test_new_labs_from_lookback(self, prep_db):
        from health_memex.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02", lookback_months=6)
        assert len(bundle["new_labs"]) > 0

    def test_imaging_includes_findings(self, prep_db):
        from health_memex.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02")
        assert len(bundle["recent_imaging"]) > 0
        img = bundle["recent_imaging"][0]
        assert "findings" in img
        assert img["findings"]  # non-empty

    def test_notes_include_full_content(self, prep_db):
        from health_memex.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02")
        assert len(bundle["recent_notes"]) > 0
        # The long oncology note should have more than 300 chars
        long_note = max(bundle["recent_notes"], key=lambda n: len(n.get("content") or ""))
        assert len(long_note["content"]) > 300

    def test_treatment_context_note_identified(self, prep_db):
        from health_memex.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02")
        ctx = bundle["treatment_context_note"]
        assert ctx is not None
        assert "oncolog" in ctx["content"].lower() or "treatment" in ctx["content"].lower()

    def test_saved_notes_included(self, prep_db):
        from health_memex.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02")
        assert len(bundle["saved_notes"]) == 1
        note = bundle["saved_notes"][0]
        assert note["title"] == "Trial Research"
        assert "oncology" in note["tags"]
        assert "clinical-trials" in note["tags"]

    def test_saved_analyses_included(self, prep_db):
        from health_memex.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02")
        assert len(bundle["saved_analyses"]) == 1
        analysis = bundle["saved_analyses"][0]
        assert analysis["slug"] == "cancer-timeline"

    def test_exclude_analyses(self, prep_db):
        from health_memex.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(
            prep_db, visit_date="2026-04-02", include_analyses=False
        )
        assert bundle["saved_analyses"] == []

    def test_exclude_notes(self, prep_db):
        from health_memex.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02", include_notes=False)
        assert bundle["saved_notes"] == []

    def test_empty_db(self, tmp_path):
        from health_memex.analysis.visit_prep import generate_visit_prep_bundle

        db = HealthMemexDB(str(tmp_path / "empty.db"))
        db.init_schema()
        try:
            bundle = generate_visit_prep_bundle(db, visit_date="2026-04-02")
            # All list fields should be empty, provider/treatment_context_note should be falsy
            assert bundle["lab_trends"] == {}
            assert bundle["new_labs"] == []
            assert bundle["recent_imaging"] == []
            assert bundle["recent_notes"] == []
            assert bundle["active_medications"] == []
            assert bundle["active_conditions"] == []
            assert bundle["recent_procedures"] == []
            assert bundle["saved_notes"] == []
            assert bundle["saved_analyses"] == []
            assert bundle["provider"] == ""
            assert bundle["treatment_context_note"] is None
        finally:
            db.close()
