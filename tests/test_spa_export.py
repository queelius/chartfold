"""Tests for the SPA export module."""

from __future__ import annotations

import base64
import gzip
import json
import re

import pytest

from chartfold.db import ChartfoldDB
from chartfold.spa.export import (
    _load_analysis_json,
    _load_config_json,
    _load_images_json,
    export_spa,
)


@pytest.fixture
def spa_db(tmp_path):
    """Create a minimal DB with some test data."""
    db_path = tmp_path / "test.db"
    db = ChartfoldDB(str(db_path))
    db.init_schema()
    db.conn.execute(
        "INSERT INTO lab_results (source, test_name, value, result_date) VALUES (?, ?, ?, ?)",
        ("test_source", "Creatinine", "1.2", "2025-01-15"),
    )
    db.conn.commit()
    db.close()
    return str(db_path)


@pytest.fixture
def spa_output(tmp_path):
    """Return a path for the SPA HTML output."""
    return str(tmp_path / "output" / "chartfold.html")


@pytest.fixture
def exported_html(spa_db, spa_output):
    """Export the SPA and return the HTML content."""
    export_spa(spa_db, spa_output)
    with open(spa_output, encoding="utf-8") as f:
        return f.read()


# --- Core export tests ---


class TestSpaExport:
    """Tests for the main export_spa function."""

    def test_generates_html_file(self, spa_db, spa_output):
        """export_spa produces an HTML file with DOCTYPE and closing html tag."""
        result = export_spa(spa_db, spa_output)
        assert result == spa_output
        with open(spa_output, encoding="utf-8") as f:
            html = f.read()
        assert html.startswith("<!DOCTYPE html>")
        assert html.rstrip().endswith("</html>")

    def test_contains_sql_wasm_js(self, exported_html):
        """HTML contains the sql.js loader (initSqlJs function)."""
        assert "initSqlJs" in exported_html

    def test_contains_embedded_wasm(self, exported_html):
        """HTML contains a script tag with the embedded WASM binary."""
        assert 'id="sqljs-wasm"' in exported_html

    def test_contains_embedded_db(self, exported_html):
        """HTML contains a script tag with the embedded database."""
        assert 'id="chartfold-db"' in exported_html

    def test_embedded_db_is_decodable(self, exported_html):
        """The embedded database can be decoded, decompressed, and is valid SQLite."""
        # Extract the base64 content from the chartfold-db script tag
        match = re.search(
            r'<script id="chartfold-db" type="application/gzip\+base64">(.*?)</script>',
            exported_html,
            re.DOTALL,
        )
        assert match is not None, "Could not find chartfold-db script tag"

        db_b64 = match.group(1).strip()
        db_compressed = base64.b64decode(db_b64)
        db_bytes = gzip.decompress(db_compressed)

        # SQLite files start with "SQLite format 3\0"
        assert db_bytes[:16] == b"SQLite format 3\x00"

    def test_contains_app_js(self, exported_html):
        """HTML contains the application JavaScript."""
        assert 'id="app-js"' in exported_html

    def test_contains_app_css(self, exported_html):
        """HTML contains a style tag with CSS."""
        assert "<style>" in exported_html

    def test_contains_loading_div(self, exported_html):
        """HTML contains the loading indicator."""
        assert 'id="loading"' in exported_html
        assert "Loading database..." in exported_html

    def test_contains_config_script(self, exported_html):
        """HTML contains the config script tag."""
        assert 'id="chartfold-config"' in exported_html

    def test_contains_analysis_script(self, exported_html):
        """HTML contains the analysis script tag."""
        assert 'id="chartfold-analysis"' in exported_html

    def test_contains_images_script(self, exported_html):
        """HTML contains the images script tag."""
        assert 'id="chartfold-images"' in exported_html

    def test_contains_db_js_code(self, exported_html):
        """HTML contains the DB module code from db.js."""
        assert "DB.init" in exported_html or "const DB" in exported_html

    def test_output_dir_created(self, spa_db, tmp_path):
        """Export creates parent directories if they don't exist."""
        out_path = str(tmp_path / "a" / "b" / "c" / "out.html")
        export_spa(spa_db, out_path)
        assert (tmp_path / "a" / "b" / "c" / "out.html").is_file()

    def test_default_empty_config(self, exported_html):
        """Without a config path, the config JSON is empty object."""
        match = re.search(
            r'<script id="chartfold-config" type="application/json">(.*?)</script>',
            exported_html,
            re.DOTALL,
        )
        assert match is not None
        assert json.loads(match.group(1)) == {}

    def test_default_empty_analysis(self, exported_html):
        """Without an analysis dir, the analysis JSON is empty array."""
        match = re.search(
            r'<script id="chartfold-analysis" type="application/json">(.*?)</script>',
            exported_html,
            re.DOTALL,
        )
        assert match is not None
        assert json.loads(match.group(1)) == []

    def test_default_empty_images(self, exported_html):
        """Without embed_images, the images JSON is empty object."""
        match = re.search(
            r'<script id="chartfold-images" type="application/json">(.*?)</script>',
            exported_html,
            re.DOTALL,
        )
        assert match is not None
        assert json.loads(match.group(1)) == {}


