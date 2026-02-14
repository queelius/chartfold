"""Tests for chartfold.core modules."""

import json

import pytest

from chartfold.sources.base import detect_source, resolve_epic_dir

from chartfold.core.cda import (
    NS,
    format_date,
    get_encounter_date,
    get_sections,
    get_title,
    parse_doc,
    section_text,
)
from chartfold.core.fhir import parse_fhir_bundle
from chartfold.core.utils import (
    categorize_asset_title,
    deduplicate_by_key,
    derive_source_name,
    is_image_asset,
    normalize_date_to_iso,
    parse_iso_date,
    parse_narrative_date,
    try_parse_numeric,
)


# ---------------------------------------------------------------------------
# format_date tests
# ---------------------------------------------------------------------------


class TestFormatDate:
    def test_iso_datetime_with_tz(self):
        assert format_date("2025-06-30T13:25:00+00:00") == "06/30/2025"

    def test_iso_datetime_no_tz(self):
        assert format_date("2025-06-30T13:25:00") == "06/30/2025"

    def test_iso_date_only(self):
        assert format_date("2025-06-30") == "06/30/2025"

    def test_yyyymmdd(self):
        assert format_date("20211123") == "11/23/2021"

    def test_yyyymmdd_with_time(self):
        assert format_date("20220201073445-0600") == "02/01/2022"

    def test_empty_string(self):
        assert format_date("") == ""

    def test_none_like(self):
        assert format_date("") == ""


# ---------------------------------------------------------------------------
# parse_narrative_date tests
# ---------------------------------------------------------------------------


class TestParseNarrativeDate:
    def test_ordinal_date(self):
        assert parse_narrative_date("November 23rd, 2021 2:37pm") == "2021-11-23"

    def test_first(self):
        assert parse_narrative_date("July 1st, 2024 11:46am") == "2024-07-01"

    def test_second(self):
        assert parse_narrative_date("January 2nd, 2023") == "2023-01-02"

    def test_plain_date(self):
        assert parse_narrative_date("December 30, 2021 6:00am") == "2021-12-30"

    def test_no_time(self):
        assert parse_narrative_date("March 16, 2022") == "2022-03-16"

    def test_invalid(self):
        assert parse_narrative_date("not a date") == ""

    def test_empty(self):
        assert parse_narrative_date("") == ""


# ---------------------------------------------------------------------------
# normalize_date_to_iso tests
# ---------------------------------------------------------------------------


class TestNormalizeDateToIso:
    def test_iso_date(self):
        assert normalize_date_to_iso("2025-06-30") == "2025-06-30"

    def test_iso_datetime(self):
        assert normalize_date_to_iso("2025-06-30T13:25:00+00:00") == "2025-06-30"

    def test_yyyymmdd(self):
        assert normalize_date_to_iso("20211123") == "2021-11-23"

    def test_yyyymmdd_with_time_tz(self):
        assert normalize_date_to_iso("20220201073445-0600") == "2022-02-01"

    def test_mm_dd_yyyy(self):
        assert normalize_date_to_iso("01/15/2026") == "2026-01-15"

    def test_mm_dd_yyyy_single_digits(self):
        assert normalize_date_to_iso("1/5/2026") == "2026-01-05"

    def test_narrative_date(self):
        assert normalize_date_to_iso("November 23rd, 2021 2:37pm") == "2021-11-23"

    def test_narrative_no_ordinal(self):
        assert normalize_date_to_iso("March 16, 2022") == "2022-03-16"

    def test_empty(self):
        assert normalize_date_to_iso("") == ""

    def test_none_like(self):
        assert normalize_date_to_iso("   ") == ""

    def test_unparseable(self):
        assert normalize_date_to_iso("not a date") == ""


# ---------------------------------------------------------------------------
# try_parse_numeric tests
# ---------------------------------------------------------------------------


