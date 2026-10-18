"""Tests for health-memex arkiv import."""

import json
import os

import pytest
import yaml

from health_memex.db import HealthMemexDB
from health_memex.export_arkiv import export_arkiv
from health_memex.models import (
    ConditionRecord,
    EncounterRecord,
    FamilyHistoryRecord,
    LabResult,
    MedicationRecord,
    PathologyReport,
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
        "uri": "health-memex:lab_results/1",
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
        "uri": "health-memex:procedures/10",
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
        "uri": "health-memex:pathology_reports/3",
        "timestamp": "2024-07-03",
        "metadata": {
            "table": "pathology_reports",
            "source": "test_surgical",
            "procedure_uri": "health-memex:procedures/10",
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
    (archive_dir / "pathology_reports.jsonl").write_text(json.dumps(path_record) + "\n")


def _create_archive_with_notes(archive_dir):
    """Create an archive with notes and tags."""
    note_record = {
        "mimetype": "application/json",
        "uri": "health-memex:notes/5",
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
        "uri": "health-memex:analyses/1",
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
            "ref_id_uri": "health-memex:imaging_reports/7",
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
    (archive_dir / "source_assets.jsonl").write_text(json.dumps(asset_record) + "\n")


# ---------------------------------------------------------------------------
# Tests: _record_to_row
# ---------------------------------------------------------------------------


class TestRecordToRow:
    """Test reversing arkiv records back to DB rows."""

    def test_basic_lab_record(self):
        from health_memex.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "health-memex:lab_results/42",
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
        # exported_id is the URI's id portion; for clinical tables this is
        # the unique_id string. Tests use the older numeric form here as
        # _match_uri accepts both forms (\\w+).
        assert old_id == "42"
        assert row["source"] == "epic_anderson"
        assert row["test_name"] == "CEA"
        assert row["value_numeric"] == 5.8
        assert "table" not in row  # synthetic field stripped

    def test_fk_uri_reversed(self):
        """procedure_uri should be reversed to procedure_id holding the
        parent's unique_id string. The actual autoincrement remap happens
        at insert time via uid_map, not in _record_to_row."""
        from health_memex.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "health-memex:pathology_reports/cafef00d12345678",
            "timestamp": "2024-07-03",
            "metadata": {
                "table": "pathology_reports",
                "source": "test_surgical",
                "procedure_uri": "health-memex:procedures/abcd1234deadbeef",
                "report_date": "2024-07-03",
                "specimen": "Right colon",
                "diagnosis": "Adenocarcinoma",
            },
        }

        table, exported_id, row = _record_to_row(record)
        assert table == "pathology_reports"
        assert exported_id == "cafef00d12345678"
        # procedure_id now holds the parent's unique_id string (durable).
        # The insert step looks it up in uid_map to find the autoincrement.
        assert row["procedure_id"] == "abcd1234deadbeef"
        assert "procedure_uri" not in row

    def test_tags_extracted(self):
        """Tags in metadata should be extracted and returned separately."""
        from health_memex.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "health-memex:notes/1",
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
        from health_memex.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "health-memex:family_history/7",
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
        from health_memex.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "health-memex:analyses/1",
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
        from health_memex.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "health-memex:lab_results/1",
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
        """URI that doesn't match health-memex pattern returns None for old_id."""
        from health_memex.import_arkiv import _record_to_row

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
        """ref_id_uri should be reversed to ref_table + ref_id (parent's
        unique_id string) for source_assets. The autoincrement translation
        happens later via uid_map."""
        from health_memex.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "health-memex:source_assets/1",
            "metadata": {
                "table": "source_assets",
                "source": "test",
                "asset_type": "png",
                "file_name": "scan.png",
                "ref_id_uri": "health-memex:imaging_reports/feedfacecafebeef",
            },
        }

        _table, _exported_id, row = _record_to_row(record)
        assert row["ref_table"] == "imaging_reports"
        # ref_id now holds the parent's unique_id (durable URI form).
        assert row["ref_id"] == "feedfacecafebeef"
        assert "ref_id_uri" not in row


# ---------------------------------------------------------------------------
# Tests: validate_arkiv
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    def test_mapping(self):
        from health_memex.import_arkiv import _parse_frontmatter

        assert _parse_frontmatter("---\nname: x\n---\nbody") == {"name": "x"}

    def test_non_mapping_yaml_is_rejected(self):
        """Valid YAML that is not a mapping must not leak to callers that index it."""
        from health_memex.import_arkiv import _parse_frontmatter

        assert _parse_frontmatter("---\njust a string\n---\nbody") is None
        assert _parse_frontmatter("---\n- a\n- b\n---\nbody") is None

    def test_invalid_yaml(self):
        from health_memex.import_arkiv import _parse_frontmatter

        assert _parse_frontmatter("---\n: [unclosed\n---\nbody") is None


class TestValidateArkiv:
    def test_valid_archive(self, tmp_path):
        from health_memex.import_arkiv import validate_arkiv

        _create_minimal_archive(tmp_path)
        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is True
        assert result["errors"] == []
        assert "lab_results" in result["summary"]
        assert result["summary"]["lab_results"] == 1

    def test_missing_readme(self, tmp_path):
        from health_memex.import_arkiv import validate_arkiv

        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is False
        assert any("README.md" in e for e in result["errors"])

    def test_invalid_yaml_frontmatter(self, tmp_path):
        from health_memex.import_arkiv import validate_arkiv

        (tmp_path / "README.md").write_text("---\ninvalid: [unclosed\n---\n")
        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is False

    def test_invalid_jsonl(self, tmp_path):
        from health_memex.import_arkiv import validate_arkiv

        _create_minimal_archive(tmp_path)
        (tmp_path / "lab_results.jsonl").write_text("not json\n")
        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is False
        assert any("JSON" in e for e in result["errors"])

    def test_missing_jsonl_file(self, tmp_path):
        from health_memex.import_arkiv import validate_arkiv

        _create_minimal_archive(tmp_path)
        os.remove(tmp_path / "lab_results.jsonl")
        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is False
        assert any("Missing file" in e for e in result["errors"])

    def test_no_frontmatter_start(self, tmp_path):
        from health_memex.import_arkiv import validate_arkiv

        (tmp_path / "README.md").write_text("# Just a heading\nNo frontmatter here.")
        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is False

    def test_valid_archive_with_schema_yaml(self, tmp_path):
        from health_memex.import_arkiv import validate_arkiv

        _create_minimal_archive(tmp_path)
        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is True
        # schema.yaml was created by _create_minimal_archive

    def test_invalid_schema_yaml(self, tmp_path):
        from health_memex.import_arkiv import validate_arkiv

        _create_minimal_archive(tmp_path)
        (tmp_path / "schema.yaml").write_text("invalid: [unclosed\n")
        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is False
        assert any("schema.yaml" in e for e in result["errors"])

    def test_empty_jsonl_lines_skipped(self, tmp_path):
        from health_memex.import_arkiv import validate_arkiv

        _create_minimal_archive(tmp_path)
        record = {
            "mimetype": "application/json",
            "uri": "health-memex:lab_results/1",
            "metadata": {"table": "lab_results", "source": "test", "test_name": "CEA"},
        }
        (tmp_path / "lab_results.jsonl").write_text("\n" + json.dumps(record) + "\n\n")
        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is True
        assert result["summary"]["lab_results"] == 1


# ---------------------------------------------------------------------------
# Tests: import_arkiv
# ---------------------------------------------------------------------------


class TestContentsPathEscape:
    """README ``contents[].path`` must stay inside the archive root."""

    def _archive_with_path(self, tmp_path, shard_path):
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)
        # A perfectly valid shard sitting just outside the archive root.
        (tmp_path / "outside.jsonl").write_text((archive_dir / "lab_results.jsonl").read_text())
        frontmatter = {"name": "Evil", "contents": [{"path": shard_path, "description": "x"}]}
        readme = "---\n" + yaml.dump(frontmatter, sort_keys=False) + "---\n"
        (archive_dir / "README.md").write_text(readme)
        return archive_dir

    @pytest.mark.parametrize("shard_path", ["../outside.jsonl", "sub/../../outside.jsonl"])
    def test_validate_rejects_escaping_path(self, tmp_path, shard_path):
        from health_memex.import_arkiv import validate_arkiv

        archive_dir = self._archive_with_path(tmp_path, shard_path)
        result = validate_arkiv(str(archive_dir))
        assert result["valid"] is False
        assert any("escapes the archive root" in e for e in result["errors"])
        assert "outside" not in result["summary"]

    def test_validate_rejects_absolute_path(self, tmp_path):
        from health_memex.import_arkiv import validate_arkiv

        archive_dir = self._archive_with_path(tmp_path, str(tmp_path / "outside.jsonl"))
        result = validate_arkiv(str(archive_dir))
        assert result["valid"] is False
        assert any("escapes the archive root" in e for e in result["errors"])

    def test_validate_rejects_symlinked_shard_outside_root(self, tmp_path):
        from health_memex.import_arkiv import validate_arkiv

        archive_dir = self._archive_with_path(tmp_path, "linked.jsonl")
        (archive_dir / "linked.jsonl").symlink_to(tmp_path / "outside.jsonl")
        result = validate_arkiv(str(archive_dir))
        assert result["valid"] is False

    def test_import_rejects_escaping_path(self, tmp_path):
        from health_memex.import_arkiv import import_arkiv

        archive_dir = self._archive_with_path(tmp_path, "../outside.jsonl")
        dest_db = tmp_path / "dest.db"
        result = import_arkiv(str(archive_dir), str(dest_db))
        assert result["success"] is False
        assert any("escapes the archive root" in e for e in result["errors"])
        assert not dest_db.exists()

    def test_import_rejects_escaping_path_in_zip(self, tmp_path):
        """Same check applies after a bundle is extracted to a temp dir."""
        import zipfile as _zipfile

        from health_memex.import_arkiv import import_arkiv

        frontmatter = {"name": "Evil", "contents": [{"path": "../outside.jsonl"}]}
        bundle = tmp_path / "evil.zip"
        with _zipfile.ZipFile(bundle, "w") as zf:
            zf.writestr("README.md", "---\n" + yaml.dump(frontmatter) + "---\n")
        result = import_arkiv(str(bundle), str(tmp_path / "dest.db"))
        assert result["success"] is False
        assert any("escapes the archive root" in e for e in result["errors"])

    def test_nested_inside_path_still_allowed(self, tmp_path):
        from health_memex.import_arkiv import validate_arkiv

        archive_dir = self._archive_with_path(tmp_path, "shards/../lab_results.jsonl")
        result = validate_arkiv(str(archive_dir))
        # "shards/" does not exist, but the normalized path stays inside.
        assert not any("escapes the archive root" in e for e in result["errors"])


