"""Tests for chartfold.export_html module."""

import pytest

from chartfold.db import ChartfoldDB
from chartfold.export_html import (
    CHARTJS_MIN,
    EMBEDDED_CSS,
    SORTABLE_JS,
    _build_chart_js,
    _escape,
    _html_details,
    _html_table,
    export_html,
    export_html_full,
)
from chartfold.models import (
    AllergyRecord,
    ClinicalNote,
    ConditionRecord,
    EncounterRecord,
    ImagingReport,
    ImmunizationRecord,
    LabResult,
    MedicationRecord,
    PathologyReport,
    PatientRecord,
    ProcedureRecord,
    UnifiedRecords,
    VitalRecord,
)


@pytest.fixture
def export_db(tmp_path):
    """Database with clinical data for export testing."""
    db = ChartfoldDB(str(tmp_path / "export.db"))
    db.init_schema()

    records = UnifiedRecords(
        source="test_source",
        patient=PatientRecord(
            source="test_source", name="Test Patient", date_of_birth="1975-06-15", gender="male"
        ),
        lab_results=[
            LabResult(
                source="test_source",
                test_name="CEA",
                value="5.8",
                value_numeric=5.8,
                unit="ng/mL",
                ref_range="0.0-3.0",
                interpretation="H",
                result_date="2025-12-15",
            ),
            LabResult(
                source="test_source",
                test_name="Hemoglobin",
                value="12.5",
                value_numeric=12.5,
                unit="g/dL",
                ref_range="13.0-17.0",
                interpretation="L",
                result_date="2025-12-15",
            ),
            LabResult(
                source="test_source",
                test_name="CEA",
                value="4.2",
                value_numeric=4.2,
                unit="ng/mL",
                ref_range="0.0-3.0",
                interpretation="H",
                result_date="2025-11-01",
            ),
        ],
        medications=[
            MedicationRecord(
                source="test_source",
                name="Capecitabine 500mg",
                status="active",
                sig="2 tabs twice daily",
                route="oral",
                start_date="2025-01-01",
            ),
            MedicationRecord(
                source="test_source",
                name="Aspirin 81mg",
                status="discontinued",
                sig="1 tab daily",
                route="oral",
                start_date="2024-01-01",
                stop_date="2024-06-01",
            ),
        ],
        conditions=[
            ConditionRecord(
                source="test_source",
                condition_name="Colon cancer",
                icd10_code="C18.9",
                clinical_status="active",
                onset_date="2021-11-22",
            ),
            ConditionRecord(
                source="test_source",
                condition_name="Hypertension",
                icd10_code="I10",
                clinical_status="resolved",
                onset_date="2018-03-01",
            ),
        ],
        encounters=[
            EncounterRecord(
                source="test_source",
                encounter_date="2025-12-15",
                encounter_type="office visit",
                facility="Anderson",
                provider="Dr. Smith",
                reason="Chemotherapy follow-up",
            ),
        ],
        imaging_reports=[
            ImagingReport(
                source="test_source",
                study_name="CT Abdomen",
                modality="CT",
                study_date="2025-12-01",
                impression="No recurrence.",
            ),
        ],
        pathology_reports=[
            PathologyReport(
                source="test_source",
                report_date="2024-07-03",
                specimen="Right colon",
                diagnosis="Adenocarcinoma",
                staging="pT3N2a",
                margins="Negative",
            ),
        ],
        allergies=[
            AllergyRecord(
                source="test_source",
                allergen="Penicillin",
                reaction="Rash",
                severity="moderate",
                status="active",
            ),
        ],
        clinical_notes=[
            ClinicalNote(
                source="test_source",
                note_type="Progress Note",
                author="Dr. Smith",
                note_date="2025-12-15",
                content="Patient doing well on chemotherapy.",
            ),
        ],
        procedures=[
            ProcedureRecord(
                source="test_source",
                name="Right hemicolectomy",
                procedure_date="2024-07-01",
                provider="Dr. Surgeon",
                facility="General Hospital",
            ),
        ],
        vitals=[
            VitalRecord(
                source="test_source",
                vital_type="Blood Pressure",
                value_text="120/80",
                unit="mmHg",
                recorded_date="2025-12-15",
            ),
        ],
        immunizations=[
            ImmunizationRecord(
                source="test_source",
                vaccine_name="Flu Shot",
                admin_date="2025-10-01",
                site="Left arm",
            ),
        ],
    )
    db.load_source(records)
    yield db
    db.close()


