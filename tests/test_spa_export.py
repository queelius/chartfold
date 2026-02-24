"""Tests for the SPA export module."""

from __future__ import annotations

import base64
import gzip
import json
import re
import sqlite3
from pathlib import Path

import pytest

from chartfold.db import ChartfoldDB
from chartfold.spa.export import (
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
        """All 20 section IDs have renderers in Sections."""
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
            "patients",
            "social_history",
            "family_history",
            "mental_status",
            "personal_notes",
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
        """Overview queries counts for 14 clinical tables."""
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
            "social_history",
            "family_history",
            "mental_status",
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
        """Clinical sections query their respective tables for counts via _sectionPreamble."""
        # The shared _sectionPreamble helper builds count queries dynamically
        assert "SELECT COUNT(*) AS n FROM " in exported_html
        # Each section passes its table name to _sectionPreamble
        table_calls = [
            "_sectionPreamble(el, db, 'conditions'",
            "_sectionPreamble(el, db, 'medications'",
            "_sectionPreamble(el, db, 'lab_results'",
            "_sectionPreamble(el, db, 'encounters'",
            "_sectionPreamble(el, db, 'imaging_reports'",
            "_sectionPreamble(el, db, 'pathology_reports'",
            "_sectionPreamble(el, db, 'allergies'",
            "_sectionPreamble(el, db, 'clinical_notes'",
            "_sectionPreamble(el, db, 'procedures'",
            "_sectionPreamble(el, db, 'vitals'",
            "_sectionPreamble(el, db, 'immunizations'",
            "_sectionPreamble(el, db, 'source_assets'",
        ]
        for call in table_calls:
            assert call in exported_html, (
                f"Expected _sectionPreamble call not found: {call}"
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
        """Medications all-view renders a sortable table with all meds."""
        assert "UI.table(tableCols, allMeds)" in exported_html

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

    def test_app_has_global_search_input(self, exported_html):
        """app.js creates a global search input in the topbar."""
        assert "topbar-search" in exported_html
        assert "placeholder: 'Search...'" in exported_html

    def test_app_search_debounce(self, exported_html):
        """app.js debounces search input with setTimeout."""
        assert "searchTimeout" in exported_html
        assert "clearTimeout(searchTimeout)" in exported_html
        assert "setTimeout(function()" in exported_html

    def test_app_search_filters_table_rows(self, exported_html):
        """app.js search filters table tbody tr elements."""
        assert "querySelectorAll('table tbody tr')" in exported_html

    def test_app_search_filters_cards(self, exported_html):
        """app.js search filters card and clinical-card elements."""
        assert "querySelectorAll('.card, .clinical-card')" in exported_html

    def test_app_has_print_button(self, exported_html):
        """app.js creates a print button in the topbar."""
        assert "topbar-print" in exported_html
        assert "window.print()" in exported_html

    def test_css_has_topbar_search_styles(self, exported_html):
        """CSS includes styling for the topbar search input."""
        assert ".topbar-search" in exported_html
        assert "border-radius: 20px" in exported_html

    def test_css_has_topbar_print_styles(self, exported_html):
        """CSS includes styling for the topbar print button."""
        assert ".topbar-print" in exported_html

    def test_css_hides_search_on_mobile(self, exported_html):
        """CSS hides the search input on mobile via media query."""
        # The mobile media query should contain .topbar-search { display: none; }
        assert ".topbar-search" in exported_html


# --- ChartRenderer JS tests ---


class TestChartRendererJs:
    """Tests that verify chart.js contains the ChartRenderer implementation."""

    def test_chart_renderer_object(self, exported_html):
        """HTML contains the ChartRenderer object definition."""
        assert "var ChartRenderer" in exported_html

    def test_chart_renderer_has_palette(self, exported_html):
        """ChartRenderer has a color palette array."""
        assert "_palette:" in exported_html
        assert "#0071e3" in exported_html
        assert "#ff9500" in exported_html
        assert "#34c759" in exported_html

    def test_chart_renderer_has_line_method(self, exported_html):
        """ChartRenderer has a line(canvas, datasets, opts) method."""
        assert "line: function(canvas, datasets, opts)" in exported_html

    def test_chart_renderer_has_create_tooltip(self, exported_html):
        """ChartRenderer has a createTooltip method."""
        assert "createTooltip: function(container)" in exported_html

    def test_chart_renderer_has_set_tooltip_content(self, exported_html):
        """ChartRenderer has a _setTooltipContent helper for safe DOM tooltip rendering."""
        assert "_setTooltipContent: function(tooltip, label, value, dateStr, source)" in exported_html

    def test_chart_uses_device_pixel_ratio(self, exported_html):
        """Chart renderer uses devicePixelRatio for high-DPI displays."""
        assert "devicePixelRatio" in exported_html

    def test_chart_canvas_sizing(self, exported_html):
        """Chart sets canvas width/height from opts with defaults."""
        assert "opts.width || 800" in exported_html
        assert "opts.height || 300" in exported_html

    def test_chart_y_axis_auto_scale(self, exported_html):
        """Chart auto-scales Y axis from data min/max."""
        assert "Math.min.apply(null, allY)" in exported_html
        assert "Math.max.apply(null, allY)" in exported_html

    def test_chart_y_axis_padding(self, exported_html):
        """Chart adds 10% padding to Y axis range."""
        assert "yRange * 0.1" in exported_html

    def test_chart_ref_range_extends_scale(self, exported_html):
        """Chart extends Y scale to include reference range if provided."""
        assert "Math.min(yMin, refRange.low)" in exported_html
        assert "Math.max(yMax, refRange.high)" in exported_html

    def test_chart_ref_range_shading(self, exported_html):
        """Chart draws reference range as a shaded band."""
        assert "rgba(52, 199, 89, 0.08)" in exported_html
        assert "fillRect(padLeft" in exported_html

    def test_chart_ref_range_dashed_borders(self, exported_html):
        """Chart draws dashed borders for reference range."""
        assert "setLineDash([4, 4])" in exported_html

    def test_chart_gridlines(self, exported_html):
        """Chart draws Y-axis gridlines."""
        assert "yTicks = 5" in exported_html
        assert "#e5e5ea" in exported_html  # gridline color

    def test_chart_x_axis_date_labels(self, exported_html):
        """Chart renders X-axis date labels from date strings."""
        assert "months[d.getMonth()]" in exported_html
        assert "d.getFullYear()" in exported_html

    def test_chart_x_axis_max_labels(self, exported_html):
        """Chart limits X-axis labels to max 10."""
        assert "maxXLabels = 10" in exported_html

    def test_chart_x_axis_label_rotation(self, exported_html):
        """Chart rotates X-axis labels at an angle."""
        assert "Math.PI / 6" in exported_html

    def test_chart_line_drawing(self, exported_html):
        """Chart draws connected lines for each dataset."""
        assert "ctx.lineTo(points[lk].sx, points[lk].sy)" in exported_html

    def test_chart_line_style(self, exported_html):
        """Chart uses line width 2px with round joins."""
        assert "lineWidth = 2" in exported_html
        assert "lineJoin = 'round'" in exported_html
        assert "lineCap = 'round'" in exported_html

    def test_chart_data_points(self, exported_html):
        """Chart draws circles at data points with radius 4."""
        assert "ctx.arc(points[pk].sx, points[pk].sy, 4" in exported_html

    def test_chart_data_points_white_border(self, exported_html):
        """Chart data points have a white border for visibility."""
        assert "strokeStyle = '#fff'" in exported_html

    def test_chart_legend(self, exported_html):
        """Chart draws a legend when multiple datasets exist."""
        assert "datasets.length > 1" in exported_html
        assert "Color swatch" in exported_html
        assert "measureText" in exported_html

    def test_chart_hover_interaction(self, exported_html):
        """Chart has mousemove event handler for hover tooltips."""
        assert "addEventListener('mousemove'" in exported_html
        assert "getBoundingClientRect" in exported_html

    def test_chart_hover_finds_closest_point(self, exported_html):
        """Chart hover finds closest data point within 40px threshold."""
        assert "closestDist = Infinity" in exported_html
        assert "dist < 40" in exported_html

    def test_chart_hover_hides_on_mouseleave(self, exported_html):
        """Chart hides tooltip on mouseleave."""
        assert "addEventListener('mouseleave'" in exported_html

    def test_chart_tooltip_styling(self, exported_html):
        """Chart tooltip has proper styling (z-index, background, shadow)."""
        assert "z-index:200" in exported_html
        assert "chart-tooltip" in exported_html
        assert "pointer-events:none" in exported_html

    def test_chart_tooltip_safe_dom(self, exported_html):
        """Chart tooltip uses safe DOM methods (textContent, not innerHTML)."""
        assert "_setTooltipContent(tooltip" in exported_html
        assert "document.createTextNode" in exported_html

    def test_chart_tooltip_positioning(self, exported_html):
        """Chart tooltip is positioned near the hovered data point."""
        assert "closest.sx + 12" in exported_html
        assert "closest.sy - 12" in exported_html

    def test_chart_tooltip_bounds_check(self, exported_html):
        """Chart tooltip stays within container bounds."""
        assert "containerW = canvas.parentNode.offsetWidth" in exported_html
        assert "tipX + 160 > containerW" in exported_html

    def test_chart_area_padding(self, exported_html):
        """Chart has defined padding for axes."""
        assert "padLeft = 60" in exported_html
        assert "padRight = 20" in exported_html
        assert "padTop = 20" in exported_html
        assert "padBottom = 40" in exported_html

    def test_chart_x_range_fallback(self, exported_html):
        """Chart handles single-point X range with 1 day fallback."""
        assert "xRange === 0" in exported_html
        assert "86400000" in exported_html


# --- Lab Results section tests ---


class TestLabResultsSection:
    """Tests that verify the lab_results section in sections.js."""

    def test_lab_results_has_renderer(self, exported_html):
        """Lab results section has a renderer function."""
        assert "lab_results(el, db)" in exported_html

    def test_lab_results_queries_count(self, exported_html):
        """Lab results section queries the total count."""
        assert "SELECT COUNT(*) AS n FROM lab_results" in exported_html

    def test_lab_results_empty_state(self, exported_html):
        """Lab results shows empty state when no data."""
        assert "No lab results recorded" in exported_html

    def test_lab_results_has_tab_buttons(self, exported_html):
        """Lab results section has Charts and Table tab buttons."""
        assert "Charts" in exported_html
        assert "Table" in exported_html

    def test_lab_results_default_to_charts(self, exported_html):
        """Lab results defaults to the Charts tab."""
        assert "activeTab = 'charts'" in exported_html

    def test_lab_results_tab_switching(self, exported_html):
        """Lab results has tab switching logic with setActiveTab function."""
        assert "setActiveTab('charts')" in exported_html
        assert "setActiveTab('table')" in exported_html

    def test_lab_results_tab_active_styling(self, exported_html):
        """Lab results tabs use accent color for active state."""
        assert "style.background = 'var(--accent)'" in exported_html
        assert "style.color = '#fff'" in exported_html

    def test_lab_results_charts_read_config(self, exported_html):
        """Lab results charts sub-view reads config for key_tests."""
        # Already tested that overview reads config, but lab_results also does
        assert "key_tests.tests" in exported_html

    def test_lab_results_charts_use_aliases(self, exported_html):
        """Lab results charts use test aliases from config."""
        assert "key_tests.aliases" in exported_html

    def test_lab_results_charts_query_numeric(self, exported_html):
        """Lab results charts query only numeric values."""
        assert "value_numeric IS NOT NULL" in exported_html

    def test_lab_results_charts_group_by_source(self, exported_html):
        """Lab results charts group data by source for multi-dataset display."""
        assert "sourceMap" in exported_html

    def test_lab_results_charts_parse_ref_range(self, exported_html):
        """Lab results charts parse reference range strings."""
        assert "parseRefRange" in exported_html

    def test_lab_results_ref_range_dash_format(self, exported_html):
        """Lab results parses dash-separated ref range (e.g., '3.0-10.0')."""
        # The regex for dash format
        assert "dashMatch" in exported_html

    def test_lab_results_ref_range_lt_format(self, exported_html):
        """Lab results parses less-than ref range (e.g., '< 5.0')."""
        assert "ltMatch" in exported_html

    def test_lab_results_ref_range_gt_format(self, exported_html):
        """Lab results parses greater-than ref range (e.g., '> 1.0')."""
        assert "gtMatch" in exported_html

    def test_lab_results_charts_use_chart_renderer(self, exported_html):
        """Lab results charts call ChartRenderer.line()."""
        assert "ChartRenderer.line(canvas, datasets" in exported_html

    def test_lab_results_charts_use_chart_container(self, exported_html):
        """Lab results chart cards use .chart-container class."""
        assert "chart-container" in exported_html

    def test_lab_results_fallback_top_5(self, exported_html):
        """Lab results shows top 5 tests by count when no config."""
        assert "GROUP BY test_name ORDER BY cnt DESC LIMIT 5" in exported_html

    def test_lab_results_no_numeric_empty(self, exported_html):
        """Lab results shows message when no numeric data for charting."""
        assert "No numeric lab data available for charting" in exported_html

    def test_lab_results_table_filter_bar(self, exported_html):
        """Lab results table has a filter bar with test name, abnormal, and dates."""
        assert "SELECT DISTINCT test_name FROM lab_results ORDER BY test_name" in exported_html

    def test_lab_results_table_filter_test_name(self, exported_html):
        """Lab results table filter supports test name selection."""
        assert "test_name = ?" in exported_html

    def test_lab_results_table_filter_abnormal(self, exported_html):
        """Lab results table filter supports abnormal-only checkbox."""
        assert "abnormalOnly" in exported_html

    def test_lab_results_table_filter_date_range(self, exported_html):
        """Lab results table filter supports date range inputs."""
        assert "dateFrom" in exported_html
        assert "dateTo" in exported_html
        assert "result_date >= ?" in exported_html
        assert "result_date <= ?" in exported_html

    def test_lab_results_table_columns(self, exported_html):
        """Lab results table has expected columns."""
        for col in ["Test Name", "Value", "Unit", "Ref Range", "Date", "Source"]:
            assert col in exported_html, (
                f"Lab results table should have column '{col}'"
            )

    def test_lab_results_table_abnormal_badge(self, exported_html):
        """Lab results table shows red badge for abnormal interpretations."""
        assert "UI.badge(row.interpretation, 'red')" in exported_html

    def test_lab_results_table_abnormal_interpretations(self, exported_html):
        """Lab results table checks all standard abnormal interpretation codes."""
        for interp in ["H", "L", "HH", "LL", "HIGH", "LOW", "ABNORMAL", "A"]:
            assert f"'{interp}'" in exported_html

    def test_lab_results_table_abnormal_row_highlight(self, exported_html):
        """Lab results table highlights abnormal rows with subtle red background."""
        assert "rgba(255, 59, 48, 0.04)" in exported_html

    def test_lab_results_table_pagination(self, exported_html):
        """Lab results table has pagination with 50 per page."""
        assert "pageSize = 50" in exported_html
        assert "UI.pagination(" in exported_html

    def test_lab_results_table_ordering(self, exported_html):
        """Lab results table orders by date descending, then test name."""
        assert "ORDER BY result_date DESC, test_name" in exported_html

    def test_lab_results_table_limit_offset(self, exported_html):
        """Lab results table uses LIMIT and OFFSET for pagination."""
        assert "LIMIT ? OFFSET ?" in exported_html

    def test_lab_results_table_no_match_empty(self, exported_html):
        """Lab results table shows empty state when no results match filters."""
        assert "No lab results match the current filters" in exported_html

    def test_lab_results_table_page_clamping(self, exported_html):
        """Lab results table clamps currentPage to valid range."""
        assert "currentPage > totalPages" in exported_html

    def test_lab_results_table_filter_resets_page(self, exported_html):
        """Lab results table resets to page 1 when filters change."""
        assert "currentPage = 1" in exported_html

    def test_lab_results_charts_dataset_palette(self, exported_html):
        """Lab results charts use ChartRenderer's shared color palette."""
        assert "ChartRenderer._palette" in exported_html


# --- Additional export tests ---


class TestExportSpaAdditional:
    """Additional tests for the SPA export module."""

    def test_empty_database(self, tmp_path):
        """Export succeeds with a schema-only database (no data)."""
        db_path = tmp_path / "empty.db"
        schema = (Path(__file__).parent.parent / "src" / "chartfold" / "schema.sql").read_text()
        conn = sqlite3.connect(str(db_path))
        conn.executescript(schema)
        conn.close()

        out_path = str(tmp_path / "empty_export.html")
        result = export_spa(str(db_path), out_path)
        assert result == out_path
        with open(out_path, encoding="utf-8") as f:
            html = f.read()
        assert html.startswith("<!DOCTYPE html>")
        assert html.rstrip().endswith("</html>")
        assert 'id="chartfold-db"' in html

    def test_gzip_compression_reduces_size(self, spa_db, tmp_path):
        """The gzip-compressed base64 DB is smaller than the raw DB file."""
        out_path = str(tmp_path / "compressed.html")
        export_spa(spa_db, out_path)
        with open(out_path, encoding="utf-8") as f:
            html = f.read()

        match = re.search(
            r'<script id="chartfold-db" type="application/gzip\+base64">(.*?)</script>',
            html,
            re.DOTALL,
        )
        assert match is not None
        db_b64 = match.group(1).strip()
        compressed_bytes = base64.b64decode(db_b64)
        raw_size = Path(spa_db).stat().st_size
        assert len(compressed_bytes) < raw_size

    def test_missing_config_no_error(self, spa_db, tmp_path):
        """Export with a non-existent config path succeeds gracefully."""
        out_path = str(tmp_path / "no_config.html")
        result = export_spa(spa_db, out_path, config_path="/nonexistent/config.toml")
        assert result == out_path
        with open(out_path, encoding="utf-8") as f:
            html = f.read()
        # Config should fall back to empty object
        match = re.search(
            r'<script id="chartfold-config" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        assert match is not None
        assert json.loads(match.group(1)) == {}

    def test_config_embedded_as_json(self, spa_db, tmp_path):
        """A TOML config file is embedded as JSON in the output."""
        toml_path = tmp_path / "test_config.toml"
        toml_path.write_text(
            '[dashboard]\ntitle = "Health Dashboard"\n\n[key_tests]\ntests = ["CEA", "WBC"]\n'
        )
        out_path = str(tmp_path / "with_config.html")
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
        assert data["dashboard"]["title"] == "Health Dashboard"
        assert data["key_tests"]["tests"] == ["CEA", "WBC"]

    def test_embed_images_flag(self, spa_db, tmp_path):
        """embed_images=True triggers image asset loading from database."""
        # Create a small image file
        img_path = tmp_path / "test_image.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\nfake_png_data_for_testing")

        # Insert an image asset into the database
        conn = sqlite3.connect(spa_db)
        conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, content_type) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test", "png", str(img_path), "test_image.png", "image/png"),
        )
        conn.commit()
        conn.close()

        out_path = str(tmp_path / "with_images.html")
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
        asset_id = list(data.keys())[0]
        assert data[asset_id].startswith("data:image/png;base64,")

    def test_embed_images_skips_oversized(self, spa_db, tmp_path):
        """Images larger than 10 MB are skipped during embedding."""
        img_path = tmp_path / "huge_image.png"
        # Write 11 MB of data (over _MAX_IMAGE_SIZE = 10 * 1024 * 1024)
        img_path.write_bytes(b"\x89PNG" + b"\x00" * (11 * 1024 * 1024))

        conn = sqlite3.connect(spa_db)
        conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, content_type) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test", "png", str(img_path), "huge_image.png", "image/png"),
        )
        conn.commit()
        conn.close()

        result = _load_images_json(spa_db)
        data = json.loads(result)
        assert len(data) == 0, "Oversized images should be skipped"

    def test_embed_images_skips_missing_file(self, spa_db, tmp_path):
        """Images with non-existent file paths are skipped."""
        conn = sqlite3.connect(spa_db)
        conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, content_type) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test", "png", "/nonexistent/path/image.png", "missing.png", "image/png"),
        )
        conn.commit()
        conn.close()

        result = _load_images_json(spa_db)
        data = json.loads(result)
        assert len(data) == 0, "Missing file should be skipped"

    def test_embed_images_skips_non_image_types(self, spa_db, tmp_path):
        """Non-image asset types (pdf, xml) are skipped during embedding."""
        pdf_path = tmp_path / "document.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake pdf")

        conn = sqlite3.connect(spa_db)
        conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, content_type) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test", "pdf", str(pdf_path), "document.pdf", "application/pdf"),
        )
        conn.commit()
        conn.close()

        result = _load_images_json(spa_db)
        data = json.loads(result)
        assert len(data) == 0, "Non-image types should be skipped"

    def test_js_files_concatenated_in_order(self, exported_html):
        """db.js code appears before app.js code in the output."""
        # DB module should appear before app.js wiring
        db_pos = exported_html.find("const DB")
        app_pos = exported_html.find("Router.start()")
        assert db_pos != -1, "DB module not found in HTML"
        assert app_pos != -1, "App startup code not found in HTML"
        assert db_pos < app_pos, "db.js must come before app.js in concatenation order"

    def test_output_is_valid_html(self, exported_html):
        """Output has proper HTML structure: DOCTYPE, html, head, body tags."""
        assert "<!DOCTYPE html>" in exported_html
        assert "<html" in exported_html
        assert "<head>" in exported_html
        assert "<body>" in exported_html
        assert "</head>" in exported_html
        assert "</body>" in exported_html
        assert "</html>" in exported_html

    def test_css_custom_properties_present(self, exported_html):
        """CSS custom properties for theming are present in the output."""
        assert "--bg:" in exported_html
        assert "--accent:" in exported_html
        assert "--surface:" in exported_html
        assert "--text:" in exported_html
        assert "--border:" in exported_html
        assert "--red:" in exported_html
        assert "--green:" in exported_html


