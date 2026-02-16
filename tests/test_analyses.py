"""Tests for the structured analyses system.

Covers: analysis_parser, DB CRUD methods, CLI commands, and JSON round-trip.
"""

import json

import pytest

from chartfold.analysis_parser import parse_analysis_dir, parse_analysis_file
from chartfold.db import ChartfoldDB


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def analysis_db(tmp_path):
    """Fresh database with schema initialized."""
    db = ChartfoldDB(str(tmp_path / "test.db"))
    db.init_schema()
    yield db
    db.close()


@pytest.fixture
def sample_md_with_frontmatter(tmp_path):
    """Create a sample analysis file with YAML frontmatter."""
    content = """\
---
title: Cancer Timeline Analysis
category: oncology
summary: Timeline of diagnosis and treatment
tags: [cancer, CEA, surgery]
source: claude
related_tables: [lab_results, pathology_reports]
date_range:
  start: "2024-06-15"
  end: "2025-01-30"
---

# Cancer Timeline

## Diagnosis Phase
The patient was diagnosed in 2024.

## Treatment Phase
Surgery followed by chemotherapy.
"""
    path = tmp_path / "cancer-timeline.md"
    path.write_text(content)
    return path


@pytest.fixture
def sample_md_without_frontmatter(tmp_path):
    """Create a sample analysis file without YAML frontmatter."""
    content = """\
# Deep Clinical Analysis

## Overview
A comprehensive review of the patient's clinical data.

## Findings
Multiple significant findings were identified.
"""
    path = tmp_path / "deep-analysis.md"
    path.write_text(content)
    return path


@pytest.fixture
def sample_md_no_heading(tmp_path):
    """Create a sample file with no heading (title from filename)."""
    content = "Just some plain text analysis without any headings.\n"
    path = tmp_path / "medication-review.md"
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# Parser Tests
# ---------------------------------------------------------------------------


class TestAnalysisParser:
    def test_parse_with_frontmatter(self, sample_md_with_frontmatter):
        result = parse_analysis_file(sample_md_with_frontmatter)

        assert result["slug"] == "cancer-timeline"
        assert result["title"] == "Cancer Timeline Analysis"
        assert result["category"] == "oncology"
        assert result["summary"] == "Timeline of diagnosis and treatment"
        assert result["tags"] == ["cancer", "CEA", "surgery"]
        assert result["source"] == "claude"
        assert "# Cancer Timeline" in result["content"]
        assert "---" not in result["content"]  # frontmatter stripped

        # Remaining YAML fields stored as JSON
        fm = json.loads(result["frontmatter_json"])
        assert fm["related_tables"] == ["lab_results", "pathology_reports"]
        assert fm["date_range"]["start"] == "2024-06-15"

    def test_parse_without_frontmatter(self, sample_md_without_frontmatter):
        result = parse_analysis_file(sample_md_without_frontmatter)

        assert result["slug"] == "deep-analysis"
        assert result["title"] == "Deep Clinical Analysis"  # from first heading
        assert result["category"] is None
        assert result["summary"] is None
        assert result["tags"] == []
        assert result["source"] == "user"
        assert result["frontmatter_json"] is None
        assert "## Findings" in result["content"]

    def test_parse_no_heading_uses_filename(self, sample_md_no_heading):
        result = parse_analysis_file(sample_md_no_heading)

        assert result["slug"] == "medication-review"
        assert result["title"] == "Medication Review"  # derived from filename
        assert result["content"].startswith("Just some plain text")

    def test_parse_directory(self, tmp_path, sample_md_with_frontmatter, sample_md_without_frontmatter):
        results = parse_analysis_dir(tmp_path)

        assert len(results) == 2
        slugs = [r["slug"] for r in results]
        assert "cancer-timeline" in slugs
        assert "deep-analysis" in slugs

    def test_parse_directory_skips_readme(self, tmp_path):
        """README.md should be skipped."""
        (tmp_path / "README.md").write_text("# README\nThis is not an analysis.\n")
        (tmp_path / "actual-analysis.md").write_text("# Real Analysis\nContent here.\n")

        results = parse_analysis_dir(tmp_path)
        assert len(results) == 1
        assert results[0]["slug"] == "actual-analysis"

    def test_parse_empty_directory(self, tmp_path):
        results = parse_analysis_dir(tmp_path)
        assert results == []

    def test_parse_nonexistent_directory(self):
        with pytest.raises(FileNotFoundError):
            parse_analysis_dir("/nonexistent/path")

    def test_frontmatter_tags_as_string(self, tmp_path):
        """Tags specified as a single string should be wrapped in a list."""
        path = tmp_path / "single-tag.md"
        path.write_text("---\ntags: single-tag\n---\n\n# Title\nBody.\n")

        result = parse_analysis_file(path)
        assert result["tags"] == ["single-tag"]

    def test_unclosed_frontmatter(self, tmp_path):
        """Unclosed frontmatter (no closing ---) should be treated as plain content."""
        path = tmp_path / "unclosed.md"
        path.write_text("---\ntitle: Never Closed\n\n# Actual Content\nBody here.\n")

        result = parse_analysis_file(path)
        assert result["slug"] == "unclosed"
        # No closing ---, so entire text is content, title from heading
        assert result["title"] == "Actual Content"
        assert result["frontmatter_json"] is None

    def test_non_dict_yaml_frontmatter(self, tmp_path):
        """Non-dict YAML (e.g., a list) should be treated as empty frontmatter."""
        path = tmp_path / "list-yaml.md"
        path.write_text("---\n- item1\n- item2\n---\n\n# Title\nBody.\n")

        result = parse_analysis_file(path)
        assert result["slug"] == "list-yaml"
        assert result["title"] == "Title"
        assert result["category"] is None
        assert result["tags"] == []
        assert result["frontmatter_json"] is None

    def test_empty_content_after_frontmatter(self, tmp_path):
        """Frontmatter with no body should parse correctly."""
        path = tmp_path / "empty-body.md"
        path.write_text("---\ntitle: Just Metadata\ncategory: test\n---\n")

        result = parse_analysis_file(path)
        assert result["title"] == "Just Metadata"
        assert result["category"] == "test"
        assert result["content"] == ""


