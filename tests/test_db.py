"""Tests for chartfold.db SQLite database layer."""

from chartfold.db import ChartfoldDB, _build_upsert_sql, _cleanup_stale_records, _UNIQUE_KEYS
from chartfold.models import (
    EncounterRecord,
    ImagingReport,
    LabResult,
    SourceAsset,
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
            "genetic_variants",
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

    def test_metadata_column_exists_on_clinical_tables(self, tmp_db):
        """All clinical tables should have a metadata column."""
        clinical_tables = [
            "patients", "documents", "encounters", "lab_results", "vitals",
            "medications", "conditions", "procedures", "pathology_reports",
            "imaging_reports", "clinical_notes", "immunizations", "allergies",
            "social_history", "family_history", "mental_status",
            "genetic_variants",
        ]
        for table in clinical_tables:
            cols = tmp_db.query(f"PRAGMA table_info({table})")
            col_names = {c["name"] for c in cols}
            assert "metadata" in col_names, f"{table} missing metadata column"

    def test_metadata_column_migration(self, tmp_path):
        """init_schema should add metadata column to existing tables that lack it."""
        import sqlite3

        db_path = str(tmp_path / "legacy.db")
        # Create a minimal legacy table without metadata
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE procedures ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "source TEXT NOT NULL, name TEXT NOT NULL, "
            "procedure_date TEXT, provider TEXT)"
        )
        conn.close()

        # Now open with ChartfoldDB and init_schema — should add metadata column
        db = ChartfoldDB(db_path)
        db.init_schema()
        cols = db.query("PRAGMA table_info(procedures)")
        col_names = {c["name"] for c in cols}
        assert "metadata" in col_names
        db.close()


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

    def test_returns_load_result(self, tmp_db, sample_unified_records):
        result = tmp_db.load_source(sample_unified_records)
        assert result["skipped"] is False
        assert result["content_hash"]  # non-empty hex string
        stats = result["tables"]
        assert stats["patients"]["total"] == 1
        assert stats["patients"]["new"] == 1
        assert stats["lab_results"]["total"] == 2
        assert stats["lab_results"]["new"] == 2
        assert stats["medications"]["total"] == 1


class TestIdempotentReload:
    def test_reload_replaces_data(self, loaded_db, sample_unified_records):
        """Loading same source again should replace, not duplicate."""
        loaded_db.load_source(sample_unified_records)
        rows = loaded_db.query("SELECT * FROM lab_results")
        assert len(rows) == 2  # Same count, not doubled

    def test_reload_with_changes(self, loaded_db):
        """Reloading with different data + replace=True should reflect changes."""
        new_records = UnifiedRecords(
            source="test_source",
            lab_results=[
                LabResult(source="test_source", test_name="WBC", value="7.0", value_numeric=7.0),
            ],
        )
        loaded_db.load_source(new_records, replace=True)
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