class TestTryParseNumeric:
    def test_simple_float(self):
        assert try_parse_numeric("5.8") == 5.8

    def test_integer(self):
        assert try_parse_numeric("120") == 120.0

    def test_less_than(self):
        assert try_parse_numeric("<0.5") == 0.5

    def test_greater_than(self):
        assert try_parse_numeric(">100") == 100.0

    def test_less_equal(self):
        assert try_parse_numeric("<=3.0") == 3.0

    def test_positive_text(self):
        assert try_parse_numeric("positive") is None

    def test_empty(self):
        assert try_parse_numeric("") is None

    def test_none(self):
        assert try_parse_numeric(None) is None


# ---------------------------------------------------------------------------
# parse_iso_date tests
# ---------------------------------------------------------------------------


class TestParseIsoDate:
    def test_full_iso(self):
        assert parse_iso_date("2025-06-30T13:25:00+00:00") == "2025-06-30"

    def test_date_only(self):
        assert parse_iso_date("2025-06-30") == "2025-06-30"

    def test_empty(self):
        assert parse_iso_date("") == ""


# ---------------------------------------------------------------------------
# deduplicate_by_key tests
# ---------------------------------------------------------------------------


class TestDeduplicateByKey:
    def test_basic_dedup(self):
        items = [
            {"name": "A", "val": 1},
            {"name": "B", "val": 2},
            {"name": "A", "val": 1},
        ]
        result = deduplicate_by_key(items, key_func=lambda x: (x["name"], x["val"]))
        assert len(result) == 2

    def test_with_sort(self):
        items = [
            {"name": "B", "val": 2},
            {"name": "A", "val": 1},
        ]
        result = deduplicate_by_key(
            items,
            key_func=lambda x: x["name"],
            sort_key=lambda x: x["name"],
        )
        assert result[0]["name"] == "A"

    def test_empty(self):
        assert deduplicate_by_key([], key_func=lambda x: x) == []


# ---------------------------------------------------------------------------
# CDA XML parsing tests
# ---------------------------------------------------------------------------

SAMPLE_CDA = f"""<?xml version="1.0" encoding="UTF-8"?>
<ClinicalDocument xmlns="{NS}">
  <title>Test Document</title>
  <component>
    <structuredBody>
      <component>
        <section>
          <title>Results</title>
          <text>
            <list>
              <item>
                <caption>CEA - Final result (01/15/2026  10:30 AM CST)</caption>
                <table>
                  <tbody>
                    <tr>
                      <td>CEA</td>
                      <td>1.8</td>
                      <td>0.0-5.0</td>
                    </tr>
                  </tbody>
                </table>
              </item>
            </list>
          </text>
        </section>
        <section>
          <title>Active Problems</title>
          <text>Colon cancer</text>
        </section>
      </component>
    </structuredBody>
  </component>
  <componentOf>
    <encompassingEncounter>
      <effectiveTime>
        <low value="20260115"/>
        <high value="20260115"/>
      </effectiveTime>
    </encompassingEncounter>
  </componentOf>
</ClinicalDocument>"""


class TestCDAParsing:
    @pytest.fixture
    def cda_file(self, tmp_path):
        f = tmp_path / "test.xml"
        f.write_text(SAMPLE_CDA)
        return str(f)

    def test_parse_doc(self, cda_file):
        root = parse_doc(cda_file)
        assert root is not None

    def test_get_title(self, cda_file):
        root = parse_doc(cda_file)
        assert get_title(root) == "Test Document"

    def test_get_encounter_date(self, cda_file):
        root = parse_doc(cda_file)
        assert get_encounter_date(root) == "20260115"

    def test_get_sections(self, cda_file):
        root = parse_doc(cda_file)
        sections = get_sections(root)
        assert "Results" in sections
        assert "Active Problems" in sections

    def test_section_text(self, cda_file):
        root = parse_doc(cda_file)
        sections = get_sections(root)
        text = section_text(sections["Active Problems"])
        assert "Colon cancer" in text


# ---------------------------------------------------------------------------
# FHIR parsing tests
# ---------------------------------------------------------------------------


