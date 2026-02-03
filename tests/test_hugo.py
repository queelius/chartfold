"""Tests for chartfold.hugo.generate module."""

import json

import pytest

from chartfold.hugo.generate import _make_table, _write_page, _write_json, generate_site


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

        # Encounters
        encounters = content / "encounters.md"
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