class TestHTMLHelpers:
    """Test HTML helper functions."""

    def test_escape_special_chars(self):
        assert _escape("<script>") == "&lt;script&gt;"
        assert _escape("test & value") == "test &amp; value"
        assert _escape('"quoted"') == "&quot;quoted&quot;"

    def test_escape_none(self):
        assert _escape(None) == ""
        assert _escape("") == ""

    def test_html_table_basic(self):
        result = _html_table(["Name", "Value"], [["foo", "bar"]])
        assert "<table" in result
        assert "<th>Name</th>" in result
        assert "<td>foo</td>" in result
        assert "sortable" in result  # Default is sortable

    def test_html_table_empty(self):
        result = _html_table(["Name"], [])
        assert "No data available" in result

    def test_html_table_not_sortable(self):
        result = _html_table(["Name"], [["foo"]], sortable=False)
        assert "sortable" not in result

    def test_html_table_highlight_abnormal(self):
        result = _html_table(["Test", "Flag"], [["CEA", "H"]], highlight_col=1)
        assert 'class="abnormal"' in result

    def test_html_table_highlight_normal(self):
        result = _html_table(["Test", "Flag"], [["CEA", "Normal"]], highlight_col=1)
        # "Normal" is not in the abnormal list
        assert 'class="abnormal"' not in result

    def test_html_details(self):
        result = _html_details("Click here", "<p>Content</p>")
        assert "<details>" in result
        assert "<summary>Click here</summary>" in result
        assert "<p>Content</p>" in result

    def test_build_chart_js_empty(self):
        result = _build_chart_js("test", [], "ng/mL", "Test")
        assert result == ""

    def test_build_chart_js_with_data(self):
        datasets = [
            {
                "source": "test",
                "labels": ["2025-01-01", "2025-02-01"],
                "values": [5.0, 6.0],
                "color": "#3b82f6",
            }
        ]
        result = _build_chart_js("cea-chart", datasets, "ng/mL", "CEA Trend")
        assert 'id="cea-chart"' in result
        assert "new Chart" in result
        assert "CEA Trend" in result


class TestEmbeddedAssets:
    """Test embedded CSS and JS assets."""

    def test_chartjs_min_exists(self):
        assert len(CHARTJS_MIN) > 100
        assert "Chart" in CHARTJS_MIN

    def test_embedded_css_exists(self):
        assert len(EMBEDDED_CSS) > 100
        assert "table" in EMBEDDED_CSS
        assert "sortable" in EMBEDDED_CSS or "th" in EMBEDDED_CSS

    def test_sortable_js_exists(self):
        assert len(SORTABLE_JS) > 50
        assert "sortTable" in SORTABLE_JS


