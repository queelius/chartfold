"""Regression tests: soft-delete (archived_at) must hide records from analysis tools.

Findings R2 and R1 (2026-06-24):

R2 (correctness): every analysis-backed view and db.summary() must filter
WHERE archived_at IS NULL so that archive_record actually hides a record.
Before the fix, archiving a lab / medication / condition / etc. left it
visible in get_clinical_timeline, get_lab_trend, get_active_medications,
get_clinical_summary, generate_visit_prep(_bundle), visit_diff,
build_surgical_timeline, and db.summary().

R1 (security): the HTML SPA export must not ship soft-deleted rows, the
load_log audit trail, or (by default) personal notes / analyses.
"""

from __future__ import annotations

import base64
import gzip
import re
import sqlite3
from pathlib import Path

import pytest

from health_memex.analysis.clinical_summary import get_clinical_summary
from health_memex.analysis.lab_trends import (
    get_abnormal_labs,
    get_available_tests,
    get_lab_trend,
    get_latest_labs,
)
from health_memex.analysis.medications import (
    get_active_medications,
    get_medication_history,
    get_medication_list,
    reconcile_medications,
)
from health_memex.analysis.surgical_timeline import build_surgical_timeline
from health_memex.analysis.timeline import get_clinical_timeline
from health_memex.analysis.visit_diff import visit_diff
from health_memex.analysis.visit_prep import (
    generate_visit_prep,
    generate_visit_prep_bundle,
)
from health_memex.db import HealthMemexDB
from health_memex.models import (
    ConditionRecord,
    EncounterRecord,
    ImagingReport,
    LabResult,
    MedicationRecord,
    PathologyReport,
    ProcedureRecord,
    UnifiedRecords,
)
from health_memex.spa.export import export_spa


@pytest.fixture
def filt_db(tmp_path):
    """Database with one record in each clinically interesting table."""
    db = HealthMemexDB(str(tmp_path / "filt.db"))
    db.init_schema()
    db.load_source(
        UnifiedRecords(
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
                    source="test",
                    name="Capecitabine 500mg",
                    status="active",
                    sig="2 tablets twice daily",
                    start_date="2025-05-01",
                ),
            ],
            conditions=[
                ConditionRecord(
                    source="test",
                    condition_name="Colon cancer",
                    icd10_code="C18.9",
                    clinical_status="active",
                    onset_date="2025-04-01",
                ),
            ],
            encounters=[
                EncounterRecord(
                    source="test",
                    encounter_date="2025-06-15",
                    encounter_type="office visit",
                    facility="Anderson",
                    provider="Dr. Smith",
                ),
            ],
            imaging_reports=[
                ImagingReport(
                    source="test",
                    study_name="CT Abdomen",
                    modality="CT",
                    study_date="2025-06-01",
                    impression="No recurrence.",
                ),
            ],
            procedures=[
                ProcedureRecord(
                    source="test",
                    name="Colectomy",
                    procedure_date="2025-04-10",
                    facility="Anderson",
                ),
            ],
            pathology_reports=[
                PathologyReport(
                    source="test",
                    report_date="2025-04-12",
                    specimen="Colon",
                    diagnosis="Adenocarcinoma",
                ),
            ],
        )
    )
    yield db
    db.close()


def _id(db, table):
    return db.query(f"SELECT id FROM {table} LIMIT 1")[0]["id"]


# --- R2: analysis tools honor archived_at ---


class TestLabTrendsRespectArchive:
    def test_get_lab_trend_hides_archived(self, filt_db):
        assert len(get_lab_trend(filt_db, test_name="CEA")) == 1
        filt_db.archive_record("lab_results", _id(filt_db, "lab_results"))
        assert get_lab_trend(filt_db, test_name="CEA") == []

    def test_get_abnormal_labs_hides_archived(self, filt_db):
        assert len(get_abnormal_labs(filt_db)) == 1
        filt_db.archive_record("lab_results", _id(filt_db, "lab_results"))
        assert get_abnormal_labs(filt_db) == []

    def test_get_latest_labs_hides_archived(self, filt_db):
        assert len(get_latest_labs(filt_db)) == 1
        filt_db.archive_record("lab_results", _id(filt_db, "lab_results"))
        assert get_latest_labs(filt_db) == []

    def test_get_available_tests_hides_archived(self, filt_db):
        assert len(get_available_tests(filt_db)) == 1
        filt_db.archive_record("lab_results", _id(filt_db, "lab_results"))
        assert get_available_tests(filt_db) == []

    def test_unarchive_restores_lab(self, filt_db):
        lab_id = _id(filt_db, "lab_results")
        filt_db.archive_record("lab_results", lab_id)
        assert get_lab_trend(filt_db, test_name="CEA") == []
        filt_db.unarchive_record("lab_results", lab_id)
        assert len(get_lab_trend(filt_db, test_name="CEA")) == 1


