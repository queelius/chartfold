"""Tests for chartfold arkiv import."""

import json
import os

import yaml

from chartfold.db import ChartfoldDB
from chartfold.export_arkiv import export_arkiv
from chartfold.models import (
    FamilyHistoryRecord,
    LabResult,
    ProcedureRecord,
    UnifiedRecords,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_minimal_archive(archive_dir):
    """Create a minimal valid arkiv archive for testing."""
    contents = [{"path": "lab_results.jsonl", "description": "Labs"}]
    frontmatter = {
        "name": "Test export",
        "datetime": "2026-02-28",
        "generator": "test",
        "contents": contents,
    }

    readme = "---\n" + yaml.dump(frontmatter, sort_keys=False) + "---\n\n# Test\n"
    (archive_dir / "README.md").write_text(readme)

    schema = {"lab_results": {"record_count": 1, "metadata_keys": {}}}
    (archive_dir / "schema.yaml").write_text(yaml.dump(schema))

    record = {
        "mimetype": "application/json",
        "uri": "chartfold:lab_results/1",
        "timestamp": "2025-01-15",
        "metadata": {
            "table": "lab_results",
            "source": "test",
            "test_name": "CEA",
            "value": "5.8",
            "value_numeric": 5.8,
            "result_date": "2025-01-15",
        },
    }
    (archive_dir / "lab_results.jsonl").write_text(json.dumps(record) + "\n")


def _create_archive_with_fks(archive_dir):
    """Create an archive with FK relationships (procedures -> pathology)."""
    proc_record = {
        "mimetype": "application/json",
        "uri": "chartfold:procedures/10",
        "timestamp": "2024-07-01",
        "metadata": {
            "table": "procedures",
            "source": "test_surgical",
            "name": "Right hemicolectomy",
            "procedure_date": "2024-07-01",
            "provider": "Dr. Surgeon",
        },
    }

    path_record = {
        "mimetype": "application/json",
        "uri": "chartfold:pathology_reports/3",
        "timestamp": "2024-07-03",
        "metadata": {
            "table": "pathology_reports",
            "source": "test_surgical",
            "procedure_uri": "chartfold:procedures/10",
            "report_date": "2024-07-03",
            "specimen": "Right colon",
            "diagnosis": "Adenocarcinoma",
        },
    }

    contents = [
        {"path": "procedures.jsonl", "description": "Procedures"},
        {"path": "pathology_reports.jsonl", "description": "Pathology"},
    ]
    frontmatter = {
        "name": "Test FK export",
        "datetime": "2026-02-28",
        "generator": "test",
        "contents": contents,
    }

    readme = "---\n" + yaml.dump(frontmatter, sort_keys=False) + "---\n\n# Test\n"
    (archive_dir / "README.md").write_text(readme)
    (archive_dir / "procedures.jsonl").write_text(json.dumps(proc_record) + "\n")
    (archive_dir / "pathology_reports.jsonl").write_text(
        json.dumps(path_record) + "\n"
    )


def _create_archive_with_notes(archive_dir):
    """Create an archive with notes and tags."""
    note_record = {
        "mimetype": "application/json",
        "uri": "chartfold:notes/5",
        "timestamp": "2025-01-15T10:00:00",
        "metadata": {
            "table": "notes",
            "title": "CEA Trend",
            "content": "CEA trending up",
            "created_at": "2025-01-15T10:00:00",
            "updated_at": "2025-01-15T10:00:00",
            "tags": ["cea", "oncology"],
        },
    }

    contents = [{"path": "notes.jsonl", "description": "Notes"}]
    frontmatter = {
        "name": "Test notes export",
        "datetime": "2026-02-28",
        "generator": "test",
        "contents": contents,
    }

    readme = "---\n" + yaml.dump(frontmatter, sort_keys=False) + "---\n\n# Test\n"
    (archive_dir / "README.md").write_text(readme)
    (archive_dir / "notes.jsonl").write_text(json.dumps(note_record) + "\n")


def _create_archive_with_analyses(archive_dir):
    """Create an archive with analyses and tags."""
    analysis_record = {
        "mimetype": "application/json",
        "uri": "chartfold:analyses/1",
        "timestamp": "2025-02-01T12:00:00",
        "metadata": {
            "table": "analyses",
            "slug": "cancer-timeline",
            "title": "Cancer Timeline",
            "content": "# Cancer Timeline\n\nDetailed analysis...",
            "category": "oncology",
            "source": "claude",
            "created_at": "2025-02-01T12:00:00",
            "updated_at": "2025-02-01T12:00:00",
            "tags": ["oncology", "timeline"],
        },
    }

    contents = [{"path": "analyses.jsonl", "description": "Analyses"}]
    frontmatter = {
        "name": "Test analyses export",
        "datetime": "2026-02-28",
        "generator": "test",
        "contents": contents,
    }

    readme = "---\n" + yaml.dump(frontmatter, sort_keys=False) + "---\n\n# Test\n"
    (archive_dir / "README.md").write_text(readme)
    (archive_dir / "analyses.jsonl").write_text(json.dumps(analysis_record) + "\n")


def _create_archive_with_source_assets(archive_dir):
    """Create an archive with source assets in media/."""
    media_dir = archive_dir / "media"
    media_dir.mkdir()
    (media_dir / "scan.png").write_bytes(b"\x89PNG fake image data")

    asset_record = {
        "mimetype": "image/png",
        "uri": "file://media/scan.png",
        "timestamp": "2025-01-15",
        "metadata": {
            "table": "source_assets",
            "source": "test",
            "asset_type": "png",
            "file_name": "scan.png",
            "file_size_kb": 1,
            "title": "CT Abdomen",
            "encounter_date": "2025-01-15",
            "ref_id_uri": "chartfold:imaging_reports/7",
        },
    }

    contents = [{"path": "source_assets.jsonl", "description": "Source assets"}]
    frontmatter = {
        "name": "Test assets export",
        "datetime": "2026-02-28",
        "generator": "test",
        "contents": contents,
    }

    readme = "---\n" + yaml.dump(frontmatter, sort_keys=False) + "---\n\n# Test\n"
    (archive_dir / "README.md").write_text(readme)
    (archive_dir / "source_assets.jsonl").write_text(
        json.dumps(asset_record) + "\n"
    )


# ---------------------------------------------------------------------------
# Tests: _record_to_row
# ---------------------------------------------------------------------------


class TestRecordToRow:
    """Test reversing arkiv records back to DB rows."""

    def test_basic_lab_record(self):
        from chartfold.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "chartfold:lab_results/42",
            "timestamp": "2025-01-15",
            "metadata": {
                "table": "lab_results",
                "source": "epic_anderson",
                "test_name": "CEA",
                "value": "5.8",
                "value_numeric": 5.8,
                "unit": "ng/mL",
                "ref_range": "0.0-3.0",
                "interpretation": "H",
                "result_date": "2025-01-15",
                "status": "final",
            },
        }

        table, old_id, row = _record_to_row(record)
        assert table == "lab_results"
        assert old_id == 42
        assert row["source"] == "epic_anderson"
        assert row["test_name"] == "CEA"
        assert row["value_numeric"] == 5.8
        assert "table" not in row  # synthetic field stripped

    def test_fk_uri_reversed(self):
        """procedure_uri should be reversed to procedure_id with old ID."""
        from chartfold.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "chartfold:pathology_reports/3",
            "timestamp": "2024-07-03",
            "metadata": {
                "table": "pathology_reports",
                "source": "test_surgical",
                "procedure_uri": "chartfold:procedures/10",
                "report_date": "2024-07-03",
                "specimen": "Right colon",
                "diagnosis": "Adenocarcinoma",
            },
        }

        table, old_id, row = _record_to_row(record)
        assert table == "pathology_reports"
        assert old_id == 3
        assert row["procedure_id"] == 10
        assert "procedure_uri" not in row

    def test_tags_extracted(self):
        """Tags in metadata should be extracted and returned separately."""
        from chartfold.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "chartfold:notes/1",
            "metadata": {
                "table": "notes",
                "title": "CEA Trend",
                "content": "CEA trending up",
                "created_at": "2025-01-15T10:00:00",
                "updated_at": "2025-01-15T10:00:00",
                "tags": ["cea", "oncology"],
            },
        }

        table, _old_id, row = _record_to_row(record)
        assert table == "notes"
        assert "tags" not in row
        assert row["_tags"] == ["cea", "oncology"]

    def test_no_timestamp_field(self):
        """Records without timestamp should work fine."""
        from chartfold.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "chartfold:family_history/7",
            "metadata": {
                "table": "family_history",
                "source": "test",
                "relation": "Father",
                "condition": "Cancer",
            },
        }

        table, _old_id, row = _record_to_row(record)
        assert table == "family_history"
        assert row["relation"] == "Father"

    def test_analyses_tags_extracted(self):
        """Tags should also be extracted for analyses table."""
        from chartfold.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "chartfold:analyses/1",
            "metadata": {
                "table": "analyses",
                "slug": "cancer-timeline",
                "title": "Cancer Timeline",
                "content": "Analysis content",
                "source": "claude",
                "created_at": "2025-01-15T10:00:00",
                "updated_at": "2025-01-15T10:00:00",
                "tags": ["oncology", "timeline"],
            },
        }

        table, _old_id, row = _record_to_row(record)
        assert table == "analyses"
        assert "tags" not in row
        assert row["_tags"] == ["oncology", "timeline"]

    def test_tags_not_extracted_for_non_tag_tables(self):
        """Tags in non-tag tables should remain as normal metadata."""
        from chartfold.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "chartfold:lab_results/1",
            "metadata": {
                "table": "lab_results",
                "source": "test",
                "test_name": "Test",
                "tags": ["some", "data"],
            },
        }

        # lab_results is not in _TAG_CONFIG, so tags stay as-is
        _table, _old_id, row = _record_to_row(record)
        assert row["tags"] == ["some", "data"]
        assert "_tags" not in row

    def test_uri_without_id(self):
        """URI that doesn't match chartfold pattern returns None for old_id."""
        from chartfold.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "file://something/else",
            "metadata": {
                "table": "lab_results",
                "source": "test",
                "test_name": "Test",
            },
        }

        _table, old_id, _row = _record_to_row(record)
        assert old_id is None

    def test_ref_id_uri_reversed(self):
        """ref_id_uri should be reversed to ref_table + ref_id for source_assets."""
        from chartfold.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "chartfold:source_assets/1",
            "metadata": {
                "table": "source_assets",
                "source": "test",
                "asset_type": "png",
                "file_name": "scan.png",
                "ref_id_uri": "chartfold:imaging_reports/7",
            },
        }

        _table, _old_id, row = _record_to_row(record)
        assert row["ref_table"] == "imaging_reports"
        assert row["ref_id"] == 7
        assert "ref_id_uri" not in row