SAMPLE_FHIR = {
    "resourceType": "Bundle",
    "type": "searchset",
    "total": 3,
    "entry": [
        {
            "resource": {
                "resourceType": "Patient",
                "id": "test-patient",
                "name": [{"given": ["John"], "family": "Doe"}],
                "birthDate": "1975-06-15",
                "gender": "male",
            }
        },
        {
            "resource": {
                "resourceType": "Observation",
                "id": "obs-cea",
                "status": "final",
                "category": [{"coding": [{"code": "laboratory"}]}],
                "code": {
                    "text": "Carcinoembryonic Antigen",
                    "coding": [{"system": "http://loinc.org", "code": "IMO0002", "display": "CEA"}],
                },
                "effectiveDateTime": "2025-06-30T13:25:00+00:00",
                "valueQuantity": {"value": 5.8, "unit": "ng/mL"},
                "referenceRange": [{"text": "0.0-3.0"}],
                "note": [{"text": "Test note"}],
            }
        },
        {
            "resource": {
                "resourceType": "Condition",
                "id": "cond-1",
                "code": {
                    "text": "Colon cancer",
                    "coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "C18.9"}],
                },
                "clinicalStatus": {"coding": [{"code": "active"}]},
            }
        },
        {
            "resource": {
                "resourceType": "Immunization",
                "id": "imm-1",
                "status": "completed",
                "vaccineCode": {
                    "text": "Influenza vaccine",
                    "coding": [
                        {
                            "system": "http://hl7.org/fhir/sid/cvx",
                            "code": "158",
                            "display": "Influenza, injectable, quadrivalent",
                        }
                    ],
                },
                "occurrenceDateTime": "2025-10-15T10:00:00+00:00",
                "lotNumber": "ABC123",
            }
        },
        {
            "resource": {
                "resourceType": "Immunization",
                "id": "imm-2",
                "status": "completed",
                "vaccineCode": {
                    "text": "COVID-19 vaccine",
                    "coding": [
                        {
                            "system": "http://hl7.org/fhir/sid/cvx",
                            "code": "213",
                            "display": "SARS-COV-2 (COVID-19) vaccine, mRNA",
                        }
                    ],
                },
                "occurrenceDateTime": "2025-04-01",
            }
        },
    ],
}


class TestFHIRParsing:
    @pytest.fixture
    def fhir_file(self, tmp_path):
        f = tmp_path / "fhir.json"
        f.write_text(json.dumps(SAMPLE_FHIR))
        return str(f)

    def test_parse_patient(self, fhir_file):
        data = parse_fhir_bundle(fhir_file)
        assert data["patient"]["name"] == "John Doe"
        assert data["patient"]["gender"] == "male"

    def test_parse_observation(self, fhir_file):
        data = parse_fhir_bundle(fhir_file)
        assert len(data["observations"]) == 1
        obs = data["observations"][0]
        assert obs["text"] == "Carcinoembryonic Antigen"
        assert obs["value"] == 5.8
        assert obs["unit"] == "ng/mL"
        assert obs["ref_range"] == "0.0-3.0"
        assert obs["date_iso"] == "2025-06-30"

    def test_parse_condition(self, fhir_file):
        data = parse_fhir_bundle(fhir_file)
        assert len(data["conditions"]) == 1
        cond = data["conditions"][0]
        assert cond["text"] == "Colon cancer"
        assert cond["icd_code"] == "C18.9"
        assert cond["clinical_status"] == "active"

    def test_resource_counts(self, fhir_file):
        data = parse_fhir_bundle(fhir_file)
        assert data["resource_counts"]["Patient"] == 1
        assert data["resource_counts"]["Observation"] == 1
        assert data["resource_counts"]["Condition"] == 1
        assert data["resource_counts"]["Immunization"] == 2

    def test_parse_immunizations(self, fhir_file):
        data = parse_fhir_bundle(fhir_file)
        assert len(data["immunizations"]) == 2
        imm = data["immunizations"][0]
        assert imm["name"] == "Influenza vaccine"
        assert imm["cvx_code"] == "158"
        assert imm["date"] == "2025-10-15T10:00:00+00:00"
        assert imm["date_iso"] == "2025-10-15"
        assert imm["status"] == "completed"
        assert imm["lot"] == "ABC123"

    def test_parse_immunization_no_lot(self, fhir_file):
        data = parse_fhir_bundle(fhir_file)
        imm2 = data["immunizations"][1]
        assert imm2["name"] == "COVID-19 vaccine"
        assert imm2["cvx_code"] == "213"
        assert imm2["date_iso"] == "2025-04-01"
        assert imm2["lot"] == ""

    def test_immunizations_key_present(self, fhir_file):
        data = parse_fhir_bundle(fhir_file)
        assert "immunizations" in data

    def test_immunizations_empty_when_none(self, tmp_path):
        """Ensure immunizations is an empty list when no Immunization resources exist."""
        bundle = {
            "resourceType": "Bundle",
            "type": "searchset",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "p1",
                        "name": [{"given": ["Jane"], "family": "Smith"}],
                        "birthDate": "1990-01-01",
                        "gender": "female",
                    }
                },
            ],
        }
        f = tmp_path / "no_imm.json"
        f.write_text(json.dumps(bundle))
        data = parse_fhir_bundle(str(f))
        assert data["immunizations"] == []