class TestSecurityHardening:
    """Tests for XSS prevention, SQL safety, and resource management."""

    def test_markdown_escapes_double_quotes(self, exported_html):
        """Markdown esc() function must escape double quotes to prevent attribute breakout."""
        assert '&quot;' in exported_html or "&amp;quot;" in exported_html, (
            "markdown.js esc() must escape double quotes"
        )

    def test_markdown_sanitizes_javascript_urls(self, exported_html):
        """Markdown link handler must reject javascript: protocol URLs."""
        # Check that the protocol sanitization regex exists in the JS
        assert "javascript|data|vbscript" in exported_html.lower(), (
            "markdown.js must contain protocol check for javascript/data/vbscript URLs"
        )

    def test_db_sets_query_only_pragma(self, exported_html):
        """DB.init must set PRAGMA query_only = ON to prevent writes."""
        assert "query_only" in exported_html, (
            "db.js must set PRAGMA query_only = ON after database initialization"
        )

    def test_resource_leak_in_load_images(self, spa_db, tmp_path):
        """_load_images_json closes connection on the normal path."""
        from unittest.mock import patch, MagicMock

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        with patch("chartfold.spa.export.sqlite3.connect", return_value=mock_conn):
            _load_images_json(spa_db)
        mock_conn.close.assert_called_once()

    def test_alerts_query_uses_data_relative_date(self, exported_html):
        """Alerts query must NOT use date('now') — use data-relative dates instead."""
        assert "date('now'" not in exported_html, (
            "sections.js must not use date('now') — use data-relative dates for static exports"
        )

    def test_load_images_closes_conn_when_query_fails(self, tmp_path):
        """_load_images_json must close connection even if the SQL query fails."""
        from unittest.mock import patch, MagicMock

        db_path = tmp_path / "no_assets.db"
        conn_real = sqlite3.connect(str(db_path))
        conn_real.execute("CREATE TABLE lab_results (id INTEGER)")
        conn_real.commit()
        conn_real.close()

        # Mock sqlite3.connect to track close() calls
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = sqlite3.OperationalError("no such table: source_assets")
        with patch("chartfold.spa.export.sqlite3.connect", return_value=mock_conn):
            result = _load_images_json(str(db_path))
        assert json.loads(result) == {}
        mock_conn.close.assert_called_once()

    def test_script_injection_escaped_in_config(self, spa_db, tmp_path):
        """Config content with </script> must not break the HTML structure."""
        config_path = tmp_path / "evil.toml"
        config_path.write_text('[dashboard]\ntitle = "</script><script>alert(1)"')
        out_path = str(tmp_path / "config_inject.html")
        export_spa(spa_db, out_path, config_path=str(config_path))
        with open(out_path, encoding="utf-8") as f:
            html = f.read()
        assert '</script><script>alert' not in html, (
            "Config JSON must escape </script> sequences to prevent injection"
        )

    def test_sql_console_blocks_pragma(self, exported_html):
        """SQL console must block PRAGMA statements to prevent disabling query_only."""
        assert "PRAGMA" in exported_html.upper() or "pragma" in exported_html.lower()
        # The forbidden regex must include PRAGMA
        assert "PRAGMA" in exported_html, (
            "SQL console forbidden regex must include PRAGMA keyword"
        )

    def test_sql_console_blocks_replace(self, exported_html):
        """SQL console must block REPLACE statements (SQLite write operation)."""
        # Check the forbidden keyword regex includes REPLACE
        import re
        # Find the forbidden regex pattern in the JS
        match = re.search(r'var forbidden\s*=\s*/(.+?)/i', exported_html)
        assert match is not None, "SQL console forbidden regex not found"
        pattern = match.group(1)
        assert "REPLACE" in pattern, (
            "SQL console forbidden regex must include REPLACE keyword"
        )

    def test_markdown_escapes_single_quotes(self, exported_html):
        """Markdown esc() must escape single quotes for defense in depth."""
        assert "&#39;" in exported_html, (
            "markdown.js esc() must escape single quotes"
        )