class TestUpsertStableIds:
    """UPSERT preserves autoincrement IDs across re-imports."""

    def test_ids_stable_on_reimport(self, loaded_db, sample_unified_records):
        """Re-importing same data should keep the same row IDs."""
        rows_before = loaded_db.query("SELECT id, test_name FROM lab_results ORDER BY id")
        ids_before = {r["test_name"]: r["id"] for r in rows_before}

        loaded_db.load_source(sample_unified_records)

        rows_after = loaded_db.query("SELECT id, test_name FROM lab_results ORDER BY id")
        ids_after = {r["test_name"]: r["id"] for r in rows_after}

        assert ids_before == ids_after

    def test_upsert_updates_values(self, loaded_db):
        """UPSERT should update non-key columns when natural key matches."""
        updated = UnifiedRecords(
            source="test_source",
            lab_results=[
                LabResult(
                    source="test_source",
                    test_name="CEA",
                    value="5.8",
                    value_numeric=5.8,
                    unit="ng/mL",
                    ref_range="0.0-3.0",
                    interpretation="N",  # Changed from H to N
                    result_date="2025-01-15",
                    status="final",
                ),
                LabResult(
                    source="test_source",
                    test_name="Hemoglobin",
                    value="12.5",
                    value_numeric=12.5,
                    unit="g/dL",
                    ref_range="13.0-17.0",
                    interpretation="L",
                    result_date="2025-01-15",
                ),
            ],
        )
        # Get ID before
        cea_before = loaded_db.query(
            "SELECT id FROM lab_results WHERE test_name = 'CEA'"
        )[0]["id"]

        loaded_db.load_source(updated)

        cea_after = loaded_db.query(
            "SELECT id, interpretation FROM lab_results WHERE test_name = 'CEA'"
        )[0]
        assert cea_after["id"] == cea_before  # Same ID
        assert cea_after["interpretation"] == "N"  # Updated value

    def test_replace_true_removes_stale_records(self, loaded_db):
        """replace=True should delete records no longer in the import."""
        # Original has CEA + Hemoglobin. Import with only WBC.
        new_records = UnifiedRecords(
            source="test_source",
            lab_results=[
                LabResult(
                    source="test_source", test_name="WBC", value="7.0", value_numeric=7.0
                ),
            ],
        )
        loaded_db.load_source(new_records, replace=True)
        rows = loaded_db.query("SELECT test_name FROM lab_results")
        assert len(rows) == 1
        assert rows[0]["test_name"] == "WBC"

    def test_replace_false_preserves_existing(self, loaded_db):
        """replace=False should only add/update, not remove existing records."""
        # Original has CEA + Hemoglobin. Add WBC without removing anything.
        new_records = UnifiedRecords(
            source="test_source",
            lab_results=[
                LabResult(
                    source="test_source", test_name="WBC", value="7.0", value_numeric=7.0
                ),
            ],
        )
        loaded_db.load_source(new_records, replace=False)
        rows = loaded_db.query("SELECT test_name FROM lab_results ORDER BY test_name")
        names = [r["test_name"] for r in rows]
        assert names == ["CEA", "Hemoglobin", "WBC"]

    def test_replace_false_updates_existing(self, loaded_db):
        """replace=False should still update matching records."""
        updated = UnifiedRecords(
            source="test_source",
            lab_results=[
                LabResult(
                    source="test_source",
                    test_name="CEA",
                    value="5.8",
                    value_numeric=5.8,
                    unit="ng/mL",
                    interpretation="N",  # Changed
                    result_date="2025-01-15",
                ),
            ],
        )
        loaded_db.load_source(updated, replace=False)
        rows = loaded_db.query("SELECT * FROM lab_results ORDER BY test_name")
        assert len(rows) == 2  # CEA + Hemoglobin still both exist
        cea = next(r for r in rows if r["test_name"] == "CEA")
        assert cea["interpretation"] == "N"

    def test_cross_source_fk_stability(self, tmp_db):
        """UPSERT preserves IDs that other sources reference via FK."""
        # Load imaging report from epic
        epic = UnifiedRecords(
            source="epic",
            imaging_reports=[
                ImagingReport(
                    source="epic",
                    study_name="MRI Brain",
                    study_date="2025-01-15",
                    modality="MRI",
                    impression="Normal",
                ),
            ],
        )
        tmp_db.load_source(epic)
        img_id = tmp_db.query("SELECT id FROM imaging_reports")[0]["id"]

        # Load source_asset from mychart that references the imaging report
        mychart = UnifiedRecords(
            source="mychart",
            source_assets=[
                SourceAsset(
                    source="mychart",
                    asset_type="png",
                    file_path="/tmp/mri-image.png",
                    file_name="mri-image.png",
                    ref_table="imaging_reports",
                    ref_id=img_id,
                ),
            ],
        )
        tmp_db.load_source(mychart, replace=False)

        # Re-import epic — the imaging_report ID should be stable
        tmp_db.load_source(epic)
        img_id_after = tmp_db.query("SELECT id FROM imaging_reports")[0]["id"]
        assert img_id_after == img_id

        # Source asset reference should still be valid
        asset = tmp_db.query("SELECT ref_id FROM source_assets")[0]
        assert asset["ref_id"] == img_id

    def test_replace_true_empty_list_deletes_all(self, loaded_db):
        """replace=True with empty list should delete all records for that source."""
        empty = UnifiedRecords(source="test_source")
        loaded_db.load_source(empty, replace=True)
        rows = loaded_db.query("SELECT * FROM lab_results")
        assert len(rows) == 0

    def test_replace_false_empty_list_no_change(self, loaded_db):
        """replace=False with empty list should leave existing records."""
        empty = UnifiedRecords(source="test_source")
        loaded_db.load_source(empty, replace=False)
        rows = loaded_db.query("SELECT * FROM lab_results")
        assert len(rows) == 2  # Original data untouched


class TestBuildUpsertSql:
    """Unit tests for the UPSERT SQL builder."""

    def test_generates_on_conflict_do_update(self):
        sql = _build_upsert_sql(
            "lab_results",
            ["source", "test_name", "result_date", "value", "unit"],
            ("source", "test_name", "result_date", "value"),
        )
        assert "ON CONFLICT(source, test_name, result_date, value)" in sql
        assert "DO UPDATE SET unit = excluded.unit" in sql

    def test_all_unique_cols_uses_or_ignore(self):
        sql = _build_upsert_sql(
            "allergies",
            ["source", "allergen"],
            ("source", "allergen"),
        )
        assert "INSERT OR IGNORE" in sql
        assert "ON CONFLICT" not in sql

    def test_unique_keys_cover_all_table_map_tables(self):
        """Every table in _TABLE_MAP must have a UNIQUE key defined."""
        from chartfold.db import _TABLE_MAP
        for _, table, _ in _TABLE_MAP:
            assert table in _UNIQUE_KEYS, f"Missing UNIQUE key for {table}"