# ---------------------------------------------------------------------------
# DB CRUD Tests
# ---------------------------------------------------------------------------


class TestAnalysisCRUD:
    def test_save_and_get(self, analysis_db):
        aid = analysis_db.save_analysis(
            slug="cancer-timeline",
            title="Cancer Timeline",
            content="# Cancer Timeline\nBody here.",
            frontmatter_json='{"related_tables": ["lab_results"]}',
            category="oncology",
            summary="Timeline summary",
            tags=["cancer", "CEA"],
            source="claude",
        )
        assert aid > 0

        result = analysis_db.get_analysis("cancer-timeline")
        assert result is not None
        assert result["title"] == "Cancer Timeline"
        assert result["category"] == "oncology"
        assert result["summary"] == "Timeline summary"
        assert result["source"] == "claude"
        assert result["tags"] == ["CEA", "cancer"]  # sorted

        fm = json.loads(result["frontmatter"])
        assert fm["related_tables"] == ["lab_results"]

    def test_get_by_id(self, analysis_db):
        aid = analysis_db.save_analysis(
            slug="test-analysis",
            title="Test",
            content="Body",
        )
        result = analysis_db.get_analysis(aid)
        assert result is not None
        assert result["slug"] == "test-analysis"

    def test_get_nonexistent(self, analysis_db):
        assert analysis_db.get_analysis("nonexistent") is None
        assert analysis_db.get_analysis(9999) is None

    def test_upsert_updates_existing(self, analysis_db):
        aid1 = analysis_db.save_analysis(
            slug="cancer-timeline",
            title="Original",
            content="Original body",
            tags=["cancer"],
        )
        aid2 = analysis_db.save_analysis(
            slug="cancer-timeline",
            title="Updated",
            content="Updated body",
            tags=["cancer", "surgery"],
        )
        assert aid1 == aid2

        result = analysis_db.get_analysis("cancer-timeline")
        assert result["title"] == "Updated"
        assert result["content"] == "Updated body"
        assert result["tags"] == ["cancer", "surgery"]

    def test_upsert_preserves_created_at(self, analysis_db):
        analysis_db.save_analysis(slug="test", title="V1", content="Body1")
        v1 = analysis_db.get_analysis("test")

        analysis_db.save_analysis(slug="test", title="V2", content="Body2")
        v2 = analysis_db.get_analysis("test")

        assert v1["created_at"] == v2["created_at"]
        assert v2["updated_at"] >= v1["updated_at"]

    def test_search_by_query(self, analysis_db):
        analysis_db.save_analysis(slug="a1", title="Cancer Report", content="CEA levels")
        analysis_db.save_analysis(slug="a2", title="Medication Review", content="Aspirin details")

        results = analysis_db.search_analyses(query="CEA")
        assert len(results) == 1
        assert results[0]["slug"] == "a1"

    def test_search_by_tag(self, analysis_db):
        analysis_db.save_analysis(slug="a1", title="A1", content="B1", tags=["cancer"])
        analysis_db.save_analysis(slug="a2", title="A2", content="B2", tags=["meds"])

        results = analysis_db.search_analyses(tag="cancer")
        assert len(results) == 1
        assert results[0]["slug"] == "a1"

    def test_search_by_category(self, analysis_db):
        analysis_db.save_analysis(slug="a1", title="A1", content="B1", category="oncology")
        analysis_db.save_analysis(slug="a2", title="A2", content="B2", category="cardiology")

        results = analysis_db.search_analyses(category="oncology")
        assert len(results) == 1
        assert results[0]["slug"] == "a1"

    def test_search_combined_filters(self, analysis_db):
        analysis_db.save_analysis(
            slug="a1", title="A1", content="B1", category="oncology", tags=["cancer"]
        )
        analysis_db.save_analysis(
            slug="a2", title="A2", content="B2", category="oncology", tags=["meds"]
        )

        results = analysis_db.search_analyses(category="oncology", tag="cancer")
        assert len(results) == 1
        assert results[0]["slug"] == "a1"

    def test_list_analyses(self, analysis_db):
        analysis_db.save_analysis(slug="a1", title="A1", content="B1")
        analysis_db.save_analysis(slug="a2", title="A2", content="B2")

        results = analysis_db.list_analyses()
        assert len(results) == 2

    def test_delete_by_slug(self, analysis_db):
        analysis_db.save_analysis(slug="to-delete", title="Delete Me", content="Body")
        assert analysis_db.delete_analysis("to-delete") is True
        assert analysis_db.get_analysis("to-delete") is None

    def test_delete_by_id(self, analysis_db):
        aid = analysis_db.save_analysis(slug="to-delete", title="Delete Me", content="Body")
        assert analysis_db.delete_analysis(aid) is True
        assert analysis_db.get_analysis(aid) is None

    def test_delete_nonexistent(self, analysis_db):
        assert analysis_db.delete_analysis("nonexistent") is False

    def test_delete_cascades_tags(self, analysis_db):
        aid = analysis_db.save_analysis(
            slug="tagged", title="Tagged", content="Body", tags=["a", "b"]
        )
        analysis_db.delete_analysis(aid)

        # Tags should be gone due to CASCADE
        tags = analysis_db.query(
            "SELECT * FROM analysis_tags WHERE analysis_id = ?", (aid,)
        )
        assert tags == []

    def test_empty_tags_stripped(self, analysis_db):
        analysis_db.save_analysis(
            slug="test", title="Test", content="Body", tags=["valid", "", "  ", "also-valid"]
        )
        result = analysis_db.get_analysis("test")
        assert result["tags"] == ["also-valid", "valid"]