# ---------------------------------------------------------------------------
# Lab extractor tests
# ---------------------------------------------------------------------------


class TestCEAExtractors:
    def test_extract_cea_from_fhir(self):
        from chartfold.extractors.labs import extract_cea_from_fhir

        observations = [
            {
                "text": "Carcinoembryonic Antigen",
                "date": "2025-06-30T13:25:00+00:00",
                "date_iso": "2025-06-30",
                "value": 5.8,
                "unit": "ng/mL",
                "ref_range": "0.0-3.0",
                "notes": ["Test note"],
            },
            {
                "text": "Glucose",
                "date": "2025-06-30T13:25:00+00:00",
                "date_iso": "2025-06-30",
                "value": 95,
                "unit": "mg/dL",
                "ref_range": "70-100",
                "notes": [],
            },
        ]
        result = extract_cea_from_fhir(observations)
        assert len(result) == 1
        assert result[0]["value"] == 5.8
        assert result[0]["source"] == "FHIR"

    def test_extract_cea_from_labs(self):
        from chartfold.extractors.labs import extract_cea_from_labs

        labs = [
            {
                "test": "Carcinoembryonic Antigen",
                "date_iso": "2021-11-23",
                "value": "1.4",
                "unit": "ng/mL",
                "ref_range": "0.0-3.0",
            },
            {
                "test": "White Blood Count",
                "date_iso": "2021-11-23",
                "value": "3.8",
                "unit": "K/mm3",
                "ref_range": "4.5-10.0",
            },
        ]
        result = extract_cea_from_labs(labs)
        assert len(result) == 1
        assert result[0]["value"] == "1.4"
        assert result[0]["source"] == "CCDA"

    def test_extract_cea_dedup(self):
        from chartfold.extractors.labs import extract_cea_from_labs

        labs = [
            {"test": "Carcinoembryonic Antigen", "date_iso": "2021-11-23", "value": "1.4"},
            {"test": "Carcinoembryonic Antigen", "date_iso": "2021-11-23", "value": "1.4"},
        ]
        result = extract_cea_from_labs(labs)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Markdown formatter tests
# ---------------------------------------------------------------------------