class TestExportHTML:
    """Test export_html function."""

    def test_generates_file(self, export_db, tmp_path):
        output = str(tmp_path / "test_export.html")
        result = export_html(export_db, output_path=output)
        assert result == output
        assert (tmp_path / "test_export.html").exists()

    def test_includes_doctype(self, export_db, tmp_path):
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output)
        content = (tmp_path / "export.html").read_text()
        assert "<!DOCTYPE html>" in content

    def test_includes_title(self, export_db, tmp_path):
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output)
        content = (tmp_path / "export.html").read_text()
        assert "<title>Clinical Records Summary</title>" in content

    def test_includes_chartjs(self, export_db, tmp_path):
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output)
        content = (tmp_path / "export.html").read_text()
        assert "Chart" in content

    def test_includes_conditions(self, export_db, tmp_path):
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output)
        content = (tmp_path / "export.html").read_text()
        assert "Colon cancer" in content
        assert "Active Conditions" in content

    def test_includes_medications(self, export_db, tmp_path):
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output)
        content = (tmp_path / "export.html").read_text()
        assert "Capecitabine" in content
        assert "Active Medications" in content

    def test_includes_labs(self, export_db, tmp_path):
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output, lookback_months=24)
        content = (tmp_path / "export.html").read_text()
        assert "CEA" in content
        assert "5.8" in content

    def test_includes_encounters(self, export_db, tmp_path):
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output, lookback_months=24)
        content = (tmp_path / "export.html").read_text()
        assert "Encounters" in content
        assert "office visit" in content

    def test_includes_imaging(self, export_db, tmp_path):
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output, lookback_months=24)
        content = (tmp_path / "export.html").read_text()
        assert "CT Abdomen" in content

    def test_includes_pathology(self, export_db, tmp_path):
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output)
        content = (tmp_path / "export.html").read_text()
        assert "Pathology Reports" in content
        assert "Adenocarcinoma" in content

    def test_includes_allergies(self, export_db, tmp_path):
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output)
        content = (tmp_path / "export.html").read_text()
        assert "Allergies" in content
        assert "Penicillin" in content

    def test_includes_data_overview(self, export_db, tmp_path):
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output)
        content = (tmp_path / "export.html").read_text()
        assert "Data Overview" in content

    def test_has_sortable_tables(self, export_db, tmp_path):
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output)
        content = (tmp_path / "export.html").read_text()
        assert 'class="sortable"' in content
        assert "sortTable" in content

    def test_has_collapsible_sections(self, export_db, tmp_path):
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output)
        content = (tmp_path / "export.html").read_text()
        assert "<details>" in content or "details" in EMBEDDED_CSS

    def test_empty_db(self, tmp_path):
        db = ChartfoldDB(str(tmp_path / "empty.db"))
        db.init_schema()
        output = str(tmp_path / "empty_export.html")
        export_html(db, output_path=output)
        content = (tmp_path / "empty_export.html").read_text()
        assert "<!DOCTYPE html>" in content
        assert "Clinical Records Summary" in content
        db.close()

    def test_abnormal_flag_highlighting(self, export_db, tmp_path):
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output, lookback_months=24)
        content = (tmp_path / "export.html").read_text()
        # Should have abnormal class for high/low flags
        assert 'class="abnormal"' in content


class TestSearchFunctionality:
    """Test global search functionality in HTML export."""

    def test_includes_search_input(self, export_db, tmp_path):
        """Export should include search input element."""
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output)
        content = (tmp_path / "export.html").read_text()
        assert 'id="global-search"' in content
        assert 'placeholder="Search all sections..."' in content

    def test_includes_search_clear_button(self, export_db, tmp_path):
        """Export should include search clear button."""
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output)
        content = (tmp_path / "export.html").read_text()
        assert 'id="search-clear"' in content

    def test_includes_search_results_span(self, export_db, tmp_path):
        """Export should include search results counter."""
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output)
        content = (tmp_path / "export.html").read_text()
        assert 'id="search-results"' in content

    def test_includes_search_css(self, export_db, tmp_path):
        """Export should include search-related CSS."""
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output)
        content = (tmp_path / "export.html").read_text()
        assert ".search-container" in content
        assert "#global-search" in content

    def test_includes_search_js(self, export_db, tmp_path):
        """Export should include initSearch JavaScript function."""
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output)
        content = (tmp_path / "export.html").read_text()
        assert "initSearch" in content
        assert "doSearch" in content

    def test_search_hidden_in_print_css(self, export_db, tmp_path):
        """Search container should be hidden in print media."""
        output = str(tmp_path / "export.html")
        export_html(export_db, output_path=output)
        content = (tmp_path / "export.html").read_text()
        assert ".search-container { display: none; }" in content