class TestMedicationsRespectArchive:
    def test_active_medications_hides_archived(self, filt_db):
        assert len(get_active_medications(filt_db)) == 1
        filt_db.archive_record("medications", _id(filt_db, "medications"))
        assert get_active_medications(filt_db) == []

    def test_medication_history_hides_archived(self, filt_db):
        assert len(get_medication_history(filt_db)) == 1
        filt_db.archive_record("medications", _id(filt_db, "medications"))
        assert get_medication_history(filt_db) == []

    def test_medication_list_hides_archived(self, filt_db):
        assert len(get_medication_list(filt_db)) == 1
        filt_db.archive_record("medications", _id(filt_db, "medications"))
        assert get_medication_list(filt_db) == []

    def test_reconcile_medications_hides_archived(self, filt_db):
        assert len(reconcile_medications(filt_db)["active"]) == 1
        filt_db.archive_record("medications", _id(filt_db, "medications"))
        assert reconcile_medications(filt_db)["active"] == []


class TestTimelineRespectsArchive:
    def test_timeline_hides_archived_lab(self, filt_db):
        before = get_clinical_timeline(filt_db)
        assert any(e["type"] == "labs" for e in before)
        filt_db.archive_record("lab_results", _id(filt_db, "lab_results"))
        after = get_clinical_timeline(filt_db)
        assert not any(e["type"] == "labs" for e in after)

    def test_timeline_hides_archived_procedure(self, filt_db):
        filt_db.archive_record("procedures", _id(filt_db, "procedures"))
        after = get_clinical_timeline(filt_db)
        assert not any(e["type"] == "procedure" for e in after)

    def test_timeline_hides_archived_imaging(self, filt_db):
        filt_db.archive_record("imaging_reports", _id(filt_db, "imaging_reports"))
        after = get_clinical_timeline(filt_db)
        assert not any(e["type"] == "imaging" for e in after)

    def test_timeline_hides_archived_pathology(self, filt_db):
        filt_db.archive_record("pathology_reports", _id(filt_db, "pathology_reports"))
        after = get_clinical_timeline(filt_db)
        assert not any(e["type"] == "pathology" for e in after)

    def test_timeline_hides_archived_encounter(self, filt_db):
        filt_db.archive_record("encounters", _id(filt_db, "encounters"))
        after = get_clinical_timeline(filt_db)
        assert not any(e["type"] == "encounter" for e in after)


class TestClinicalSummaryRespectsArchive:
    def test_summary_hides_archived_records(self, filt_db):
        # Wide recent-labs window so the fixture's dated rows count as recent.
        wide = 100000
        s = get_clinical_summary(filt_db, recent_labs_days=wide)
        assert len(s["recent_labs"]) == 1
        assert len(s["active_medications"]) == 1
        assert len(s["active_conditions"]) == 1
        assert len(s["procedures"]) == 1
        assert len(s["pathology_reports"]) == 1

        for table in (
            "lab_results",
            "medications",
            "conditions",
            "procedures",
            "pathology_reports",
            "imaging_reports",
            "encounters",
        ):
            filt_db.archive_record(table, _id(filt_db, table))

        s = get_clinical_summary(filt_db, recent_labs_days=wide)
        assert s["recent_labs"] == []
        assert s["abnormal_labs"] == []
        assert s["active_medications"] == []
        assert s["all_medications"] == []
        assert s["active_conditions"] == []
        assert s["all_conditions"] == []
        assert s["procedures"] == []
        assert s["pathology_reports"] == []
        assert s["recent_imaging"] == []
        assert s["all_imaging"] == []
        assert s["recent_encounters"] == []