class TestImportArkiv:
    def test_import_creates_database(self, tmp_path):
        from health_memex.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)
        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is True
        assert (tmp_path / "imported.db").exists()
        with HealthMemexDB(db_path) as db:
            labs = db.query("SELECT * FROM lab_results")
            assert len(labs) == 1
            assert labs[0]["test_name"] == "CEA"
            assert labs[0]["value_numeric"] == 5.8

    def test_import_validate_only(self, tmp_path):
        from health_memex.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)
        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path, validate_only=True)
        assert result["success"] is True
        assert not (tmp_path / "imported.db").exists()

    def test_import_refuses_overwrite(self, tmp_path):
        from health_memex.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)
        db_path = str(tmp_path / "existing.db")
        with HealthMemexDB(db_path) as db:
            db.init_schema()
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is False
        assert "already exists" in result["errors"][0]

    def test_import_overwrites_when_requested(self, tmp_path):
        from health_memex.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)
        db_path = str(tmp_path / "existing.db")
        with HealthMemexDB(db_path) as db:
            db.init_schema()
        result = import_arkiv(str(archive_dir), db_path, overwrite=True)
        assert result["success"] is True
        with HealthMemexDB(db_path) as db:
            labs = db.query("SELECT * FROM lab_results")
            assert len(labs) == 1

    def test_import_fk_remapping(self, tmp_path):
        """FK relationships should be preserved after import with ID remapping."""
        from health_memex.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_archive_with_fks(archive_dir)

        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is True

        with HealthMemexDB(db_path) as db:
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
        from health_memex.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_archive_with_notes(archive_dir)

        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is True

        with HealthMemexDB(db_path) as db:
            notes = db.search_notes_personal()
            assert len(notes) == 1
            assert notes[0]["title"] == "CEA Trend"
            assert set(notes[0]["tags"]) == {"cea", "oncology"}

    def test_import_analyses_with_tags(self, tmp_path):
        """Analyses should be imported with their tags unfolded."""
        from health_memex.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_archive_with_analyses(archive_dir)

        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is True

        with HealthMemexDB(db_path) as db:
            analysis = db.get_analysis("cancer-timeline")
            assert analysis is not None
            assert analysis["title"] == "Cancer Timeline"
            assert set(analysis["tags"]) == {"oncology", "timeline"}

    def test_import_source_assets(self, tmp_path):
        """Source assets should be imported with file_path pointing to media/."""
        from health_memex.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_archive_with_source_assets(archive_dir)

        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is True

        with HealthMemexDB(db_path) as db:
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
        from health_memex.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        # No README.md
        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is False
        assert len(result["errors"]) > 0

    def test_import_preserves_all_lab_fields(self, tmp_path):
        """All lab result fields should be preserved after import."""
        from health_memex.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()

        record = {
            "mimetype": "application/json",
            "uri": "health-memex:lab_results/1",
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

        with HealthMemexDB(db_path) as db:
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
        from health_memex.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()

        lab_record = {
            "mimetype": "application/json",
            "uri": "health-memex:lab_results/1",
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
            "uri": "health-memex:family_history/1",
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

        with HealthMemexDB(db_path) as db:
            labs = db.query("SELECT * FROM lab_results")
            fh = db.query("SELECT * FROM family_history")
            assert len(labs) == 1
            assert len(fh) == 1

    def test_import_source_asset_ref_id_remapping(self, tmp_path):
        """Source asset ref_id should be remapped through id_map."""
        from health_memex.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()

        # Create media/ with a file
        media_dir = archive_dir / "media"
        media_dir.mkdir()
        (media_dir / "scan.png").write_bytes(b"\x89PNG data")

        # Imaging report record (will get a new ID on import)
        imaging_record = {
            "mimetype": "application/json",
            "uri": "health-memex:imaging_reports/50",
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
                "ref_id_uri": "health-memex:imaging_reports/50",
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
        (archive_dir / "imaging_reports.jsonl").write_text(json.dumps(imaging_record) + "\n")
        (archive_dir / "source_assets.jsonl").write_text(json.dumps(asset_record) + "\n")

        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is True

        with HealthMemexDB(db_path) as db:
            assets = db.query("SELECT * FROM source_assets")
            assert len(assets) == 1
            # ref_table should be set
            assert assets[0]["ref_table"] == "imaging_reports"
            # ref_id should point to the new ID of the imaging report
            imaging = db.query("SELECT id FROM imaging_reports")
            assert len(imaging) == 1
            assert assets[0]["ref_id"] == imaging[0]["id"]

    def test_import_partial_archive_missing_fk_parent(self, tmp_path):
        """Child records with FK to missing parent should get NULL FK."""
        from health_memex.import_arkiv import import_arkiv

        arkiv_dir = tmp_path / "arkiv"
        arkiv_dir.mkdir()

        # Build archive with pathology_reports in contents but NO procedures
        contents = [
            {"path": "lab_results.jsonl", "description": "Labs"},
            {"path": "pathology_reports.jsonl", "description": "Pathology"},
        ]
        frontmatter = {
            "name": "Test export",
            "datetime": "2026-02-28",
            "generator": "test",
            "contents": contents,
        }
        readme = "---\n" + yaml.dump(frontmatter, sort_keys=False) + "---\n\n# Test\n"
        (arkiv_dir / "README.md").write_text(readme)
        schema = {"lab_results": {}, "pathology_reports": {}}
        (arkiv_dir / "schema.yaml").write_text(yaml.dump(schema))
        (arkiv_dir / "lab_results.jsonl").write_text("")  # empty, no labs needed

        # Write a pathology_report referencing a procedure that doesn't exist
        path_file = os.path.join(str(arkiv_dir), "pathology_reports.jsonl")
        record = {
            "mimetype": "application/json",
            "uri": "health-memex:pathology_reports/1",
            "metadata": {
                "table": "pathology_reports",
                "source": "test",
                "report_date": "2025-03-15",
                "specimen": "Colon biopsy",
                "diagnosis": "Adenocarcinoma",
                "procedure_uri": "health-memex:procedures/999",  # no procedures in archive
            },
        }
        with open(path_file, "w") as f:
            f.write(json.dumps(record) + "\n")

        db_path = str(tmp_path / "test.db")
        result = import_arkiv(str(arkiv_dir), db_path)
        assert result["success"] is True
        assert result["counts"]["pathology_reports"] == 1

        with HealthMemexDB(db_path) as db:
            reports = db.query("SELECT * FROM pathology_reports")
            assert len(reports) == 1
            assert reports[0]["procedure_id"] is None  # NULL, not stale old ID
            assert reports[0]["specimen"] == "Colon biopsy"


# ---------------------------------------------------------------------------
# Tests: Round-trip (export -> import -> verify)
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """End-to-end round-trip tests via arkiv format."""

    def test_round_trip_labs(self, tmp_path):
        """Export labs to arkiv, import back, verify data preserved."""
        from health_memex.import_arkiv import import_arkiv

        # Create source DB with labs
        src_db_path = str(tmp_path / "source.db")
        with HealthMemexDB(src_db_path) as db:
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
        with HealthMemexDB(imported_db_path) as db:
            labs = db.query("SELECT * FROM lab_results ORDER BY test_name")
            assert len(labs) == 2
            cea = next(lab for lab in labs if lab["test_name"] == "CEA")
            assert cea["value_numeric"] == 5.8
            assert cea["interpretation"] == "H"
            assert cea["test_loinc"] == "2039-6"

            hgb = next(lab for lab in labs if lab["test_name"] == "Hemoglobin")
            assert hgb["value_numeric"] == 12.5

    def test_round_trip_fk_relationships(self, tmp_path):
        """FK relationships preserved through export -> import cycle.

        Loads procedure first, then loads pathology with FK pointing at
        the procedure. Going through load_source ensures unique_id is
        populated automatically (which the export now requires).
        """
        from health_memex.import_arkiv import import_arkiv

        # Create source DB with FK relationships
        src_db_path = str(tmp_path / "source.db")
        with HealthMemexDB(src_db_path) as db:
            db.init_schema()
            db.load_source(
                UnifiedRecords(
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
            )
            proc_id = db.query("SELECT id FROM procedures")[0]["id"]

            # Load pathology pointing at the procedure. The dataclass
            # carries the autoincrement procedure_id; load_source
            # auto-fills the pathology row's unique_id so it can be
            # exported.
            db.load_source(
                UnifiedRecords(
                    source="test_surgical",
                    pathology_reports=[
                        PathologyReport(
                            source="test_surgical",
                            procedure_id=proc_id,
                            report_date="2024-07-03",
                            specimen="Right colon",
                            diagnosis="Adenocarcinoma",
                        ),
                    ],
                )
            )

            archive_dir = str(tmp_path / "arkiv-export")
            export_arkiv(db, archive_dir)

        # Import
        imported_db_path = str(tmp_path / "imported.db")
        result = import_arkiv(archive_dir, imported_db_path)
        assert result["success"] is True

        # Verify FK join works
        with HealthMemexDB(imported_db_path) as db:
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
        from health_memex.import_arkiv import import_arkiv

        # Create source DB with notes
        src_db_path = str(tmp_path / "source.db")
        with HealthMemexDB(src_db_path) as db:
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
        with HealthMemexDB(imported_db_path) as db:
            notes = db.search_notes_personal()
            assert len(notes) == 2

            cea_note = next(n for n in notes if n["title"] == "CEA Analysis")
            assert set(cea_note["tags"]) == {"oncology", "cea"}

            visit_note = next(n for n in notes if n["title"] == "Visit Prep")
            assert set(visit_note["tags"]) == {"visit-prep"}

    def test_round_trip_family_history_no_timestamp(self, tmp_path):
        """Tables without timestamp fields should round-trip correctly."""
        from health_memex.import_arkiv import import_arkiv

        src_db_path = str(tmp_path / "source.db")
        with HealthMemexDB(src_db_path) as db:
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

        with HealthMemexDB(imported_db_path) as db:
            fh = db.query("SELECT * FROM family_history ORDER BY relation")
            assert len(fh) == 2
            assert fh[0]["relation"] == "Father"
            assert fh[0]["condition"] == "Heart Disease"
            assert fh[1]["relation"] == "Mother"
            assert fh[1]["condition"] == "Diabetes"

    def test_round_trip_comprehensive(self, tmp_path):
        """Multi-table round-trip with counts, values, FKs, and tags."""
        from health_memex.import_arkiv import import_arkiv

        src_db_path = str(tmp_path / "source.db")
        with HealthMemexDB(src_db_path) as db:
            db.init_schema()

            records = UnifiedRecords(
                source="test_source",
                lab_results=[
                    LabResult(
                        source="test_source",
                        test_name="CEA",
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
                        result_date="2025-01-15",
                    ),
                ],
                encounters=[
                    EncounterRecord(
                        source="test_source",
                        encounter_date="2025-01-15",
                        encounter_type="office visit",
                        facility="Test Hospital",
                    ),
                ],
                medications=[
                    MedicationRecord(
                        source="test_source",
                        name="Capecitabine",
                        status="active",
                    ),
                ],
                conditions=[
                    ConditionRecord(
                        source="test_source",
                        condition_name="Colon cancer",
                        icd10_code="C18.9",
                    ),
                ],
                procedures=[
                    ProcedureRecord(
                        source="test_source",
                        name="Right hemicolectomy",
                        procedure_date="2024-07-01",
                    ),
                ],
                family_history=[
                    FamilyHistoryRecord(
                        source="test_source",
                        relation="Father",
                        condition="Heart Disease",
                    ),
                ],
            )
            db.load_source(records)

            # Add pathology linked to procedure (via load_source so
            # unique_id is auto-filled — required by export now).
            procs = db.query("SELECT id FROM procedures")
            proc_id = procs[0]["id"]
            db.load_source(
                UnifiedRecords(
                    source="test_source",
                    pathology_reports=[
                        PathologyReport(
                            source="test_source",
                            procedure_id=proc_id,
                            report_date="2024-07-03",
                            specimen="Right colon",
                            diagnosis="Adenocarcinoma",
                        ),
                    ],
                )
            )

            # Add note with tags
            db.save_note(
                title="CEA Trend",
                content="CEA trending up",
                tags=["oncology", "cea"],
            )

            # Record counts before export
            original_counts = {}
            for table in [
                "lab_results",
                "encounters",
                "medications",
                "conditions",
                "procedures",
                "pathology_reports",
                "family_history",
                "notes",
            ]:
                rows = db.query(f"SELECT COUNT(*) as cnt FROM {table}")
                original_counts[table] = rows[0]["cnt"]

            archive_dir = str(tmp_path / "arkiv-export")
            export_arkiv(db, archive_dir)

        # Import into new DB
        imported_db_path = str(tmp_path / "imported.db")
        result = import_arkiv(archive_dir, imported_db_path)
        assert result["success"] is True

        # Verify counts and values
        with HealthMemexDB(imported_db_path) as idb:
            for table, expected in original_counts.items():
                rows = idb.query(f"SELECT COUNT(*) as cnt FROM {table}")
                assert rows[0]["cnt"] == expected, f"{table}: {rows[0]['cnt']} != {expected}"

            # Verify data values
            cea = idb.query("SELECT * FROM lab_results WHERE test_name = 'CEA'")[0]
            assert cea["value_numeric"] == 5.8
            assert cea["interpretation"] == "H"

            meds = idb.query("SELECT * FROM medications WHERE name = 'Capecitabine'")[0]
            assert meds["status"] == "active"

            # FK preserved
            fk_result = idb.query("""
                SELECT p.name AS proc_name, pr.diagnosis
                FROM pathology_reports pr
                JOIN procedures p ON pr.procedure_id = p.id
            """)
            assert len(fk_result) == 1
            assert fk_result[0]["proc_name"] == "Right hemicolectomy"
            assert fk_result[0]["diagnosis"] == "Adenocarcinoma"

            # Tags preserved
            tags = idb.query(
                "SELECT tag FROM note_tags nt JOIN notes n ON nt.note_id = n.id "
                "WHERE n.title = 'CEA Trend' ORDER BY tag"
            )
            assert [t["tag"] for t in tags] == ["cea", "oncology"]


class TestImportCLI:
    """CLI integration tests for arkiv import."""

    def test_cli_import_arkiv(self, tmp_path):
        """CLI: health-memex import <dir> works end-to-end."""
        import subprocess
        import sys

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)

        db_path = str(tmp_path / "imported.db")
        result = subprocess.run(
            [sys.executable, "-m", "health_memex", "import", str(archive_dir), "--db", db_path],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert (tmp_path / "imported.db").exists()

    def test_cli_import_validate_only(self, tmp_path):
        """CLI: health-memex import --validate-only works."""
        import subprocess
        import sys

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)

        db_path = str(tmp_path / "imported.db")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "health_memex",
                "import",
                str(archive_dir),
                "--db",
                db_path,
                "--validate-only",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert not (tmp_path / "imported.db").exists()


# ---------------------------------------------------------------------------
# Tests: bundle unwrap (C5b)
# ---------------------------------------------------------------------------


class TestBundleImport:
    """End-to-end: export to bundle, then import it back."""

    def _populate_db(self, db_path):
        """Create a small DB with labs + a procedure+pathology FK pair."""
        with HealthMemexDB(db_path) as db:
            db.init_schema()
            records = UnifiedRecords(
                source="test_bundle",
                lab_results=[
                    LabResult(
                        test_name="CEA",
                        value="5.8",
                        value_numeric=5.8,
                        result_date="2025-01-15",
                        source="test_bundle",
                    ),
                ],
                procedures=[
                    ProcedureRecord(
                        name="Colonoscopy",
                        procedure_date="2024-11-02",
                        source="test_bundle",
                    ),
                ],
            )
            db.load_source(records, replace=False)

    def test_import_from_zip_bundle(self, tmp_path):
        from health_memex.import_arkiv import import_arkiv

        src_db = str(tmp_path / "src.db")
        self._populate_db(src_db)

        zip_path = str(tmp_path / "archive.zip")
        with HealthMemexDB(src_db) as db:
            export_arkiv(db, zip_path)
        assert os.path.isfile(zip_path)

        dest_db = str(tmp_path / "dest.db")
        result = import_arkiv(zip_path, dest_db)
        assert result["success"] is True, result.get("errors")
        assert os.path.isfile(dest_db)
        with HealthMemexDB(dest_db) as db:
            labs = db.query("SELECT * FROM lab_results WHERE test_name='CEA'")
            assert len(labs) == 1
            procs = db.query("SELECT * FROM procedures WHERE name='Colonoscopy'")
            assert len(procs) == 1

    def test_import_from_tar_gz_bundle(self, tmp_path):
        from health_memex.import_arkiv import import_arkiv

        src_db = str(tmp_path / "src.db")
        self._populate_db(src_db)

        tgz_path = str(tmp_path / "archive.tar.gz")
        with HealthMemexDB(src_db) as db:
            export_arkiv(db, tgz_path)
        assert os.path.isfile(tgz_path)

        dest_db = str(tmp_path / "dest.db")
        result = import_arkiv(tgz_path, dest_db)
        assert result["success"] is True, result.get("errors")
        with HealthMemexDB(dest_db) as db:
            labs = db.query("SELECT * FROM lab_results WHERE test_name='CEA'")
            assert len(labs) == 1

    def test_import_from_tgz_extension(self, tmp_path):
        from health_memex.import_arkiv import import_arkiv

        src_db = str(tmp_path / "src.db")
        self._populate_db(src_db)

        tgz_path = str(tmp_path / "archive.tgz")
        with HealthMemexDB(src_db) as db:
            export_arkiv(db, tgz_path)

        dest_db = str(tmp_path / "dest.db")
        result = import_arkiv(tgz_path, dest_db)
        assert result["success"] is True, result.get("errors")

    def test_validate_from_zip_bundle(self, tmp_path):
        from health_memex.import_arkiv import validate_arkiv

        src_db = str(tmp_path / "src.db")
        self._populate_db(src_db)

        zip_path = str(tmp_path / "archive.zip")
        with HealthMemexDB(src_db) as db:
            export_arkiv(db, zip_path)

        result = validate_arkiv(zip_path)
        assert result["valid"] is True
        assert result["summary"].get("lab_results", 0) >= 1

    def test_validate_rejects_non_archive_file(self, tmp_path):
        from health_memex.import_arkiv import validate_arkiv

        bogus = tmp_path / "not_an_archive.txt"
        bogus.write_text("hello")
        result = validate_arkiv(str(bogus))
        assert result["valid"] is False

    def test_validate_rejects_bad_zip(self, tmp_path):
        from health_memex.import_arkiv import validate_arkiv

        bogus = tmp_path / "corrupt.zip"
        bogus.write_bytes(b"not a real zip")
        result = validate_arkiv(str(bogus))
        assert result["valid"] is False
        assert result["errors"], "expected an error message"

    def test_zip_path_traversal_rejected(self, tmp_path):
        """A zip with .. entries must not escape the extraction dir."""
        import zipfile as _zipfile

        from health_memex.import_arkiv import validate_arkiv

        malicious = tmp_path / "evil.zip"
        with _zipfile.ZipFile(malicious, "w") as zf:
            zf.writestr("../evil_README.md", "escaped!")

        result = validate_arkiv(str(malicious))
        assert result["valid"] is False

    def test_tar_symlink_escape_rejected(self, tmp_path):
        """A tar member linking outside the extraction dir is refused."""
        import io
        import tarfile as _tarfile

        from health_memex.import_arkiv import validate_arkiv

        malicious = tmp_path / "evil.tar.gz"
        with _tarfile.open(malicious, "w:gz") as tf:
            readme = b"---\ncontents: []\n---\n"
            info = _tarfile.TarInfo("README.md")
            info.size = len(readme)
            tf.addfile(info, io.BytesIO(readme))
            link = _tarfile.TarInfo("media/passwd")
            link.type = _tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tf.addfile(link)

        result = validate_arkiv(str(malicious))
        assert result["valid"] is False

    @pytest.mark.parametrize("name", ["archive.zip", "archive.tar.gz"])
    def test_media_round_trip_through_bundle(self, tmp_path, name):
        """Source assets in media/ survive export -> bundle -> import."""
        from health_memex.import_arkiv import import_arkiv

        src_db = str(tmp_path / "src.db")
        self._populate_db(src_db)
        media_src = tmp_path / "ehr_files"
        media_src.mkdir()
        (media_src / "scan.pdf").write_bytes(b"%PDF fake")
        with HealthMemexDB(src_db) as db:
            db.conn.execute(
                """INSERT INTO source_assets
                   (source, asset_type, file_path, file_name, file_size_kb, content_type)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    "test_bundle",
                    "pdf",
                    str(media_src / "scan.pdf"),
                    "scan.pdf",
                    0,
                    "application/pdf",
                ),
            )
            db.conn.commit()
            bundle = str(tmp_path / name)
            export_arkiv(db, bundle)

        dest_db = str(tmp_path / "dest.db")
        result = import_arkiv(bundle, dest_db)
        assert result["success"] is True, result.get("errors")
        assert result["counts"].get("source_assets") == 1
        with HealthMemexDB(dest_db) as db:
            rows = db.query("SELECT file_name, content_type, file_path FROM source_assets")
        assert len(rows) == 1
        assert rows[0]["file_name"] == "scan.pdf"
        assert rows[0]["content_type"] == "application/pdf"
        # The media/ file was found in the extracted bundle and resolved.
        assert rows[0]["file_path"].endswith(os.path.join("media", "scan.pdf"))

    def test_directory_input_still_works(self, tmp_path):
        """Directory inputs continue to work after the bundle refactor."""
        from health_memex.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)

        dest_db = str(tmp_path / "dest.db")
        result = import_arkiv(str(archive_dir), dest_db)
        assert result["success"] is True
        with HealthMemexDB(dest_db) as db:
            labs = db.query("SELECT * FROM lab_results")
            assert len(labs) == 1


# ---------------------------------------------------------------------------
# Tests: --merge (C7)
# ---------------------------------------------------------------------------


class TestMergeImport:
    """--merge: UPSERT into an existing DB by natural key."""

    def _populate_db(self, db_path, labs=None, procedures=None):
        """Populate a DB with the given records under a fixed source."""
        with HealthMemexDB(db_path) as db:
            db.init_schema()
            records = UnifiedRecords(
                source="test_merge",
                lab_results=list(labs or []),
                procedures=list(procedures or []),
            )
            db.load_source(records, replace=False)

    def test_merge_creates_db_when_missing(self, tmp_path):
        """--merge should create the DB if it doesn't yet exist."""
        from health_memex.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)

        dest_db = str(tmp_path / "new.db")
        assert not os.path.exists(dest_db)

        result = import_arkiv(str(archive_dir), dest_db, merge=True)
        assert result["success"] is True, result.get("errors")
        assert os.path.isfile(dest_db)
        with HealthMemexDB(dest_db) as db:
            labs = db.query("SELECT * FROM lab_results")
            assert len(labs) == 1

    def test_merge_preserves_existing_rows(self, tmp_path):
        """--merge must not wipe rows that already exist in the DB."""
        from health_memex.import_arkiv import import_arkiv

        # Existing DB: one pre-existing lab under a different source
        dest_db = str(tmp_path / "existing.db")
        self._populate_db(
            dest_db,
            labs=[
                LabResult(
                    test_name="WBC",
                    value="6.2",
                    value_numeric=6.2,
                    result_date="2024-01-05",
                    source="pre_existing",
                ),
            ],
        )

        # Archive: a different lab
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)

        result = import_arkiv(str(archive_dir), dest_db, merge=True)
        assert result["success"] is True, result.get("errors")
        with HealthMemexDB(dest_db) as db:
            labs = db.query("SELECT test_name, source FROM lab_results ORDER BY test_name")
            test_names = sorted(r["test_name"] for r in labs)
            assert "WBC" in test_names, "existing row was wiped by merge"
            assert "CEA" in test_names, "new row was not imported"

    def test_merge_is_idempotent_on_reimport(self, tmp_path):
        """Running --merge twice with the same archive must not duplicate rows."""
        from health_memex.import_arkiv import import_arkiv

        # Build an archive by exporting from a populated source DB
        src_db = str(tmp_path / "src.db")
        self._populate_db(
            src_db,
            labs=[
                LabResult(
                    test_name="CEA",
                    value="5.8",
                    value_numeric=5.8,
                    result_date="2025-01-15",
                    source="test_merge",
                ),
            ],
            procedures=[
                ProcedureRecord(
                    name="Colonoscopy",
                    procedure_date="2024-11-02",
                    source="test_merge",
                ),
            ],
        )
        archive_path = str(tmp_path / "archive.zip")
        with HealthMemexDB(src_db) as db:
            export_arkiv(db, archive_path)

        dest_db = str(tmp_path / "dest.db")

        # First merge: should create + populate
        r1 = import_arkiv(archive_path, dest_db, merge=True)
        assert r1["success"] is True, r1.get("errors")

        # Second merge: should be a no-op row-count-wise
        r2 = import_arkiv(archive_path, dest_db, merge=True)
        assert r2["success"] is True, r2.get("errors")

        with HealthMemexDB(dest_db) as db:
            labs = db.query("SELECT COUNT(*) AS n FROM lab_results")
            procs = db.query("SELECT COUNT(*) AS n FROM procedures")
            assert labs[0]["n"] == 1, "lab row duplicated on re-merge"
            assert procs[0]["n"] == 1, "procedure row duplicated on re-merge"

    def test_merge_remaps_fks_on_conflict(self, tmp_path):
        """A re-merged pathology report must still point at the correct procedure."""
        from health_memex.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_archive_with_fks(archive_dir)

        dest_db = str(tmp_path / "dest.db")
        r1 = import_arkiv(str(archive_dir), dest_db, merge=True)
        assert r1["success"] is True, r1.get("errors")

        r2 = import_arkiv(str(archive_dir), dest_db, merge=True)
        assert r2["success"] is True, r2.get("errors")

        with HealthMemexDB(dest_db) as db:
            joined = db.query(
                """
                SELECT p.name AS proc_name, pr.diagnosis
                FROM pathology_reports pr
                JOIN procedures p ON pr.procedure_id = p.id
                """
            )
            assert len(joined) == 1, "FK relationship broken after merge"

    def test_merge_and_overwrite_are_mutually_exclusive(self, tmp_path):
        from health_memex.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)

        result = import_arkiv(
            str(archive_dir),
            str(tmp_path / "x.db"),
            overwrite=True,
            merge=True,
        )
        assert result["success"] is False
        assert "mutually exclusive" in result["errors"][0].lower()

    def test_default_still_refuses_existing_db(self, tmp_path):
        """Without --merge or --overwrite, an existing DB should still be rejected."""
        from health_memex.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)

        dest_db = str(tmp_path / "existing.db")
        with HealthMemexDB(dest_db) as db:
            db.init_schema()

        result = import_arkiv(str(archive_dir), dest_db)
        assert result["success"] is False
        msg = result["errors"][0]
        assert "--merge" in msg and "--overwrite" in msg

    def test_cli_merge_flag_works(self, tmp_path):
        """CLI: health-memex import --merge round-trips successfully."""
        import subprocess
        import sys

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)

        dest_db = str(tmp_path / "cli.db")
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "health_memex",
                "import",
                str(archive_dir),
                "--db",
                dest_db,
                "--merge",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        assert os.path.isfile(dest_db)
        with HealthMemexDB(dest_db) as db:
            labs = db.query("SELECT * FROM lab_results")
            assert len(labs) == 1