class TestExportHTMLFull:
    """Test export_html_full function."""

    def test_generates_file(self, export_db, tmp_path):
        output = str(tmp_path / "full_export.html")
        result = export_html_full(export_db, output_path=output)
        assert result == output
        assert (tmp_path / "full_export.html").exists()

    def test_includes_all_conditions(self, export_db, tmp_path):
        """Full export should include resolved conditions too."""
        output = str(tmp_path / "full.html")
        export_html_full(export_db, output_path=output)
        content = (tmp_path / "full.html").read_text()
        assert "Colon cancer" in content
        assert "Hypertension" in content  # Resolved condition

    def test_includes_all_medications(self, export_db, tmp_path):
        """Full export should include discontinued medications."""
        output = str(tmp_path / "full.html")
        export_html_full(export_db, output_path=output)
        content = (tmp_path / "full.html").read_text()
        assert "Capecitabine" in content
        assert "Aspirin" in content  # Discontinued

    def test_includes_clinical_notes(self, export_db, tmp_path):
        """Full export includes clinical notes section."""
        output = str(tmp_path / "full.html")
        export_html_full(export_db, output_path=output)
        content = (tmp_path / "full.html").read_text()
        assert "Clinical Notes" in content
        assert "Progress Note" in content

    def test_includes_procedures(self, export_db, tmp_path):
        """Full export includes procedures section."""
        output = str(tmp_path / "full.html")
        export_html_full(export_db, output_path=output)
        content = (tmp_path / "full.html").read_text()
        assert "Procedures" in content
        assert "hemicolectomy" in content

    def test_includes_vitals(self, export_db, tmp_path):
        """Full export includes vitals section."""
        output = str(tmp_path / "full.html")
        export_html_full(export_db, output_path=output)
        content = (tmp_path / "full.html").read_text()
        assert "Vitals" in content
        assert "Blood Pressure" in content

    def test_includes_immunizations(self, export_db, tmp_path):
        """Full export includes immunizations section."""
        output = str(tmp_path / "full.html")
        export_html_full(export_db, output_path=output)
        content = (tmp_path / "full.html").read_text()
        assert "Immunizations" in content
        assert "Flu Shot" in content

    def test_title_indicates_full_export(self, export_db, tmp_path):
        output = str(tmp_path / "full.html")
        export_html_full(export_db, output_path=output)
        content = (tmp_path / "full.html").read_text()
        assert "Full Export" in content

    def test_includes_all_lab_results(self, export_db, tmp_path):
        """Full export should not filter by lookback period."""
        output = str(tmp_path / "full.html")
        export_html_full(export_db, output_path=output)
        content = (tmp_path / "full.html").read_text()
        # Should have both CEA results (Dec 2025 and Nov 2025)
        assert "5.8" in content
        assert "4.2" in content


class TestSourceDocumentsSection:
    """Tests for source documents rendering in HTML export."""

    def test_renders_category_grouped_assets(self, tmp_db):
        """Source assets grouped by category appear in output."""
        db = tmp_db
        db.conn.execute(
            "INSERT INTO source_assets "
            "(source, asset_type, file_path, file_name, file_size_kb, "
            "title, encounter_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test", "pdf", "/tmp/lab.pdf", "lab.pdf", 50,
             "015_Laboratory", "2025-01-15"),
        )
        db.conn.commit()

        from chartfold.export_html import _render_source_documents_section
        html = _render_source_documents_section(db)
        assert "Laboratory" in html
        assert "lab.pdf" in html
        assert "Source Documents" in html

    def test_empty_when_no_assets(self, tmp_db):
        """Returns empty string when no source assets exist."""
        from chartfold.export_html import _render_source_documents_section
        html = _render_source_documents_section(tmp_db)
        assert html == ""

    def test_image_asset_gets_base64_tag(self, tmp_db, tmp_path):
        """Image assets should be rendered with base64 data URI."""
        db = tmp_db
        # Create a tiny valid PNG file
        import base64
        img_path = tmp_path / "test.png"
        # Minimal 1x1 PNG
        png_data = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
            "nGNgYPgPAAEDAQAIicLsAAAAASUVORK5CYII="
        )
        img_path.write_bytes(png_data)

        db.conn.execute(
            "INSERT INTO source_assets "
            "(source, asset_type, file_path, file_name, file_size_kb, "
            "title, encounter_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test", "png", str(img_path), "test.png", 1,
             "CT Scan", "2025-01-15"),
        )
        db.conn.commit()

        from chartfold.export_html import _render_source_documents_section
        html = _render_source_documents_section(db)
        assert "data:image/png;base64," in html
        assert "<img" in html

    def test_pdf_gets_link_not_img(self, tmp_db):
        """PDF assets get a link, not an img tag."""
        db = tmp_db
        db.conn.execute(
            "INSERT INTO source_assets "
            "(source, asset_type, file_path, file_name, file_size_kb, "
            "title, encounter_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test", "pdf", "/tmp/report.pdf", "report.pdf", 85,
             "Lab Report", "2025-01-15"),
        )
        db.conn.commit()

        from chartfold.export_html import _render_source_documents_section
        html = _render_source_documents_section(db)
        assert "<a " in html
        assert "report.pdf" in html
        assert "<img" not in html  # PDFs should NOT get img tags


