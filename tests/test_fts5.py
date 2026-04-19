"""Tests for FTS5 full-text search over clinical_notes, pathology_reports, imaging_reports.

Verifies that:
- FTS5 virtual tables are created by init_schema
- Triggers keep FTS in sync on INSERT/UPDATE/DELETE (including UPSERT)
- Backfill populates FTS for rows loaded before the FTS tables existed
- MATCH queries return the expected rows via rowid join
- Archived rows are filtered by callers (FTS indexes them but queries exclude them)
"""

from __future__ import annotations

import pytest

from health_memex.db import HealthMemexDB
from health_memex.models import (
    ClinicalNote,
    ImagingReport,
    PathologyReport,
    UnifiedRecords,
)


@pytest.fixture
def fts_db(tmp_path):
    db_path = str(tmp_path / "fts.db")
    db = HealthMemexDB(db_path)
    db.init_schema()
    yield db
    db.close()


class TestFtsTablesExist:
    def test_clinical_notes_fts(self, fts_db):
        rows = fts_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'clinical_notes_fts'"
        ).fetchall()
        assert rows

    def test_pathology_fts(self, fts_db):
        rows = fts_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'pathology_fts'"
        ).fetchall()
        assert rows

    def test_imaging_fts(self, fts_db):
        rows = fts_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'imaging_fts'"
        ).fetchall()
        assert rows


class TestClinicalNotesFts:
    def _insert_note(self, db, content):
        db.load_source(
            UnifiedRecords(
                source="test",
                clinical_notes=[
                    ClinicalNote(
                        source="test",
                        note_type="Progress Note",
                        note_date="2025-06-15",
                        content=content,
                        author="Dr. Smith",
                    )
                ],
            )
        )
        return db.query("SELECT id FROM clinical_notes")[0]["id"]

    def test_insert_indexes_content(self, fts_db):
        self._insert_note(fts_db, "Patient reports elevated CEA and new abdominal pain.")
        rows = fts_db.conn.execute(
            "SELECT rowid FROM clinical_notes_fts WHERE clinical_notes_fts MATCH 'CEA'"
        ).fetchall()
        assert len(rows) == 1

    def test_match_stemming(self, fts_db):
        # 'porter' tokenizer stems so 'diabetes' matches 'diabetic'
        self._insert_note(fts_db, "Patient has diabetic neuropathy.")
        rows = fts_db.conn.execute(
            "SELECT rowid FROM clinical_notes_fts WHERE clinical_notes_fts MATCH 'diabetes'"
        ).fetchall()
        assert len(rows) == 1

    def test_match_phrase(self, fts_db):
        self._insert_note(fts_db, "Mild left-sided weakness noted.")
        rows = fts_db.conn.execute(
            "SELECT rowid FROM clinical_notes_fts WHERE clinical_notes_fts MATCH '\"left-sided weakness\"'"
        ).fetchall()
        assert len(rows) == 1

    def test_match_non_matching_returns_empty(self, fts_db):
        self._insert_note(fts_db, "Normal exam. No complaints.")
        rows = fts_db.conn.execute(
            "SELECT rowid FROM clinical_notes_fts WHERE clinical_notes_fts MATCH 'tachycardia'"
        ).fetchall()
        assert rows == []

    def test_update_refreshes_index(self, fts_db):
        note_id = self._insert_note(fts_db, "Initial content about hypertension.")
        fts_db.conn.execute(
            "UPDATE clinical_notes SET content = ? WHERE id = ?",
            ("Revised content about dyslipidemia.", note_id),
        )
        fts_db.conn.commit()
        # Old term is gone
        assert (
            fts_db.conn.execute(
                "SELECT rowid FROM clinical_notes_fts WHERE clinical_notes_fts MATCH 'hypertension'"
            ).fetchall()
            == []
        )
        # New term is present
        assert (
            len(
                fts_db.conn.execute(
                    "SELECT rowid FROM clinical_notes_fts WHERE clinical_notes_fts MATCH 'dyslipidemia'"
                ).fetchall()
            )
            == 1
        )

    def test_delete_removes_from_index(self, fts_db):
        note_id = self._insert_note(fts_db, "Patient has asthma.")
        fts_db.conn.execute("DELETE FROM clinical_notes WHERE id = ?", (note_id,))
        fts_db.conn.commit()
        assert (
            fts_db.conn.execute(
                "SELECT rowid FROM clinical_notes_fts WHERE clinical_notes_fts MATCH 'asthma'"
            ).fetchall()
            == []
        )


class TestPathologyFts:
    def _insert_report(self, db, **kwargs):
        defaults = {
            "source": "test",
            "report_date": "2025-06-15",
            "specimen": "Left breast biopsy",
        }
        defaults.update(kwargs)
        db.load_source(
            UnifiedRecords(
                source="test",
                pathology_reports=[PathologyReport(**defaults)],
            )
        )
        return db.query("SELECT id FROM pathology_reports")[0]["id"]

    def test_diagnosis_indexed(self, fts_db):
        self._insert_report(fts_db, diagnosis="Invasive ductal carcinoma")
        rows = fts_db.conn.execute(
            "SELECT rowid FROM pathology_fts WHERE pathology_fts MATCH 'carcinoma'"
        ).fetchall()
        assert len(rows) == 1

    def test_column_scoped_search(self, fts_db):
        self._insert_report(
            fts_db,
            diagnosis="Invasive ductal carcinoma",
            staging="T2 N0 M0 clinical",
        )
        # Scope the search to the staging column.
        staging_hits = fts_db.conn.execute(
            "SELECT rowid FROM pathology_fts WHERE pathology_fts MATCH 'staging:clinical'"
        ).fetchall()
        assert len(staging_hits) == 1
        # Same term scoped to diagnosis — shouldn't match.
        diag_hits = fts_db.conn.execute(
            "SELECT rowid FROM pathology_fts WHERE pathology_fts MATCH 'diagnosis:clinical'"
        ).fetchall()
        assert diag_hits == []


