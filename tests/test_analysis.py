"""Tests for chartfold.analysis modules."""

import pytest

from chartfold.analysis.lab_trends import (
    get_abnormal_labs,
    get_available_tests,
    get_lab_series,
    get_lab_trend,
    get_latest_labs,
)
from chartfold.analysis.cross_source import match_encounters_by_date
from chartfold.analysis.medications import get_active_medications, get_medication_history
from chartfold.analysis.visit_diff import visit_diff
from chartfold.analysis.surgical_timeline import build_surgical_timeline
from chartfold.analysis.visit_prep import generate_visit_prep
from chartfold.db import ChartfoldDB
from chartfold.models import (
    ClinicalNote,
    ConditionRecord,
    EncounterRecord,
    ImagingReport,
    LabResult,
    MedicationRecord,
    PathologyReport,
    ProcedureRecord,
    UnifiedRecords,
)


@pytest.fixture
def analysis_db(tmp_path):
    """Database with analysis-suitable test data."""
    db = ChartfoldDB(str(tmp_path / "analysis.db"))
    db.init_schema()

    records = UnifiedRecords(
        source="test",
        lab_results=[
            LabResult(source="test", test_name="CEA", value="1.4", value_numeric=1.4,
                      unit="ng/mL", ref_range="0.0-3.0", result_date="2025-01-01"),
            LabResult(source="test", test_name="CEA", value="5.8", value_numeric=5.8,
                      unit="ng/mL", ref_range="0.0-3.0", interpretation="H",
                      result_date="2025-06-15"),
            LabResult(source="test", test_name="Hemoglobin", value="12.5", value_numeric=12.5,
                      unit="g/dL", ref_range="13.0-17.0", interpretation="L",
                      result_date="2025-06-15"),
            LabResult(source="test", test_name="WBC", value="6.2", value_numeric=6.2,
                      unit="K/mm3", result_date="2024-01-15"),
        ],
        medications=[
            MedicationRecord(source="test", name="Capecitabine 500mg", status="active",
                             sig="2 tablets twice daily"),
            MedicationRecord(source="test", name="Ondansetron 8mg", status="active",
                             sig="As needed for nausea"),
            MedicationRecord(source="test", name="Oxycodone 5mg", status="completed",
                             sig="PRN pain"),
        ],
        encounters=[
            EncounterRecord(source="test", encounter_date="2025-06-15",
                            encounter_type="office visit", facility="Anderson",
                            provider="Dr. Smith"),
        ],
        conditions=[
            ConditionRecord(source="test", condition_name="Colon cancer",
                            icd10_code="C18.9", clinical_status="active"),
        ],
        imaging_reports=[
            ImagingReport(source="test", study_name="CT Abdomen", modality="CT",
                          study_date="2025-06-01", impression="No recurrence."),
        ],
    )
    db.load_source(records)
    yield db
    db.close()


class TestLabTrends:
    def test_get_trend_by_name(self, analysis_db):
        results = get_lab_trend(analysis_db, test_name="CEA")
        assert len(results) == 2
        assert results[0]["result_date"] == "2025-01-01"  # Chronological
        assert results[1]["value_numeric"] == 5.8

    def test_get_trend_with_date_range(self, analysis_db):
        results = get_lab_trend(analysis_db, test_name="CEA", start_date="2025-06-01")
        assert len(results) == 1
        assert results[0]["value_numeric"] == 5.8

    def test_get_trend_no_args(self, analysis_db):
        results = get_lab_trend(analysis_db)
        assert results == []

    def test_get_abnormal(self, analysis_db):
        results = get_abnormal_labs(analysis_db)
        assert len(results) == 2  # CEA (H) and Hemoglobin (L)

    def test_get_latest(self, analysis_db):
        results = get_latest_labs(analysis_db)
        assert len(results) >= 3
        # Each test should appear once
        test_names = [r["test_name"] for r in results]
        assert "CEA" in test_names