class TestEncodeImageBase64:
    """Tests for base64 image encoding helper."""

    def test_valid_png(self, tmp_path):
        """Valid PNG file returns data URI."""
        import base64
        img_path = tmp_path / "test.png"
        png_data = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
            "nGNgYPgPAAEDAQAIicLsAAAAASUVORK5CYII="
        )
        img_path.write_bytes(png_data)

        from chartfold.export_html import _encode_image_base64
        result = _encode_image_base64(str(img_path))
        assert result.startswith("data:image/png;base64,")

    def test_missing_file_returns_empty(self):
        """Missing file returns empty string."""
        from chartfold.export_html import _encode_image_base64
        assert _encode_image_base64("/nonexistent/file.png") == ""

    def test_unsupported_type_returns_empty(self, tmp_path):
        """Non-image file returns empty string."""
        p = tmp_path / "test.pdf"
        p.write_bytes(b"fake pdf content")
        from chartfold.export_html import _encode_image_base64
        assert _encode_image_base64(str(p)) == ""


class TestLinkedAssetsOnCards:
    """Tests for linked source assets displayed on imaging/pathology cards."""

    # Minimal 1x1 PNG for tests
    _PNG_B64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
        "nGNgYPgPAAEDAQAIicLsAAAAASUVORK5CYII="
    )

    def _insert_imaging_report(self, db, study_name="CT Abdomen", study_date="2025-12-01"):
        """Insert an imaging report and return its row id."""
        db.conn.execute(
            "INSERT INTO imaging_reports (source, study_name, modality, study_date, impression) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test_source", study_name, "CT", study_date, "No recurrence."),
        )
        db.conn.commit()
        row = db.query("SELECT id FROM imaging_reports ORDER BY id DESC LIMIT 1")
        return row[0]["id"]

    def _insert_pathology_report(self, db, report_date="2024-07-03"):
        """Insert a pathology report and return its row id."""
        db.conn.execute(
            "INSERT INTO pathology_reports (source, report_date, specimen, diagnosis) "
            "VALUES (?, ?, ?, ?)",
            ("test_source", report_date, "Right colon", "Adenocarcinoma"),
        )
        db.conn.commit()
        row = db.query("SELECT id FROM pathology_reports ORDER BY id DESC LIMIT 1")
        return row[0]["id"]

    def _insert_asset(self, db, ref_table, ref_id, asset_type, file_path, file_name,
                      encounter_date="", source="test_source"):
        db.conn.execute(
            "INSERT INTO source_assets "
            "(source, asset_type, file_path, file_name, file_size_kb, "
            "title, encounter_date, ref_table, ref_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (source, asset_type, file_path, file_name, 10,
             file_name, encounter_date, ref_table, ref_id),
        )
        db.conn.commit()

    def test_imaging_card_shows_linked_image(self, tmp_db, tmp_path):
        """Imaging card with a linked PNG shows a base64 img tag."""
        import base64
        img_path = tmp_path / "scan.png"
        img_path.write_bytes(base64.b64decode(self._PNG_B64))

        img_id = self._insert_imaging_report(tmp_db)
        self._insert_asset(
            tmp_db, "imaging_reports", img_id, "png",
            str(img_path), "scan.png", encounter_date="2025-12-01",
        )

        from chartfold.export_html import _render_imaging_section
        html = _render_imaging_section(tmp_db, lookback_date="")
        assert "data:image/png;base64," in html
        assert "<img" in html
        assert "CT Abdomen" in html

    def test_imaging_card_shows_linked_pdf(self, tmp_db, tmp_path):
        """Imaging card with a linked PDF shows a download link."""
        img_id = self._insert_imaging_report(tmp_db)
        self._insert_asset(
            tmp_db, "imaging_reports", img_id, "pdf",
            "/tmp/report.pdf", "report.pdf", encounter_date="2025-12-01",
        )

        from chartfold.export_html import _render_imaging_section
        html = _render_imaging_section(tmp_db, lookback_date="")
        assert "report.pdf" in html
        assert "<a " in html
        assert "CT Abdomen" in html

    def test_pathology_card_shows_linked_image(self, tmp_db, tmp_path):
        """Pathology card with a linked PNG shows a base64 img tag."""
        import base64
        img_path = tmp_path / "slide.png"
        img_path.write_bytes(base64.b64decode(self._PNG_B64))

        path_id = self._insert_pathology_report(tmp_db)
        self._insert_asset(
            tmp_db, "pathology_reports", path_id, "png",
            str(img_path), "slide.png", encounter_date="2024-07-03",
        )

        from chartfold.export_html import _render_pathology_section
        html = _render_pathology_section(tmp_db)
        assert "data:image/png;base64," in html
        assert "<img" in html
        assert "Adenocarcinoma" in html

    def test_imaging_card_no_assets_unchanged(self, tmp_db):
        """Imaging card without linked assets renders normally."""
        self._insert_imaging_report(tmp_db)

        from chartfold.export_html import _render_imaging_section
        html = _render_imaging_section(tmp_db, lookback_date="")
        assert "CT Abdomen" in html
        assert "No recurrence" in html
        # No asset-related content
        assert "Linked" not in html or "Attachments" not in html

    def test_imaging_fallback_to_date_source_match(self, tmp_db, tmp_path):
        """When no ref_id match, fall back to date+source matching."""
        import base64
        img_path = tmp_path / "fallback.png"
        img_path.write_bytes(base64.b64decode(self._PNG_B64))

        self._insert_imaging_report(tmp_db, study_date="2025-12-01")
        # Insert asset with no ref_id but matching date and source
        tmp_db.conn.execute(
            "INSERT INTO source_assets "
            "(source, asset_type, file_path, file_name, file_size_kb, "
            "title, encounter_date, ref_table) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("test_source", "png", str(img_path), "fallback.png", 5,
             "fallback.png", "2025-12-01", "imaging_reports"),
        )
        tmp_db.conn.commit()

        from chartfold.export_html import _render_imaging_section
        html = _render_imaging_section(tmp_db, lookback_date="")
        assert "data:image/png;base64," in html

    def test_get_linked_assets_ref_id_match(self, tmp_db):
        """_get_linked_assets returns assets matching ref_table + ref_id."""
        img_id = self._insert_imaging_report(tmp_db)
        self._insert_asset(
            tmp_db, "imaging_reports", img_id, "pdf",
            "/tmp/scan.pdf", "scan.pdf",
        )

        from chartfold.export_html import _get_linked_assets
        assets = _get_linked_assets(tmp_db, "imaging_reports", img_id)
        assert len(assets) == 1
        assert assets[0]["file_name"] == "scan.pdf"

    def test_get_linked_assets_fallback(self, tmp_db):
        """_get_linked_assets falls back to date+source when no ref_id match."""
        self._insert_imaging_report(tmp_db, study_date="2025-12-01")
        # Asset with ref_table but no ref_id
        tmp_db.conn.execute(
            "INSERT INTO source_assets "
            "(source, asset_type, file_path, file_name, file_size_kb, "
            "title, encounter_date, ref_table) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("test_source", "pdf", "/tmp/fallback.pdf", "fallback.pdf", 20,
             "fallback.pdf", "2025-12-01", "imaging_reports"),
        )
        tmp_db.conn.commit()

        from chartfold.export_html import _get_linked_assets
        assets = _get_linked_assets(
            tmp_db, "imaging_reports", 999, date="2025-12-01", source="test_source"
        )
        assert len(assets) == 1
        assert assets[0]["file_name"] == "fallback.pdf"

    def test_get_linked_assets_empty(self, tmp_db):
        """_get_linked_assets returns empty list when no matches."""
        from chartfold.export_html import _get_linked_assets
        assets = _get_linked_assets(tmp_db, "imaging_reports", 999)
        assert assets == []

    def test_render_linked_assets_html_image(self, tmp_path):
        """_render_linked_assets_html renders img tag for image assets."""
        import base64
        img_path = tmp_path / "test.png"
        img_path.write_bytes(base64.b64decode(self._PNG_B64))

        from chartfold.export_html import _render_linked_assets_html
        assets = [{"asset_type": "png", "file_path": str(img_path), "file_name": "test.png"}]
        html = _render_linked_assets_html(assets)
        assert "data:image/png;base64," in html
        assert "<img" in html

    def test_render_linked_assets_html_pdf(self):
        """_render_linked_assets_html renders link for PDF assets."""
        from chartfold.export_html import _render_linked_assets_html
        assets = [{"asset_type": "pdf", "file_path": "/tmp/report.pdf", "file_name": "report.pdf"}]
        html = _render_linked_assets_html(assets)
        assert "<a " in html
        assert "report.pdf" in html

    def test_render_linked_assets_html_empty(self):
        """_render_linked_assets_html returns empty string for no assets."""
        from chartfold.export_html import _render_linked_assets_html
        assert _render_linked_assets_html([]) == ""