class TestVisitPrepRespectsArchive:
    def test_visit_prep_hides_archived(self, filt_db):
        prep = generate_visit_prep(filt_db, visit_date="2025-06-20", lookback_months=12)
        assert len(prep["recent_labs"]) == 1
        assert len(prep["active_meds"]) == 1
        for table in ("lab_results", "medications", "conditions", "encounters", "imaging_reports"):
            filt_db.archive_record(table, _id(filt_db, table))
        prep = generate_visit_prep(filt_db, visit_date="2025-06-20", lookback_months=12)
        assert prep["recent_labs"] == []
        assert prep["active_meds"] == []
        assert prep["active_conditions"] == []
        assert prep["recent_encounters"] == []
        assert prep["recent_imaging"] == []

    def test_visit_prep_bundle_hides_archived(self, filt_db):
        bundle = generate_visit_prep_bundle(filt_db, visit_date="2025-06-20", lookback_months=12)
        assert len(bundle["new_labs"]) == 1
        assert len(bundle["active_medications"]) == 1
        for table in (
            "lab_results",
            "medications",
            "conditions",
            "imaging_reports",
            "clinical_notes",
            "procedures",
        ):
            row = filt_db.query(f"SELECT id FROM {table} LIMIT 1")
            if row:
                filt_db.archive_record(table, row[0]["id"])
        bundle = generate_visit_prep_bundle(filt_db, visit_date="2025-06-20", lookback_months=12)
        assert bundle["new_labs"] == []
        assert bundle["active_medications"] == []
        assert bundle["active_conditions"] == []
        assert bundle["recent_imaging"] == []
        assert bundle["lab_trends"] == {}


class TestVisitDiffRespectsArchive:
    def test_visit_diff_hides_archived(self, filt_db):
        diff = visit_diff(filt_db, "2025-01-01")
        assert diff["summary"]["labs"] == 1
        assert diff["summary"]["medication_changes"] == 1
        for table in (
            "lab_results",
            "medications",
            "conditions",
            "encounters",
            "imaging_reports",
            "procedures",
            "pathology_reports",
        ):
            filt_db.archive_record(table, _id(filt_db, table))
        diff = visit_diff(filt_db, "2025-01-01")
        assert diff["summary"]["labs"] == 0
        assert diff["summary"]["medication_changes"] == 0
        assert diff["summary"]["conditions"] == 0
        assert diff["summary"]["encounters"] == 0
        assert diff["summary"]["imaging"] == 0
        assert diff["summary"]["procedures"] == 0
        assert diff["summary"]["pathology"] == 0


class TestSurgicalTimelineRespectsArchive:
    def test_surgical_timeline_hides_archived_procedure(self, filt_db):
        tl = build_surgical_timeline(filt_db)
        assert len(tl) == 1
        filt_db.archive_record("procedures", _id(filt_db, "procedures"))
        assert build_surgical_timeline(filt_db) == []

    def test_surgical_timeline_hides_archived_pathology(self, filt_db):
        filt_db.archive_record("pathology_reports", _id(filt_db, "pathology_reports"))
        tl = build_surgical_timeline(filt_db)
        # The procedure remains, but its archived pathology must not be linked.
        assert len(tl) == 1
        assert tl[0]["pathology"] is None


class TestSummaryRespectsArchive:
    def test_db_summary_excludes_archived(self, filt_db):
        s = filt_db.summary()
        assert s["lab_results"] == 1
        filt_db.archive_record("lab_results", _id(filt_db, "lab_results"))
        s = filt_db.summary()
        assert s["lab_results"] == 0


# --- R1: SPA export must not ship archived rows, notes, analyses, or load_log ---


