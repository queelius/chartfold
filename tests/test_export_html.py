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