class TestAnalysisSection:
    """Tests for analysis section rendering in HTML export."""

    def test_analysis_renders_markdown_content(self, tmp_path):
        """Analysis markdown files should render as HTML sections."""
        analysis_dir = tmp_path / "analysis"
        analysis_dir.mkdir()
        (analysis_dir / "summary.md").write_text("# Treatment Summary\n\nChemo completed.")

        from chartfold.export_html import _render_analysis_section
        html = _render_analysis_section(analysis_dir)
        assert "Treatment Summary" in html
        assert "Chemo completed" in html

    def test_analysis_no_dir_returns_empty(self):
        """No analysis dir should return empty string."""
        from chartfold.export_html import _render_analysis_section
        assert _render_analysis_section(None) == ""

    def test_analysis_empty_dir_returns_empty(self, tmp_path):
        """Empty dir should return empty string."""
        analysis_dir = tmp_path / "analysis"
        analysis_dir.mkdir()
        from chartfold.export_html import _render_analysis_section
        assert _render_analysis_section(analysis_dir) == ""

    def test_analysis_strips_frontmatter(self, tmp_path):
        """Files with YAML frontmatter should have it stripped."""
        analysis_dir = tmp_path / "analysis"
        analysis_dir.mkdir()
        (analysis_dir / "report.md").write_text(
            '---\ntitle: "Report"\ntags: [test]\n---\n\nReport content here.'
        )
        from chartfold.export_html import _render_analysis_section
        html = _render_analysis_section(analysis_dir)
        assert "Report content here" in html
        assert "tags:" not in html

    def test_analysis_multiple_files(self, tmp_path):
        """Multiple files should each get their own card."""
        analysis_dir = tmp_path / "analysis"
        analysis_dir.mkdir()
        (analysis_dir / "file1.md").write_text("# First\n\nContent one.")
        (analysis_dir / "file2.md").write_text("# Second\n\nContent two.")
        from chartfold.export_html import _render_analysis_section
        html = _render_analysis_section(analysis_dir)
        assert "First" in html
        assert "Second" in html
        assert "Content one" in html
        assert "Content two" in html

    def test_analysis_ignores_non_md_files(self, tmp_path):
        """Non-markdown files should be ignored."""
        analysis_dir = tmp_path / "analysis"
        analysis_dir.mkdir()
        (analysis_dir / "notes.txt").write_text("Text file")
        (analysis_dir / "data.csv").write_text("a,b,c")
        from chartfold.export_html import _render_analysis_section
        assert _render_analysis_section(analysis_dir) == ""