# --- Config loading tests ---


class TestLoadConfigJson:
    """Tests for _load_config_json helper."""

    def test_missing_file(self):
        """Returns '{}' for non-existent path."""
        assert _load_config_json("/nonexistent/config.toml") == "{}"

    def test_empty_path(self):
        """Returns '{}' for empty string."""
        assert _load_config_json("") == "{}"

    def test_valid_toml(self, tmp_path):
        """Loads a TOML file and returns JSON."""
        toml_path = tmp_path / "config.toml"
        toml_path.write_text('[dashboard]\ntitle = "My Health"\n')
        result = _load_config_json(str(toml_path))
        data = json.loads(result)
        assert data["dashboard"]["title"] == "My Health"

    def test_export_with_config(self, spa_db, tmp_path):
        """Export with a config file embeds the config JSON."""
        toml_path = tmp_path / "config.toml"
        toml_path.write_text('[dashboard]\ntitle = "Test"\n')
        out_path = str(tmp_path / "out.html")
        export_spa(spa_db, out_path, config_path=str(toml_path))
        with open(out_path, encoding="utf-8") as f:
            html = f.read()
        match = re.search(
            r'<script id="chartfold-config" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        assert match is not None
        data = json.loads(match.group(1))
        assert data["dashboard"]["title"] == "Test"


# --- Analysis loading tests ---


class TestLoadAnalysisJson:
    """Tests for _load_analysis_json helper."""

    def test_missing_dir(self):
        """Returns '[]' for non-existent directory."""
        assert _load_analysis_json("/nonexistent/dir") == "[]"

    def test_empty_path(self):
        """Returns '[]' for empty string."""
        assert _load_analysis_json("") == "[]"

    def test_empty_dir(self, tmp_path):
        """Returns '[]' for empty directory."""
        result = _load_analysis_json(str(tmp_path))
        assert json.loads(result) == []

    def test_loads_markdown_files(self, tmp_path):
        """Loads .md files with title derived from filename."""
        (tmp_path / "cea-trends.md").write_text("CEA is trending down.")
        (tmp_path / "medication_review.md").write_text("Meds are stable.")
        result = json.loads(_load_analysis_json(str(tmp_path)))
        assert len(result) == 2
        # Sorted by name
        assert result[0]["title"] == "Cea Trends"
        assert result[0]["body"] == "CEA is trending down."
        assert result[0]["filename"] == "cea-trends.md"
        assert result[1]["title"] == "Medication Review"

    def test_strips_frontmatter(self, tmp_path):
        """YAML frontmatter delimited by --- is stripped."""
        content = "---\ntitle: My Analysis\ndate: 2025-01-15\n---\nActual content here."
        (tmp_path / "analysis.md").write_text(content)
        result = json.loads(_load_analysis_json(str(tmp_path)))
        assert len(result) == 1
        assert result[0]["body"] == "Actual content here."

    def test_no_frontmatter_preserved(self, tmp_path):
        """Files without frontmatter are preserved as-is."""
        content = "No frontmatter here.\n\nJust plain text."
        (tmp_path / "plain.md").write_text(content)
        result = json.loads(_load_analysis_json(str(tmp_path)))
        assert result[0]["body"] == content

    def test_ignores_non_md_files(self, tmp_path):
        """Only .md files are loaded, not .txt or others."""
        (tmp_path / "notes.md").write_text("Markdown.")
        (tmp_path / "notes.txt").write_text("Text.")
        (tmp_path / "data.json").write_text("{}")
        result = json.loads(_load_analysis_json(str(tmp_path)))
        assert len(result) == 1
        assert result[0]["filename"] == "notes.md"

    def test_export_with_analysis(self, spa_db, tmp_path):
        """Export with analysis dir embeds the analysis JSON."""
        analysis_dir = tmp_path / "analysis"
        analysis_dir.mkdir()
        (analysis_dir / "test.md").write_text("Test content.")
        out_path = str(tmp_path / "out.html")
        export_spa(spa_db, out_path, analysis_dir=str(analysis_dir))
        with open(out_path, encoding="utf-8") as f:
            html = f.read()
        match = re.search(
            r'<script id="chartfold-analysis" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        assert match is not None
        data = json.loads(match.group(1))
        assert len(data) == 1
        assert data[0]["body"] == "Test content."


# --- Image loading tests ---


class TestLoadImagesJson:
    """Tests for _load_images_json helper."""

    def test_no_assets(self, spa_db):
        """Returns '{}' when no source_assets exist."""
        result = _load_images_json(spa_db)
        assert json.loads(result) == {}

    def test_non_image_assets_skipped(self, spa_db):
        """Non-image assets (pdf, xml) are skipped."""
        import sqlite3

        conn = sqlite3.connect(spa_db)
        conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, content_type) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test", "pdf", "/tmp/report.pdf", "report.pdf", "application/pdf"),
        )
        conn.commit()
        conn.close()
        result = _load_images_json(spa_db)
        assert json.loads(result) == {}

    def test_image_asset_embedded(self, spa_db, tmp_path):
        """Image assets are base64-encoded with data URI."""
        import sqlite3

        # Create a tiny PNG-like file
        img_path = tmp_path / "scan.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\nfake_image_data")

        conn = sqlite3.connect(spa_db)
        conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, content_type) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test", "png", str(img_path), "scan.png", "image/png"),
        )
        conn.commit()
        conn.close()

        result = json.loads(_load_images_json(spa_db))
        assert len(result) == 1
        # The key is the string asset ID
        asset_id = list(result.keys())[0]
        assert result[asset_id].startswith("data:image/png;base64,")

    def test_missing_image_file_skipped(self, spa_db):
        """Assets pointing to non-existent files are skipped."""
        import sqlite3

        conn = sqlite3.connect(spa_db)
        conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, content_type) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test", "png", "/nonexistent/scan.png", "scan.png", "image/png"),
        )
        conn.commit()
        conn.close()

        result = _load_images_json(spa_db)
        assert json.loads(result) == {}

    def test_export_with_images(self, spa_db, tmp_path):
        """Export with embed_images=True includes image data."""
        import sqlite3

        img_path = tmp_path / "photo.jpg"
        img_path.write_bytes(b"\xff\xd8\xff\xe0fake_jpeg")

        conn = sqlite3.connect(spa_db)
        conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, content_type) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test", "jpg", str(img_path), "photo.jpg", "image/jpeg"),
        )
        conn.commit()
        conn.close()

        out_path = str(tmp_path / "out.html")
        export_spa(spa_db, out_path, embed_images=True)
        with open(out_path, encoding="utf-8") as f:
            html = f.read()
        match = re.search(
            r'<script id="chartfold-images" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        assert match is not None
        data = json.loads(match.group(1))
        assert len(data) == 1

    def test_images_not_embedded_by_default(self, spa_db, tmp_path):
        """By default, embed_images=False produces empty images JSON."""
        import sqlite3

        img_path = tmp_path / "photo.jpg"
        img_path.write_bytes(b"\xff\xd8\xff\xe0fake_jpeg")

        conn = sqlite3.connect(spa_db)
        conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, content_type) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test", "jpg", str(img_path), "photo.jpg", "image/jpeg"),
        )
        conn.commit()
        conn.close()

        out_path = str(tmp_path / "out.html")
        export_spa(spa_db, out_path)  # embed_images defaults to False
        with open(out_path, encoding="utf-8") as f:
            html = f.read()
        match = re.search(
            r'<script id="chartfold-images" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        assert match is not None
        assert json.loads(match.group(1)) == {}

    def test_invalid_db_returns_empty(self, tmp_path):
        """Non-database file returns empty JSON."""
        bad_db = tmp_path / "notadb.db"
        bad_db.write_text("not a database")
        result = _load_images_json(str(bad_db))
        assert json.loads(result) == {}


# --- Router JS tests ---


class TestRouterJs:
    """Tests that verify router.js is properly structured and embedded."""

    def test_router_object_in_html(self, exported_html):
        """HTML contains the Router object definition."""
        assert "const Router" in exported_html

    def test_router_has_init_method(self, exported_html):
        """Router has init(contentEl, sidebarEl) method."""
        assert "init(contentEl, sidebarEl)" in exported_html

    def test_router_has_register_method(self, exported_html):
        """Router has register method for adding sections."""
        assert "register(id, label, group, count, renderFn)" in exported_html

    def test_router_has_navigate_method(self, exported_html):
        """Router has navigate(sectionId) method."""
        assert "navigate(sectionId)" in exported_html

    def test_router_has_start_method(self, exported_html):
        """Router has start() method."""
        assert "start()" in exported_html

    def test_router_uses_event_delegation(self, exported_html):
        """Router uses event delegation with closest('.sidebar-item')."""
        assert ".closest('.sidebar-item')" in exported_html

    def test_router_handles_popstate(self, exported_html):
        """Router listens for popstate events for browser back/forward."""
        assert "'popstate'" in exported_html

    def test_router_sets_location_hash(self, exported_html):
        """Router updates location.hash for bookmarking."""
        assert "history.pushState" in exported_html

    def test_router_closes_mobile_sidebar(self, exported_html):
        """Router removes .open class from sidebar on navigate."""
        # The navigate method should close the mobile sidebar
        assert "classList.remove('open')" in exported_html

    def test_router_clears_content(self, exported_html):
        """Router clears content area before rendering a section."""
        assert "contentEl.textContent = ''" in exported_html

    def test_router_updates_active_class(self, exported_html):
        """Router manages the .active class on sidebar items."""
        assert "classList.remove('active')" in exported_html
        assert "classList.add('active')" in exported_html

    def test_router_default_to_overview(self, exported_html):
        """Router defaults to 'overview' section when no hash is set."""
        assert "navigate('overview')" in exported_html


# --- Sections JS tests ---


class TestSectionsJs:
    """Tests that verify sections.js contains all required section renderers."""

    def test_sections_object_in_html(self, exported_html):
        """HTML contains the Sections object definition."""
        assert "const Sections" in exported_html

    def test_all_section_ids_present(self, exported_html):
        """All 15 section IDs have renderers in Sections."""
        expected_sections = [
            "overview",
            "conditions",
            "medications",
            "lab_results",
            "encounters",
            "imaging",
            "pathology",
            "allergies",
            "clinical_notes",
            "procedures",
            "vitals",
            "immunizations",
            "sources",
            "analysis",
            "sql_console",
        ]
        for section_id in expected_sections:
            # Each section should appear as a method: "section_id(el, db)"
            assert f"{section_id}(el, db)" in exported_html, (
                f"Section '{section_id}' renderer not found in exported HTML"
            )

    def test_sections_use_section_header(self, exported_html):
        """Section renderers use UI.sectionHeader for consistent headings."""
        assert "UI.sectionHeader(" in exported_html

    def test_sections_use_empty_state(self, exported_html):
        """Section renderers use UI.empty for placeholder messages."""
        assert "UI.empty(" in exported_html

    def test_overview_section_header(self, exported_html):
        """Overview section renders with a proper section header."""
        assert "UI.sectionHeader('Overview'" in exported_html

    def test_overview_has_card_grid(self, exported_html):
        """Overview section renders summary cards in a card-grid."""
        assert "card-grid" in exported_html

    def test_overview_card_grid_tables(self, exported_html):
        """Overview queries counts for 11 clinical tables."""
        overview_tables = [
            "conditions",
            "medications",
            "lab_results",
            "encounters",
            "imaging_reports",
            "pathology_reports",
            "clinical_notes",
            "procedures",
            "vitals",
            "immunizations",
            "allergies",
        ]
        for table in overview_tables:
            assert table in exported_html, (
                f"Overview should reference table '{table}'"
            )

    def test_overview_cards_navigate_on_click(self, exported_html):
        """Overview cards navigate to their section on click."""
        assert "Router.navigate(sec)" in exported_html

    def test_overview_reads_config_for_sparklines(self, exported_html):
        """Overview reads the chartfold-config for key lab test sparklines."""
        assert "getElementById('chartfold-config')" in exported_html
        assert "key_tests" in exported_html

    def test_overview_has_sparkline(self, exported_html):
        """Overview uses UI.sparkline for key lab trends."""
        assert "UI.sparkline(" in exported_html

    def test_overview_key_lab_trends_heading(self, exported_html):
        """Overview has a 'Key Lab Trends' heading."""
        assert "Key Lab Trends" in exported_html

    def test_overview_alerts_section(self, exported_html):
        """Overview has a 'Recent Alerts' section for abnormal labs."""
        assert "Recent Alerts" in exported_html

    def test_overview_abnormal_interpretations_query(self, exported_html):
        """Overview queries for abnormal lab interpretations."""
        for interp in ["H", "L", "HH", "LL", "HIGH", "LOW", "ABNORMAL", "A"]:
            assert f"'{interp}'" in exported_html, (
                f"Overview should query for interpretation '{interp}'"
            )

    def test_overview_no_alerts_green_badge(self, exported_html):
        """Overview shows green badge when no abnormal results."""
        assert "No abnormal results in the last 30 days" in exported_html

    def test_overview_alert_value_has_red_badge(self, exported_html):
        """Overview alert table shows red badge for interpretation."""
        assert "UI.badge(row.interpretation, 'red')" in exported_html

    def test_overview_sparkline_reverses_order(self, exported_html):
        """Overview reverses lab values for sparkline (DESC -> chronological)."""
        # The code iterates from length-1 to 0 to reverse
        assert "labRows.length - 1" in exported_html

    def test_overview_uses_aliases_for_lab_queries(self, exported_html):
        """Overview uses test aliases from config for lab queries."""
        assert "aliases" in exported_html

    def test_clinical_sections_query_counts(self, exported_html):
        """Clinical sections query their respective tables for counts."""
        table_queries = [
            "SELECT COUNT(*) AS n FROM conditions",
            "SELECT COUNT(*) AS n FROM medications",
            "SELECT COUNT(*) AS n FROM lab_results",
            "SELECT COUNT(*) AS n FROM encounters",
            "SELECT COUNT(*) AS n FROM imaging_reports",
            "SELECT COUNT(*) AS n FROM pathology_reports",
            "SELECT COUNT(*) AS n FROM allergies",
            "SELECT COUNT(*) AS n FROM clinical_notes",
            "SELECT COUNT(*) AS n FROM procedures",
            "SELECT COUNT(*) AS n FROM vitals",
            "SELECT COUNT(*) AS n FROM immunizations",
            "SELECT COUNT(*) AS n FROM source_assets",
        ]
        for query in table_queries:
            assert query in exported_html, (
                f"Expected count query not found: {query}"
            )

    def test_sql_console_section_no_count(self, exported_html):
        """SQL console section does not query a count table."""
        assert "UI.sectionHeader('SQL Console'" in exported_html

    def test_analysis_section_reads_embedded_json(self, exported_html):
        """Analysis section reads from the chartfold-analysis embedded data."""
        # The analysis section should reference the embedded JSON
        assert "getElementById('chartfold-analysis')" in exported_html

    # --- Conditions section tests ---

    def test_conditions_queries_active(self, exported_html):
        """Conditions section queries active conditions with LOWER()."""
        assert "LOWER(clinical_status) = 'active'" in exported_html

    def test_conditions_queries_resolved(self, exported_html):
        """Conditions section queries non-active conditions."""
        assert "LOWER(clinical_status) != 'active'" in exported_html

    def test_conditions_active_green_badge(self, exported_html):
        """Conditions section uses green badge for active status."""
        assert "UI.badge('Active', 'green')" in exported_html

    def test_conditions_resolved_gray_badge(self, exported_html):
        """Conditions section uses gray badge for resolved status."""
        assert "UI.badge('Resolved', 'gray')" in exported_html

    def test_conditions_icd10_badge(self, exported_html):
        """Conditions section shows ICD-10 codes as gray badges."""
        assert "icd10_code" in exported_html

    def test_conditions_collapsible_resolved(self, exported_html):
        """Conditions section puts resolved conditions in a details element."""
        assert "Resolved & Other" in exported_html

    def test_conditions_empty_state(self, exported_html):
        """Conditions section shows empty state when no conditions."""
        assert "No conditions recorded" in exported_html

    # --- Medications section tests ---

    def test_medications_queries_all(self, exported_html):
        """Medications section queries all meds ordered by status and name."""
        assert "SELECT * FROM medications ORDER BY status, name" in exported_html

    def test_medications_cross_source_detection(self, exported_html):
        """Medications section detects multi-source medications."""
        assert "Multi-source" in exported_html

    def test_medications_uses_clinical_cards(self, exported_html):
        """Medications section uses clinicalCard for active medications."""
        assert "UI.clinicalCard(" in exported_html

    def test_medications_groups_by_status(self, exported_html):
        """Medications section splits active from other status groups."""
        assert "activeMeds" in exported_html
        assert "otherGroups" in exported_html

    def test_medications_table_for_non_active(self, exported_html):
        """Medications non-active groups rendered as sortable tables."""
        assert "UI.table(tableCols, gMeds)" in exported_html

    def test_medications_empty_state(self, exported_html):
        """Medications section shows empty state when no medications."""
        assert "No medications recorded" in exported_html

    def test_medications_case_insensitive_status(self, exported_html):
        """Medications section uses toLowerCase for case-insensitive status."""
        assert "toLowerCase()" in exported_html


# --- App.js wiring tests ---


class TestAppJsRouterWiring:
    """Tests that app.js properly wires Router and Sections together."""

    def test_app_calls_router_init(self, exported_html):
        """app.js calls Router.init with content and sidebar elements."""
        assert "Router.init(" in exported_html

    def test_app_registers_sections(self, exported_html):
        """app.js calls Router.register for each sidebar section."""
        assert "Router.register(" in exported_html

    def test_app_calls_router_start(self, exported_html):
        """app.js calls Router.start() to begin navigation."""
        assert "Router.start()" in exported_html

    def test_app_no_hardcoded_empty_state(self, exported_html):
        """app.js does not hardcode an empty state in the content area."""
        # The old hardcoded message should be removed; Router handles it
        assert "Select a section from the sidebar to begin." not in exported_html

    def test_app_passes_section_renderers(self, exported_html):
        """app.js passes Sections[sec.id] as the render function."""
        assert "Sections[sec.id]" in exported_html

    def test_app_content_div_created_empty(self, exported_html):
        """app.js creates the #content div without child content."""
        # The content div is created with just className and id, no children
        # (Router.start() will populate it)
        assert "id: 'content'" in exported_html