@pytest.fixture
def multi_source_db(tmp_path):
    """Database with lab data from multiple sources for cross-source testing."""
    db = ChartfoldDB(str(tmp_path / "multi.db"))
    db.init_schema()

    epic_records = UnifiedRecords(
        source="epic_anderson",
        lab_results=[
            LabResult(source="epic_anderson", test_name="CEA", value="1.4", value_numeric=1.4,
                      unit="ng/mL", ref_range="0.0-3.0", result_date="2025-01-01"),
            LabResult(source="epic_anderson", test_name="CEA", value="5.8", value_numeric=5.8,
                      unit="ng/mL", ref_range="0.0-3.0", interpretation="H",
                      result_date="2025-06-15"),
            LabResult(source="epic_anderson", test_name="Hemoglobin", value="12.5", value_numeric=12.5,
                      unit="g/dL", ref_range="13.0-17.0", interpretation="L",
                      result_date="2025-06-15"),
        ],
    )
    meditech_records = UnifiedRecords(
        source="meditech_anderson",
        lab_results=[
            LabResult(source="meditech_anderson", test_name="CEA", value="3.2", value_numeric=3.2,
                      unit="ng/mL", ref_range="0.0-5.0", interpretation="",
                      result_date="2025-03-15"),
            LabResult(source="meditech_anderson", test_name="CEA", value="4.1", value_numeric=4.1,
                      unit="ng/mL", ref_range="0.0-5.0", interpretation="",
                      result_date="2025-08-01"),
        ],
    )
    db.load_source(epic_records)
    db.load_source(meditech_records)
    yield db
    db.close()


@pytest.fixture
def synonym_db(tmp_path):
    """Database with different test names for the same test across sources."""
    db = ChartfoldDB(str(tmp_path / "synonym.db"))
    db.init_schema()

    epic_records = UnifiedRecords(
        source="epic_anderson",
        lab_results=[
            LabResult(source="epic_anderson", test_name="CEA", test_loinc="2039-6",
                      value="1.4", value_numeric=1.4, unit="ng/mL",
                      ref_range="0.0-3.0", result_date="2025-01-15"),
            LabResult(source="epic_anderson", test_name="CEA", test_loinc="2039-6",
                      value="5.8", value_numeric=5.8, unit="ng/mL",
                      ref_range="0.0-3.0", interpretation="H",
                      result_date="2025-06-15"),
        ],
    )
    meditech_records = UnifiedRecords(
        source="meditech_siteman",
        lab_results=[
            LabResult(source="meditech_siteman",
                      test_name="Carcinoembryonic Antigen", test_loinc="2039-6",
                      value="4.1", value_numeric=4.1, unit="ng/mL",
                      ref_range="0.0-5.0", result_date="2024-11-01"),
            LabResult(source="meditech_siteman",
                      test_name="Carcinoembryonic Antigen", test_loinc="2039-6",
                      value="2.5", value_numeric=2.5, unit="ng/mL",
                      ref_range="0.0-5.0", result_date="2025-03-01"),
            LabResult(source="meditech_siteman",
                      test_name="Carcinoembryonic Antigen", test_loinc="2039-6",
                      value="3.8", value_numeric=3.8, unit="ng/mL",
                      ref_range="0.0-5.0", result_date="2025-08-01"),
        ],
    )
    db.load_source(epic_records)
    db.load_source(meditech_records)
    yield db
    db.close()


class TestLabTrendMultiName:
    def test_single_name_misses_synonyms(self, synonym_db):
        """Searching for 'CEA' with LIKE does NOT match 'Carcinoembryonic Antigen'."""
        results = get_lab_trend(synonym_db, test_name="CEA")
        assert len(results) == 2  # Only Epic's results
        assert all(r["source"] == "epic_anderson" for r in results)

    def test_multi_name_finds_all(self, synonym_db):
        """Using test_names with both variants finds all results."""
        results = get_lab_trend(synonym_db, test_names=["CEA", "Carcinoembryonic Antigen"])
        assert len(results) == 5  # 2 Epic + 3 MEDITECH

    def test_multi_name_chronological(self, synonym_db):
        results = get_lab_trend(synonym_db, test_names=["CEA", "Carcinoembryonic Antigen"])
        dates = [r["result_date"] for r in results]
        assert dates == sorted(dates)

    def test_multi_name_with_date_filter(self, synonym_db):
        results = get_lab_trend(
            synonym_db,
            test_names=["CEA", "Carcinoembryonic Antigen"],
            start_date="2025-01-01",
        )
        assert len(results) == 4  # Excludes 2024-11-01

    def test_loinc_takes_precedence_over_test_names(self, synonym_db):
        """LOINC filter should be preferred over test_names if both provided."""
        results = get_lab_trend(synonym_db, test_loinc="2039-6",
                                test_names=["CEA", "Carcinoembryonic Antigen"])
        # test_loinc matches all 5 since both names share the same LOINC
        assert len(results) == 5