# ---------------------------------------------------------------------------
# CLI Tests
# ---------------------------------------------------------------------------


class TestAnalysesCLI:
    def test_load_analyses(self, tmp_path, analysis_db):
        """Test the CLI load analyses command logic."""
        md_dir = tmp_path / "analyses"
        md_dir.mkdir()
        (md_dir / "test-one.md").write_text(
            "---\ntitle: Test One\ncategory: testing\ntags: [test]\n---\n\nBody one.\n"
        )
        (md_dir / "test-two.md").write_text("# Test Two\n\nBody two.\n")

        # Simulate what _load_analyses does
        from chartfold.analysis_parser import parse_analysis_dir

        analyses = parse_analysis_dir(md_dir)
        for a in analyses:
            analysis_db.save_analysis(**a)

        results = analysis_db.list_analyses()
        assert len(results) == 2
        slugs = {r["slug"] for r in results}
        assert slugs == {"test-one", "test-two"}

    def test_cli_analyses_list(self, analysis_db, capsys):
        """Test analyses list output formatting."""
        analysis_db.save_analysis(
            slug="cancer-timeline",
            title="Cancer Timeline",
            content="Body",
            category="oncology",
            tags=["cancer"],
        )

        from chartfold.cli import _handle_analyses_list

        _handle_analyses_list(analysis_db)
        output = capsys.readouterr().out
        assert "cancer-timeline" in output
        assert "Cancer Timeline" in output
        assert "oncology" in output

    def test_cli_analyses_show(self, analysis_db, capsys):
        """Test analyses show output."""
        analysis_db.save_analysis(
            slug="test",
            title="Test Analysis",
            content="Full body content here.",
            category="testing",
            tags=["test"],
            source="claude",
        )

        from chartfold.cli import _handle_analyses_show

        _handle_analyses_show(analysis_db, "test")
        output = capsys.readouterr().out
        assert "Test Analysis" in output
        assert "testing" in output
        assert "Full body content here." in output
        assert "claude" in output


