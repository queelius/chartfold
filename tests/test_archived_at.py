"""Tests for soft-delete (archived_at) across clinical records, notes, and analyses.

Verifies the *-memex ecosystem contract: every record table carries
archived_at, DELETE endpoints default to soft-delete, re-imports resurrect
archived records by natural key, and URI references survive soft deletion.
"""

from __future__ import annotations

import pytest

from health_memex.db import _SOFT_DELETE_TABLES, HealthMemexDB
from health_memex.models import (
    ConditionRecord,
    EncounterRecord,
    LabResult,
    UnifiedRecords,
)


@pytest.fixture
def soft_db(tmp_path):
    """Empty database with schema initialized."""
    db_path = str(tmp_path / "soft_test.db")
    db = HealthMemexDB(db_path)
    db.init_schema()
    yield db
    db.close()


class TestSchemaHasArchivedAt:
    """Verify every record table has the archived_at column."""

    def test_clinical_tables_have_column(self, soft_db):
        clinical = [t for t in _SOFT_DELETE_TABLES if t not in {"notes", "analyses"}]
        for table in clinical:
            cols = {row[1] for row in soft_db.conn.execute(f"PRAGMA table_info({table})")}
            assert "archived_at" in cols, f"{table} missing archived_at"

    def test_notes_has_column(self, soft_db):
        cols = {row[1] for row in soft_db.conn.execute("PRAGMA table_info(notes)")}
        assert "archived_at" in cols

    def test_analyses_has_column(self, soft_db):
        cols = {row[1] for row in soft_db.conn.execute("PRAGMA table_info(analyses)")}
        assert "archived_at" in cols

    def test_load_log_does_not_have_column(self, soft_db):
        cols = {row[1] for row in soft_db.conn.execute("PRAGMA table_info(load_log)")}
        assert "archived_at" not in cols


class TestSoftDeletePrimitives:
    """archive_record / unarchive_record / purge_record."""

    def _make_lab(self, db):
        db.load_source(
            UnifiedRecords(
                source="test",
                lab_results=[
                    LabResult(
                        source="test",
                        test_name="CEA",
                        value="5.8",
                        value_numeric=5.8,
                        result_date="2025-06-15",
                    )
                ],
            )
        )
        return db.query("SELECT id FROM lab_results")[0]["id"]

    def test_archive_sets_timestamp(self, soft_db):
        lab_id = self._make_lab(soft_db)
        assert soft_db.archive_record("lab_results", lab_id) is True
        row = soft_db.query("SELECT archived_at FROM lab_results WHERE id = ?", (lab_id,))[0]
        assert row["archived_at"] is not None

    def test_archive_idempotent(self, soft_db):
        lab_id = self._make_lab(soft_db)
        assert soft_db.archive_record("lab_results", lab_id) is True
        # Second archive: row already archived, returns False
        assert soft_db.archive_record("lab_results", lab_id) is False

    def test_unarchive_clears_timestamp(self, soft_db):
        lab_id = self._make_lab(soft_db)
        soft_db.archive_record("lab_results", lab_id)
        assert soft_db.unarchive_record("lab_results", lab_id) is True
        row = soft_db.query("SELECT archived_at FROM lab_results WHERE id = ?", (lab_id,))[0]
        assert row["archived_at"] is None

    def test_purge_removes_row(self, soft_db):
        lab_id = self._make_lab(soft_db)
        assert soft_db.purge_record("lab_results", lab_id) is True
        assert soft_db.query("SELECT id FROM lab_results WHERE id = ?", (lab_id,)) == []

    def test_rejects_unknown_table(self, soft_db):
        with pytest.raises(ValueError, match="does not support soft delete"):
            soft_db.archive_record("load_log", 1)

    def test_rejects_non_record_table(self, soft_db):
        with pytest.raises(ValueError, match="does not support soft delete"):
            soft_db.archive_record("note_tags", 1)


class TestUpsertResurrection:
    """A re-import that matches an archived record's natural key should clear archived_at."""

    def test_lab_resurrection(self, soft_db):
        records = UnifiedRecords(
            source="test",
            lab_results=[
                LabResult(
                    source="test",
                    test_name="CEA",
                    value="5.8",
                    value_numeric=5.8,
                    result_date="2025-06-15",
                )
            ],
        )
        soft_db.load_source(records)
        lab_id = soft_db.query("SELECT id FROM lab_results")[0]["id"]

        soft_db.archive_record("lab_results", lab_id)
        assert soft_db.query("SELECT archived_at FROM lab_results")[0]["archived_at"] is not None

        # Re-import the same record — natural key matches, so UPSERT resurrects.
        soft_db.load_source(records)
        row = soft_db.query("SELECT id, archived_at FROM lab_results")[0]
        assert row["id"] == lab_id, "Resurrection must preserve the id"
        assert row["archived_at"] is None, "Resurrection must clear archived_at"

    def test_condition_resurrection(self, soft_db):
        records = UnifiedRecords(
            source="test",
            conditions=[
                ConditionRecord(
                    source="test",
                    condition_name="Hypertension",
                    icd10_code="I10",
                )
            ],
        )
        soft_db.load_source(records)
        cond_id = soft_db.query("SELECT id FROM conditions")[0]["id"]
        soft_db.archive_record("conditions", cond_id)
        soft_db.load_source(records)
        assert soft_db.query("SELECT archived_at FROM conditions")[0]["archived_at"] is None