class TestMarkdownWriter:
    def test_heading(self):
        from chartfold.formatters.markdown import MarkdownWriter

        md = MarkdownWriter()
        md.heading("Test", level=2)
        assert "## Test" in md.text()

    def test_table(self):
        from chartfold.formatters.markdown import MarkdownWriter

        md = MarkdownWriter()
        md.table(["A", "B"], [["1", "2"], ["3", "4"]])
        text = md.text()
        assert "| A | B |" in text
        assert "| 1 | 2 |" in text

    def test_separator(self):
        from chartfold.formatters.markdown import MarkdownWriter

        md = MarkdownWriter()
        md.separator()
        assert "---" in md.text()

    def test_write_to_file(self, tmp_path):
        from chartfold.formatters.markdown import MarkdownWriter

        md = MarkdownWriter()
        md.heading("Test")
        md.w("Content")
        out = tmp_path / "test.md"
        lines = md.write_to_file(str(out))
        assert lines == 3
        assert out.read_text().startswith("## Test")

    def test_format_epic_output(self):
        from chartfold.formatters.markdown import format_epic_output

        data = {
            "inventory": [
                {
                    "doc_id": "DOC0001",
                    "date": "N/A",
                    "title": "Test",
                    "size_kb": 100,
                    "sections": ["Results"],
                },
            ],
            "errors": [],
            "cea_values": [{"date": "01/15/2026", "value": "1.8", "ref_range": "<=5.0"}],
            "lab_results": [],
            "imaging_reports": [],
            "pathology_reports": [],
            "clinical_notes": [],
            "medications": "",
            "problems": "",
            "encounter_timeline": [],
        }
        text = format_epic_output(data)
        assert "Extracted Clinical Data" in text
        assert "1.8" in text
        assert "DOC0001" in text


# ---------------------------------------------------------------------------
# Source Auto-Detection
# ---------------------------------------------------------------------------


class TestDetectSource:
    def test_epic_direct(self, tmp_path):
        (tmp_path / "DOC0001.XML").write_text("<xml/>")
        (tmp_path / "DOC0002.XML").write_text("<xml/>")
        assert detect_source(str(tmp_path)) == "epic"

    def test_epic_ihe_xdm(self, tmp_path):
        doc_dir = tmp_path / "IHE_XDM" / "Alexander1"
        doc_dir.mkdir(parents=True)
        (doc_dir / "DOC0001.XML").write_text("<xml/>")
        assert detect_source(str(tmp_path)) == "epic"

    def test_meditech_fhir(self, tmp_path):
        (tmp_path / "US Core FHIR Resources.json").write_text("{}")
        assert detect_source(str(tmp_path)) == "meditech"

    def test_meditech_ccda_dir(self, tmp_path):
        (tmp_path / "CCDA").mkdir()
        assert detect_source(str(tmp_path)) == "meditech"

    def test_athena_document_xml(self, tmp_path):
        doc_dir = tmp_path / "Document_XML"
        doc_dir.mkdir()
        (doc_dir / "AmbulatorySummary_alltime.xml").write_text("<xml/>")
        assert detect_source(str(tmp_path)) == "athena"

    def test_athena_direct(self, tmp_path):
        (tmp_path / "AmbulatorySummary_alltime.xml").write_text("<xml/>")
        assert detect_source(str(tmp_path)) == "athena"

    def test_unknown_returns_none(self, tmp_path):
        (tmp_path / "random.txt").write_text("hello")
        assert detect_source(str(tmp_path)) is None

    def test_empty_dir_returns_none(self, tmp_path):
        assert detect_source(str(tmp_path)) is None

    def test_nonexistent_dir_returns_none(self):
        assert detect_source("/nonexistent/path/xyz") is None


class TestResolveEpicDir:
    def test_direct_docs(self, tmp_path):
        (tmp_path / "DOC0001.XML").write_text("<xml/>")
        assert resolve_epic_dir(str(tmp_path)) == str(tmp_path)

    def test_ihe_xdm_traversal(self, tmp_path):
        doc_dir = tmp_path / "IHE_XDM" / "Alexander1"
        doc_dir.mkdir(parents=True)
        (doc_dir / "DOC0001.XML").write_text("<xml/>")
        assert resolve_epic_dir(str(tmp_path)) == str(doc_dir)

    def test_no_docs_returns_input(self, tmp_path):
        assert resolve_epic_dir(str(tmp_path)) == str(tmp_path)