class TestNewSections:
    """Tests for the 5 new section renderers: patients, social_history,
    family_history, mental_status, personal_notes."""

    def test_patients_section_exists(self, exported_html):
        """patients section renderer defined in Sections object."""
        assert "patients(el, db)" in exported_html

    def test_patients_queries_table(self, exported_html):
        """patients section queries the patients table."""
        assert "FROM patients" in exported_html

    def test_patients_displays_demographics_fields(self, exported_html):
        """patients section shows DOB, Gender, MRN, Address, Phone."""
        for field in ["Date of Birth", "Gender", "MRN", "Address", "Phone"]:
            assert field in exported_html

    def test_social_history_section_exists(self, exported_html):
        """social_history section renderer defined."""
        assert "social_history(el, db)" in exported_html

    def test_social_history_queries_table(self, exported_html):
        """social_history section queries the social_history table."""
        assert "FROM social_history" in exported_html

    def test_social_history_columns(self, exported_html):
        """social_history section shows category, value, date, source columns."""
        # Verify column headers are present in the JS
        for col in ["Category", "Value", "Date", "Source"]:
            # These appear as table column label strings
            assert col in exported_html

    def test_family_history_section_exists(self, exported_html):
        """family_history section renderer defined."""
        assert "family_history(el, db)" in exported_html

    def test_family_history_queries_table(self, exported_html):
        """family_history section queries the family_history table."""
        assert "FROM family_history" in exported_html

    def test_family_history_groups_by_relation(self, exported_html):
        """family_history section groups conditions by relation."""
        assert "relation" in exported_html

    def test_family_history_shows_deceased_badge(self, exported_html):
        """family_history section badges for deceased relatives."""
        assert "deceased" in exported_html

    def test_mental_status_section_exists(self, exported_html):
        """mental_status section renderer defined."""
        assert "mental_status(el, db)" in exported_html

    def test_mental_status_queries_table(self, exported_html):
        """mental_status section queries the mental_status table."""
        assert "FROM mental_status" in exported_html

    def test_mental_status_groups_by_instrument(self, exported_html):
        """mental_status section groups by instrument and date."""
        assert "instrument" in exported_html

    def test_mental_status_shows_total_score(self, exported_html):
        """mental_status section shows total_score as badge."""
        assert "total_score" in exported_html

    def test_personal_notes_section_exists(self, exported_html):
        """personal_notes section renderer defined."""
        assert "personal_notes(el, db)" in exported_html

    def test_personal_notes_queries_table(self, exported_html):
        """personal_notes section queries the notes table."""
        assert "FROM notes" in exported_html

    def test_personal_notes_fetches_tags(self, exported_html):
        """personal_notes section fetches tags from note_tags."""
        assert "FROM note_tags" in exported_html

    def test_personal_notes_shows_ref_link(self, exported_html):
        """personal_notes section shows linked ref_table info."""
        assert "ref_table" in exported_html

    def test_sidebar_has_new_groups(self, exported_html):
        """Sidebar defines History and Admin groups for new sections."""
        assert "History" in exported_html
        assert "Admin" in exported_html

    def test_sidebar_has_all_new_sections(self, exported_html):
        """Sidebar includes all 5 new section entries."""
        for sid in ["social_history", "family_history", "mental_status", "patients", "personal_notes"]:
            assert f'"id": "{sid}"' in exported_html or f"id: \"{sid}\"" in exported_html or f"'{sid}'" in exported_html

    def test_new_sections_with_data(self, tmp_path):
        """Integration: new sections render when data is present in DB."""
        db_path = tmp_path / "full.db"
        db = ChartfoldDB(str(db_path))
        db.init_schema()
        db.conn.execute(
            "INSERT INTO patients (source, name, date_of_birth, gender, mrn) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test", "Jane Doe", "1980-01-01", "female", "12345"),
        )
        db.conn.execute(
            "INSERT INTO social_history (source, category, value, recorded_date) "
            "VALUES (?, ?, ?, ?)",
            ("test", "Smoking Status", "Never smoker", "2025-01-15"),
        )
        db.conn.execute(
            "INSERT INTO family_history (source, relation, condition) "
            "VALUES (?, ?, ?)",
            ("test", "Father", "Hypertension"),
        )
        db.conn.execute(
            "INSERT INTO mental_status (source, instrument, question, answer, score, total_score, recorded_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test", "PHQ-9", "Little interest?", "Several days", 1, 5, "2025-01-15"),
        )
        db.conn.execute(
            "INSERT INTO notes (title, content, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("My Note", "Test content", "2025-01-15T12:00:00", "2025-01-15T12:00:00"),
        )
        db.conn.commit()
        db.close()

        out = str(tmp_path / "out.html")
        export_spa(str(db_path), out)
        html = Path(out).read_text(encoding="utf-8")

        # The database embeds these records — verify the DB was embedded
        assert 'id="chartfold-db"' in html
        # The section code is present
        assert "patients(el, db)" in html
        assert "social_history(el, db)" in html
        assert "family_history(el, db)" in html
        assert "mental_status(el, db)" in html
        assert "personal_notes(el, db)" in html