class TestLabSeriesMultiName:
    def test_multi_name_series(self, synonym_db):
        series = get_lab_series(synonym_db,
                                test_names=["CEA", "Carcinoembryonic Antigen"])
        assert len(series["results"]) == 5
        assert "epic_anderson" in series["sources"]
        assert "meditech_siteman" in series["sources"]

    def test_multi_name_ref_range_discrepancy(self, synonym_db):
        series = get_lab_series(synonym_db,
                                test_names=["CEA", "Carcinoembryonic Antigen"])
        assert series["ref_range_discrepancy"] is True

    def test_single_name_series_misses_synonyms(self, synonym_db):
        """Confirm the problem: single test_name misses cross-source data."""
        series = get_lab_series(synonym_db, test_name="CEA")
        assert len(series["results"]) == 2
        assert len(series["sources"]) == 1

    def test_multi_name_empty_when_no_match(self, synonym_db):
        series = get_lab_series(synonym_db, test_names=["NonExistent", "AlsoNot"])
        assert series["results"] == []


class TestLabSeries:
    def test_cross_source_series(self, multi_source_db):
        series = get_lab_series(multi_source_db, test_name="CEA")
        assert series["test_name"] == "CEA"
        assert len(series["results"]) == 4
        # Chronological order
        dates = [r["result_date"] for r in series["results"]]
        assert dates == sorted(dates)

    def test_cross_source_sources(self, multi_source_db):
        series = get_lab_series(multi_source_db, test_name="CEA")
        assert "epic_anderson" in series["sources"]
        assert "meditech_anderson" in series["sources"]

    def test_ref_range_discrepancy(self, multi_source_db):
        series = get_lab_series(multi_source_db, test_name="CEA")
        assert series["ref_range_discrepancy"] is True
        assert series["ref_ranges"]["epic_anderson"] == "0.0-3.0"
        assert series["ref_ranges"]["meditech_anderson"] == "0.0-5.0"

    def test_no_discrepancy_single_source(self, multi_source_db):
        series = get_lab_series(multi_source_db, test_name="Hemoglobin")
        assert series["ref_range_discrepancy"] is False
        assert len(series["sources"]) == 1

    def test_empty_result(self, multi_source_db):
        series = get_lab_series(multi_source_db, test_name="NonExistentTest")
        assert series["results"] == []
        assert series["sources"] == []
        assert series["ref_range_discrepancy"] is False

    def test_no_args(self, multi_source_db):
        series = get_lab_series(multi_source_db)
        assert series["results"] == []

    def test_date_filter(self, multi_source_db):
        series = get_lab_series(multi_source_db, test_name="CEA", start_date="2025-06-01")
        assert len(series["results"]) == 2  # June epic + Aug meditech

    def test_loinc_filter(self, multi_source_db):
        """get_lab_series should also work with LOINC codes."""
        series = get_lab_series(multi_source_db, test_loinc="nonexistent")
        assert series["results"] == []


