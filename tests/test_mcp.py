"""Tests for chartfold.mcp.server tools.

Tests the tool functions directly (not via MCP protocol).
"""

import pytest

from chartfold.db import ChartfoldDB
from chartfold.models import (
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
def mcp_db(tmp_path, monkeypatch):
    """Set up a test database and configure MCP to use it."""
    db_path = str(tmp_path / "mcp_test.db")
    monkeypatch.setenv("CHARTFOLD_DB", db_path)

    db = ChartfoldDB(db_path)
    db.init_schema()

    records = UnifiedRecords(
        source="test",
        lab_results=[
            LabResult(
                source="test",
                test_name="CEA",
                value="5.8",
                value_numeric=5.8,
                unit="ng/mL",
                ref_range="0.0-3.0",
                interpretation="H",
                result_date="2025-06-15",
            ),
        ],
        medications=[
            MedicationRecord(
                source="test", name="Capecitabine 500mg", status="active", sig="2 tabs twice daily"
            ),
        ],
        conditions=[
            ConditionRecord(
                source="test",
                condition_name="Colon cancer",
                icd10_code="C18.9",
                clinical_status="active",
            ),
        ],
    )
    db.load_source(records)
    db.close()

    # Reload the module to pick up new env var
    import chartfold.mcp.server as srv

    monkeypatch.setattr(srv, "DB_PATH", db_path)
    yield srv


@pytest.fixture
def mcp_multi_db(tmp_path, monkeypatch):
    """Multi-source database for cross-source MCP tool testing."""
    db_path = str(tmp_path / "mcp_multi.db")
    monkeypatch.setenv("CHARTFOLD_DB", db_path)

    db = ChartfoldDB(db_path)
    db.init_schema()

    epic = UnifiedRecords(
        source="epic",
        lab_results=[
            LabResult(
                source="epic",
                test_name="CEA",
                value="5.8",
                value_numeric=5.8,
                unit="ng/mL",
                ref_range="0.0-3.0",
                interpretation="H",
                result_date="2025-06-15",
            ),
            LabResult(
                source="epic",
                test_name="Hemoglobin",
                value="12.5",
                value_numeric=12.5,
                unit="g/dL",
                ref_range="13.0-17.0",
                interpretation="L",
                result_date="2025-06-15",
            ),
            LabResult(
                source="epic",
                test_name="CEA",
                value="3.2",
                value_numeric=3.2,
                unit="ng/mL",
                ref_range="0.0-3.0",
                interpretation="",
                result_date="2025-01-10",
            ),
        ],
        medications=[
            MedicationRecord(
                source="epic",
                name="Capecitabine 500mg",
                status="active",
                sig="2 tabs twice daily",
                start_date="2025-01-01",
            ),
        ],
        encounters=[
            EncounterRecord(
                source="epic",
                encounter_date="2025-06-15",
                encounter_type="office visit",
                facility="Anderson",
                provider="Dr. Smith",
            ),
        ],
        procedures=[
            ProcedureRecord(
                source="epic",
                name="Right hemicolectomy",
                procedure_date="2024-07-01",
                facility="Anderson",
            ),
        ],
        pathology_reports=[
            PathologyReport(
                source="epic",
                report_date="2024-07-03",
                specimen="Right colon",
                diagnosis="Adenocarcinoma",
                staging="pT3N2a",
                margins="Negative",
            ),
        ],
        imaging_reports=[
            ImagingReport(
                source="epic",
                study_name="CT Abdomen",
                modality="CT",
                study_date="2024-06-01",
                impression="Mass in right colon.",
            ),
        ],
    )
    meditech = UnifiedRecords(
        source="meditech",
        lab_results=[
            LabResult(
                source="meditech",
                test_name="CEA",
                value="5.8",
                value_numeric=5.8,
                unit="ng/mL",
                ref_range="0.0-5.0",
                interpretation="H",
                result_date="2025-06-15",
            ),
        ],
        medications=[
            MedicationRecord(
                source="meditech",
                name="Capecitabine 500mg",
                status="completed",
                sig="2 tabs twice daily",
                start_date="2025-01-01",
                stop_date="2025-06-01",
            ),
        ],
        encounters=[
            EncounterRecord(
                source="meditech",
                encounter_date="2025-06-15",
                encounter_type="lab visit",
                facility="Anderson Lab",
            ),
        ],
    )
    db.load_source(epic)
    db.load_source(meditech)
    db.close()

    import chartfold.mcp.server as srv

    monkeypatch.setattr(srv, "DB_PATH", db_path)
    yield srv


class TestRunSQL:
    def test_select(self, mcp_db):
        result = mcp_db.run_sql("SELECT test_name, value FROM lab_results")
        assert len(result) == 1
        assert result[0]["test_name"] == "CEA"

    def test_rejects_insert(self, mcp_db):
        result = mcp_db.run_sql("INSERT INTO lab_results (source) VALUES ('bad')")
        assert "Error" in result

    def test_rejects_delete(self, mcp_db):
        result = mcp_db.run_sql("DELETE FROM lab_results")
        assert "Error" in result

    def test_rejects_drop(self, mcp_db):
        result = mcp_db.run_sql("DROP TABLE lab_results")
        assert "Error" in result

    def test_allows_with(self, mcp_db):
        result = mcp_db.run_sql("WITH recent AS (SELECT * FROM lab_results) SELECT * FROM recent")
        assert len(result) == 1

    def test_sql_error(self, mcp_db):
        result = mcp_db.run_sql("SELECT * FROM nonexistent_table")
        assert "Error" in result


class TestQueryLabs:
    def test_by_name(self, mcp_db):
        result = mcp_db.query_labs(test_name="CEA")
        assert len(result) == 1
        assert result[0]["value_numeric"] == 5.8


class TestGetMedications:
    def test_active(self, mcp_db):
        result = mcp_db.get_medications(status="active")
        assert len(result) == 1
        assert "Capecitabine" in result[0]["name"]

    def test_all(self, mcp_db):
        result = mcp_db.get_medications()
        assert len(result) == 1


class TestGetSchema:
    def test_returns_ddl(self, mcp_db):
        result = mcp_db.get_schema()
        assert "CREATE TABLE" in result
        assert "lab_results" in result
        assert "medications" in result


class TestGetDatabaseSummary:
    def test_summary(self, mcp_db):
        result = mcp_db.get_database_summary()
        assert "table_counts" in result
        assert result["table_counts"]["lab_results"] == 1


class TestGetLabSeriesTool:
    def test_cross_source_series(self, mcp_multi_db):
        result = mcp_multi_db.get_lab_series_tool(test_name="CEA")
        assert result["test_name"] == "CEA"
        assert len(result["results"]) >= 3  # 2 epic + 1 meditech
        assert len(result["sources"]) == 2

    def test_ref_range_discrepancy(self, mcp_multi_db):
        result = mcp_multi_db.get_lab_series_tool(test_name="CEA")
        # epic has 0.0-3.0, meditech has 0.0-5.0
        assert result["ref_range_discrepancy"] is True

    def test_empty_result(self, mcp_multi_db):
        result = mcp_multi_db.get_lab_series_tool(test_name="nonexistent")
        assert result["results"] == []


class TestGetAvailableTests:
    def test_lists_tests(self, mcp_multi_db):
        result = mcp_multi_db.get_available_tests_tool()
        names = [r["test_name"] for r in result]
        assert "CEA" in names
        assert "Hemoglobin" in names

    def test_counts(self, mcp_multi_db):
        result = mcp_multi_db.get_available_tests_tool()
        cea = next(r for r in result if r["test_name"] == "CEA")
        assert cea["count"] == 3  # 2 epic + 1 meditech


class TestGetAbnormalLabs:
    def test_finds_abnormal(self, mcp_multi_db):
        result = mcp_multi_db.get_abnormal_labs_tool()
        assert len(result) >= 2  # CEA H from epic, CEA H from meditech, Hgb L from epic

    def test_date_filter(self, mcp_multi_db):
        result = mcp_multi_db.get_abnormal_labs_tool(start_date="2025-06-01")
        # Should exclude any results before June 2025
        for r in result:
            assert r["result_date"] >= "2025-06-01"


class TestReconcileMedications:
    def test_finds_discrepancy(self, mcp_multi_db):
        result = mcp_multi_db.reconcile_medications_tool()
        assert "discrepancies" in result
        # Capecitabine is "active" in epic, "completed" in meditech
        assert len(result["discrepancies"]) >= 1
        disc_names = [d["name"].lower() for d in result["discrepancies"]]
        assert any("capecitabine" in n for n in disc_names)

    def test_active_list(self, mcp_multi_db):
        result = mcp_multi_db.reconcile_medications_tool()
        assert "active" in result


class TestMatchCrossSourceEncounters:
    def test_finds_same_day(self, mcp_multi_db):
        result = mcp_multi_db.match_cross_source_encounters()
        # Both sources have encounters on 2025-06-15
        assert len(result) >= 1
        match = result[0]
        assert match["date"] == "2025-06-15"
        sources = {e["source"] for e in match["encounters"]}
        assert "epic" in sources
        assert "meditech" in sources

    def test_no_matches_single_source(self, mcp_db):
        result = mcp_db.match_cross_source_encounters()
        assert result == []


class TestGetTimeline:
    def test_includes_labs(self, mcp_multi_db):
        result = mcp_multi_db.get_timeline(event_types="labs")
        assert len(result) >= 1
        assert all(e["type"] == "lab" for e in result)

    def test_includes_pathology(self, mcp_multi_db):
        result = mcp_multi_db.get_timeline(event_types="pathology")
        assert len(result) >= 1
        assert all(e["type"] == "pathology" for e in result)

    def test_all_types(self, mcp_multi_db):
        result = mcp_multi_db.get_timeline()
        types = {e["type"] for e in result}
        # Should have encounters, procedures, imaging, labs, pathology
        assert "encounter" in types
        assert "lab" in types

    def test_date_filter(self, mcp_multi_db):
        result = mcp_multi_db.get_timeline(start_date="2025-01-01")
        for e in result:
            assert e["date"] >= "2025-01-01"


class TestGetSurgicalTimeline:
    def test_links_pathology(self, mcp_multi_db):
        result = mcp_multi_db.get_surgical_timeline()
        assert len(result) >= 1
        entry = result[0]
        assert entry["procedure"]["name"] == "Right hemicolectomy"
        assert entry["pathology"] is not None
        assert entry["pathology"]["diagnosis"] == "Adenocarcinoma"

    def test_pre_op_imaging(self, mcp_multi_db):
        result = mcp_multi_db.get_surgical_timeline(pre_op_imaging_days=90)
        entry = result[0]
        # CT Abdomen on 2024-06-01 is 30 days before procedure on 2024-07-01
        assert len(entry["related_imaging"]) >= 1

    def test_narrow_window_excludes(self, mcp_multi_db):
        # With only 5 days pre-op window, the CT from 30 days before should be excluded
        result = mcp_multi_db.get_surgical_timeline(pre_op_imaging_days=5)
        entry = result[0]
        assert len(entry["related_imaging"]) == 0


class TestGetVisitDiff:
    def test_returns_diff(self, mcp_multi_db):
        result = mcp_multi_db.get_visit_diff(since_date="2025-06-01")
        assert "new_labs" in result
        assert "summary" in result
        assert len(result["new_labs"]) >= 1

    def test_nothing_new(self, mcp_multi_db):
        result = mcp_multi_db.get_visit_diff(since_date="2099-01-01")
        assert result["summary"]["labs"] == 0


class TestGetDataQualityReport:
    def test_reports_duplicates(self, mcp_multi_db):
        result = mcp_multi_db.get_data_quality_report()
        assert "duplicate_labs" in result
        assert "coverage" in result
        assert result["sources_count"] == 2


# --- Notes MCP tools ---


@pytest.fixture
def mcp_notes_db(tmp_path, monkeypatch):
    """Database with a few pre-saved notes for MCP notes tool testing."""
    db_path = str(tmp_path / "mcp_notes.db")
    monkeypatch.setenv("CHARTFOLD_DB", db_path)

    db = ChartfoldDB(db_path)
    db.init_schema()
    db.save_note(title="CEA Trend", content="CEA rising from 3.2 to 5.8", tags=["oncology", "cea"])
    db.save_note(title="Visit Prep Feb", content="Questions for Dr. Tan", tags=["visit-prep"])
    db.save_note(
        title="Lab Analysis",
        content="Hemoglobin trending down",
        tags=["oncology"],
        ref_table="lab_results",
        ref_id=1,
    )
    db.close()

    import chartfold.mcp.server as srv

    monkeypatch.setattr(srv, "DB_PATH", db_path)
    yield srv


class TestSaveNoteTool:
    def test_create(self, mcp_notes_db):
        result = mcp_notes_db.save_note(
            title="New Note", content="Fresh analysis", tags="oncology,labs"
        )
        assert result["status"] == "created"
        assert result["id"] > 0

    def test_update(self, mcp_notes_db):
        created = mcp_notes_db.save_note(title="Draft", content="v1")
        result = mcp_notes_db.save_note(title="Final", content="v2", note_id=created["id"])
        assert result["status"] == "updated"
        assert result["id"] == created["id"]

    def test_empty_tags_string(self, mcp_notes_db):
        result = mcp_notes_db.save_note(title="No Tags", content="body", tags="")
        note = mcp_notes_db.get_note(result["id"])
        assert note["tags"] == []


class TestSearchNotesPersonalTool:
    def test_search_by_tag(self, mcp_notes_db):
        results = mcp_notes_db.search_notes_personal(tag="oncology")
        assert len(results) == 2  # CEA Trend + Lab Analysis

    def test_search_by_query(self, mcp_notes_db):
        results = mcp_notes_db.search_notes_personal(query="CEA")
        assert len(results) >= 1
        assert any("CEA" in r["title"] for r in results)

    def test_search_all(self, mcp_notes_db):
        results = mcp_notes_db.search_notes_personal()
        assert len(results) == 3

    def test_search_no_match(self, mcp_notes_db):
        results = mcp_notes_db.search_notes_personal(query="nonexistent")
        assert results == []


class TestGetNoteTool:
    def test_get_existing(self, mcp_notes_db):
        # Create a note and retrieve it
        created = mcp_notes_db.save_note(title="Test", content="Body", tags="t1,t2")
        result = mcp_notes_db.get_note(created["id"])
        assert result["title"] == "Test"
        assert result["content"] == "Body"
        assert sorted(result["tags"]) == ["t1", "t2"]

    def test_get_not_found(self, mcp_notes_db):
        result = mcp_notes_db.get_note(99999)
        assert isinstance(result, str)
        assert "not found" in result


class TestDeleteNoteTool:
    def test_delete_existing(self, mcp_notes_db):
        created = mcp_notes_db.save_note(title="To Delete", content="bye")
        result = mcp_notes_db.delete_note(created["id"])
        assert result["deleted"] is True
        # Verify it's gone
        get_result = mcp_notes_db.get_note(created["id"])
        assert "not found" in get_result

    def test_delete_nonexistent(self, mcp_notes_db):
        result = mcp_notes_db.delete_note(99999)
        assert result["deleted"] is False