# ---------------------------------------------------------------------------
# Tests: validate_arkiv
# ---------------------------------------------------------------------------


class TestValidateArkiv:
    def test_valid_archive(self, tmp_path):
        from chartfold.import_arkiv import validate_arkiv

        _create_minimal_archive(tmp_path)
        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is True
        assert result["errors"] == []
        assert "lab_results" in result["summary"]
        assert result["summary"]["lab_results"] == 1

    def test_missing_readme(self, tmp_path):
        from chartfold.import_arkiv import validate_arkiv

        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is False
        assert any("README.md" in e for e in result["errors"])

    def test_invalid_yaml_frontmatter(self, tmp_path):
        from chartfold.import_arkiv import validate_arkiv

        (tmp_path / "README.md").write_text("---\ninvalid: [unclosed\n---\n")
        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is False

    def test_invalid_jsonl(self, tmp_path):
        from chartfold.import_arkiv import validate_arkiv

        _create_minimal_archive(tmp_path)
        (tmp_path / "lab_results.jsonl").write_text("not json\n")
        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is False
        assert any("JSON" in e for e in result["errors"])

    def test_missing_jsonl_file(self, tmp_path):
        from chartfold.import_arkiv import validate_arkiv

        _create_minimal_archive(tmp_path)
        os.remove(tmp_path / "lab_results.jsonl")
        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is False
        assert any("Missing file" in e for e in result["errors"])

    def test_no_frontmatter_start(self, tmp_path):
        from chartfold.import_arkiv import validate_arkiv

        (tmp_path / "README.md").write_text("# Just a heading\nNo frontmatter here.")
        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is False

    def test_valid_archive_with_schema_yaml(self, tmp_path):
        from chartfold.import_arkiv import validate_arkiv

        _create_minimal_archive(tmp_path)
        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is True
        # schema.yaml was created by _create_minimal_archive

    def test_invalid_schema_yaml(self, tmp_path):
        from chartfold.import_arkiv import validate_arkiv

        _create_minimal_archive(tmp_path)
        (tmp_path / "schema.yaml").write_text("invalid: [unclosed\n")
        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is False
        assert any("schema.yaml" in e for e in result["errors"])

    def test_empty_jsonl_lines_skipped(self, tmp_path):
        from chartfold.import_arkiv import validate_arkiv

        _create_minimal_archive(tmp_path)
        record = {
            "mimetype": "application/json",
            "uri": "chartfold:lab_results/1",
            "metadata": {"table": "lab_results", "source": "test", "test_name": "CEA"},
        }
        (tmp_path / "lab_results.jsonl").write_text(
            "\n" + json.dumps(record) + "\n\n"
        )
        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is True
        assert result["summary"]["lab_results"] == 1