# ---------------------------------------------------------------------------
# JSON Round-Trip Tests
# ---------------------------------------------------------------------------


class TestAnalysesRoundTrip:
    def test_analyses_in_export(self, analysis_db, tmp_path):
        """Analyses should auto-appear in JSON export via auto-discovery."""
        analysis_db.save_analysis(
            slug="test-analysis",
            title="Test",
            content="Body",
            tags=["tag1"],
        )

        from chartfold.export_full import export_full_json

        output_path = str(tmp_path / "export.json")
        export_full_json(analysis_db, output_path)

        with open(output_path) as f:
            data = json.load(f)

        assert "analyses" in data["tables"]
        assert "analysis_tags" in data["tables"]
        assert len(data["tables"]["analyses"]) == 1
        assert data["tables"]["analyses"][0]["slug"] == "test-analysis"
        assert len(data["tables"]["analysis_tags"]) == 1

    def test_analyses_round_trip(self, analysis_db, tmp_path):
        """Analyses should survive export -> import round-trip with FK remapping."""
        analysis_db.save_analysis(
            slug="cancer",
            title="Cancer Timeline",
            content="Body",
            category="oncology",
            tags=["cancer", "CEA"],
            source="claude",
        )

        from chartfold.export_full import export_full_json, import_json

        json_path = str(tmp_path / "export.json")
        import_db_path = str(tmp_path / "imported.db")

        export_full_json(analysis_db, json_path)

        result = import_json(json_path, import_db_path)
        assert result["success"] is True
        assert result["counts"]["analyses"] == 1
        assert result["counts"]["analysis_tags"] == 2

        with ChartfoldDB(import_db_path) as imported_db:
            imported_db.init_schema()
            analysis = imported_db.get_analysis("cancer")
            assert analysis is not None
            assert analysis["title"] == "Cancer Timeline"
            assert analysis["category"] == "oncology"
            assert sorted(analysis["tags"]) == ["CEA", "cancer"]

            # Verify FK integrity (analysis_tags point to valid analysis)
            tags = imported_db.query(
                "SELECT at.tag FROM analysis_tags at "
                "JOIN analyses a ON at.analysis_id = a.id "
                "WHERE a.slug = 'cancer' ORDER BY at.tag"
            )
            assert [t["tag"] for t in tags] == ["CEA", "cancer"]

    def test_analyses_in_summary(self, analysis_db):
        """Analyses should appear in auto-discovered summary."""
        analysis_db.save_analysis(slug="test", title="Test", content="Body")
        summary = analysis_db.summary()
        assert "analyses" in summary
        assert summary["analyses"] == 1
        assert "analysis_tags" in summary
