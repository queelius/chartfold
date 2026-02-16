"""Tests for chartfold.mcp.server tools.

Tests the tool functions directly (not via MCP protocol).
"""

import pytest

from chartfold.db import ChartfoldDB
from chartfold.models import (
    ConditionRecord,
    EncounterRecord,
    LabResult,
    MedicationRecord,
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
    """Multi-source database for cross-source testing."""
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


# ---------------------------------------------------------------------------
# run_sql — read-only connection enforcement
# ---------------------------------------------------------------------------


class TestRunSQL:
    def test_select(self, mcp_db):
        result = mcp_db.run_sql("SELECT test_name, value FROM lab_results")
        assert len(result) == 1
        assert result[0]["test_name"] == "CEA"

    def test_allows_with(self, mcp_db):
        result = mcp_db.run_sql("WITH recent AS (SELECT * FROM lab_results) SELECT * FROM recent")
        assert len(result) == 1

    def test_allows_pragma(self, mcp_db):
        result = mcp_db.run_sql("PRAGMA table_info('lab_results')")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_rejects_insert(self, mcp_db):
        result = mcp_db.run_sql("INSERT INTO lab_results (source) VALUES ('bad')")
        assert isinstance(result, str)
        assert "Error" in result

    def test_rejects_delete(self, mcp_db):
        result = mcp_db.run_sql("DELETE FROM lab_results")
        assert isinstance(result, str)
        assert "Error" in result

    def test_rejects_drop(self, mcp_db):
        result = mcp_db.run_sql("DROP TABLE lab_results")
        assert isinstance(result, str)
        assert "Error" in result

    def test_rejects_update(self, mcp_db):
        result = mcp_db.run_sql("UPDATE lab_results SET value = 'hacked'")
        assert isinstance(result, str)
        assert "Error" in result

    def test_rejects_create(self, mcp_db):
        result = mcp_db.run_sql("CREATE TABLE evil (id INTEGER)")
        assert isinstance(result, str)
        assert "Error" in result

    def test_rejects_attach(self, mcp_db):
        result = mcp_db.run_sql("ATTACH DATABASE ':memory:' AS evil")
        assert isinstance(result, str)
        assert "Error" in result

    def test_sql_error(self, mcp_db):
        result = mcp_db.run_sql("SELECT * FROM nonexistent_table")
        assert isinstance(result, str)
        assert "Error" in result

    def test_readonly_message_for_write(self, mcp_db):
        """Verify write attempts get the read-only specific error."""
        result = mcp_db.run_sql("INSERT INTO lab_results (source) VALUES ('bad')")
        assert isinstance(result, str)
        assert "read-only" in result.lower() or "error" in result.lower()

    def test_cross_source_query(self, mcp_multi_db):
        """The LLM can write cross-source queries directly."""
        result = mcp_multi_db.run_sql(
            "SELECT source, COUNT(*) as n FROM lab_results GROUP BY source ORDER BY source"
        )
        assert len(result) == 2
        sources = {r["source"] for r in result}
        assert sources == {"epic", "meditech"}

    def test_json_extract(self, mcp_db):
        """Verify json_extract works for querying analyses frontmatter."""
        # First save an analysis with frontmatter
        mcp_db.save_analysis(
            slug="test-json",
            title="Test",
            content="body",
            frontmatter_yaml="status: current\ndate: 2025-01-01",
        )
        result = mcp_db.run_sql(
            "SELECT slug, json_extract(frontmatter, '$.status') as status FROM analyses"
        )
        assert len(result) >= 1
        match = [r for r in result if r["slug"] == "test-json"]
        assert match[0]["status"] == "current"


# ---------------------------------------------------------------------------
# get_schema
# ---------------------------------------------------------------------------


class TestGetSchema:
    def test_returns_ddl(self, mcp_db):
        result = mcp_db.get_schema()
        assert "CREATE TABLE" in result
        assert "lab_results" in result
        assert "medications" in result
        assert "analyses" in result
        assert "source_assets" in result


# ---------------------------------------------------------------------------
# get_database_summary
# ---------------------------------------------------------------------------


class TestGetDatabaseSummary:
    def test_summary(self, mcp_db):
        result = mcp_db.get_database_summary()
        assert "table_counts" in result
        assert result["table_counts"]["lab_results"] == 1

    def test_multi_source(self, mcp_multi_db):
        result = mcp_multi_db.get_database_summary()
        assert "load_history" in result
        assert len(result["load_history"]) == 2


# ---------------------------------------------------------------------------
# Personal notes CRUD
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Structured analyses CRUD
# ---------------------------------------------------------------------------


class TestSaveAnalysisTool:
    def test_create(self, mcp_notes_db):
        result = mcp_notes_db.save_analysis(
            slug="test-analysis",
            title="Test Analysis",
            content="# Analysis\n\nBody text.",
            category="oncology",
            tags="cancer,CEA",
        )
        assert result["status"] == "created"
        assert result["slug"] == "test-analysis"

    def test_upsert(self, mcp_notes_db):
        mcp_notes_db.save_analysis(slug="dup", title="v1", content="first")
        result = mcp_notes_db.save_analysis(slug="dup", title="v2", content="second")
        assert result["status"] == "updated"
        fetched = mcp_notes_db.get_analysis("dup")
        assert fetched["title"] == "v2"
        assert fetched["content"] == "second"

    def test_with_frontmatter_yaml(self, mcp_notes_db):
        result = mcp_notes_db.save_analysis(
            slug="fm-test",
            title="Frontmatter Test",
            content="body",
            frontmatter_yaml="status: current\ndate: 2025-01-01",
        )
        assert result["status"] == "created"
        fetched = mcp_notes_db.get_analysis("fm-test")
        assert fetched["frontmatter"] is not None


class TestGetAnalysisTool:
    def test_get_existing(self, mcp_notes_db):
        mcp_notes_db.save_analysis(slug="get-test", title="Get Test", content="body")
        result = mcp_notes_db.get_analysis("get-test")
        assert result["title"] == "Get Test"

    def test_not_found(self, mcp_notes_db):
        result = mcp_notes_db.get_analysis("nonexistent")
        assert isinstance(result, str)
        assert "not found" in result


class TestSearchAnalysesTool:
    def test_search_by_category(self, mcp_notes_db):
        mcp_notes_db.save_analysis(slug="s1", title="A", content="body", category="oncology")
        mcp_notes_db.save_analysis(slug="s2", title="B", content="body", category="timeline")
        results = mcp_notes_db.search_analyses(category="oncology")
        assert all(r["category"] == "oncology" for r in results)

    def test_search_by_tag(self, mcp_notes_db):
        mcp_notes_db.save_analysis(slug="t1", title="A", content="body", tags="cancer,CEA")
        results = mcp_notes_db.search_analyses(tag="CEA")
        assert len(results) >= 1


class TestListAnalysesTool:
    def test_list(self, mcp_notes_db):
        mcp_notes_db.save_analysis(slug="l1", title="First", content="body")
        mcp_notes_db.save_analysis(slug="l2", title="Second", content="body")
        results = mcp_notes_db.list_analyses()
        slugs = [r["slug"] for r in results]
        assert "l1" in slugs
        assert "l2" in slugs


class TestDeleteAnalysisTool:
    def test_delete(self, mcp_notes_db):
        mcp_notes_db.save_analysis(slug="del-me", title="Delete Me", content="body")
        result = mcp_notes_db.delete_analysis("del-me")
        assert result["deleted"] is True
        assert mcp_notes_db.get_analysis("del-me") == "Analysis 'del-me' not found."

    def test_delete_nonexistent(self, mcp_notes_db):
        result = mcp_notes_db.delete_analysis("nope")
        assert result["deleted"] is False
