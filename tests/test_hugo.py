"""Tests for chartfold.hugo.generate module."""

import json

import pytest

from chartfold.db import ChartfoldDB
from chartfold.hugo.generate import (
    _format_report_text,
    _make_linked_table,
    _make_table,
    _write_json,
    _write_page,
    generate_site,
)
from chartfold.models import ClinicalNote, EncounterRecord, UnifiedRecords


class TestMakeTable:
    def test_basic_table(self):
        table = _make_table(["Name", "Value"], [["CEA", "5.8"], ["WBC", "6.2"]])
        assert "| Name | Value |" in table
        assert "| CEA | 5.8 |" in table
        assert "| WBC | 6.2 |" in table

    def test_separator_row(self):
        table = _make_table(["A", "B"], [["1", "2"]])
        lines = table.split("\n")
        assert lines[1].startswith("| ---")

    def test_empty_rows(self):
        table = _make_table(["A"], [])
        assert "No data available" in table

    def test_pipe_escaping(self):
        table = _make_table(["Note"], [["has | pipe"]])
        assert "has \\| pipe" in table

    def test_none_handling(self):
        table = _make_table(["A", "B"], [["val", None]])
        assert "| val |  |" in table


class TestMakeLinkedTable:
    def test_basic_linked_table(self):
        table = _make_linked_table(
            ["Date", "Name"],
            [[("2025-01-01", "/items/1/"), "Item A"],
             [("2025-02-01", "/items/2/"), "Item B"]],
            link_col=0,
        )
        assert "[2025-01-01](/items/1/)" in table
        assert "[2025-02-01](/items/2/)" in table
        assert "| Item A |" in table

    def test_empty_rows(self):
        table = _make_linked_table(["A"], [])
        assert "No data available" in table

    def test_non_default_link_col(self):
        table = _make_linked_table(
            ["ID", "Link"],
            [["1", ("click", "/go/")]],
            link_col=1,
        )
        assert "| 1 | [click](/go/) |" in table

    def test_pipe_escaping_in_link(self):
        table = _make_linked_table(
            ["Link", "Other"],
            [[("has | pipe", "/url/"), "ok"]],
            link_col=0,
        )
        assert "[has \\| pipe](/url/)" in table

    def test_plain_string_in_link_col(self):
        """Non-tuple value in link_col is rendered as plain text."""
        table = _make_linked_table(
            ["Date", "Name"],
            [["plain", "Item"]],
            link_col=0,
        )
        assert "| plain | Item |" in table


class TestWritePage:
    def test_writes_frontmatter(self, tmp_path):
        filepath = tmp_path / "test.md"
        _write_page(filepath, "My Title", "Body text")
        content = filepath.read_text()
        assert 'title: "My Title"' in content
        assert "---" in content
        assert "Body text" in content

    def test_creates_parent_dirs(self, tmp_path):
        filepath = tmp_path / "a" / "b" / "test.md"
        _write_page(filepath, "Deep", "Content")
        assert filepath.exists()

    def test_extra_frontmatter(self, tmp_path):
        filepath = tmp_path / "test.md"
        _write_page(filepath, "Title", "Body", extra_frontmatter='weight: 1\n')
        content = filepath.read_text()
        assert "weight: 1" in content


class TestWriteJson:
    def test_writes_json(self, tmp_path):
        filepath = tmp_path / "data.json"
        _write_json(filepath, {"key": "value", "num": 42})
        loaded = json.loads(filepath.read_text())
        assert loaded["key"] == "value"
        assert loaded["num"] == 42

    def test_handles_dates(self, tmp_path):
        from datetime import date
        filepath = tmp_path / "data.json"
        _write_json(filepath, {"d": date(2025, 1, 15)})
        loaded = json.loads(filepath.read_text())
        assert loaded["d"] == "2025-01-15"

    def test_creates_parent_dirs(self, tmp_path):
        filepath = tmp_path / "sub" / "dir" / "data.json"
        _write_json(filepath, [1, 2, 3])
        assert filepath.exists()