class TestBasicMarkdownToHtml:
    """Tests for basic markdown to HTML conversion."""

    def test_headings(self):
        from chartfold.export_html import _basic_markdown_to_html
        result = _basic_markdown_to_html("# Heading One\n## Heading Two\n### Heading Three")
        assert "<h3>" in result
        assert "Heading One" in result
        assert "Heading Two" in result
        assert "<h4>" in result
        assert "Heading Three" in result

    def test_paragraphs(self):
        from chartfold.export_html import _basic_markdown_to_html
        result = _basic_markdown_to_html("Some text here.")
        assert "<p>Some text here.</p>" in result

    def test_lists(self):
        from chartfold.export_html import _basic_markdown_to_html
        result = _basic_markdown_to_html("- Item one\n- Item two")
        assert "<ul>" in result
        assert "<li>Item one</li>" in result
        assert "<li>Item two</li>" in result
        assert "</ul>" in result

    def test_empty_input(self):
        from chartfold.export_html import _basic_markdown_to_html
        result = _basic_markdown_to_html("")
        assert result == ""

    def test_html_escaping(self):
        from chartfold.export_html import _basic_markdown_to_html
        result = _basic_markdown_to_html("Test <script>alert(1)</script>")
        assert "&lt;script&gt;" in result
        assert "<script>" not in result