# ---------------------------------------------------------------------------
# Tests: import_arkiv
# ---------------------------------------------------------------------------


class TestImportArkiv:
    def test_import_creates_database(self, tmp_path):
        from chartfold.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)
        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is True
        assert (tmp_path / "imported.db").exists()
        with ChartfoldDB(db_path) as db:
            labs = db.query("SELECT * FROM lab_results")
            assert len(labs) == 1
            assert labs[0]["test_name"] == "CEA"
            assert labs[0]["value_numeric"] == 5.8

    def test_import_validate_only(self, tmp_path):
        from chartfold.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)
        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path, validate_only=True)
        assert result["success"] is True
        assert not (tmp_path / "imported.db").exists()

    def test_import_refuses_overwrite(self, tmp_path):
        from chartfold.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)
        db_path = str(tmp_path / "existing.db")
        with ChartfoldDB(db_path) as db:
            db.init_schema()
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is False
        assert "already exists" in result["errors"][0]

    def test_import_overwrites_when_requested(self, tmp_path):
        from chartfold.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)
        db_path = str(tmp_path / "existing.db")
        with ChartfoldDB(db_path) as db:
            db.init_schema()
        result = import_arkiv(str(archive_dir), db_path, overwrite=True)
        assert result["success"] is True
        with ChartfoldDB(db_path) as db:
            labs = db.query("SELECT * FROM lab_results")
            assert len(labs) == 1

    def test_import_fk_remapping(self, tmp_path):
        """FK relationships should be preserved after import with ID remapping."""
        from chartfold.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_archive_with_fks(archive_dir)

        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is True

        with ChartfoldDB(db_path) as db:
            # FK join should work
            joined = db.query("""
                SELECT p.name AS proc_name, pr.diagnosis
                FROM pathology_reports pr
                JOIN procedures p ON pr.procedure_id = p.id
            """)
            assert len(joined) == 1
            assert joined[0]["proc_name"] == "Right hemicolectomy"
            assert joined[0]["diagnosis"] == "Adenocarcinoma"

    def test_import_notes_with_tags(self, tmp_path):
        """Notes should be imported with their tags unfolded."""
        from chartfold.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_archive_with_notes(archive_dir)

        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is True

        with ChartfoldDB(db_path) as db:
            notes = db.search_notes_personal()
            assert len(notes) == 1
            assert notes[0]["title"] == "CEA Trend"
            assert set(notes[0]["tags"]) == {"cea", "oncology"}

    def test_import_analyses_with_tags(self, tmp_path):
        """Analyses should be imported with their tags unfolded."""
        from chartfold.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_archive_with_analyses(archive_dir)

        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is True

        with ChartfoldDB(db_path) as db:
            analysis = db.get_analysis("cancer-timeline")
            assert analysis is not None
            assert analysis["title"] == "Cancer Timeline"
            assert set(analysis["tags"]) == {"oncology", "timeline"}

    def test_import_source_assets(self, tmp_path):
        """Source assets should be imported with file_path pointing to media/."""
        from chartfold.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_archive_with_source_assets(archive_dir)

        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is True

        with ChartfoldDB(db_path) as db:
            assets = db.query("SELECT * FROM source_assets")
            assert len(assets) == 1
            assert assets[0]["asset_type"] == "png"
            assert assets[0]["file_name"] == "scan.png"
            assert assets[0]["content_type"] == "image/png"
            # file_path should point to the archive's media/ copy
            assert "media" in assets[0]["file_path"]
            assert os.path.isfile(assets[0]["file_path"])

    def test_import_invalid_archive(self, tmp_path):
        """Importing an invalid archive should fail gracefully."""
        from chartfold.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        # No README.md
        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is False
        assert len(result["errors"]) > 0

    def test_import_preserves_all_lab_fields(self, tmp_path):
        """All lab result fields should be preserved after import."""
        from chartfold.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()

        record = {
            "mimetype": "application/json",
            "uri": "chartfold:lab_results/1",
            "timestamp": "2025-01-15",
            "metadata": {
                "table": "lab_results",
                "source": "epic_anderson",
                "test_name": "CEA",
                "test_loinc": "2039-6",
                "panel_name": "Tumor Markers",
                "value": "5.8",
                "value_numeric": 5.8,
                "unit": "ng/mL",
                "ref_range": "0.0-3.0",
                "interpretation": "H",
                "result_date": "2025-01-15",
                "status": "final",
            },
        }

        contents = [{"path": "lab_results.jsonl", "description": "Labs"}]
        frontmatter = {
            "name": "Full lab test",
            "datetime": "2026-02-28",
            "generator": "test",
            "contents": contents,
        }
        readme = "---\n" + yaml.dump(frontmatter, sort_keys=False) + "---\n\n# Test\n"
        (archive_dir / "README.md").write_text(readme)
        (archive_dir / "lab_results.jsonl").write_text(json.dumps(record) + "\n")

        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is True

        with ChartfoldDB(db_path) as db:
            labs = db.query("SELECT * FROM lab_results")
            assert len(labs) == 1
            lab = labs[0]
            assert lab["source"] == "epic_anderson"
            assert lab["test_name"] == "CEA"
            assert lab["test_loinc"] == "2039-6"
            assert lab["panel_name"] == "Tumor Markers"
            assert lab["value"] == "5.8"
            assert lab["value_numeric"] == 5.8
            assert lab["unit"] == "ng/mL"
            assert lab["ref_range"] == "0.0-3.0"
            assert lab["interpretation"] == "H"
            assert lab["result_date"] == "2025-01-15"
            assert lab["status"] == "final"

    def test_import_multiple_tables(self, tmp_path):
        """Importing an archive with multiple tables should work."""
        from chartfold.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()

        lab_record = {
            "mimetype": "application/json",
            "uri": "chartfold:lab_results/1",
            "metadata": {
                "table": "lab_results",
                "source": "test",
                "test_name": "CEA",
                "value": "5.8",
                "value_numeric": 5.8,
                "result_date": "2025-01-15",
            },
        }
        fh_record = {
            "mimetype": "application/json",
            "uri": "chartfold:family_history/1",
            "metadata": {
                "table": "family_history",
                "source": "test",
                "relation": "Father",
                "condition": "Heart Disease",
            },
        }

        contents = [
            {"path": "lab_results.jsonl", "description": "Labs"},
            {"path": "family_history.jsonl", "description": "Family history"},
        ]
        frontmatter = {
            "name": "Multi-table test",
            "datetime": "2026-02-28",
            "generator": "test",
            "contents": contents,
        }
        readme = "---\n" + yaml.dump(frontmatter, sort_keys=False) + "---\n\n# Test\n"
        (archive_dir / "README.md").write_text(readme)
        (archive_dir / "lab_results.jsonl").write_text(json.dumps(lab_record) + "\n")
        (archive_dir / "family_history.jsonl").write_text(json.dumps(fh_record) + "\n")

        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is True
        assert result["counts"]["lab_results"] == 1
        assert result["counts"]["family_history"] == 1

        with ChartfoldDB(db_path) as db:
            labs = db.query("SELECT * FROM lab_results")
            fh = db.query("SELECT * FROM family_history")
            assert len(labs) == 1
            assert len(fh) == 1

    def test_import_source_asset_ref_id_remapping(self, tmp_path):
        """Source asset ref_id should be remapped through id_map."""
        from chartfold.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()

        # Create media/ with a file
        media_dir = archive_dir / "media"
        media_dir.mkdir()
        (media_dir / "scan.png").write_bytes(b"\x89PNG data")

        # Imaging report record (will get a new ID on import)
        imaging_record = {
            "mimetype": "application/json",
            "uri": "chartfold:imaging_reports/50",
            "timestamp": "2025-01-15",
            "metadata": {
                "table": "imaging_reports",
                "source": "test",
                "study_name": "CT Abdomen",
                "modality": "CT",
                "study_date": "2025-01-15",
            },
        }

        # Source asset referencing the imaging report by old ID
        asset_record = {
            "mimetype": "image/png",
            "uri": "file://media/scan.png",
            "timestamp": "2025-01-15",
            "metadata": {
                "table": "source_assets",
                "source": "test",
                "asset_type": "png",
                "file_name": "scan.png",
                "file_size_kb": 1,
                "encounter_date": "2025-01-15",
                "ref_id_uri": "chartfold:imaging_reports/50",
            },
        }

        contents = [
            {"path": "imaging_reports.jsonl", "description": "Imaging"},
            {"path": "source_assets.jsonl", "description": "Assets"},
        ]
        frontmatter = {
            "name": "Asset ref test",
            "datetime": "2026-02-28",
            "generator": "test",
            "contents": contents,
        }
        readme = "---\n" + yaml.dump(frontmatter, sort_keys=False) + "---\n\n# Test\n"
        (archive_dir / "README.md").write_text(readme)
        (archive_dir / "imaging_reports.jsonl").write_text(
            json.dumps(imaging_record) + "\n"
        )
        (archive_dir / "source_assets.jsonl").write_text(
            json.dumps(asset_record) + "\n"
        )

        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is True

        with ChartfoldDB(db_path) as db:
            assets = db.query("SELECT * FROM source_assets")
            assert len(assets) == 1
            # ref_table should be set
            assert assets[0]["ref_table"] == "imaging_reports"
            # ref_id should point to the new ID of the imaging report
            imaging = db.query("SELECT id FROM imaging_reports")
            assert len(imaging) == 1
            assert assets[0]["ref_id"] == imaging[0]["id"]