class TestNoteSoftDelete:
    def test_delete_defaults_to_soft(self, soft_db):
        note_id = soft_db.save_note(title="T", content="C")
        assert soft_db.delete_note(note_id) is True
        # Row still exists
        assert soft_db.conn.execute("SELECT 1 FROM notes WHERE id = ?", (note_id,)).fetchone()
        # But get_note hides it
        assert soft_db.get_note(note_id) is None

    def test_include_archived_returns_note(self, soft_db):
        note_id = soft_db.save_note(title="T", content="C")
        soft_db.delete_note(note_id)
        archived = soft_db.get_note(note_id, include_archived=True)
        assert archived is not None
        assert archived["archived_at"] is not None

    def test_hard_delete_removes_row(self, soft_db):
        note_id = soft_db.save_note(title="T", content="C")
        assert soft_db.delete_note(note_id, hard=True) is True
        assert (
            soft_db.conn.execute("SELECT 1 FROM notes WHERE id = ?", (note_id,)).fetchone() is None
        )

    def test_search_hides_archived_by_default(self, soft_db):
        nid1 = soft_db.save_note(title="Active", content="x", tags=["keep"])
        nid2 = soft_db.save_note(title="Gone", content="y", tags=["keep"])
        soft_db.delete_note(nid2)
        visible = soft_db.search_notes_personal(tag="keep")
        ids = {r["id"] for r in visible}
        assert nid1 in ids
        assert nid2 not in ids

    def test_search_include_archived_shows_all(self, soft_db):
        nid1 = soft_db.save_note(title="Active", content="x", tags=["keep"])
        nid2 = soft_db.save_note(title="Gone", content="y", tags=["keep"])
        soft_db.delete_note(nid2)
        all_rows = soft_db.search_notes_personal(tag="keep", include_archived=True)
        ids = {r["id"] for r in all_rows}
        assert {nid1, nid2} <= ids

    def test_save_note_by_id_resurrects(self, soft_db):
        note_id = soft_db.save_note(title="T", content="C")
        soft_db.delete_note(note_id)
        assert soft_db.get_note(note_id) is None
        # Re-saving by id brings it back
        soft_db.save_note(title="T2", content="C2", note_id=note_id)
        restored = soft_db.get_note(note_id)
        assert restored is not None
        assert restored["title"] == "T2"


class TestAnalysisSoftDelete:
    def test_delete_defaults_to_soft(self, soft_db):
        soft_db.save_analysis(slug="foo", title="T", content="C")
        assert soft_db.delete_analysis("foo") is True
        assert soft_db.get_analysis("foo") is None

    def test_hard_delete_frees_slug(self, soft_db):
        soft_db.save_analysis(slug="foo", title="Original", content="C")
        soft_db.delete_analysis("foo", hard=True)
        # Slug is now available for reuse
        soft_db.save_analysis(slug="foo", title="Different", content="C2")
        a = soft_db.get_analysis("foo")
        assert a is not None
        assert a["title"] == "Different"

    def test_re_save_resurrects(self, soft_db):
        soft_db.save_analysis(slug="foo", title="V1", content="C")
        soft_db.delete_analysis("foo")
        # Re-saving the same slug brings it back with new content
        soft_db.save_analysis(slug="foo", title="V2", content="C2")
        a = soft_db.get_analysis("foo")
        assert a is not None
        assert a["title"] == "V2"
        assert a["archived_at"] is None

    def test_list_analyses_hides_archived(self, soft_db):
        soft_db.save_analysis(slug="a", title="A", content="x")
        soft_db.save_analysis(slug="b", title="B", content="y")
        soft_db.delete_analysis("b")
        slugs = {a["slug"] for a in soft_db.list_analyses()}
        assert slugs == {"a"}


class TestOrphanSurvival:
    """Contract: marginalia URIs outlive the records they reference."""

    def test_note_survives_referenced_record_archive(self, soft_db):
        soft_db.load_source(
            UnifiedRecords(
                source="test",
                encounters=[
                    EncounterRecord(
                        source="test",
                        encounter_date="2025-06-15",
                        encounter_type="office visit",
                        facility="Anderson",
                    )
                ],
            )
        )
        enc_id = soft_db.query("SELECT id FROM encounters")[0]["id"]
        note_id = soft_db.save_note(
            title="Follow-up",
            content="Patient reported improvement",
            ref_table="encounters",
            ref_id=enc_id,
        )

        # Archive the referenced encounter
        soft_db.archive_record("encounters", enc_id)

        # Note still exists with its reference intact
        note = soft_db.get_note(note_id)
        assert note is not None
        assert note["ref_table"] == "encounters"
        assert note["ref_id"] == enc_id
