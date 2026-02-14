"""Tests for core FHIR and CDA parsers — new functions for data parity."""

from lxml import etree

from chartfold.core.cda import NS, extract_patient_demographics, get_encounter_end_date
from chartfold.core.fhir import _parse_allergy_intolerance, _parse_procedure


class TestGetEncounterEndDate:
    def test_with_high_value(self):
        xml = f"""<root xmlns="{NS}">
            <componentOf>
                <encompassingEncounter>
                    <effectiveTime>
                        <low value="20250115"/>
                        <high value="20250116"/>
                    </effectiveTime>
                </encompassingEncounter>
            </componentOf>
        </root>"""
        root = etree.fromstring(xml.encode())
        assert get_encounter_end_date(root) == "20250116"

    def test_without_high_value(self):
        xml = f"""<root xmlns="{NS}">
            <componentOf>
                <encompassingEncounter>
                    <effectiveTime>
                        <low value="20250115"/>
                    </effectiveTime>
                </encompassingEncounter>
            </componentOf>
        </root>"""
        root = etree.fromstring(xml.encode())
        assert get_encounter_end_date(root) == ""

    def test_no_encounter(self):
        xml = f'<root xmlns="{NS}"></root>'
        root = etree.fromstring(xml.encode())
        assert get_encounter_end_date(root) == ""


class TestExtractPatientDemographics:
    def test_full_demographics(self):
        xml = f"""<root xmlns="{NS}">
            <recordTarget>
                <patientRole>
                    <id extension="MRN12345"/>
                    <telecom value="tel:555-1234"/>
                    <addr>
                        <streetAddressLine>123 Main St</streetAddressLine>
                        <city>Springfield</city>
                        <state>IL</state>
                        <postalCode>62701</postalCode>
                    </addr>
                    <patient>
                        <name>
                            <given>John</given>
                            <family>Doe</family>
                        </name>
                        <administrativeGenderCode displayName="Male"/>
                        <birthTime value="19750615"/>
                    </patient>
                </patientRole>
            </recordTarget>
        </root>"""
        root = etree.fromstring(xml.encode())
        info = extract_patient_demographics(root)
        assert info["name"] == "John Doe"
        assert info["gender"] == "Male"
        assert info["date_of_birth"] == "19750615"
        assert info["mrn"] == "MRN12345"
        assert "Springfield" in info["address"]
        assert info["phone"] == "555-1234"

    def test_missing_elements(self):
        xml = f"""<root xmlns="{NS}">
            <recordTarget>
                <patientRole>
                    <patient>
                        <name>
                            <given>Jane</given>
                            <family>Smith</family>
                        </name>
                    </patient>
                </patientRole>
            </recordTarget>
        </root>"""
        root = etree.fromstring(xml.encode())
        info = extract_patient_demographics(root)
        assert info["name"] == "Jane Smith"
        assert info["mrn"] == ""
        assert info["phone"] == ""
        assert info["address"] == ""
        assert info["gender"] == ""

    def test_no_record_target(self):
        xml = f'<root xmlns="{NS}"></root>'
        root = etree.fromstring(xml.encode())
        info = extract_patient_demographics(root)
        assert info["name"] == ""


class TestParseAllergyIntolerance:
    def test_basic_allergy(self):
        ai = {
            "code": {"text": "Penicillin"},
            "reaction": [
                {
                    "manifestation": [
                        {"coding": [{"display": "Rash"}]}
                    ],
                    "severity": "moderate",
                }
            ],
            "clinicalStatus": {"coding": [{"code": "active"}]},
            "onsetDateTime": "2020-01-15",
        }
        result = _parse_allergy_intolerance(ai)
        assert result["allergen"] == "Penicillin"
        assert result["reaction"] == "Rash"
        assert result["severity"] == "moderate"
        assert result["clinical_status"] == "active"
        assert result["onset_iso"] == "2020-01-15"

    def test_missing_fields(self):
        ai = {"code": {"text": "Latex"}}
        result = _parse_allergy_intolerance(ai)
        assert result["allergen"] == "Latex"
        assert result["reaction"] == ""
        assert result["severity"] == ""
        assert result["clinical_status"] == ""

    def test_coding_fallback(self):
        ai = {"code": {"coding": [{"display": "Aspirin allergy"}]}}
        result = _parse_allergy_intolerance(ai)
        assert result["allergen"] == "Aspirin allergy"


class TestParseProcedure:
    def test_basic_procedure(self):
        proc = {
            "code": {
                "text": "Right hemicolectomy",
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "44441009",
                        "display": "Right hemicolectomy",
                    }
                ],
            },
            "performedDateTime": "2024-07-01",
            "status": "completed",
        }
        result = _parse_procedure(proc)
        assert result["name"] == "Right hemicolectomy"
        assert result["snomed"] == "44441009"
        assert result["date_iso"] == "2024-07-01"
        assert result["status"] == "completed"

    def test_period_date(self):
        proc = {
            "code": {"text": "Liver biopsy"},
            "performedPeriod": {"start": "2025-01-10T08:00:00Z"},
            "status": "completed",
        }
        result = _parse_procedure(proc)
        assert result["name"] == "Liver biopsy"
        assert result["date_iso"] == "2025-01-10"

    def test_no_snomed(self):
        proc = {
            "code": {
                "text": "Appendectomy",
                "coding": [{"system": "http://cpt.ama-assn.org", "code": "44950"}],
            },
            "status": "completed",
        }
        result = _parse_procedure(proc)
        assert result["snomed"] == ""
        assert result["name"] == "Appendectomy"
