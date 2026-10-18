"""Tests for the write_record MCP tool (UPSERT by natural key).

Covers the behavior change from plain INSERT to UPSERT:
- first write returns status 'created'
- natural-key collision returns status 'updated' (no IntegrityError)
- missing natural-key columns fail fast with a clear error
- column-name validation still blocks SQL injection attempts
- source is still required
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from health_memex.db import HealthMemexDB


@pytest.fixture
def mcp_srv(tmp_path, monkeypatch):
    """Fresh DB + reset MCP singleton."""
    import health_memex.mcp.server as srv

    db_path = str(tmp_path / "wr.db")
    db = HealthMemexDB(db_path)
    db.init_schema()
    db.close()

    monkeypatch.setenv("HEALTH_MEMEX_DB", db_path)
    monkeypatch.setattr(srv, "DB_PATH", db_path)
    monkeypatch.setattr(srv, "_db", None)
    return srv


class TestBasicInsert:
    def test_create_status(self, mcp_srv):
        result = mcp_srv.write_record(
            "lab_results",
            {
                "source": "test",
                "test_name": "CEA",
                "result_date": "2025-06-15",
                "value": "5.8",
                "value_numeric": 5.8,
                "unit": "ng/mL",
            },
        )
        assert "error" not in result, result
        assert result["status"] == "created"
        assert result["id"] > 0

    def test_missing_source_rejected(self, mcp_srv):
        result = mcp_srv.write_record(
            "lab_results",
            {
                "test_name": "CEA",
                "result_date": "2025-06-15",
                "value": "5.8",
            },
        )
        assert "error" in result
        assert "source" in result["error"].lower()

    def test_invalid_table_rejected(self, mcp_srv):
        result = mcp_srv.write_record("not_a_table", {"source": "test"})
        assert "error" in result
        assert "not writable" in result["error"].lower()

    def test_invalid_column_rejected(self, mcp_srv):
        result = mcp_srv.write_record(
            "lab_results",
            {
                "source": "test",
                "test_name": "CEA",
                "result_date": "2025-06-15",
                "value": "5.8",
                "injected_col": "oops",
            },
        )
        assert "error" in result
        assert "invalid column" in result["error"].lower()


class TestUpsertBehavior:
    """The core behavior change: natural-key collision updates instead of erroring."""

    _base: ClassVar[dict] = {
        "source": "test",
        "test_name": "CEA",
        "result_date": "2025-06-15",
        "value": "5.8",
    }

    def test_second_write_same_nk_updates(self, mcp_srv):
        r1 = mcp_srv.write_record("lab_results", {**self._base, "unit": "ng/mL"})
        assert r1["status"] == "created"

        r2 = mcp_srv.write_record(
            "lab_results", {**self._base, "unit": "ng/mL", "interpretation": "H"}
        )
        assert "error" not in r2, r2
        assert r2["status"] == "updated"
        assert r2["id"] == r1["id"], "UPSERT must preserve the id"

    def test_updated_fields_persist(self, mcp_srv):
        mcp_srv.write_record("lab_results", {**self._base, "unit": "ng/mL"})
        mcp_srv.write_record("lab_results", {**self._base, "unit": "ng/mL", "interpretation": "H"})
        rows = mcp_srv.run_sql("SELECT interpretation FROM lab_results WHERE test_name = 'CEA'")
        assert rows[0]["interpretation"] == "H"

    def test_different_nk_creates_new_row(self, mcp_srv):
        r1 = mcp_srv.write_record("lab_results", {**self._base, "value": "5.8"})
        r2 = mcp_srv.write_record(
            "lab_results", {**self._base, "value": "6.2"}
        )  # different value -> different NK
        assert r1["status"] == "created"
        assert r2["status"] == "created"
        assert r1["id"] != r2["id"]


class TestNaturalKeyValidation:
    def test_missing_nk_column_rejected(self, mcp_srv):
        # lab_results NK = (source, test_name, result_date, value)
        result = mcp_srv.write_record(
            "lab_results",
            {
                "source": "test",
                "test_name": "CEA",
                # Missing result_date and value
                "unit": "ng/mL",
            },
        )
        assert "error" in result
        assert "natural-key" in result["error"].lower()
        assert "result_date" in result["error"]
        assert "value" in result["error"]

    def test_encounter_requires_all_nk_fields(self, mcp_srv):
        # encounters NK = (source, encounter_date, encounter_type, facility)
        result = mcp_srv.write_record(
            "encounters",
            {
                "source": "test",
                "encounter_date": "2025-06-15",
                # Missing encounter_type and facility
            },
        )
        assert "error" in result
        assert "natural-key" in result["error"].lower()


class TestResurrectionViaWriteRecord:
    """write_record uses _build_upsert_sql, which clears archived_at on conflict."""

    def test_write_record_resurrects_archived(self, mcp_srv):
        # Create, archive, then re-write
        r1 = mcp_srv.write_record(
            "lab_results",
            {
                "source": "test",
                "test_name": "CEA",
                "result_date": "2025-06-15",
                "value": "5.8",
            },
        )
        mcp_srv.archive_record("lab_results", r1["id"])
        rows = mcp_srv.run_sql(f"SELECT archived_at FROM lab_results WHERE id = {r1['id']}")
        assert rows[0]["archived_at"] is not None

        # Re-write with the same natural key -> UPDATE branch -> archived_at cleared
        r2 = mcp_srv.write_record(
            "lab_results",
            {
                "source": "test",
                "test_name": "CEA",
                "result_date": "2025-06-15",
                "value": "5.8",
                "interpretation": "H",
            },
        )
        assert r2["status"] == "updated"
        rows = mcp_srv.run_sql(f"SELECT archived_at FROM lab_results WHERE id = {r1['id']}")
        assert rows[0]["archived_at"] is None, "UPSERT must clear archived_at"


class TestUniqueId:
    """S1: write_record must assign the durable content-hash unique_id at
    write time, not leave it NULL until the next init_schema backfill."""

    _base: ClassVar[dict] = {
        "source": "test",
        "test_name": "CEA",
        "result_date": "2025-06-15",
        "value": "5.8",
    }

    def test_write_record_populates_unique_id(self, mcp_srv):
        from health_memex.db import HealthMemexDB, _compute_unique_id

        result = mcp_srv.write_record("lab_results", dict(self._base))
        assert "error" not in result, result
        row_id = result["id"]

        db = HealthMemexDB(mcp_srv.DB_PATH)
        try:
            row = db.conn.execute(
                "SELECT unique_id FROM lab_results WHERE id = ?", (row_id,)
            ).fetchone()
        finally:
            db.close()
        assert row["unique_id"], "write_record left unique_id NULL"
        # Matches the durable hash the federation resolves URIs by.
        assert row["unique_id"] == _compute_unique_id("lab_results", dict(self._base))

    def test_unique_id_resolvable_same_session(self, mcp_srv):
        """get_record by the content-hash unique_id must work in the same
        session the row was written (no restart/backfill required)."""
        from health_memex.db import _compute_unique_id

        result = mcp_srv.write_record("lab_results", dict(self._base))
        uid = _compute_unique_id("lab_results", dict(self._base))
        rows = mcp_srv.run_sql(f"SELECT id FROM lab_results WHERE unique_id = '{uid}'")
        assert rows and rows[0]["id"] == result["id"]