class TestImagingFts:
    def _insert_report(self, db, **kwargs):
        defaults = {
            "source": "test",
            "study_name": "CT Chest",
            "modality": "CT",
            "study_date": "2025-06-15",
        }
        defaults.update(kwargs)
        db.load_source(
            UnifiedRecords(
                source="test",
                imaging_reports=[ImagingReport(**defaults)],
            )
        )
        return db.query("SELECT id FROM imaging_reports")[0]["id"]

    def test_impression_indexed(self, fts_db):
        self._insert_report(fts_db, impression="3mm pulmonary nodule in RUL")
        rows = fts_db.conn.execute(
            "SELECT rowid FROM imaging_fts WHERE imaging_fts MATCH 'nodule'"
        ).fetchall()
        assert len(rows) == 1

    def test_findings_and_impression_both_searchable(self, fts_db):
        self._insert_report(
            fts_db,
            findings="Scattered subpleural reticulation",
            impression="Likely usual interstitial pneumonia",
        )
        for term in ("reticulation", "interstitial"):
            rows = fts_db.conn.execute(
                "SELECT rowid FROM imaging_fts WHERE imaging_fts MATCH ?", (term,)
            ).fetchall()
            assert len(rows) == 1, f"Missing match for {term!r}"


class TestBackfill:
    """Verify FTS5 backfill populates indexes for rows inserted before FTS existed."""

    def test_backfill_populates_existing_rows(self, tmp_path):
        db_path = str(tmp_path / "pre_fts.db")
        db = HealthMemexDB(db_path)
        db.init_schema()
        # Insert a row, then drop the FTS index to simulate the "DB existed
        # before FTS was added" migration case.
        db.conn.execute(
            "INSERT INTO clinical_notes (source, note_type, note_date, content, author) "
            "VALUES ('test', 'Progress', '2025-06-01', 'Legacy note about arthritis.', 'Dr. X')"
        )
        db.conn.execute("INSERT INTO clinical_notes_fts(clinical_notes_fts) VALUES ('delete-all')")
        db.conn.commit()
        # MATCH should return nothing after delete-all
        assert (
            db.conn.execute(
                "SELECT rowid FROM clinical_notes_fts WHERE clinical_notes_fts MATCH 'arthritis'"
            ).fetchall()
            == []
        )
        # Backfill detects the docsize gap and rebuilds.
        db._backfill_fts_indexes()
        db.conn.commit()
        rows = db.conn.execute(
            "SELECT rowid FROM clinical_notes_fts WHERE clinical_notes_fts MATCH 'arthritis'"
        ).fetchall()
        assert len(rows) == 1
        db.close()

    def test_backfill_noop_when_in_sync(self, tmp_path):
        """When FTS is in sync, backfill does nothing — idempotent."""
        db = HealthMemexDB(str(tmp_path / "sync.db"))
        db.init_schema()
        db.conn.execute(
            "INSERT INTO clinical_notes (source, note_type, note_date, content, author) "
            "VALUES ('test', 'Progress', '2025-06-01', 'Patient has migraines.', 'Dr. X')"
        )
        db.conn.commit()
        before = db.conn.execute("SELECT COUNT(*) FROM clinical_notes_fts_docsize").fetchone()[0]
        db._backfill_fts_indexes()
        after = db.conn.execute("SELECT COUNT(*) FROM clinical_notes_fts_docsize").fetchone()[0]
        assert before == after
        db.close()


class TestArchivedRowsFilteredByCallers:
    """FTS5 indexes archived rows too; production queries filter archived_at IS NULL."""

    def test_search_notes_mcp_hides_archived(self, tmp_path, monkeypatch):
        import health_memex.mcp.server as srv

        db_path = str(tmp_path / "mcp_fts.db")
        monkeypatch.setenv("HEALTH_MEMEX_DB", db_path)
        monkeypatch.setattr(srv, "DB_PATH", db_path)
        monkeypatch.setattr(srv, "_db", None)

        db = HealthMemexDB(db_path)
        db.init_schema()
        db.load_source(
            UnifiedRecords(
                source="test",
                clinical_notes=[
                    ClinicalNote(
                        source="test",
                        note_type="Progress",
                        note_date="2025-06-01",
                        content="Active note about bronchitis.",
                        author="Dr. X",
                    ),
                    ClinicalNote(
                        source="test",
                        note_type="Progress",
                        note_date="2025-07-01",
                        content="Archived note about bronchitis.",
                        author="Dr. Y",
                    ),
                ],
            )
        )
        archived_id = db.query("SELECT id FROM clinical_notes WHERE author = ?", ("Dr. Y",))[0][
            "id"
        ]
        db.archive_record("clinical_notes", archived_id)
        db.close()

        results = srv.search_notes(query_text="bronchitis")
        authors = {r["author"] for r in results}
        assert "Dr. X" in authors
        assert "Dr. Y" not in authors, "Archived notes must be excluded from FTS results"