class TestGenerateSite:
    def test_generates_full_site(self, loaded_db, tmp_path):
        """End-to-end test: generate Hugo site from a loaded database."""
        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir))

        # Content directory exists
        content = hugo_dir / "content"
        assert content.exists()

        # Dashboard page
        index = content / "_index.md"
        assert index.exists()
        assert "Dashboard" in index.read_text()

        # Timeline page
        timeline = content / "timeline.md"
        assert timeline.exists()

        # Labs section
        labs_index = content / "labs" / "_index.md"
        assert labs_index.exists()

        # Encounters (now a section with _index.md)
        encounters = content / "encounters" / "_index.md"
        assert encounters.exists()

        # Medications
        medications = content / "medications.md"
        assert medications.exists()

        # Conditions
        conditions = content / "conditions.md"
        assert conditions.exists()

    def test_generates_data_files(self, loaded_db, tmp_path):
        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir))

        data = hugo_dir / "data"
        assert data.exists()

        # Timeline JSON
        timeline_json = data / "timeline.json"
        assert timeline_json.exists()
        events = json.loads(timeline_json.read_text())
        assert isinstance(events, list)

    def test_copies_scaffolding(self, loaded_db, tmp_path):
        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir))

        # CSS should be copied
        css = hugo_dir / "static" / "css" / "style.css"
        assert css.exists()

        # Hugo config
        config = hugo_dir / "hugo.toml"
        assert config.exists()

        # Layouts
        baseof = hugo_dir / "layouts" / "_default" / "baseof.html"
        assert baseof.exists()

    def test_dashboard_includes_medications(self, loaded_db, tmp_path):
        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir))
        index = (hugo_dir / "content" / "_index.md").read_text()
        assert "Active Medications" in index

    def test_dashboard_includes_conditions(self, loaded_db, tmp_path):
        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir))
        index = (hugo_dir / "content" / "_index.md").read_text()
        assert "Active Conditions" in index

    def test_dashboard_includes_encounters(self, loaded_db, tmp_path):
        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir))
        index = (hugo_dir / "content" / "_index.md").read_text()
        assert "Recent Encounters" in index

    def test_timeline_includes_labs(self, loaded_db, tmp_path):
        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir))
        timeline_json = json.loads((hugo_dir / "data" / "timeline.json").read_text())
        event_types = {e["type"] for e in timeline_json}
        assert "Labs" in event_types

    def test_encounter_detail_pages(self, loaded_db, tmp_path):
        """Each encounter gets a detail page."""
        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir))
        enc_dir = hugo_dir / "content" / "encounters"
        assert enc_dir.is_dir()
        # Index page exists
        assert (enc_dir / "_index.md").exists()
        # At least one detail page
        detail_pages = list(enc_dir.glob("[0-9]*.md"))
        assert len(detail_pages) >= 1
        # Detail page contains metadata
        detail = detail_pages[0].read_text()
        assert "Date:" in detail or "Type:" in detail

    def test_encounter_index_has_links(self, loaded_db, tmp_path):
        """Encounter index table has clickable links."""
        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir))
        index = (hugo_dir / "content" / "encounters" / "_index.md").read_text()
        assert "/encounters/" in index
        assert "[" in index  # markdown link

    def test_pathology_detail_pages(self, surgical_db, tmp_path):
        """Pathology reports get detail pages with diagnosis and structured fields."""
        hugo_dir = tmp_path / "site"
        generate_site(surgical_db.db_path, str(hugo_dir))
        path_dir = hugo_dir / "content" / "pathology"
        assert path_dir.is_dir()
        assert (path_dir / "_index.md").exists()
        detail_pages = list(path_dir.glob("[0-9]*.md"))
        assert len(detail_pages) >= 2
        # Check one has diagnosis section
        detail = detail_pages[0].read_text()
        assert "Diagnosis" in detail

    def test_pathology_index_links(self, surgical_db, tmp_path):
        """Pathology index table links to detail pages."""
        hugo_dir = tmp_path / "site"
        generate_site(surgical_db.db_path, str(hugo_dir))
        index = (hugo_dir / "content" / "pathology" / "_index.md").read_text()
        assert "/pathology/" in index

    def test_imaging_detail_pages(self, surgical_db, tmp_path):
        """Imaging reports get detail pages with impression."""
        hugo_dir = tmp_path / "site"
        generate_site(surgical_db.db_path, str(hugo_dir))
        img_dir = hugo_dir / "content" / "imaging"
        assert img_dir.is_dir()
        assert (img_dir / "_index.md").exists()
        detail_pages = list(img_dir.glob("[0-9]*.md"))
        assert len(detail_pages) >= 2

    def test_imaging_index_links(self, surgical_db, tmp_path):
        """Imaging index table links to detail pages."""
        hugo_dir = tmp_path / "site"
        generate_site(surgical_db.db_path, str(hugo_dir))
        index = (hugo_dir / "content" / "imaging" / "_index.md").read_text()
        assert "/imaging/" in index

    def test_clinical_notes_section(self, tmp_path):
        """Clinical notes section generates index and detail pages."""
        from chartfold.models import ClinicalNote
        db = ChartfoldDB(str(tmp_path / "notes.db"))
        db.init_schema()
        records = UnifiedRecords(
            source="test",
            clinical_notes=[
                ClinicalNote(source="test", note_type="Progress",
                             author="Dr. A", note_date="2025-01-15",
                             content="Patient doing well."),
                ClinicalNote(source="test", note_type="H&P",
                             author="Dr. B", note_date="2025-01-20",
                             content="Comprehensive exam performed."),
            ],
        )
        db.load_source(records)

        hugo_dir = tmp_path / "site"
        generate_site(db.db_path, str(hugo_dir))
        db.close()

        notes_dir = hugo_dir / "content" / "notes"
        assert notes_dir.is_dir()
        assert (notes_dir / "_index.md").exists()
        detail_pages = list(notes_dir.glob("[0-9]*.md"))
        assert len(detail_pages) == 2
        # Check index has links
        index = (notes_dir / "_index.md").read_text()
        assert "/notes/" in index
        # Check detail page has content
        detail = detail_pages[0].read_text()
        assert "Author:" in detail or "Type:" in detail

    def test_clinical_notes_empty(self, loaded_db, tmp_path):
        """Clinical notes section shows 'No data' when empty."""
        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir))
        notes_index = hugo_dir / "content" / "notes" / "_index.md"
        assert notes_index.exists()
        assert "No data available" in notes_index.read_text()

    def test_site_with_config(self, loaded_db, tmp_path):
        """Test that generate_site respects a config file."""
        hugo_dir = tmp_path / "site"
        config_path = tmp_path / "test.toml"
        config_path.write_text("""
[key_tests]
tests = ["CEA"]
""")
        generate_site(loaded_db.db_path, str(hugo_dir), config_path=str(config_path))
        # CEA should have a trend page
        cea = hugo_dir / "content" / "labs" / "cea.md"
        assert cea.exists()

    def test_labs_index_links_to_trend_pages(self, loaded_db, tmp_path):
        """Labs index links to configured trend chart pages."""
        hugo_dir = tmp_path / "site"
        config_path = tmp_path / "test.toml"
        config_path.write_text('[key_tests]\ntests = ["CEA"]\n')
        generate_site(loaded_db.db_path, str(hugo_dir), config_path=str(config_path))
        index = (hugo_dir / "content" / "labs" / "_index.md").read_text()
        assert "Trend Charts" in index
        assert "[CEA](/labs/cea/)" in index

    def test_timeline_has_links(self, loaded_db, tmp_path):
        """Timeline table has clickable links to detail pages."""
        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir))
        timeline = (hugo_dir / "content" / "timeline.md").read_text()
        # Should contain markdown links
        assert "[" in timeline
        assert "](/encounters/" in timeline or "](/labs/" in timeline

    def test_timeline_events_have_link_field(self, loaded_db, tmp_path):
        """Timeline JSON events include a link field."""
        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir))
        events = json.loads((hugo_dir / "data" / "timeline.json").read_text())
        for e in events:
            assert "link" in e

    def test_surgical_detail_pages(self, surgical_db, tmp_path):
        """Surgical timeline generates detail pages for each procedure."""
        hugo_dir = tmp_path / "site"
        generate_site(surgical_db.db_path, str(hugo_dir))
        surg_dir = hugo_dir / "content" / "surgical"
        assert surg_dir.is_dir()
        assert (surg_dir / "_index.md").exists()
        detail_pages = list(surg_dir.glob("[0-9]*.md"))
        assert len(detail_pages) >= 2

    def test_surgical_detail_has_pathology(self, surgical_db, tmp_path):
        """Surgical detail pages include linked pathology information."""
        hugo_dir = tmp_path / "site"
        generate_site(surgical_db.db_path, str(hugo_dir))
        surg_dir = hugo_dir / "content" / "surgical"
        detail_pages = list(surg_dir.glob("[0-9]*.md"))
        # At least one page should have pathology
        found_pathology = False
        for page in detail_pages:
            text = page.read_text()
            if "Pathology" in text and "Diagnosis" in text:
                found_pathology = True
                break
        assert found_pathology

    def test_surgical_detail_has_imaging(self, surgical_db, tmp_path):
        """Surgical detail pages include related imaging when available."""
        hugo_dir = tmp_path / "site"
        generate_site(surgical_db.db_path, str(hugo_dir))
        surg_dir = hugo_dir / "content" / "surgical"
        detail_pages = list(surg_dir.glob("[0-9]*.md"))
        found_imaging = False
        for page in detail_pages:
            text = page.read_text()
            if "Related Imaging" in text:
                found_imaging = True
                break
        assert found_imaging

    def test_surgical_index_has_links(self, surgical_db, tmp_path):
        """Surgical index table links to detail pages."""
        hugo_dir = tmp_path / "site"
        generate_site(surgical_db.db_path, str(hugo_dir))
        index = (hugo_dir / "content" / "surgical" / "_index.md").read_text()
        assert "/surgical/" in index
        assert "[" in index

    def test_encounter_enrichment(self, tmp_path):
        """Encounter detail pages show related notes/labs from the same date."""
        db = ChartfoldDB(str(tmp_path / "enrich.db"))
        db.init_schema()
        records = UnifiedRecords(
            source="test",
            encounters=[
                EncounterRecord(
                    source="test", encounter_date="2025-01-15",
                    encounter_type="Office Visit", facility="Test Clinic",
                    provider="Dr. A",
                ),
            ],
            clinical_notes=[
                ClinicalNote(
                    source="test", note_type="Progress",
                    author="Dr. A", note_date="2025-01-15",
                    content="Patient doing well after chemo.",
                ),
            ],
            lab_results=[
                _make_lab("CEA", "5.8", "2025-01-15"),
            ],
        )
        db.load_source(records)

        hugo_dir = tmp_path / "site"
        generate_site(db.db_path, str(hugo_dir))
        db.close()

        enc_dir = hugo_dir / "content" / "encounters"
        detail_pages = list(enc_dir.glob("[0-9]*.md"))
        assert len(detail_pages) == 1
        detail = detail_pages[0].read_text()
        assert "Related Records" in detail
        assert "Clinical Notes" in detail
        assert "Lab Results" in detail

    def test_encounter_enrichment_no_related(self, loaded_db, tmp_path):
        """Encounter detail pages work without related records on same date."""
        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir))
        enc_dir = hugo_dir / "content" / "encounters"
        detail_pages = list(enc_dir.glob("[0-9]*.md"))
        assert len(detail_pages) >= 1
        # All detail pages should still render without error
        for page in detail_pages:
            text = page.read_text()
            assert "Date:" in text or "Type:" in text