def _embedded_db(html_path: str) -> sqlite3.Connection:
    """Decode the embedded SQLite DB from an exported SPA HTML file."""
    html = Path(html_path).read_text(encoding="utf-8")
    match = re.search(
        r'<script id="health-memex-db" type="application/gzip\+base64">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None, "embedded DB script tag not found"
    db_bytes = gzip.decompress(base64.b64decode(match.group(1).strip()))
    conn = sqlite3.connect(":memory:")
    conn.deserialize(db_bytes)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def spa_export_db(tmp_path):
    """DB with active + archived rows, a note, and an analysis, plus a load_log entry."""
    db_path = str(tmp_path / "spa_filt.db")
    db = HealthMemexDB(db_path)
    db.init_schema()
    db.load_source(
        UnifiedRecords(
            source="test",
            lab_results=[
                LabResult(
                    source="test",
                    test_name="ActiveCEA",
                    value="1.0",
                    value_numeric=1.0,
                    result_date="2025-01-01",
                ),
                LabResult(
                    source="test",
                    test_name="SecretCEA",
                    value="9.9",
                    value_numeric=9.9,
                    result_date="2025-02-02",
                ),
            ],
        )
    )
    # Archive the "secret" lab.
    secret_id = db.query("SELECT id FROM lab_results WHERE test_name = 'SecretCEA'")[0]["id"]
    db.archive_record("lab_results", secret_id)
    # Personal marginalia and analysis.
    db.save_note(title="Private observation", content="do not publish this", tags=["private"])
    db.save_analysis(slug="private-analysis", title="Private analysis", content="confidential body")
    db.close()
    return db_path


class TestSpaExportSanitizes:
    def test_archived_lab_absent_by_default(self, spa_export_db, tmp_path):
        out = str(tmp_path / "out.html")
        export_spa(spa_export_db, out)
        conn = _embedded_db(out)
        try:
            names = {r["test_name"] for r in conn.execute("SELECT test_name FROM lab_results")}
        finally:
            conn.close()
        assert "ActiveCEA" in names, "active records must still ship"
        assert "SecretCEA" not in names, "archived records must NOT ship in the SPA"

    def test_load_log_dropped_by_default(self, spa_export_db, tmp_path):
        out = str(tmp_path / "out.html")
        export_spa(spa_export_db, out)
        conn = _embedded_db(out)
        try:
            tables = {
                r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            conn.close()
        assert "load_log" not in tables, "load_log audit trail must be dropped from the SPA"

    def test_notes_and_analyses_absent_by_default(self, spa_export_db, tmp_path):
        out = str(tmp_path / "out.html")
        export_spa(spa_export_db, out)
        conn = _embedded_db(out)
        try:
            tables = {
                r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            conn.close()
        # Deny-by-default drops the marginalia tables entirely.
        assert "notes" not in tables, "personal notes table must not ship by default"
        assert "note_tags" not in tables
        assert "analyses" not in tables, "analyses table must not ship by default"
        assert "analysis_tags" not in tables

    def test_include_notes_ships_notes(self, spa_export_db, tmp_path):
        out = str(tmp_path / "out_notes.html")
        export_spa(spa_export_db, out, include_notes=True)
        conn = _embedded_db(out)
        try:
            note_rows = conn.execute("SELECT COUNT(*) AS n FROM notes").fetchone()["n"]
            analysis_rows = conn.execute("SELECT COUNT(*) AS n FROM analyses").fetchone()["n"]
            # Even with notes, archived clinical rows stay out.
            names = {r["test_name"] for r in conn.execute("SELECT test_name FROM lab_results")}
        finally:
            conn.close()
        assert note_rows == 1, "include_notes=True must ship personal notes"
        assert analysis_rows == 1, "include_notes=True must ship analyses"
        assert "SecretCEA" not in names, "archived rows still excluded with include_notes"

    def test_spa_still_renders(self, spa_export_db, tmp_path):
        """The sanitized SPA must still be a valid, renderable bundle."""
        out = str(tmp_path / "out.html")
        export_spa(spa_export_db, out)
        html = Path(out).read_text(encoding="utf-8")
        assert html.startswith("<!DOCTYPE html>")
        assert html.rstrip().endswith("</html>")
        assert 'id="health-memex-db"' in html
        assert "Router.start()" in html
        # The active record is queryable in the embedded DB.
        conn = _embedded_db(out)
        try:
            n = conn.execute("SELECT COUNT(*) AS n FROM lab_results").fetchone()["n"]
        finally:
            conn.close()
        assert n == 1