# ---------------------------------------------------------------------------
# derive_source_name tests
# ---------------------------------------------------------------------------


class TestDeriveSourceName:
    def test_simple_directory(self):
        assert derive_source_name("/path/to/anderson", "epic") == "epic_anderson"

    def test_with_trailing_slash(self):
        assert derive_source_name("/path/to/anderson/", "epic") == "epic_anderson"

    def test_meditech_type(self):
        assert derive_source_name("/exports/siteman", "meditech") == "meditech_siteman"

    def test_athena_type(self):
        assert derive_source_name("/exports/sihf_jan26", "athena") == "athena_sihf_jan26"

    def test_skips_common_subdirs_ccda(self):
        """Should go up one level for common subdirectory names."""
        assert derive_source_name("/exports/siteman/CCDA", "meditech") == "meditech_siteman"

    def test_skips_common_subdirs_document_xml(self):
        assert derive_source_name("/exports/sihf/Document_XML", "athena") == "athena_sihf"

    def test_skips_common_subdirs_ihe_xdm(self):
        assert derive_source_name("/exports/anderson/IHE_XDM", "epic") == "epic_anderson"

    def test_skips_common_subdirs_alexander1(self):
        """Alexander1 is a common Epic subdirectory under IHE_XDM."""
        assert derive_source_name("/exports/anderson/IHE_XDM/Alexander1", "epic") == "epic_ihe_xdm"

    def test_normalizes_spaces(self):
        assert derive_source_name("/path/to/my export", "epic") == "epic_my_export"

    def test_normalizes_special_chars(self):
        assert (
            derive_source_name("/path/to/dr-tan's_records", "meditech")
            == "meditech_dr_tan_s_records"
        )

    def test_normalizes_case(self):
        assert derive_source_name("/path/to/Anderson", "epic") == "epic_anderson"

    def test_collapses_multiple_underscores(self):
        assert derive_source_name("/path/to/foo--bar", "epic") == "epic_foo_bar"

    def test_strips_leading_trailing_underscores(self):
        assert derive_source_name("/path/to/_export_", "epic") == "epic_export"

    def test_empty_path_fallback(self):
        assert derive_source_name("", "epic") == "epic_unknown"

    def test_root_path_fallback(self):
        assert derive_source_name("/", "meditech") == "meditech_unknown"


# ---------------------------------------------------------------------------
# Asset helper tests
# ---------------------------------------------------------------------------


class TestAssetHelpers:
    def test_is_image_png(self):
        assert is_image_asset("png") is True

    def test_is_image_jpg(self):
        assert is_image_asset("jpg") is True

    def test_is_image_tiff(self):
        assert is_image_asset("tiff") is True

    def test_is_not_image_pdf(self):
        assert is_image_asset("pdf") is False

    def test_is_not_image_html(self):
        assert is_image_asset("html") is False

    def test_categorize_laboratory(self):
        assert categorize_asset_title("015_Laboratory") == "Laboratory"

    def test_categorize_surgical(self):
        assert categorize_asset_title("010_Surgical_Services") == "Surgical Services"

    def test_categorize_admissions(self):
        assert categorize_asset_title("000_Admissions") == "Admissions"

    def test_categorize_discharge(self):
        assert categorize_asset_title("006_Discharge_Transfer_Document") == "Discharge"

    def test_categorize_patient_care(self):
        assert categorize_asset_title("018_Patient_Care_Notes") == "Patient Care Notes"

    def test_categorize_medications(self):
        assert categorize_asset_title("019_Medications") == "Medications"

    def test_categorize_orders(self):
        assert categorize_asset_title("020_Orders") == "Orders"

    def test_categorize_consents(self):
        assert categorize_asset_title("003_Consents") == "Consents"

    def test_categorize_unknown_title(self):
        assert categorize_asset_title("Random title") == "General"

    def test_categorize_empty(self):
        assert categorize_asset_title("") == "General"