# ---------------------------------------------------------------------------
# Tests: Round-trip (export -> import -> verify)
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """End-to-end round-trip tests via arkiv format."""

    def test_round_trip_labs(self, tmp_path):
        """Export labs to arkiv, import back, verify data preserved."""
        from chartfold.import_arkiv import import_arkiv

        # Create source DB with labs
        src_db_path = str(tmp_path / "source.db")
        with ChartfoldDB(src_db_path) as db:
            db.init_schema()
            records = UnifiedRecords(
                source="test_source",
                lab_results=[
                    LabResult(
                        source="test_source",
                        test_name="CEA",
                        test_loinc="2039-6",
                        panel_name="Tumor Markers",
                        value="5.8",
                        value_numeric=5.8,
                        unit="ng/mL",
                        ref_range="0.0-3.0",
                        interpretation="H",
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
            db.load_source(records)

            # Export
            archive_dir = str(tmp_path / "arkiv-export")
            export_arkiv(db, archive_dir)

        # Import into new DB
        imported_db_path = str(tmp_path / "imported.db")
        result = import_arkiv(archive_dir, imported_db_path)
        assert result["success"] is True

        # Verify
        with ChartfoldDB(imported_db_path) as db:
            labs = db.query("SELECT * FROM lab_results ORDER BY test_name")
            assert len(labs) == 2
            cea = next(lab for lab in labs if lab["test_name"] == "CEA")
            assert cea["value_numeric"] == 5.8
            assert cea["interpretation"] == "H"
            assert cea["test_loinc"] == "2039-6"

            hgb = next(lab for lab in labs if lab["test_name"] == "Hemoglobin")
            assert hgb["value_numeric"] == 12.5

    def test_round_trip_fk_relationships(self, tmp_path):
        """FK relationships preserved through export -> import cycle."""
        from chartfold.import_arkiv import import_arkiv

        # Create source DB with FK relationships
        src_db_path = str(tmp_path / "source.db")
        with ChartfoldDB(src_db_path) as db:
            db.init_schema()
            records = UnifiedRecords(
                source="test_surgical",
                procedures=[
                    ProcedureRecord(
                        source="test_surgical",
                        name="Right hemicolectomy",
                        procedure_date="2024-07-01",
                        provider="Dr. Surgeon",
                    ),
                ],
            )
            db.load_source(records)

            # Get procedure ID and manually insert linked pathology
            proc = db.query("SELECT id FROM procedures")[0]
            db.conn.execute(
                """INSERT INTO pathology_reports
                   (source, procedure_id, report_date, specimen, diagnosis)
                   VALUES (?, ?, ?, ?, ?)""",
                ("test_surgical", proc["id"], "2024-07-03", "Right colon", "Adenocarcinoma"),
            )
            db.conn.commit()

            archive_dir = str(tmp_path / "arkiv-export")
            export_arkiv(db, archive_dir)

        # Import
        imported_db_path = str(tmp_path / "imported.db")
        result = import_arkiv(archive_dir, imported_db_path)
        assert result["success"] is True

        # Verify FK join works
        with ChartfoldDB(imported_db_path) as db:
            joined = db.query("""
                SELECT p.name AS proc_name, pr.diagnosis
                FROM pathology_reports pr
                JOIN procedures p ON pr.procedure_id = p.id
            """)
            assert len(joined) == 1
            assert joined[0]["proc_name"] == "Right hemicolectomy"
            assert joined[0]["diagnosis"] == "Adenocarcinoma"

    def test_round_trip_notes_with_tags(self, tmp_path):
        """Notes with tags preserved through export -> import cycle."""
        from chartfold.import_arkiv import import_arkiv

        # Create source DB with notes
        src_db_path = str(tmp_path / "source.db")
        with ChartfoldDB(src_db_path) as db:
            db.init_schema()
            db.save_note(
                title="CEA Analysis",
                content="CEA trending upward",
                tags=["oncology", "cea"],
            )
            db.save_note(
                title="Visit Prep",
                content="Questions for next visit",
                tags=["visit-prep"],
            )

            archive_dir = str(tmp_path / "arkiv-export")
            export_arkiv(db, archive_dir)

        # Import
        imported_db_path = str(tmp_path / "imported.db")
        result = import_arkiv(archive_dir, imported_db_path)
        assert result["success"] is True

        # Verify
        with ChartfoldDB(imported_db_path) as db:
            notes = db.search_notes_personal()
            assert len(notes) == 2

            cea_note = next(n for n in notes if n["title"] == "CEA Analysis")
            assert set(cea_note["tags"]) == {"oncology", "cea"}

            visit_note = next(n for n in notes if n["title"] == "Visit Prep")
            assert set(visit_note["tags"]) == {"visit-prep"}

    def test_round_trip_family_history_no_timestamp(self, tmp_path):
        """Tables without timestamp fields should round-trip correctly."""
        from chartfold.import_arkiv import import_arkiv

        src_db_path = str(tmp_path / "source.db")
        with ChartfoldDB(src_db_path) as db:
            db.init_schema()
            records = UnifiedRecords(
                source="test",
                family_history=[
                    FamilyHistoryRecord(
                        source="test",
                        relation="Father",
                        condition="Heart Disease",
                    ),
                    FamilyHistoryRecord(
                        source="test",
                        relation="Mother",
                        condition="Diabetes",
                    ),
                ],
            )
            db.load_source(records)

            archive_dir = str(tmp_path / "arkiv-export")
            export_arkiv(db, archive_dir)

        imported_db_path = str(tmp_path / "imported.db")
        result = import_arkiv(archive_dir, imported_db_path)
        assert result["success"] is True

        with ChartfoldDB(imported_db_path) as db:
            fh = db.query("SELECT * FROM family_history ORDER BY relation")
            assert len(fh) == 2
            assert fh[0]["relation"] == "Father"
            assert fh[0]["condition"] == "Heart Disease"
            assert fh[1]["relation"] == "Mother"
            assert fh[1]["condition"] == "Diabetes"