class TestFormatReportText:
    def test_empty_text(self):
        assert _format_report_text("") == ""
        assert _format_report_text(None) is None

    def test_section_markers_get_paragraph_breaks(self):
        text = "Some text Diagnosis: cancer found"
        result = _format_report_text(text)
        assert "\n\nDiagnosis:" in result

    def test_multiple_section_markers(self):
        text = "Specimen: liver Gross Description: 5cm segment History: colon cancer"
        result = _format_report_text(text)
        assert "\n\nSpecimen:" in result
        assert "\n\nGross Description:" in result
        assert "\n\nHistory:" in result

    def test_normalizes_multiple_spaces(self):
        text = "too    many   spaces   here"
        result = _format_report_text(text)
        assert "too many spaces here" in result

    def test_preserves_list_items(self):
        text = "Items:\n- first item\n- second item"
        result = _format_report_text(text)
        assert "  - first item" in result
        assert "  - second item" in result

    def test_strips_per_line_whitespace(self):
        text = "  line one  \n  line two  "
        result = _format_report_text(text)
        lines = result.split("\n")
        assert lines[0] == "line one"
        assert lines[1] == "line two"

    def test_does_not_duplicate_existing_breaks(self):
        text = "Header\n\nDiagnosis: cancer"
        result = _format_report_text(text)
        # Should not get triple newlines
        assert "\n\n\n" not in result


