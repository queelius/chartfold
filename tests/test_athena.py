"""Tests for chartfold.sources.athena parser."""

import pytest
from lxml import etree

from chartfold.core.cda import NS
from chartfold.sources.athena import (
    _extract_allergies,
    _extract_encounters,
    _extract_family_history,
    _extract_medications,
    _extract_mental_status,
    _extract_patient,
    _extract_problems,
    _extract_results,
    _extract_vitals,
    _parse_vital_value,
    _parse_vital_value_unit,
)


def _make_section(title: str, html: str) -> etree._Element:
    """Create a CDA section element from title and HTML text content."""
    xml = f"""<section xmlns="{NS}">
        <title>{title}</title>
        <text>{html}</text>
    </section>"""
    return etree.fromstring(xml)


def _make_document(patient_xml: str = "") -> etree._Element:
    """Create a minimal CDA document with patient info."""
    xml = f"""<ClinicalDocument xmlns="{NS}">
        <recordTarget>
            <patientRole>
                {patient_xml}
            </patientRole>
        </recordTarget>
    </ClinicalDocument>"""
    return etree.fromstring(xml)


class TestPatientExtraction:
    def test_extract_basic_patient(self):
        root = _make_document("""
            <id extension="12345" root="2.16.840.1.113883.3.564"/>
            <telecom use="HP" value="tel:+1-618-555-1234"/>
            <patient>
                <name use="L">
                    <given>Alexander</given>
                    <family>Towell</family>
                </name>
                <administrativeGenderCode code="M" displayName="Male"/>
                <birthTime value="19750804"/>
            </patient>
        """)
        patient = _extract_patient(root)
        assert patient["name"] == "Alexander Towell"
        assert patient["dob"] == "1975-08-04"
        assert patient["gender"] == "male"
        assert patient["mrn"] == "12345"
        assert "618-555-1234" in patient["phone"]


class TestResultsExtraction:
    def test_extract_lab_results(self):
        section = _make_section("Results", """
            <table>
                <thead>
                    <tr>
                        <th>Created Date</th>
                        <th>Observation Date</th>
                        <th>Name</th>
                        <th>Description</th>
                        <th>Value</th>
                        <th>Unit</th>
                        <th>Range</th>
                        <th>Abnormal Flag</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>10/01/2021</td>
                        <td>10/02/2021</td>
                        <td>CBC with differential/platelet</td>
                        <td><content ID="r1">WBC</content></td>
                        <td>6.4</td>
                        <td>x10e3/uL</td>
                        <td>3.4-10.8</td>
                        <td/>
                    </tr>
                    <tr>
                        <td>10/01/2021</td>
                        <td>10/02/2021</td>
                        <td>CBC with differential/platelet</td>
                        <td><content ID="r2">RBC</content></td>
                        <td>4.04</td>
                        <td>x10e6/uL</td>
                        <td>4.14-5.80</td>
                        <td>below low normal</td>
                    </tr>
                </tbody>
            </table>
        """)
        results = _extract_results(section)
        assert len(results) == 2
        assert results[0]["test_name"] == "WBC"
        assert results[0]["panel_name"] == "CBC with differential/platelet"
        assert results[0]["value"] == "6.4"
        assert results[0]["unit"] == "x10e3/uL"
        assert results[0]["ref_range"] == "3.4-10.8"
        assert results[0]["date"] == "2021-10-02"  # Uses observation date
        assert results[1]["interpretation"] == "below low normal"


class TestVitalsExtraction:
    def test_extract_vitals_basic(self):
        section = _make_section("Vitals", """
            <table>
                <thead>
                    <tr>
                        <th>Date Recorded</th>
                        <th>Body height</th>
                        <th>Body mass index (BMI)</th>
                        <th>Body weight</th>
                        <th>Heart rate</th>
                        <th>Oxygen saturation</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>01/18/2023</td>
                        <td><content ID="v1">185.42 cm</content></td>
                        <td><content ID="v2">28.6 kg/m2</content></td>
                        <td><content ID="v3">98157.39 g</content></td>
                        <td><content ID="v4">64 /min</content></td>
                        <td><content ID="v5">99 %</content></td>
                    </tr>
                </tbody>
            </table>
        """)
        vitals = _extract_vitals(section)
        assert len(vitals) >= 4

        types = {v["type"]: v for v in vitals}
        assert "height" in types
        assert types["height"]["value"] == 185.42
        assert "weight" in types
        # Weight should be converted from grams to kg
        assert abs(types["weight"]["value"] - 98.16) < 0.1
        assert types["weight"]["unit"] == "kg"
        assert "heart_rate" in types
        assert types["heart_rate"]["value"] == 64.0

    def test_extract_blood_pressure_content(self):
        section = _make_section("Vitals", """
            <table>
                <thead>
                    <tr>
                        <th>Date Recorded</th>
                        <th>Systolic And Diastolic</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>01/18/2023</td>
                        <td>
                            <content ID="bp1">122/</content>
                            <content ID="bp2">72 mm[Hg]</content>
                        </td>
                    </tr>
                </tbody>
            </table>
        """)
        vitals = _extract_vitals(section)
        types = {v["type"]: v for v in vitals}
        assert "bp_systolic" in types
        assert types["bp_systolic"]["value"] == 122.0
        assert "bp_diastolic" in types
        assert types["bp_diastolic"]["value"] == 72.0


