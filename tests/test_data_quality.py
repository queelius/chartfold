"""Tests for chartfold.analysis.data_quality module."""

import pytest

from chartfold.analysis.data_quality import (
    find_duplicate_labs,
    get_data_quality,
    source_coverage_matrix,
)
from chartfold.db import ChartfoldDB
from chartfold.models import (
    ConditionRecord,
    LabResult,
    MedicationRecord,
    UnifiedRecords,
)


@pytest.fixture
def quality_db(tmp_path):
    """Database with cross-source data for quality testing."""
    db = ChartfoldDB(str(tmp_path / "quality.db"))
    db.init_schema()

    epic = UnifiedRecords(
        source="epic_anderson",
        lab_results=[
            # Duplicate: same test, same date, same value
            LabResult(
                source="epic_anderson",
                test_name="CEA",
                value="5.8",
                value_numeric=5.8,
                unit="ng/mL",
                ref_range="0.0-3.0",
                result_date="2025-06-15",
            ),
            # Not a duplicate: different date
            LabResult(
                source="epic_anderson",
                test_name="CEA",
                value="3.2",
                value_numeric=3.2,
                unit="ng/mL",
                ref_range="0.0-3.0",
                result_date="2025-01-01",
            ),
            # Unique to epic
            LabResult(
                source="epic_anderson",
                test_name="Hemoglobin",
                value="12.5",
                value_numeric=12.5,
                unit="g/dL",
                result_date="2025-06-15",
            ),
        ],
        medications=[
            MedicationRecord(source="epic_anderson", name="Capecitabine", status="active"),
        ],
        conditions=[
            ConditionRecord(
                source="epic_anderson", condition_name="Colon cancer", clinical_status="active"
            ),
        ],
    )
    meditech = UnifiedRecords(
        source="meditech_anderson",
        lab_results=[
            # Duplicate: same test, same date, same value
            LabResult(
                source="meditech_anderson",
                test_name="CEA",
                value="5.8",
                value_numeric=5.8,
                unit="ng/mL",
                ref_range="0.0-5.0",
                result_date="2025-06-15",
            ),
            # Duplicate: same test, same date, DIFFERENT value
            LabResult(
                source="meditech_anderson",
                test_name="Hemoglobin",
                value="12.8",
                value_numeric=12.8,
                unit="g/dL",
                result_date="2025-06-15",
            ),
        ],
        medications=[
            MedicationRecord(source="meditech_anderson", name="Capecitabine", status="active"),
        ],
    )
    db.load_source(epic)
    db.load_source(meditech)
    yield db
    db.close()


class TestDuplicateLabs:
    def test_finds_duplicates(self, quality_db):
        dupes = find_duplicate_labs(quality_db)
        assert len(dupes) == 2  # CEA and Hemoglobin on 2025-06-15

    def test_value_match_flag(self, quality_db):
        dupes = find_duplicate_labs(quality_db)
        cea = next(d for d in dupes if d["test_name"] == "CEA")
        hgb = next(d for d in dupes if d["test_name"] == "Hemoglobin")
        # CEA has same value (5.8) from both sources
        assert cea["value_match"] is True
        # Hemoglobin has different values (12.5 vs 12.8)
        assert hgb["value_match"] is False

    def test_records_included(self, quality_db):
        dupes = find_duplicate_labs(quality_db)
        cea = next(d for d in dupes if d["test_name"] == "CEA")
        assert len(cea["records"]) == 2
        sources = {r["source"] for r in cea["records"]}
        assert sources == {"epic_anderson", "meditech_anderson"}

    def test_no_duplicates_empty_db(self, tmp_db):
        dupes = find_duplicate_labs(tmp_db)
        assert dupes == []


class TestSourceCoverage:
    def test_lists_sources(self, quality_db):
        coverage = source_coverage_matrix(quality_db)
        assert "epic_anderson" in coverage["sources"]
        assert "meditech_anderson" in coverage["sources"]

    def test_table_counts(self, quality_db):
        coverage = source_coverage_matrix(quality_db)
        lab_counts = coverage["tables"]["lab_results"]
        assert lab_counts["epic_anderson"] == 3
        assert lab_counts["meditech_anderson"] == 2

    def test_table_missing_source(self, quality_db):
        coverage = source_coverage_matrix(quality_db)
        # Conditions only in epic
        cond_counts = coverage["tables"]["conditions"]
        assert cond_counts.get("epic_anderson") == 1
        assert "meditech_anderson" not in cond_counts

    def test_summary_totals(self, quality_db):
        coverage = source_coverage_matrix(quality_db)
        assert coverage["summary"]["epic_anderson"] > 0
        assert coverage["summary"]["meditech_anderson"] > 0

    def test_empty_db(self, tmp_db):
        coverage = source_coverage_matrix(tmp_db)
        assert coverage["sources"] == []
        assert coverage["summary"] == {}


class TestDataQuality:
    def test_combined_report(self, quality_db):
        report = get_data_quality(quality_db)
        assert "duplicate_labs" in report
        assert "coverage" in report
        assert report["duplicate_count"] == 2
        assert report["sources_count"] == 2

    def test_empty_db(self, tmp_db):
        report = get_data_quality(tmp_db)
        assert report["duplicate_count"] == 0
        assert report["sources_count"] == 0
