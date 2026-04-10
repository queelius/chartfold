"""Tests for the visit prep bundle feature."""

from __future__ import annotations

import pytest

from chartfold.config import LabTestConfig
from chartfold.db import ChartfoldDB
from chartfold.models import LabResult, UnifiedRecords


@pytest.fixture
def prep_db(tmp_path):
    """Database with enough data for visit prep bundle tests."""
    db = ChartfoldDB(str(tmp_path / "prep.db"))
    db.init_schema()

    records = UnifiedRecords(
        source="test_source",
        lab_results=[
            LabResult(source="test_source", test_name="CEA", value="5.8",
                      value_numeric=5.8, ref_range="<=5.0", result_date="2025-07-08"),
            LabResult(source="test_source", test_name="CEA", value="4.6",
                      value_numeric=4.6, ref_range="<=5.0", result_date="2025-07-31"),
            LabResult(source="test_source", test_name="CEA", value="3.9",
                      value_numeric=3.9, ref_range="<=5.0", result_date="2025-08-14"),
            LabResult(source="test_source", test_name="CEA", value="2.9",
                      value_numeric=2.9, ref_range="<=5.0", result_date="2025-11-06"),
            LabResult(source="test_source", test_name="CEA", value="1.8",
                      value_numeric=1.8, ref_range="<=5.0", result_date="2026-01-15"),
            LabResult(source="test_source", test_name="CEA", value="1.7",
                      value_numeric=1.7, ref_range="<=5.0", result_date="2026-02-05"),
            LabResult(source="test_source", test_name="CEA", value="1.8",
                      value_numeric=1.8, ref_range="<=5.0", result_date="2026-03-05"),
            LabResult(source="test_source", test_name="CEA", value="2.3",
                      value_numeric=2.3, ref_range="<=5.0", result_date="2026-03-19"),
            LabResult(source="test_source", test_name="Hemoglobin", value="15.8",
                      value_numeric=15.8, result_date="2026-01-15"),
            LabResult(source="test_source", test_name="Hemoglobin", value="14.3",
                      value_numeric=14.3, result_date="2026-03-19"),
            LabResult(source="test_source", test_name="Hemoglobin", value="16.1",
                      value_numeric=16.1, result_date="2026-02-19"),
            LabResult(source="test_source", test_name="WBC", value="4.57",
                      value_numeric=4.57, result_date="2026-03-05"),
            LabResult(source="test_source", test_name="WBC", value="4.32",
                      value_numeric=4.32, result_date="2026-03-19"),
            LabResult(source="test_source", test_name="Glucose", value="103",
                      value_numeric=103.0, result_date="2026-03-19"),
        ],
    )
    db.load_source(records)
    yield db
    db.close()


class TestScoreTreatmentContextNote:
    """Test the heuristic that identifies the most comprehensive clinical note."""

    def test_oncology_keyword_scores_highest(self):
        from chartfold.analysis.visit_prep import _score_treatment_context_note

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
        from chartfold.analysis.visit_prep import _score_treatment_context_note

        note = {
            "note_date": "2026-03-01",
            "note_type": "Vitals",
            "author": "",
            "content": "BP 120/80",
            "source": "epic",
        }
        assert _score_treatment_context_note(note) == 0

    def test_long_note_scores_by_length(self):
        from chartfold.analysis.visit_prep import _score_treatment_context_note

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
        from chartfold.analysis.visit_prep import _score_treatment_context_note

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
        from chartfold.analysis.visit_prep import _resolve_key_test_trends

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
        from chartfold.analysis.visit_prep import _resolve_key_test_trends

        trends = _resolve_key_test_trends(prep_db, config_tests=[], max_readings=8)
        assert "CEA" in trends
        assert "Hemoglobin" in trends
        assert "WBC" in trends
        assert "Glucose" in trends

    def test_max_readings_limits_output(self, prep_db):
        from chartfold.analysis.visit_prep import _resolve_key_test_trends

        config_tests = [LabTestConfig(name="CEA", match=["CEA"])]
        trends = _resolve_key_test_trends(prep_db, config_tests, max_readings=3)
        assert len(trends["CEA"]) == 3
        assert trends["CEA"][-1]["date"] == "2026-03-19"

    def test_match_aliases(self, prep_db):
        from chartfold.analysis.visit_prep import _resolve_key_test_trends

        config_tests = [LabTestConfig(name="Hgb", match=["Hemoglobin", "Hgb"])]
        trends = _resolve_key_test_trends(prep_db, config_tests, max_readings=8)
        assert "Hgb" in trends
        assert len(trends["Hgb"]) == 3
