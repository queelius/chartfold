"""Tests for pathology extraction and linkage."""

import base64

import pytest

from chartfold.core.fhir import decode_presented_form
from chartfold.extractors.pathology import (
    _days_between,
    _name_similarity,
    link_pathology_to_procedures,
    parse_pathology_sections,
)


class TestDecodePresented:
    def test_decode_plain_text(self):
        text = "Diagnosis: Adenocarcinoma, invasive."
        b64 = base64.b64encode(text.encode()).decode()
        result = decode_presented_form(b64, "text/plain")
        assert "Adenocarcinoma" in result

    def test_decode_html(self):
        html = "<html><body><p>Diagnosis: <b>Adenocarcinoma</b></p></body></html>"
        b64 = base64.b64encode(html.encode()).decode()
        result = decode_presented_form(b64, "text/html")
        assert "Adenocarcinoma" in result
        assert "<b>" not in result

    def test_empty_data(self):
        assert decode_presented_form("", "text/plain") == ""


class TestParsePathologySections:
    def test_extract_diagnosis(self):
        text = """
        SURGICAL PATHOLOGY REPORT
        Diagnosis: Invasive adenocarcinoma of the colon, moderately differentiated.
        pT4aN1a, 6/23 lymph nodes positive.
        Gross Description: Sigmoid colon segment, 30 cm in length.
        Microscopic Description: Tumor invades through muscularis propria.
        """
        sections = parse_pathology_sections(text)
        assert "adenocarcinoma" in sections["diagnosis"].lower()

    def test_extract_staging(self):
        text = "Stage pT4aN1a. Tumor invades through serosa."
        sections = parse_pathology_sections(text)
        assert sections["staging"] == "pT4aN1a"

    def test_extract_margins(self):
        text = "Surgical margins are negative for malignancy."
        sections = parse_pathology_sections(text)
        assert "negative" in sections["margins"].lower()

    def test_extract_lymph_nodes(self):
        text = "4/14 lymph nodes positive for metastatic carcinoma."
        sections = parse_pathology_sections(text)
        assert "4/14" in sections["lymph_nodes"]

    def test_empty_text(self):
        sections = parse_pathology_sections("")
        assert all(v == "" for v in sections.values())


class TestLinkage:
    def test_link_by_date(self):
        pathology = [
            {"id": 1, "report_date": "2021-12-30", "specimen": "colon", "diagnosis": "adenocarcinoma"},
        ]
        procedures = [
            {"id": 10, "procedure_date": "2021-12-29", "name": "sigmoid colectomy"},
            {"id": 11, "procedure_date": "2021-02-01", "name": "EGD"},
        ]
        links = link_pathology_to_procedures(pathology, procedures)
        assert len(links) == 1
        assert links[0] == (1, 10)

    def test_no_link_beyond_max_days(self):
        pathology = [
            {"id": 1, "report_date": "2025-01-01", "specimen": "liver", "diagnosis": "metastasis"},
        ]
        procedures = [
            {"id": 10, "procedure_date": "2024-01-01", "name": "liver resection"},
        ]
        links = link_pathology_to_procedures(pathology, procedures, max_days=14)
        assert len(links) == 0

    def test_empty_inputs(self):
        assert link_pathology_to_procedures([], []) == []


class TestHelpers:
    def test_days_between(self):
        assert _days_between("2021-12-29", "2021-12-30") == 1
        assert _days_between("2021-12-30", "2021-12-29") == 1
        assert _days_between("", "2021-12-30") is None

    def test_name_similarity(self):
        assert _name_similarity("colon resection", "sigmoid colectomy") > 0.2
        assert _name_similarity("", "test") == 0.0