class TestLinkedSources:
    def test_linked_sources_copies_files(self, loaded_db, tmp_path):
        """--linked-sources copies asset files into static/sources/."""
        # Create a fake asset file on disk
        asset_dir = tmp_path / "assets"
        asset_dir.mkdir()
        pdf_file = asset_dir / "report.pdf"
        pdf_file.write_text("fake pdf content")

        # Insert an asset record
        loaded_db.conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, "
            "file_size_kb, title, encounter_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test_source", "pdf", str(pdf_file), "report.pdf", 10,
             "Test Report", "2025-01-15"),
        )
        loaded_db.conn.commit()

        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir), linked_sources=True)

        # Sources page should exist
        sources_page = hugo_dir / "content" / "sources.md"
        assert sources_page.exists()
        content = sources_page.read_text()
        assert "Source Documents" in content
        assert "Test Report" in content
        assert "pdf" in content

        # Static file should be copied
        static_sources = hugo_dir / "static" / "sources" / "test_source"
        assert static_sources.is_dir()
        copied_files = list(static_sources.glob("*.pdf"))
        assert len(copied_files) == 1
        assert "report.pdf" in copied_files[0].name

    def test_linked_sources_missing_file_skipped(self, loaded_db, tmp_path):
        """Assets with missing file_path are silently skipped."""
        loaded_db.conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, "
            "file_size_kb, title) VALUES (?, ?, ?, ?, ?, ?)",
            ("test_source", "pdf", "/nonexistent/path/report.pdf", "report.pdf",
             10, "Missing File"),
        )
        loaded_db.conn.commit()

        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir), linked_sources=True)

        sources_page = hugo_dir / "content" / "sources.md"
        assert sources_page.exists()
        # Should not contain the missing file entry
        content = sources_page.read_text()
        assert "Missing File" not in content or "No source assets" in content

    def test_linked_sources_placeholder_by_default(self, loaded_db, tmp_path):
        """Without --linked-sources, a placeholder sources page is generated."""
        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir))

        sources_page = hugo_dir / "content" / "sources.md"
        assert sources_page.exists()
        content = sources_page.read_text()
        assert "Source Documents" in content
        assert "--linked-sources" in content

    def test_linked_sources_empty_db(self, loaded_db, tmp_path):
        """With --linked-sources but no assets, shows 'No source assets'."""
        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir), linked_sources=True)

        sources_page = hugo_dir / "content" / "sources.md"
        assert sources_page.exists()
        assert "No source assets" in sources_page.read_text()

    def test_linked_sources_multiple_sources(self, loaded_db, tmp_path):
        """Assets from different sources go into separate subdirectories."""
        asset_dir = tmp_path / "assets"
        asset_dir.mkdir()
        f1 = asset_dir / "epic_doc.pdf"
        f1.write_text("epic content")
        f2 = asset_dir / "meditech_doc.pdf"
        f2.write_text("meditech content")

        loaded_db.conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, "
            "file_size_kb) VALUES (?, ?, ?, ?, ?)",
            ("epic", "pdf", str(f1), "epic_doc.pdf", 5),
        )
        loaded_db.conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, "
            "file_size_kb) VALUES (?, ?, ?, ?, ?)",
            ("meditech", "pdf", str(f2), "meditech_doc.pdf", 8),
        )
        loaded_db.conn.commit()

        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir), linked_sources=True)

        # Both source subdirectories should exist
        assert (hugo_dir / "static" / "sources" / "epic").is_dir()
        assert (hugo_dir / "static" / "sources" / "meditech").is_dir()