class TestMedicationExtraction:
    def test_extract_medications(self):
        section = _make_section("Medications", """
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Sig</th>
                        <th>Start Date</th>
                        <th>Stop Date</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><content ID="m1">erythromycin 500 mg tablet</content></td>
                        <td><content ID="s1">TAKE 1 G BY MOUTH</content></td>
                        <td/>
                        <td>03/01/2022</td>
                        <td>aborted</td>
                    </tr>
                    <tr>
                        <td><content ID="m2">levothyroxine 50 mcg tablet</content></td>
                        <td><content ID="s2">TAKE 1 TABLET DAILY</content></td>
                        <td>01/18/2023</td>
                        <td/>
                        <td>active</td>
                    </tr>
                </tbody>
            </table>
        """)
        meds = _extract_medications(section)
        assert len(meds) == 2
        assert "erythromycin" in meds[0]["name"]
        assert meds[0]["status"] == "aborted"
        assert "levothyroxine" in meds[1]["name"]
        assert meds[1]["status"] == "active"


class TestProblemExtraction:
    def test_extract_problems(self):
        section = _make_section("Problems", """
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Problem SNOMED Code</th>
                        <th>Status</th>
                        <th>Onset Date</th>
                        <th>Resolution Date</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><content ID="p0">Sleep apnea</content></td>
                        <td>73430006</td>
                        <td>Active</td>
                        <td>09/27/2021</td>
                        <td/>
                    </tr>
                </tbody>
            </table>
        """)
        conditions = _extract_problems(section)
        assert len(conditions) == 1
        assert conditions[0]["name"] == "Sleep apnea"
        assert conditions[0]["snomed"] == "73430006"
        assert conditions[0]["status"] == "active"


class TestMentalStatusExtraction:
    def test_question_answer_table(self):
        section = _make_section("Mental Status", """
            <table>
                <thead>
                    <tr>
                        <th>Question</th>
                        <th>Answer</th>
                        <th>Note</th>
                        <th>LastModified by</th>
                        <th>Organization Details</th>
                        <th>LastModified Time</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><content>Do you feel stressed?</content></td>
                        <td>Not at all</td>
                        <td/>
                        <td>Provider A</td>
                        <td>SIHF</td>
                        <td>09/27/2021 10:16:05</td>
                    </tr>
                </tbody>
            </table>
        """)
        entries = _extract_mental_status(section)
        assert len(entries) == 1
        assert "stressed" in entries[0]["question"]
        assert entries[0]["answer"] == "Not at all"
        assert entries[0]["date"] == "2021-09-27"

    def test_phq_score_table(self):
        section = _make_section("Mental Status", """
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Assessment</th>
                        <th>Value</th>
                        <th>LastModified by</th>
                        <th>Organization Details</th>
                        <th>LastModified Time</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>10/27/2025</td>
                        <td><content ID="s1">PHQ-2/PHQ-9</content></td>
                        <td>8</td>
                        <td>Provider B</td>
                        <td>SIHF</td>
                        <td>10/27/2025 14:42:25</td>
                    </tr>
                    <tr>
                        <td>10/27/2025</td>
                        <td><content ID="a1">Little interest or pleasure</content></td>
                        <td>Not at all</td>
                        <td>Provider B</td>
                        <td>SIHF</td>
                        <td>10/27/2025 14:42:25</td>
                    </tr>
                    <tr>
                        <td>10/27/2025</td>
                        <td><content ID="a2">Feeling down, depressed</content></td>
                        <td>Several days</td>
                        <td>Provider B</td>
                        <td>SIHF</td>
                        <td>10/27/2025 14:42:25</td>
                    </tr>
                </tbody>
            </table>
        """)
        entries = _extract_mental_status(section)
        assert len(entries) == 3
        # First entry is the total score
        assert entries[0]["instrument"] == "PHQ-2/PHQ-9"
        assert entries[0]["total_score"] == 8
        # Subsequent entries are individual questions
        assert "interest" in entries[1]["question"].lower()
        assert entries[1]["instrument"] == "PHQ-2/PHQ-9"