class TestSpaUxImprovements:
    """Tests for the SPA UX improvements (Feb 2026)."""

    # --- Analysis Section Overhaul ---

    def test_analysis_queries_frontmatter(self, exported_html):
        """Analysis section queries frontmatter and parses it in JS."""
        assert "frontmatter" in exported_html
        assert "JSON.parse" in exported_html

    def test_analysis_splits_current_archived(self, exported_html):
        """Analysis section splits current vs archived analyses."""
        assert "currentAnalyses" in exported_html
        assert "archivedAnalyses" in exported_html

    def test_analysis_status_badge(self, exported_html):
        """Analysis cards show status badges."""
        assert "statusVariant" in exported_html

    def test_analysis_category_badge(self, exported_html):
        """Analysis cards show category badge."""
        assert "entry.category" in exported_html
        assert "UI.badge(entry.category" in exported_html

    def test_analysis_tag_chips(self, exported_html):
        """Analysis cards show tag chips from analysis_tags."""
        assert "tagMap" in exported_html
        assert "analysis_tags" in exported_html

    def test_analysis_all_collapsed(self, exported_html):
        """All analysis cards render as collapsed details elements."""
        # No more first-entry-expanded pattern
        assert "renderAnalysisCard" in exported_html

    def test_analysis_summary_text(self, exported_html):
        """Analysis cards show summary text from DB."""
        assert "entry.summary" in exported_html

    def test_analysis_archived_group(self, exported_html):
        """Archived analyses grouped under a collapsible heading."""
        assert "'Archived ('" in exported_html

    # --- Overview Dashboard Enhancement ---

    def test_overview_date_formatting(self, exported_html):
        """Topbar date is formatted as human-readable."""
        assert "toLocaleDateString" in exported_html
        assert "'Updated: '" in exported_html

    def test_overview_cards_have_latest_date(self, exported_html):
        """Overview cards query MAX date for each table."""
        assert "MAX(" in exported_html
        assert "Latest:" in exported_html

    def test_overview_recent_activity(self, exported_html):
        """Overview section includes Recent Activity card."""
        assert "'Recent Activity'" in exported_html
        assert "activityRows" in exported_html

    def test_overview_activity_type_badges(self, exported_html):
        """Recent Activity uses color-coded type badges."""
        assert "Lab: 'blue'" in exported_html
        assert "Procedure: 'orange'" in exported_html

    # --- Conditions: Fill Empty Names ---

    def test_conditions_empty_name_shows_icd10(self, exported_html):
        """When condition_name is empty, ICD-10 code is shown."""
        assert "row.icd10_code" in exported_html

    def test_conditions_code_only_badge(self, exported_html):
        """Empty condition names get a 'code only' badge."""
        assert "'code only'" in exported_html

    # --- Medications: Reconciliation Tab ---

    def test_medications_has_three_tabs(self, exported_html):
        """Medications section has Active, All, and Reconciliation tabs."""
        assert "'Active Medications'" in exported_html
        assert "'All Medications'" in exported_html
        assert "'Reconciliation'" in exported_html

    def test_medications_reconciliation_groups(self, exported_html):
        """Reconciliation groups medications by normalized name."""
        assert "reconGroups" in exported_html
        assert "toLowerCase().trim()" in exported_html

    def test_medications_discrepancy_badge(self, exported_html):
        """Reconciliation flags status discrepancies with orange badge."""
        assert "'Status differs'" in exported_html
        assert "hasDiscrepancy" in exported_html

    def test_medications_all_view_table(self, exported_html):
        """All view shows a complete table with status badges."""
        assert "UI.table(tableCols, allMeds)" in exported_html

    # --- SQL Console: Schema Reference ---

    def test_sql_console_schema_reference(self, exported_html):
        """SQL Console has a collapsible Schema Reference."""
        assert "'Schema Reference'" in exported_html

    def test_sql_console_schema_lazy_load(self, exported_html):
        """Schema Reference is lazy-loaded on first open."""
        assert "schemaLoaded" in exported_html

    def test_sql_console_schema_pragma(self, exported_html):
        """Schema Reference queries PRAGMA table_info."""
        assert "PRAGMA table_info" in exported_html

    def test_sql_console_schema_sqlite_master(self, exported_html):
        """Schema Reference queries sqlite_master for table names."""
        assert "sqlite_master" in exported_html

    # --- Dark Mode ---

    def test_dark_mode_media_query(self, exported_html):
        """CSS includes prefers-color-scheme: dark media query."""
        assert "prefers-color-scheme: dark" in exported_html

    def test_dark_mode_overrides_bg(self, exported_html):
        """Dark mode overrides --bg custom property."""
        assert "--bg: #1c1c1e" in exported_html

    def test_dark_mode_overrides_surface(self, exported_html):
        """Dark mode overrides --surface custom property."""
        assert "--surface: #2c2c2e" in exported_html

    def test_dark_mode_overrides_text(self, exported_html):
        """Dark mode overrides --text custom property."""
        assert "--text: #f5f5f7" in exported_html

    def test_dark_mode_overrides_accent(self, exported_html):
        """Dark mode uses iOS dark blue accent."""
        assert "--accent: #0a84ff" in exported_html

    def test_dark_mode_chart_tooltip(self, exported_html):
        """Dark mode styles chart tooltips."""
        assert ".chart-tooltip" in exported_html


