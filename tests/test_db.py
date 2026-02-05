"""Tests for chartfold.db SQLite database layer."""

from chartfold.db import ChartfoldDB
from chartfold.models import (
    LabResult,
    UnifiedRecords,
)


class TestSchemaCreation:
    def test_creates_all_tables(self, tmp_db):
        tables = tmp_db.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        table_names = {t["name"] for t in tables}
        expected = {
            "patients",
            "documents",
            "encounters",
            "lab_results",
            "vitals",
            "medications",
            "conditions",
            "procedures",
            "pathology_reports",
            "imaging_reports",
            "clinical_notes",
            "immunizations",
            "allergies",
            "social_history",
            "family_history",
            "mental_status",
            "load_log",
        }
        assert expected.issubset(table_names)

    def test_wal_mode(self, tmp_db):
        result = tmp_db.query("PRAGMA journal_mode")
        assert result[0]["journal_mode"] == "wal"

    def test_foreign_keys_on(self, tmp_db):
        result = tmp_db.query("PRAGMA foreign_keys")
        assert result[0]["foreign_keys"] == 1

    def test_idempotent_schema(self, tmp_db):
        """Running init_schema twice should not error."""
        tmp_db.init_schema()
        tables = tmp_db.query("SELECT name FROM sqlite_master WHERE type='table'")
        assert len(tables) > 10


class TestLoadSource:
    def test_load_patient(self, loaded_db):
        rows = loaded_db.query("SELECT * FROM patients")
        assert len(rows) == 1
        assert rows[0]["name"] == "John Doe"
        assert rows[0]["source"] == "test_source"

    def test_load_documents(self, loaded_db):
        rows = loaded_db.query("SELECT * FROM documents")
        assert len(rows) == 1
        assert rows[0]["doc_id"] == "DOC0001"

    def test_load_encounters(self, loaded_db):
        rows = loaded_db.query("SELECT * FROM encounters")
        assert len(rows) == 1
        assert rows[0]["facility"] == "Test Hospital"

    def test_load_lab_results(self, loaded_db):
        rows = loaded_db.query("SELECT * FROM lab_results ORDER BY test_name")
        assert len(rows) == 2
        cea = next(r for r in rows if r["test_name"] == "CEA")
        assert cea["value"] == "5.8"
        assert cea["value_numeric"] == 5.8
        assert cea["interpretation"] == "H"

    def test_load_medications(self, loaded_db):
        rows = loaded_db.query("SELECT * FROM medications")
        assert len(rows) == 1
        assert "Capecitabine" in rows[0]["name"]

    def test_load_conditions(self, loaded_db):
        rows = loaded_db.query("SELECT * FROM conditions")
        assert len(rows) == 1
        assert rows[0]["icd10_code"] == "C18.9"

    def test_load_log(self, loaded_db):
        rows = loaded_db.query("SELECT * FROM load_log")
        assert len(rows) == 1
        assert rows[0]["source"] == "test_source"
        assert rows[0]["lab_results_count"] == 2

    def test_returns_counts(self, tmp_db, sample_unified_records):
        counts = tmp_db.load_source(sample_unified_records)
        assert counts["patients"] == 1
        assert counts["lab_results"] == 2
        assert counts["medications"] == 1


class TestIdempotentReload:
    def test_reload_replaces_data(self, loaded_db, sample_unified_records):
        """Loading same source again should replace, not duplicate."""
        loaded_db.load_source(sample_unified_records)
        rows = loaded_db.query("SELECT * FROM lab_results")
        assert len(rows) == 2  # Same count, not doubled

    def test_reload_with_changes(self, loaded_db):
        """Reloading with different data should reflect changes."""
        new_records = UnifiedRecords(
            source="test_source",
            lab_results=[
                LabResult(source="test_source", test_name="WBC", value="7.0", value_numeric=7.0),
            ],
        )
        loaded_db.load_source(new_records)
        rows = loaded_db.query("SELECT * FROM lab_results")
        assert len(rows) == 1
        assert rows[0]["test_name"] == "WBC"

    def test_multiple_sources_coexist(self, loaded_db):
        """Loading a different source should not affect existing data."""
        source2 = UnifiedRecords(
            source="other_source",
            lab_results=[
                LabResult(
                    source="other_source", test_name="Glucose", value="95", value_numeric=95.0
                ),
            ],
        )
        loaded_db.load_source(source2)
        rows = loaded_db.query("SELECT * FROM lab_results ORDER BY source")
        assert len(rows) == 3  # 2 from test_source + 1 from other_source


class TestQuery:
    def test_basic_query(self, loaded_db):
        rows = loaded_db.query("SELECT test_name FROM lab_results WHERE value_numeric > ?", (5.0,))
        assert len(rows) == 2  # CEA=5.8, Hemoglobin=12.5

    def test_numeric_filter(self, loaded_db):
        rows = loaded_db.query(
            "SELECT test_name, value_numeric FROM lab_results WHERE interpretation = 'H'"
        )
        assert len(rows) == 1
        assert rows[0]["test_name"] == "CEA"

    def test_empty_result(self, loaded_db):
        rows = loaded_db.query("SELECT * FROM lab_results WHERE test_name = 'NONEXISTENT'")
        assert rows == []


class TestSummary:
    def test_summary(self, loaded_db):
        summary = loaded_db.summary()
        assert summary["patients"] == 1
        assert summary["lab_results"] == 2
        assert summary["medications"] == 1
        assert summary["conditions"] == 1
        assert summary["vitals"] == 0

    def test_sources(self, loaded_db):
        sources = loaded_db.sources()
        assert len(sources) == 1
        assert sources[0]["source"] == "test_source"


class TestContextManager:
    def test_context_manager(self, tmp_path):
        db_path = str(tmp_path / "ctx.db")
        with ChartfoldDB(db_path) as db:
            db.init_schema()
            db.query("SELECT 1")
        # After context exits, connection should be closed
        # Verify by creating new connection
        with ChartfoldDB(db_path) as db2:
            tables = db2.query("SELECT name FROM sqlite_master WHERE type='table'")
            assert len(tables) > 0
