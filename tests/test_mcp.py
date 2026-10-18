"""Tests for health_memex.mcp.server tools.

Tests the tool functions directly (not via MCP protocol).
"""

import pytest

from health_memex.db import HealthMemexDB
from health_memex.models import (
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
    monkeypatch.setenv("HEALTH_MEMEX_DB", db_path)

    db = HealthMemexDB(db_path)
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
    import health_memex.mcp.server as srv

    monkeypatch.setattr(srv, "DB_PATH", db_path)
    monkeypatch.setattr(srv, "_db", None)  # Reset singleton for fresh connection
    yield srv


@pytest.fixture
def mcp_multi_db(tmp_path, monkeypatch):
    """Multi-source database for cross-source testing."""
    db_path = str(tmp_path / "mcp_multi.db")
    monkeypatch.setenv("HEALTH_MEMEX_DB", db_path)

    db = HealthMemexDB(db_path)
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

    import health_memex.mcp.server as srv

    monkeypatch.setattr(srv, "DB_PATH", db_path)
    monkeypatch.setattr(srv, "_db", None)  # Reset singleton for fresh connection
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
# get_record (federation entrypoint)
# ---------------------------------------------------------------------------


class TestGetRecord:
    """Single-record lookup by URI kind+id; powers the federation
    layer's URI resolver."""

    def test_lab_result_round_trip(self, mcp_db):
        """A real row returns {kind, id, record} with the row payload.

        ``id`` is echoed back as the caller passed it (string), so trail
        URIs round-trip cleanly regardless of which id format was used.
        """
        result = mcp_db.get_record("lab_results", "1")
        assert result["kind"] == "lab_results"
        assert result["id"] == "1"  # echoed verbatim
        assert result["record"]["test_name"] == "CEA"
        assert result["record"]["value"] == "5.8"
        assert result["record"]["source"] == "test"

    def test_resolves_id_with_uri_fragment(self, mcp_db):
        """A URI fragment addresses a position within a record, not a
        different record, so it must be stripped before resolution and
        echoed back rather than causing an invalid_id error."""
        result = mcp_db.get_record("lab_results", "1#page=2")
        assert "error" not in result
        assert result["kind"] == "lab_results"
        assert result["id"] == "1#page=2"  # echoed verbatim
        assert result["fragment"] == "page=2"
        assert result["record"]["test_name"] == "CEA"

    def test_no_fragment_key_when_absent(self, mcp_db):
        """Plain ids carry no fragment key in the response."""
        result = mcp_db.get_record("lab_results", "1")
        assert "fragment" not in result

    def test_unknown_kind(self, mcp_db):
        """An unrecognised kind returns a structured error listing the
        valid kinds so the operator can self-diagnose typos."""
        result = mcp_db.get_record("not_a_real_table", "1")
        assert result["error"] == "unknown_kind"
        assert result["kind"] == "not_a_real_table"
        assert "lab_results" in result["valid_kinds"]
        # Notes/analyses are valid kinds even though they're outside
        # _UNIQUE_KEYS (they live in the marginalia layer).
        assert "notes" in result["valid_kinds"]
        assert "analyses" in result["valid_kinds"]

    def test_invalid_id_format(self, mcp_db):
        """Non-integer ids return a structured error rather than a SQL
        error. Health-memex ids are autoincrement integers."""
        result = mcp_db.get_record("lab_results", "not-an-int")
        assert result["error"] == "invalid_id"
        assert result["id"] == "not-an-int"

    def test_not_found(self, mcp_db):
        """A valid kind + integer id that doesn't exist returns
        ``not_found`` (not a SQL error). ``id`` is echoed verbatim."""
        result = mcp_db.get_record("lab_results", "999999")
        assert result["error"] == "not_found"
        assert result["kind"] == "lab_results"
        assert result["id"] == "999999"

    def test_kind_is_treated_literally(self, mcp_db):
        """SQL-injection-style kinds are rejected at the allowlist gate
        before reaching the query, so attempts like
        ``lab_results; DROP TABLE x`` come back as unknown_kind."""
        result = mcp_db.get_record("lab_results; DROP TABLE x", "1")
        assert result["error"] == "unknown_kind"

    def test_record_kinds_declaration_matches_schema(self, mcp_db):
        """get_record_kinds covers exactly the resolvable kinds, and every
        declared table/id column exists in the real schema."""
        from health_memex.mcp.server import _RECORD_KINDS

        kinds = mcp_db.get_record_kinds()["kinds"]
        assert {k["kind"] for k in kinds} == _RECORD_KINDS
        for k in kinds:
            result = mcp_db.run_sql(
                f"SELECT COUNT(*) AS n FROM (SELECT `{k['id_column']}` FROM `{k['table']}` LIMIT 0)"
            )
            assert result == [{"n": 0}], (k, result)

    def test_declared_id_column_resolves(self, mcp_db):
        uid = mcp_db.run_sql("SELECT unique_id FROM lab_results LIMIT 1")[0]["unique_id"]
        assert mcp_db.get_record("lab_results", uid)["record"]["test_name"] == "CEA"

    def test_each_clinical_kind_resolvable(self, mcp_multi_db):
        """A smoke test that every kind in the allowlist runs against
        the real schema without a SQL error. Most return not_found
        (the test fixture only loads a few rows), which is fine — we
        just want to verify no unknown-table errors slip through."""
        from health_memex.mcp.server import _RECORD_KINDS

        for kind in _RECORD_KINDS:
            result = mcp_multi_db.get_record(kind, "1")
            assert result.get("error") != "sql_error", (
                f"kind {kind!r} produced a SQL error: {result.get('detail')}"
            )

    def test_id_echoed_as_string(self, mcp_db):
        """The id parameter is typed as str (URIs carry strings) and
        echoed back verbatim so the caller's format is preserved.

        This matters because get_record now accepts both autoincrement
        digits and 16-hex unique_id strings — only string-echoing
        round-trips unambiguously.
        """
        result = mcp_db.get_record("lab_results", "1")
        assert result["id"] == "1"
        assert isinstance(result["id"], str)

    def test_lookup_by_unique_id(self, mcp_db):
        """The durable form: pass the 16-hex unique_id and get the same
        row back. unique_id was populated automatically when the test
        fixture's lab record was loaded via load_source."""
        # First fetch the row's unique_id via SQL.
        rows = mcp_db.run_sql("SELECT unique_id FROM lab_results WHERE id = 1")
        uid = rows[0]["unique_id"]
        assert uid is not None and len(uid) == 16
        # Now look up by unique_id and verify same record.
        result = mcp_db.get_record("lab_results", uid)
        assert result["kind"] == "lab_results"
        assert result["id"] == uid  # echoed back as the durable form
        assert result["record"]["test_name"] == "CEA"
        assert result["record"]["unique_id"] == uid

    def test_unique_id_lookup_not_found(self, mcp_db):
        """A well-formed but unknown unique_id returns not_found."""
        result = mcp_db.get_record("lab_results", "0123456789abcdef")
        assert result["error"] == "not_found"
        assert result["id"] == "0123456789abcdef"

    def test_invalid_id_neither_format(self, mcp_db):
        """A string that's neither 16-hex nor digits-only fails fast."""
        result = mcp_db.get_record("lab_results", "not-a-real-id")
        assert result["error"] == "invalid_id"

    def test_notes_use_autoincrement_only(self, mcp_db):
        """The notes table has no natural key, so it has no unique_id.
        get_record should look up notes by autoincrement id only.
        Passing a hex-shaped string returns not_found (no fallback to
        the unique_id branch happens, because the column doesn't exist).
        """
        # First save a note so we have something to look up.
        mcp_db.save_note(title="t", content="c")
        # Autoincrement lookup works.
        result = mcp_db.get_record("notes", "1")
        assert result["kind"] == "notes"
        assert result["record"]["title"] == "t"
        # Hex-shaped id is not supported for notes (no unique_id column).
        # The current implementation falls through to invalid_id because
        # the input is neither 16-hex (with unique_id support) nor digits.
        result = mcp_db.get_record("notes", "0123456789abcdef")
        assert result["error"] == "invalid_id"


class TestUniqueIdDurability:
    """The headline V2b property: same source data, same unique_id.

    Re-importing the same UnifiedRecords (e.g. weekly EHR refresh)
    must produce the same unique_id strings, so trail steps and arkiv
    URIs survive across re-imports.
    """

    def test_reimport_preserves_unique_id(self, tmp_path):
        """Two independent imports of the same record yield the same
        unique_id. This is the proof that URIs into health-memex are
        actually durable now."""
        from health_memex.db import HealthMemexDB
        from health_memex.models import LabResult, UnifiedRecords

        recs = UnifiedRecords(
            source="test_durable",
            lab_results=[
                LabResult(
                    source="test_durable",
                    test_name="CEA",
                    value="5.8",
                    value_numeric=5.8,
                    result_date="2025-06-15",
                ),
            ],
        )
        db_path = str(tmp_path / "first_import.db")

        # First import
        db1 = HealthMemexDB(db_path)
        db1.init_schema()
        db1.load_source(recs)
        first_uid = db1.query("SELECT unique_id FROM lab_results")[0]["unique_id"]
        db1.close()

        # Re-create the DB from scratch and import the same data
        import os

        os.unlink(db_path)
        db2 = HealthMemexDB(db_path)
        db2.init_schema()
        db2.load_source(recs)
        second_uid = db2.query("SELECT unique_id FROM lab_results")[0]["unique_id"]
        db2.close()

        assert first_uid == second_uid, (
            "unique_id must survive DB rebuild + re-import — "
            "that's the whole point of V2b durable IDs"
        )
        assert len(first_uid) == 16

    def test_unique_id_distinguishes_natural_keys(self, tmp_path):
        """Different natural keys must produce different unique_ids."""
        from health_memex.db import HealthMemexDB
        from health_memex.models import LabResult, UnifiedRecords

        recs = UnifiedRecords(
            source="test_distinct",
            lab_results=[
                LabResult(
                    source="test_distinct",
                    test_name="CEA",
                    value="5.8",
                    result_date="2025-06-15",
                ),
                LabResult(
                    source="test_distinct",
                    test_name="CEA",
                    value="6.2",  # different value -> different natural key
                    result_date="2025-07-20",
                ),
            ],
        )
        db = HealthMemexDB(str(tmp_path / "distinct.db"))
        db.init_schema()
        db.load_source(recs)
        uids = [r["unique_id"] for r in db.query("SELECT unique_id FROM lab_results")]
        db.close()
        assert len(set(uids)) == 2, "two distinct natural keys → two distinct unique_ids"

    def test_readonly_query_works_when_shm_missing(self, tmp_path, monkeypatch):
        """Regression: _readonly_query (mode=ro) on a WAL-mode DB used
        to fail with 'unable to open database file' when .db-shm wasn't
        already on disk. The fix is to call _get_db() first so the R/W
        singleton creates -shm before mode=ro tries to attach.

        We simulate the scenario by:
          1. creating + populating a DB via HealthMemexDB
          2. closing it cleanly, then deleting -shm + -wal sidecars
             (mimicking a checkpoint that cleared them)
          3. resetting the MCP server's _db singleton
          4. calling run_sql, which goes through _readonly_query
        """
        import os

        from health_memex.db import HealthMemexDB
        from health_memex.models import LabResult, UnifiedRecords

        db_path = str(tmp_path / "wal_test.db")
        db = HealthMemexDB(db_path)
        db.init_schema()
        db.load_source(
            UnifiedRecords(
                source="walfix",
                lab_results=[
                    LabResult(
                        source="walfix",
                        test_name="WBC",
                        value="6.2",
                        result_date="2025-01-15",
                    ),
                ],
            )
        )
        # Force a WAL checkpoint and close. This + deleting sidecars
        # mimics a fresh-subprocess scenario where -shm may not exist.
        db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.close()
        for sidecar in (db_path + "-shm", db_path + "-wal"):
            if os.path.exists(sidecar):
                os.unlink(sidecar)

        monkeypatch.setenv("HEALTH_MEMEX_DB", db_path)
        import health_memex.mcp.server as srv

        monkeypatch.setattr(srv, "DB_PATH", db_path)
        monkeypatch.setattr(srv, "_db", None)

        # This call previously raised "unable to open database file".
        # With the _get_db() prelude in _readonly_query, -shm gets
        # recreated via the R/W singleton before the mode=ro attach.
        result = srv.run_sql("SELECT test_name FROM lab_results")
        assert isinstance(result, list), f"expected list, got {result!r}"
        assert len(result) == 1
        assert result[0]["test_name"] == "WBC"

    def test_migration_backfills_existing_rows(self, tmp_path):
        """A DB created before the unique_id column existed must get
        unique_ids on the next init_schema(). Simulates upgrading a
        live install."""
        import sqlite3

        from health_memex.db import HealthMemexDB
        from health_memex.models import LabResult, UnifiedRecords

        db_path = str(tmp_path / "old.db")

        # Create a DB without the unique_id column (simulate old version)
        db = HealthMemexDB(db_path)
        db.init_schema()
        db.load_source(
            UnifiedRecords(
                source="legacy",
                lab_results=[
                    LabResult(
                        source="legacy",
                        test_name="WBC",
                        value="6.2",
                        result_date="2025-01-15",
                    ),
                ],
            )
        )
        # Forcibly NULL the unique_id to simulate a row from before the
        # migration ran.
        db.conn.execute("UPDATE lab_results SET unique_id = NULL")
        db.conn.commit()
        db.close()

        # Verify the row is NULL
        check_conn = sqlite3.connect(db_path)
        check_conn.row_factory = sqlite3.Row
        row = check_conn.execute("SELECT unique_id FROM lab_results").fetchone()
        assert row["unique_id"] is None
        check_conn.close()

        # Re-open and re-init: migration should backfill
        db2 = HealthMemexDB(db_path)
        db2.init_schema()
        rows = db2.query("SELECT unique_id FROM lab_results")
        db2.close()
        assert rows[0]["unique_id"] is not None
        assert len(rows[0]["unique_id"]) == 16


# ---------------------------------------------------------------------------
# Personal notes CRUD
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_notes_db(tmp_path, monkeypatch):
    """Database with a few pre-saved notes for MCP notes tool testing."""
    db_path = str(tmp_path / "mcp_notes.db")
    monkeypatch.setenv("HEALTH_MEMEX_DB", db_path)

    db = HealthMemexDB(db_path)
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

    import health_memex.mcp.server as srv

    monkeypatch.setattr(srv, "DB_PATH", db_path)
    monkeypatch.setattr(srv, "_db", None)  # Reset singleton for fresh connection
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


class TestVisitPrepBundle:
    def test_get_visit_prep_bundle_returns_all_sections(self, mcp_db):
        from health_memex.mcp.server import get_visit_prep_bundle

        result = get_visit_prep_bundle(visit_date="2026-04-02")
        assert isinstance(result, dict)
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
        assert set(result.keys()) == expected_keys

    def test_get_visit_prep_bundle_exclude_flags(self, mcp_db):
        from health_memex.mcp.server import get_visit_prep_bundle

        result = get_visit_prep_bundle(include_analyses=False, include_notes=False)
        assert result["saved_analyses"] == []
        assert result["saved_notes"] == []


class TestGetRecordArchivedFlag:
    """R4: get_record keeps archived records resolvable but flags them."""

    def test_active_record_not_flagged(self, mcp_db):
        result = mcp_db.get_record("lab_results", "1")
        assert result.get("archived") is False

    def test_archived_record_flagged(self, mcp_db):
        import os

        from health_memex.db import HealthMemexDB

        wdb = HealthMemexDB(os.environ["HEALTH_MEMEX_DB"])
        assert wdb.archive_record("lab_results", 1) is True
        wdb.close()
        mcp_db._db = None  # reset the read-only singleton to see the write

        result = mcp_db.get_record("lab_results", "1")
        assert "error" not in result  # still resolvable
        assert result["archived"] is True