class TestAssetLookup:
    def test_build_asset_lookup_by_ref(self, loaded_db, tmp_path):
        """Assets with ref_table/ref_id appear in by_ref lookup."""
        loaded_db.conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, "
            "file_size_kb, title, ref_table, ref_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("test_source", "pdf", "/tmp/report.pdf", "report.pdf",
             10, "Lab Report", "lab_results", 1),
        )
        loaded_db.conn.commit()

        from chartfold.hugo.generate import _build_asset_lookup
        lookup = _build_asset_lookup(loaded_db)

        assert ("lab_results", 1) in lookup["by_ref"]
        assets = lookup["by_ref"][("lab_results", 1)]
        assert len(assets) == 1
        assert assets[0]["file_name"] == "report.pdf"

    def test_build_asset_lookup_by_date_source(self, loaded_db, tmp_path):
        """Assets with encounter_date+source appear in by_date_source lookup."""
        loaded_db.conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, "
            "file_size_kb, title, encounter_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test_source", "pdf", "/tmp/visit.pdf", "visit.pdf",
             20, "Visit Doc", "2025-01-15"),
        )
        loaded_db.conn.commit()

        from chartfold.hugo.generate import _build_asset_lookup
        lookup = _build_asset_lookup(loaded_db)

        assert ("2025-01-15", "test_source") in lookup["by_date_source"]

    def test_build_asset_lookup_empty_db(self, loaded_db):
        """Empty source_assets returns empty lookups."""
        from chartfold.hugo.generate import _build_asset_lookup
        lookup = _build_asset_lookup(loaded_db)

        assert lookup["by_ref"] == {}
        assert lookup["by_date_source"] == {}
        assert lookup["by_date"] == {}
        assert lookup["all"] == []


def _make_lab(name, value, date):
    """Helper to create a LabResult for testing."""
    from chartfold.models import LabResult
    return LabResult(
        source="test", test_name=name, value=value,
        unit="ng/mL", result_date=date,
    )