class TestAvailableTests:
    def test_returns_all_tests(self, multi_source_db):
        tests = get_available_tests(multi_source_db)
        names = [t["test_name"] for t in tests]
        assert "CEA" in names
        assert "Hemoglobin" in names

    def test_count_and_sources(self, multi_source_db):
        tests = get_available_tests(multi_source_db)
        cea = next(t for t in tests if t["test_name"] == "CEA")
        assert cea["count"] == 4
        assert "epic_anderson" in cea["sources"]
        assert "meditech_anderson" in cea["sources"]

    def test_date_range(self, multi_source_db):
        tests = get_available_tests(multi_source_db)
        cea = next(t for t in tests if t["test_name"] == "CEA")
        assert cea["first_date"] == "2025-01-01"
        assert cea["last_date"] == "2025-08-01"

    def test_ordered_by_frequency(self, multi_source_db):
        tests = get_available_tests(multi_source_db)
        assert tests[0]["test_name"] == "CEA"  # 4 results vs 1 for Hemoglobin


@pytest.fixture
def visit_diff_db(tmp_path):
    """Database with varied data for testing visit_diff across date ranges."""
    db = ChartfoldDB(str(tmp_path / "diff.db"))
    db.init_schema()

    records = UnifiedRecords(
        source="test",
        lab_results=[
            LabResult(source="test", test_name="CEA", value="1.4", value_numeric=1.4,
                      unit="ng/mL", result_date="2025-01-01"),
            LabResult(source="test", test_name="CEA", value="5.8", value_numeric=5.8,
                      unit="ng/mL", interpretation="H", result_date="2025-06-15"),
        ],
        imaging_reports=[
            ImagingReport(source="test", study_name="CT Abdomen", modality="CT",
                          study_date="2025-05-01", impression="No recurrence."),
            ImagingReport(source="test", study_name="PET/CT", modality="PET",
                          study_date="2025-07-01", impression="New uptake noted."),
        ],
        medications=[
            MedicationRecord(source="test", name="Capecitabine", status="active",
                             start_date="2025-01-01"),
            MedicationRecord(source="test", name="Ondansetron", status="active",
                             start_date="2025-06-01"),
            MedicationRecord(source="test", name="Oxycodone", status="completed",
                             start_date="2024-06-01", stop_date="2025-06-01"),
        ],
        clinical_notes=[
            ClinicalNote(source="test", note_type="progress", author="Dr. Smith",
                         note_date="2025-06-15", content="Follow up visit."),
        ],
        conditions=[
            ConditionRecord(source="test", condition_name="Colon cancer",
                            clinical_status="active", onset_date="2021-11-22"),
            ConditionRecord(source="test", condition_name="Anemia",
                            clinical_status="active", onset_date="2025-06-01"),
        ],
        encounters=[
            EncounterRecord(source="test", encounter_date="2025-01-15",
                            encounter_type="office visit", facility="Anderson"),
            EncounterRecord(source="test", encounter_date="2025-06-15",
                            encounter_type="office visit", facility="Anderson"),
        ],
        procedures=[
            ProcedureRecord(source="test", name="Colonoscopy",
                            procedure_date="2025-03-01", facility="Anderson"),
        ],
        pathology_reports=[
            PathologyReport(source="test", report_date="2025-03-03",
                            specimen="Colon biopsy", diagnosis="No dysplasia"),
        ],
    )
    db.load_source(records)
    yield db
    db.close()