class TestLoadDiffStats:
    """Tests for the new/existing/removed diff stats in LoadResult."""

    def test_first_load_all_new(self, tmp_db, sample_unified_records):
        """First load should report all records as new."""
        result = tmp_db.load_source(sample_unified_records)
        stats = result["tables"]
        assert stats["lab_results"]["new"] == 2
        assert stats["lab_results"]["existing"] == 0
        assert stats["lab_results"]["removed"] == 0

    def test_reload_all_existing(self, loaded_db, sample_unified_records):
        """Reloading same data should report all records as existing."""
        result = loaded_db.load_source(sample_unified_records)
        # Second load with same hash is skipped
        assert result["skipped"] is True

    def test_mixed_new_and_existing(self, loaded_db):
        """Adding one new record to existing data should show both."""
        new_records = UnifiedRecords(
            source="test_source",
            lab_results=[
                LabResult(
                    source="test_source", test_name="CEA", value="5.8",
                    value_numeric=5.8, result_date="2025-01-15",
                ),
                LabResult(
                    source="test_source", test_name="Hemoglobin", value="12.5",
                    value_numeric=12.5, result_date="2025-01-15",
                ),
                LabResult(
                    source="test_source", test_name="WBC", value="7.0",
                    value_numeric=7.0, result_date="2025-01-15",
                ),
            ],
        )
        result = loaded_db.load_source(new_records)
        stats = result["tables"]["lab_results"]
        assert stats["new"] == 1  # WBC is new
        assert stats["existing"] == 2  # CEA and Hemoglobin existed
        assert stats["total"] == 3

    def test_replace_true_shows_removed(self, loaded_db):
        """replace=True should report removed records."""
        new_records = UnifiedRecords(
            source="test_source",
            lab_results=[
                LabResult(
                    source="test_source", test_name="WBC", value="7.0",
                    value_numeric=7.0,
                ),
            ],
        )
        result = loaded_db.load_source(new_records, replace=True)
        stats = result["tables"]["lab_results"]
        assert stats["new"] == 1  # WBC
        assert stats["removed"] == 2  # CEA and Hemoglobin gone

    def test_replace_false_no_removed(self, loaded_db):
        """replace=False should never report removed records."""
        new_records = UnifiedRecords(
            source="test_source",
            lab_results=[
                LabResult(
                    source="test_source", test_name="WBC", value="7.0",
                    value_numeric=7.0,
                ),
            ],
        )
        result = loaded_db.load_source(new_records)
        stats = result["tables"]["lab_results"]
        assert stats["removed"] == 0
        # Old records (CEA, Hemoglobin) still exist
        rows = loaded_db.query("SELECT * FROM lab_results")
        assert len(rows) == 3


class TestContentHash:
    """Tests for content hash and skip-on-duplicate behavior."""

    def test_content_hash_stored_in_load_log(self, tmp_db, sample_unified_records):
        """Content hash should be stored in load_log."""
        tmp_db.load_source(sample_unified_records)
        log = tmp_db.query("SELECT content_hash FROM load_log WHERE source='test_source'")
        assert len(log) == 1
        assert len(log[0]["content_hash"]) == 64  # SHA-256 hex

    def test_identical_data_skipped(self, tmp_db, sample_unified_records):
        """Loading identical data twice should skip the second load."""
        result1 = tmp_db.load_source(sample_unified_records)
        result2 = tmp_db.load_source(sample_unified_records)
        assert result1["skipped"] is False
        assert result2["skipped"] is True
        assert result1["content_hash"] == result2["content_hash"]

    def test_different_data_not_skipped(self, loaded_db):
        """Loading different data should not be skipped."""
        new_records = UnifiedRecords(
            source="test_source",
            lab_results=[
                LabResult(source="test_source", test_name="WBC", value="7.0",
                          value_numeric=7.0),
            ],
        )
        result = loaded_db.load_source(new_records)
        assert result["skipped"] is False

    def test_hash_deterministic(self, sample_unified_records):
        """Same data should always produce the same hash."""
        from chartfold.db import _content_hash
        h1 = _content_hash(sample_unified_records)
        h2 = _content_hash(sample_unified_records)
        assert h1 == h2

    def test_hash_differs_for_different_data(self, sample_unified_records):
        """Different data should produce different hashes."""
        from chartfold.db import _content_hash
        h1 = _content_hash(sample_unified_records)

        modified = UnifiedRecords(
            source="test_source",
            lab_results=[
                LabResult(source="test_source", test_name="Different", value="99"),
            ],
        )
        h2 = _content_hash(modified)
        assert h1 != h2


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