class TestLinkedAssetImages:
    """Tests for the upgraded _renderLinkedAssets with inline thumbnails."""

    def test_queries_asset_id_and_type(self, exported_html):
        """_renderLinkedAssets should query id, file_name, asset_type."""
        assert "SELECT id, file_name, asset_type FROM source_assets" in exported_html

    def test_loads_embedded_images_cache(self, exported_html):
        """_getEmbeddedImages should parse chartfold-images script tag."""
        assert "_getEmbeddedImages" in exported_html
        assert "chartfold-images" in exported_html

    def test_renders_img_tag_for_image_assets(self, exported_html):
        """Should render <img> tags for assets with embedded image data."""
        assert "max-height: 120px" in exported_html
        assert "max-width: 200px" in exported_html

    def test_clickable_thumbnail_opens_full_size(self, exported_html):
        """Thumbnails should call _showImageOverlay on click."""
        assert "_showImageOverlay" in exported_html

    def test_overlay_has_dismiss_behavior(self, exported_html):
        """Image overlay should close on click and Escape key."""
        assert "cursor: zoom-out" in exported_html
        assert "Escape" in exported_html

    def test_falls_back_to_badge_for_non_images(self, exported_html):
        """Non-image assets should still render as badges."""
        assert "otherAssets" in exported_html
        assert "UI.badge(otherAssets" in exported_html

    def test_sources_section_uses_shared_cache(self, exported_html):
        """Sources section should use _getEmbeddedImages() not duplicate loading."""
        # Should only have one getElementById('chartfold-images') — in the cache function
        count = exported_html.count("getElementById('chartfold-images')")
        assert count == 1