class TestVisitDiff:
    def test_returns_all_categories(self, visit_diff_db):
        diff = visit_diff(visit_diff_db, since_date="2025-06-01")
        assert "new_labs" in diff
        assert "new_imaging" in diff
        assert "new_pathology" in diff
        assert "medication_changes" in diff
        assert "new_notes" in diff
        assert "new_conditions" in diff
        assert "new_encounters" in diff
        assert "new_procedures" in diff
        assert "summary" in diff

    def test_filters_by_date(self, visit_diff_db):
        diff = visit_diff(visit_diff_db, since_date="2025-06-01")
        # Only June 15 CEA (5.8) should be included
        assert len(diff["new_labs"]) == 1
        assert diff["new_labs"][0]["value"] == "5.8"

    def test_imaging_filter(self, visit_diff_db):
        diff = visit_diff(visit_diff_db, since_date="2025-06-01")
        assert len(diff["new_imaging"]) == 1
        assert diff["new_imaging"][0]["study_name"] == "PET/CT"

    def test_medication_changes(self, visit_diff_db):
        diff = visit_diff(visit_diff_db, since_date="2025-06-01")
        # Ondansetron started June 1, Oxycodone stopped June 1
        assert len(diff["medication_changes"]) == 2

    def test_conditions_by_onset(self, visit_diff_db):
        diff = visit_diff(visit_diff_db, since_date="2025-06-01")
        assert len(diff["new_conditions"]) == 1
        assert diff["new_conditions"][0]["condition_name"] == "Anemia"

    def test_summary_counts(self, visit_diff_db):
        diff = visit_diff(visit_diff_db, since_date="2025-06-01")
        assert diff["summary"]["labs"] == 1
        assert diff["summary"]["imaging"] == 1
        assert diff["summary"]["medication_changes"] == 2
        assert diff["summary"]["conditions"] == 1

    def test_early_date_gets_everything(self, visit_diff_db):
        diff = visit_diff(visit_diff_db, since_date="2020-01-01")
        assert len(diff["new_labs"]) == 2
        assert len(diff["new_encounters"]) == 2

    def test_future_date_gets_nothing(self, visit_diff_db):
        diff = visit_diff(visit_diff_db, since_date="2030-01-01")
        assert all(v == 0 for v in diff["summary"].values())

    def test_empty_date_returns_error(self, visit_diff_db):
        diff = visit_diff(visit_diff_db, since_date="")
        assert "error" in diff

    def test_since_date_preserved(self, visit_diff_db):
        diff = visit_diff(visit_diff_db, since_date="2025-06-01")
        assert diff["since_date"] == "2025-06-01"


class TestMedications:
    def test_active_medications(self, analysis_db):
        active = get_active_medications(analysis_db)
        assert len(active) == 2
        names = [m["name"] for m in active]
        assert "Capecitabine 500mg" in names
        assert "Ondansetron 8mg" in names

    def test_medication_history(self, analysis_db):
        history = get_medication_history(analysis_db)
        assert len(history) == 3  # All medications

    def test_medication_history_filtered(self, analysis_db):
        history = get_medication_history(analysis_db, med_name="capecitabine")
        assert len(history) == 1


class TestVisitPrep:
    def test_generate_prep(self, analysis_db):
        prep = generate_visit_prep(analysis_db, visit_date="2025-07-01", lookback_months=3)
        assert prep["visit_date"] == "2025-07-01"
        assert len(prep["active_meds"]) == 2
        assert len(prep["active_conditions"]) == 1
        # Recent labs within 3 months of July 2025
        assert len(prep["recent_labs"]) >= 2  # CEA + Hemoglobin from June

    def test_prep_default_date(self, analysis_db):
        prep = generate_visit_prep(analysis_db)
        assert prep["visit_date"]  # Should be today's date


class TestSurgicalTimeline:
    def test_builds_timeline(self, surgical_db):
        timeline = build_surgical_timeline(surgical_db)
        assert len(timeline) == 2

    def test_procedure_fields(self, surgical_db):
        timeline = build_surgical_timeline(surgical_db)
        proc0 = timeline[0]["procedure"]
        assert proc0["name"] == "Right hemicolectomy"
        assert proc0["date"] == "2024-07-01"
        assert proc0["facility"] == "Anderson Hospital"

    def test_pathology_linked(self, surgical_db):
        timeline = build_surgical_timeline(surgical_db)
        # Pathology report_date 2024-07-03 within 14 days of procedure 2024-07-01
        path0 = timeline[0]["pathology"]
        assert path0 is not None
        assert "adenocarcinoma" in path0["diagnosis"].lower()
        assert "pT3N2a" in path0["staging"]

    def test_related_imaging(self, surgical_db):
        timeline = build_surgical_timeline(surgical_db)
        # CT on 2024-06-25 is within 30 days of 2024-07-01 procedure
        imgs = timeline[0]["related_imaging"]
        assert len(imgs) >= 1
        assert any("CT" in img["study"] for img in imgs)

    def test_second_procedure(self, surgical_db):
        timeline = build_surgical_timeline(surgical_db)
        proc1 = timeline[1]["procedure"]
        assert proc1["name"] == "Liver resection"
        path1 = timeline[1]["pathology"]
        assert path1 is not None
        assert "cauterized" in path1["margins"].lower()

    def test_empty_db(self, tmp_db):
        timeline = build_surgical_timeline(tmp_db)
        assert timeline == []

    def test_imaging_has_timing(self, surgical_db):
        timeline = build_surgical_timeline(surgical_db)
        imgs = timeline[0]["related_imaging"]
        # CT on 2024-06-25 before proc on 2024-07-01 → pre-op
        ct_img = next(i for i in imgs if "CT" in i["study"])
        assert ct_img["timing"] == "pre-op"

    def test_wider_preop_window(self, surgical_db):
        """Pre-op imaging up to 90 days before should be captured."""
        timeline = build_surgical_timeline(surgical_db, pre_op_imaging_days=90)
        # CT on 2024-06-25 is 6 days before 2024-07-01 — well within 90
        imgs = timeline[0]["related_imaging"]
        assert any("CT" in img["study"] for img in imgs)

    def test_related_medications(self, surgical_db):
        """related_medications should be present (may be empty in test fixture)."""
        timeline = build_surgical_timeline(surgical_db)
        assert "related_medications" in timeline[0]

    def test_imaging_source_included(self, surgical_db):
        timeline = build_surgical_timeline(surgical_db)
        imgs = timeline[0]["related_imaging"]
        if imgs:
            assert "source" in imgs[0]