class TestEncounterExtraction:
    def test_extract_encounters_with_continuation(self):
        section = _make_section("Past Encounters", """
            <table>
                <thead>
                    <tr>
                        <th>Encounter ID</th>
                        <th>Performer</th>
                        <th>Location</th>
                        <th>Encounter Start Date</th>
                        <th>Encounter Closed Date</th>
                        <th>Diagnosis/Indication</th>
                        <th>Diagnosis SNOMED-CT Code</th>
                        <th>Diagnosis ICD10 Code</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><content ID="e1">3916671</content></td>
                        <td>Dr. Smith</td>
                        <td>Bethalto HC</td>
                        <td>09/27/2021 09:54:02</td>
                        <td>09/28/2021 09:16:42</td>
                        <td>Adult health examination</td>
                        <td>268565007</td>
                        <td>Z00.00</td>
                    </tr>
                    <tr>
                        <td/>
                        <td/>
                        <td/>
                        <td/>
                        <td/>
                        <td>Obesity</td>
                        <td>414916001</td>
                        <td>E66.9</td>
                    </tr>
                    <tr>
                        <td><content ID="e2">3920000</content></td>
                        <td>Dr. Jones</td>
                        <td>Main Office</td>
                        <td>01/18/2023</td>
                        <td>01/18/2023</td>
                        <td>Follow-up visit</td>
                        <td>390906007</td>
                        <td>Z09</td>
                    </tr>
                </tbody>
            </table>
        """)
        encounters = _extract_encounters(section)
        assert len(encounters) == 2
        # First encounter has 2 diagnoses (continuation row)
        assert encounters[0]["id"] == "3916671"
        assert encounters[0]["provider"] == "Dr. Smith"
        assert "Bethalto" in encounters[0]["facility"]
        assert encounters[0]["date"] == "2021-09-27"
        assert len(encounters[0]["diagnoses"]) == 2
        assert encounters[0]["diagnoses"][1]["name"] == "Obesity"
        assert encounters[0]["diagnoses"][1]["icd10"] == "E66.9"
        # Second encounter
        assert encounters[1]["id"] == "3920000"


class TestVitalHelpers:
    def test_parse_vital_value(self):
        assert _parse_vital_value("185.42 cm") == 185.42
        assert _parse_vital_value("64 /min") == 64.0
        assert _parse_vital_value("") is None

    def test_parse_vital_value_unit(self):
        val, unit = _parse_vital_value_unit("185.42 cm")
        assert val == 185.42
        assert unit == "cm"

        val, unit = _parse_vital_value_unit("97.5 [degF]")
        assert val == 97.5
        assert unit == "[degF]"

        val, unit = _parse_vital_value_unit("")
        assert val is None


class TestFamilyHistoryExtraction:
    def test_extract_with_description_header(self):
        """Test that 'Description' column header is recognized for conditions (athenahealth format)."""
        section = _make_section("Family History", """
            <table>
                <thead>
                    <tr>
                        <th>Family Member</th>
                        <th>Description</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Father</td>
                        <td>Diabetes mellitus type 2</td>
                    </tr>
                    <tr>
                        <td>Mother</td>
                        <td>Hypertension</td>
                    </tr>
                </tbody>
            </table>
        """)
        entries = _extract_family_history(section)
        assert len(entries) == 2
        assert entries[0]["relation"] == "Father"
        assert entries[0]["condition"] == "Diabetes mellitus type 2"
        assert entries[1]["relation"] == "Mother"
        assert entries[1]["condition"] == "Hypertension"

    def test_extract_with_diagnosis_header(self):
        """Test that 'Diagnosis' column header still works."""
        section = _make_section("Family History", """
            <table>
                <thead>
                    <tr>
                        <th>Relation</th>
                        <th>Diagnosis</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Brother</td>
                        <td>Asthma</td>
                    </tr>
                </tbody>
            </table>
        """)
        entries = _extract_family_history(section)
        assert len(entries) == 1
        assert entries[0]["relation"] == "Brother"
        assert entries[0]["condition"] == "Asthma"

    def test_extract_with_condition_header(self):
        """Test that 'Condition' column header still works."""
        section = _make_section("Family History", """
            <table>
                <thead>
                    <tr>
                        <th>Relation</th>
                        <th>Condition</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Sister</td>
                        <td>Migraine</td>
                    </tr>
                </tbody>
            </table>
        """)
        entries = _extract_family_history(section)
        assert len(entries) == 1
        assert entries[0]["relation"] == "Sister"
        assert entries[0]["condition"] == "Migraine"

    def test_extract_with_name_header(self):
        """Test that 'Name' column header (exact match) still works."""
        section = _make_section("Family History", """
            <table>
                <thead>
                    <tr>
                        <th>Relation</th>
                        <th>Name</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Grandfather</td>
                        <td>Heart disease</td>
                    </tr>
                </tbody>
            </table>
        """)
        entries = _extract_family_history(section)
        assert len(entries) == 1
        assert entries[0]["relation"] == "Grandfather"
        assert entries[0]["condition"] == "Heart disease"

    def test_empty_section_returns_empty(self):
        """Test that an empty Family History section returns no entries."""
        section = _make_section("Family History", "")
        entries = _extract_family_history(section)
        assert entries == []