@pytest.fixture
def cross_source_encounter_db(tmp_path):
    """Database with encounters from multiple sources on the same date."""
    db = ChartfoldDB(str(tmp_path / "cross.db"))
    db.init_schema()

    epic = UnifiedRecords(
        source="epic_anderson",
        encounters=[
            EncounterRecord(source="epic_anderson", encounter_date="2025-06-15",
                            encounter_type="office visit", facility="Anderson Hospital",
                            provider="Dr. Oncologist"),
            EncounterRecord(source="epic_anderson", encounter_date="2025-01-10",
                            encounter_type="inpatient", facility="Anderson Hospital"),
        ],
    )
    meditech = UnifiedRecords(
        source="meditech_anderson",
        encounters=[
            EncounterRecord(source="meditech_anderson", encounter_date="2025-06-15",
                            encounter_type="inpatient", facility="Anderson Hospital",
                            provider="Dr. Surgeon"),
        ],
    )
    athena = UnifiedRecords(
        source="athena_sihf",
        encounters=[
            EncounterRecord(source="athena_sihf", encounter_date="2025-06-16",
                            encounter_type="office visit", facility="SIHF",
                            provider="Dr. PCP"),
        ],
    )
    db.load_source(epic)
    db.load_source(meditech)
    db.load_source(athena)
    yield db
    db.close()


class TestCrossSourceEncounterMatching:
    def test_exact_date_match(self, cross_source_encounter_db):
        matches = match_encounters_by_date(cross_source_encounter_db)
        # June 15 appears in both epic and meditech
        assert len(matches) == 1
        assert matches[0]["date"] == "2025-06-15"
        assert len(matches[0]["encounters"]) == 2

    def test_no_match_single_source_date(self, cross_source_encounter_db):
        matches = match_encounters_by_date(cross_source_encounter_db)
        # Jan 10 is only in epic — should not appear
        matched_dates = [m["date"] for m in matches]
        assert "2025-01-10" not in matched_dates

    def test_tolerance_matching(self, cross_source_encounter_db):
        # With 1-day tolerance, June 15 (epic/meditech) + June 16 (athena) should match
        matches = match_encounters_by_date(cross_source_encounter_db, tolerance_days=1)
        assert len(matches) >= 1
        # Find the June 15 match — should now include athena
        june_match = next(m for m in matches if m["date"] == "2025-06-15")
        assert "athena_sihf" in june_match["sources"]

    def test_sources_listed(self, cross_source_encounter_db):
        matches = match_encounters_by_date(cross_source_encounter_db)
        assert "epic_anderson" in matches[0]["sources"]
        assert "meditech_anderson" in matches[0]["sources"]

    def test_empty_db(self, tmp_db):
        matches = match_encounters_by_date(tmp_db)
        assert matches == []
