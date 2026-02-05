"""Tests for MEDITECH source parser."""

import json

import pytest

from chartfold.core.cda import NS
from chartfold.sources.meditech import (
    _extract_meditech_allergies,
    _extract_meditech_family_history,
    _extract_meditech_immunizations,
    _extract_meditech_labs,
    _extract_meditech_mental_status,
    _extract_meditech_social_history,
    _extract_meditech_vitals,
    _parse_toc,
    deduplicate_allergies,
    deduplicate_family_history,
    deduplicate_immunizations,
    deduplicate_labs,
    deduplicate_mental_status,
    deduplicate_notes,
    deduplicate_problems,
    deduplicate_social_history,
    deduplicate_vitals,
)


# Sample MEDITECH lab section XML
MEDITECH_LAB_XML = f"""<section xmlns="{NS}">
  <title>Relevant Diagnostic Tests and/or Laboratory Data</title>
  <text>
    <content styleCode="Bold">Laboratory Results</content>
    <table>
      <thead>
        <tr>
          <th>Test</th>
          <th>Date/Time</th>
          <th>Result</th>
          <th>Interpretation</th>
          <th>Reference Range</th>
          <th>Result Comment</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>White Blood Count</td>
          <td>November 23rd, 2021 2:37pm</td>
          <td>3.8 K/mm3</td>
          <td>Below low normal</td>
          <td>4.5-10.0</td>
          <td/>
        </tr>
        <tr>
          <td>Carcinoembryonic Antigen</td>
          <td>November 23rd, 2021 2:37pm</td>
          <td>1.4 ng/mL</td>
          <td/>
          <td>0.0-3.0</td>
          <td/>
        </tr>
        <tr>
          <td>Hemoglobin</td>
          <td>November 23rd, 2021 2:37pm</td>
          <td>9.4 g/dL</td>
          <td>Below low normal</td>
          <td>14.0-18.0</td>
          <td/>
        </tr>
      </tbody>
    </table>
  </text>
</section>"""


class TestMeditechLabExtraction:
    @pytest.fixture
    def lab_section(self):
        from lxml import etree

        return etree.fromstring(MEDITECH_LAB_XML)

    def test_extract_labs(self, lab_section):
        labs = _extract_meditech_labs(lab_section)
        assert len(labs) == 3

    def test_lab_values(self, lab_section):
        labs = _extract_meditech_labs(lab_section)
        wbc = next(lab for lab in labs if lab["test"] == "White Blood Count")
        assert wbc["value"] == "3.8"
        assert wbc["unit"] == "K/mm3"
        assert wbc["date_iso"] == "2021-11-23"
        assert wbc["interpretation"] == "Below low normal"
        assert wbc["ref_range"] == "4.5-10.0"

    def test_cea_extraction(self, lab_section):
        labs = _extract_meditech_labs(lab_section)
        cea = next(lab for lab in labs if "Carcinoembryonic" in lab["test"])
        assert cea["value"] == "1.4"
        assert cea["unit"] == "ng/mL"
        assert cea["ref_range"] == "0.0-3.0"

    def test_hemoglobin(self, lab_section):
        labs = _extract_meditech_labs(lab_section)
        hgb = next(lab for lab in labs if lab["test"] == "Hemoglobin")
        assert hgb["value"] == "9.4"
        assert hgb["interpretation"] == "Below low normal"


class TestDeduplication:
    def test_deduplicate_labs(self):
        labs = [
            {"test": "WBC", "date_iso": "2021-11-23", "value": "3.8"},
            {"test": "WBC", "date_iso": "2021-11-23", "value": "3.8"},  # duplicate
            {"test": "WBC", "date_iso": "2021-12-30", "value": "10.3"},  # different date
        ]
        result = deduplicate_labs(labs)
        assert len(result) == 2

    def test_deduplicate_notes_keeps_longest(self):
        notes = [
            {"type": "Progress Note", "encounter_date": "20220201", "text": "Short note"},
            {
                "type": "Progress Note",
                "encounter_date": "20220201",
                "text": "This is a much longer version of the progress note with more detail",
            },
        ]
        result = deduplicate_notes(notes)
        assert len(result) == 1
        assert "longer" in result[0]["text"]

    def test_deduplicate_problems(self):
        problems = [
            {"name": "Colon Cancer"},
            {"name": "colon cancer"},  # case-insensitive dup
            {"name": "Neuropathy"},
        ]
        result = deduplicate_problems(problems)
        assert len(result) == 2


class TestTOCParser:
    def test_parse_toc(self, tmp_path):
        toc_file = tmp_path / "toc.ndjson"
        entries = [
            {
                "resourceType": "DocumentReference",
                "description": "Lab Report",
                "docStatus": "final",
                "date": "2026-01-30T21:16:43-06:00",
                "content": [
                    {
                        "attachment": {
                            "contentType": "image/pdf",
                            "url": "Record_Documents\\015_Laboratory\\lab.pdf",
                            "size": 12345,
                            "title": "Lab Report",
                            "creation": "2025-06-30T13:25:00",
                        }
                    }
                ],
            },
            {
                "resourceType": "DocumentReference",
                "description": "Consent",
                "docStatus": "final",
                "content": [
                    {"attachment": {"url": "consent.pdf", "size": 100, "title": "Consent"}}
                ],
            },
        ]
        toc_file.write_text("\n".join(json.dumps(e) for e in entries))

        result = _parse_toc(str(toc_file))
        assert len(result) == 2
        assert result[0]["description"] == "Lab Report"
        assert result[0]["size"] == 12345
        assert result[1]["description"] == "Consent"


# ── Vitals XML fixtures ──

MEDITECH_VITALS_XML = f"""<section xmlns="{NS}">
  <title>Vital Signs</title>
  <text>
    <table>
      <thead>
        <tr>
          <th>Vital Reading</th>
          <th>Result</th>
          <th>Reference Range</th>
          <th>Collection Date/Time</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Height</td>
          <td>73 [in_i]</td>
          <td/>
          <td>November 22nd, 2021 12:34pm</td>
        </tr>
        <tr>
          <td>Weight</td>
          <td>105.70 kg</td>
          <td/>
          <td>November 22nd, 2021 12:34pm</td>
        </tr>
        <tr>
          <td>Body Temperature</td>
          <td>96.8 [degF]</td>
          <td/>
          <td>November 22nd, 2021 12:34pm</td>
        </tr>
        <tr>
          <td>Heart Rate</td>
          <td>72 bpm</td>
          <td>60-100</td>
          <td>November 22nd, 2021 12:34pm</td>
        </tr>
        <tr>
          <td>Respiratory Rate</td>
          <td>16 /min</td>
          <td/>
          <td>November 22nd, 2021 12:34pm</td>
        </tr>
        <tr>
          <td>Oxygen Saturation</td>
          <td>98 %</td>
          <td/>
          <td>November 22nd, 2021 12:34pm</td>
        </tr>
        <tr>
          <td>BP Systolic</td>
          <td>130 mmHg</td>
          <td/>
          <td>November 22nd, 2021 12:34pm</td>
        </tr>
        <tr>
          <td>BP Diastolic</td>
          <td>82 mmHg</td>
          <td/>
          <td>November 22nd, 2021 12:34pm</td>
        </tr>
        <tr>
          <td>BMI</td>
          <td>30.64 kg/m2</td>
          <td>18.5-24.9</td>
          <td>November 22nd, 2021 12:34pm</td>
        </tr>
      </tbody>
    </table>
  </text>
</section>"""


class TestMeditechVitalsExtraction:
    @pytest.fixture
    def vitals_section(self):
        from lxml import etree

        return etree.fromstring(MEDITECH_VITALS_XML)

    def test_extract_all_vitals(self, vitals_section):
        vitals = _extract_meditech_vitals(vitals_section)
        assert len(vitals) == 9

    def test_height(self, vitals_section):
        vitals = _extract_meditech_vitals(vitals_section)
        height = next(v for v in vitals if v["type"] == "height")
        assert height["value"] == 73.0
        assert height["unit"] == "in_i"
        assert height["date_iso"] == "2021-11-22"

    def test_weight(self, vitals_section):
        vitals = _extract_meditech_vitals(vitals_section)
        weight = next(v for v in vitals if v["type"] == "weight")
        assert weight["value"] == 105.70
        assert weight["unit"] == "kg"

    def test_temperature_bracketed_unit(self, vitals_section):
        vitals = _extract_meditech_vitals(vitals_section)
        temp = next(v for v in vitals if v["type"] == "temperature")
        assert temp["value"] == 96.8
        assert temp["unit"] == "degF"

    def test_heart_rate(self, vitals_section):
        vitals = _extract_meditech_vitals(vitals_section)
        hr = next(v for v in vitals if v["type"] == "heart_rate")
        assert hr["value"] == 72.0
        assert hr["unit"] == "bpm"

    def test_bp_systolic(self, vitals_section):
        vitals = _extract_meditech_vitals(vitals_section)
        bp = next(v for v in vitals if v["type"] == "bp_systolic")
        assert bp["value"] == 130.0

    def test_bp_diastolic(self, vitals_section):
        vitals = _extract_meditech_vitals(vitals_section)
        bp = next(v for v in vitals if v["type"] == "bp_diastolic")
        assert bp["value"] == 82.0

    def test_spo2(self, vitals_section):
        vitals = _extract_meditech_vitals(vitals_section)
        spo2 = next(v for v in vitals if v["type"] == "spo2")
        assert spo2["value"] == 98.0

    def test_bmi_with_ref_range(self, vitals_section):
        vitals = _extract_meditech_vitals(vitals_section)
        bmi = next(v for v in vitals if v["type"] == "bmi")
        assert bmi["value"] == 30.64
        assert bmi["ref_range"] == "18.5-24.9"

    def test_empty_section(self):
        from lxml import etree

        empty = etree.fromstring(f'<section xmlns="{NS}"><title>Vital Signs</title></section>')
        assert _extract_meditech_vitals(empty) == []

    def test_unknown_vital_name_ignored(self):
        from lxml import etree

        xml = f"""<section xmlns="{NS}">
          <text>
            <table>
              <thead><tr><th>Vital Reading</th><th>Result</th></tr></thead>
              <tbody><tr><td>Unknown Vital</td><td>42 units</td></tr></tbody>
            </table>
          </text>
        </section>"""
        section = etree.fromstring(xml)
        vitals = _extract_meditech_vitals(section)
        assert len(vitals) == 0


# ── Immunizations XML fixtures ──

MEDITECH_IMMUNIZATIONS_XML = f"""<section xmlns="{NS}">
  <title>Immunizations</title>
  <text>
    <table>
      <thead>
        <tr>
          <th>Immunization</th>
          <th>Event Date</th>
          <th>Not Given Reason</th>
          <th>Dose Number</th>
          <th>Manufacturer</th>
          <th>Lot Number</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Influenza, seasonal, injectable</td>
          <td>October 15th, 2024 10:00am</td>
          <td/>
          <td>1</td>
          <td>Sanofi Pasteur</td>
          <td>ABC123</td>
        </tr>
        <tr>
          <td>COVID-19, mRNA, LNP-S, bivalent</td>
          <td>September 20th, 2023 2:00pm</td>
          <td/>
          <td>5</td>
          <td>Pfizer</td>
          <td>XY789</td>
        </tr>
      </tbody>
    </table>
  </text>
</section>"""


class TestMeditechImmunizationsExtraction:
    @pytest.fixture
    def imm_section(self):
        from lxml import etree

        return etree.fromstring(MEDITECH_IMMUNIZATIONS_XML)

    def test_extract_immunizations(self, imm_section):
        imms = _extract_meditech_immunizations(imm_section)
        assert len(imms) == 2

    def test_flu_vaccine(self, imm_section):
        imms = _extract_meditech_immunizations(imm_section)
        flu = next(i for i in imms if "Influenza" in i["name"])
        assert flu["date_iso"] == "2024-10-15"
        assert flu["lot"] == "ABC123"
        assert flu["manufacturer"] == "Sanofi Pasteur"

    def test_covid_vaccine(self, imm_section):
        imms = _extract_meditech_immunizations(imm_section)
        covid = next(i for i in imms if "COVID" in i["name"])
        assert covid["date_iso"] == "2023-09-20"
        assert covid["lot"] == "XY789"

    def test_empty_section(self):
        from lxml import etree

        empty = etree.fromstring(f'<section xmlns="{NS}"><title>Immunizations</title></section>')
        assert _extract_meditech_immunizations(empty) == []


# ── Allergies XML fixtures ──

MEDITECH_NO_ALLERGIES_XML = f"""<section xmlns="{NS}">
  <title>Allergies, Adverse Reactions, Alerts</title>
  <text>No known allergies</text>
</section>"""

MEDITECH_NEGATION_ALLERGIES_XML = f"""<section xmlns="{NS}">
  <title>Allergies</title>
  <text>No known allergies</text>
  <entry>
    <act classCode="ACT" moodCode="EVN">
      <entryRelationship>
        <observation classCode="OBS" moodCode="EVN" negationInd="true">
          <code code="ASSERTION"/>
        </observation>
      </entryRelationship>
    </act>
  </entry>
</section>"""

MEDITECH_REAL_ALLERGIES_XML = f"""<section xmlns="{NS}">
  <title>Allergies</title>
  <text>
    <table>
      <thead>
        <tr>
          <th>Allergen</th>
          <th>Reaction</th>
          <th>Severity</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Penicillin</td>
          <td>Rash</td>
          <td>Moderate</td>
          <td>Active</td>
        </tr>
        <tr>
          <td>Sulfa drugs</td>
          <td>Hives</td>
          <td>Severe</td>
          <td>Active</td>
        </tr>
      </tbody>
    </table>
  </text>
</section>"""


class TestMeditechAllergiesExtraction:
    def test_no_known_allergies_text(self):
        from lxml import etree

        section = etree.fromstring(MEDITECH_NO_ALLERGIES_XML)
        assert _extract_meditech_allergies(section) == []

    def test_no_known_allergies_negation(self):
        from lxml import etree

        section = etree.fromstring(MEDITECH_NEGATION_ALLERGIES_XML)
        assert _extract_meditech_allergies(section) == []

    def test_real_allergies(self):
        from lxml import etree

        section = etree.fromstring(MEDITECH_REAL_ALLERGIES_XML)
        allergies = _extract_meditech_allergies(section)
        assert len(allergies) == 2
        pen = next(a for a in allergies if a["allergen"] == "Penicillin")
        assert pen["reaction"] == "Rash"
        assert pen["severity"] == "Moderate"
        assert pen["status"] == "Active"

    def test_sulfa_allergy(self):
        from lxml import etree

        section = etree.fromstring(MEDITECH_REAL_ALLERGIES_XML)
        allergies = _extract_meditech_allergies(section)
        sulfa = next(a for a in allergies if "Sulfa" in a["allergen"])
        assert sulfa["severity"] == "Severe"

    def test_empty_section(self):
        from lxml import etree

        empty = etree.fromstring(f'<section xmlns="{NS}"><title>Allergies</title></section>')
        assert _extract_meditech_allergies(empty) == []


# ── Social History XML fixtures ──

MEDITECH_SOCIAL_HISTORY_XML = f"""<section xmlns="{NS}">
  <title>Social History</title>
  <text/>
  <entry>
    <observation classCode="OBS" moodCode="EVN">
      <code code="72166-2" displayName="Tobacco smoking status" codeSystem="2.16.840.1.113883.6.1"/>
      <value displayName="Never smoker" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="CD"/>
      <effectiveTime value="20211122"/>
    </observation>
  </entry>
  <entry>
    <observation classCode="OBS" moodCode="EVN">
      <code code="76689-9" displayName="Sex assigned at birth" codeSystem="2.16.840.1.113883.6.1"/>
      <value displayName="Male" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="CD"/>
    </observation>
  </entry>
</section>"""


class TestMeditechSocialHistoryExtraction:
    @pytest.fixture
    def sh_section(self):
        from lxml import etree

        return etree.fromstring(MEDITECH_SOCIAL_HISTORY_XML)

    def test_extract_social_history(self, sh_section):
        entries = _extract_meditech_social_history(sh_section)
        assert len(entries) == 2

    def test_smoking_status(self, sh_section):
        entries = _extract_meditech_social_history(sh_section)
        smoking = next(e for e in entries if e["category"] == "tobacco_smoking_status")
        assert smoking["value"] == "Never smoker"
        assert smoking["loinc"] == "72166-2"
        assert smoking["date_iso"] == "2021-11-22"

    def test_sex_assigned(self, sh_section):
        entries = _extract_meditech_social_history(sh_section)
        sex = next(e for e in entries if e["category"] == "sex_assigned_at_birth")
        assert sex["value"] == "Male"
        assert sex["loinc"] == "76689-9"

    def test_empty_section(self):
        from lxml import etree

        empty = etree.fromstring(f'<section xmlns="{NS}"><title>Social History</title></section>')
        assert _extract_meditech_social_history(empty) == []


# ── Family History XML fixtures ──

MEDITECH_FAMILY_HISTORY_STRUCTURED_XML = f"""<section xmlns="{NS}"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <title>Family History</title>
  <text/>
  <entry>
    <organizer classCode="CLUSTER" moodCode="EVN">
      <subject>
        <relatedSubject classCode="PRS">
          <code displayName="Father" codeSystem="2.16.840.1.113883.5.111"/>
        </relatedSubject>
      </subject>
      <component>
        <observation classCode="OBS" moodCode="EVN">
          <value xsi:type="CD" displayName="Carcinoma of colon"/>
        </observation>
      </component>
      <component>
        <observation classCode="OBS" moodCode="EVN">
          <value xsi:type="CD" displayName="Hypertension"/>
        </observation>
      </component>
    </organizer>
  </entry>
</section>"""

MEDITECH_FAMILY_HISTORY_TABLE_XML = f"""<section xmlns="{NS}">
  <title>Family History</title>
  <text>
    <table>
      <thead>
        <tr>
          <th>Relationship</th>
          <th>Condition</th>
          <th>Age at Onset</th>
          <th>Recorded Date/Time</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Mother</td>
          <td>Type 2 Diabetes</td>
          <td>55</td>
          <td>November 22nd, 2021</td>
        </tr>
        <tr>
          <td>Father</td>
          <td>Heart Disease</td>
          <td>60</td>
          <td>November 22nd, 2021</td>
        </tr>
      </tbody>
    </table>
  </text>
</section>"""


class TestMeditechFamilyHistoryExtraction:
    def test_structured_entries(self):
        from lxml import etree

        section = etree.fromstring(MEDITECH_FAMILY_HISTORY_STRUCTURED_XML)
        entries = _extract_meditech_family_history(section)
        assert len(entries) == 2
        assert entries[0]["relation"] == "Father"
        assert entries[0]["condition"] == "Carcinoma of colon"
        assert entries[1]["condition"] == "Hypertension"

    def test_table_fallback(self):
        from lxml import etree

        section = etree.fromstring(MEDITECH_FAMILY_HISTORY_TABLE_XML)
        entries = _extract_meditech_family_history(section)
        assert len(entries) == 2
        mother = next(e for e in entries if e["relation"] == "Mother")
        assert mother["condition"] == "Type 2 Diabetes"
        father = next(e for e in entries if e["relation"] == "Father")
        assert father["condition"] == "Heart Disease"

    def test_empty_section(self):
        from lxml import etree

        empty = etree.fromstring(f'<section xmlns="{NS}"><title>Family History</title></section>')
        assert _extract_meditech_family_history(empty) == []

    def test_nullflavor_relation(self):
        """When relation has nullFlavor, falls back to 'Not Specified'."""
        from lxml import etree

        xml = f"""<section xmlns="{NS}"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
          <title>Family History</title>
          <text/>
          <entry>
            <organizer classCode="CLUSTER" moodCode="EVN">
              <subject>
                <relatedSubject classCode="PRS">
                  <code nullFlavor="UNK"/>
                </relatedSubject>
              </subject>
              <component>
                <observation classCode="OBS" moodCode="EVN">
                  <value xsi:type="CD" displayName="Asthma"/>
                </observation>
              </component>
            </organizer>
          </entry>
        </section>"""
        section = etree.fromstring(xml)
        entries = _extract_meditech_family_history(section)
        assert len(entries) == 1
        assert entries[0]["relation"] == "Not Specified"
        assert entries[0]["condition"] == "Asthma"


# ── Mental Status XML fixtures ──

MEDITECH_MENTAL_STATUS_XML = f"""<section xmlns="{NS}">
  <title>Mental Status</title>
  <text>
    <table>
      <thead>
        <tr>
          <th>Observation</th>
          <th>Response</th>
          <th>Date Recorded</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Little interest or pleasure in doing things?</td>
          <td>Not at all</td>
          <td>November 22nd, 2021 12:30pm</td>
        </tr>
        <tr>
          <td>Feeling down, depressed, or hopeless?</td>
          <td>Several days</td>
          <td>November 22nd, 2021 12:30pm</td>
        </tr>
      </tbody>
    </table>
  </text>
</section>"""

MEDITECH_MENTAL_STATUS_STRUCTURED_XML = f"""<section xmlns="{NS}">
  <title>Mental Status</title>
  <text/>
  <entry>
    <observation classCode="OBS" moodCode="EVN">
      <code displayName="PHQ-2 total score"/>
      <value displayName="1"/>
      <effectiveTime value="20211122"/>
    </observation>
  </entry>
</section>"""


class TestMeditechMentalStatusExtraction:
    def test_table_extraction(self):
        from lxml import etree

        section = etree.fromstring(MEDITECH_MENTAL_STATUS_XML)
        entries = _extract_meditech_mental_status(section)
        assert len(entries) == 2

    def test_observation_values(self):
        from lxml import etree

        section = etree.fromstring(MEDITECH_MENTAL_STATUS_XML)
        entries = _extract_meditech_mental_status(section)
        q1 = entries[0]
        assert "Little interest" in q1["observation"]
        assert q1["response"] == "Not at all"
        assert q1["date_iso"] == "2021-11-22"

    def test_second_observation(self):
        from lxml import etree

        section = etree.fromstring(MEDITECH_MENTAL_STATUS_XML)
        entries = _extract_meditech_mental_status(section)
        q2 = entries[1]
        assert "depressed" in q2["observation"]
        assert q2["response"] == "Several days"

    def test_structured_fallback(self):
        from lxml import etree

        section = etree.fromstring(MEDITECH_MENTAL_STATUS_STRUCTURED_XML)
        entries = _extract_meditech_mental_status(section)
        assert len(entries) == 1
        assert entries[0]["observation"] == "PHQ-2 total score"
        assert entries[0]["response"] == "1"
        assert entries[0]["date_iso"] == "2021-11-22"

    def test_empty_section(self):
        from lxml import etree

        empty = etree.fromstring(f'<section xmlns="{NS}"><title>Mental Status</title></section>')
        assert _extract_meditech_mental_status(empty) == []


# ── Deduplication tests for new types ──


class TestNewDeduplication:
    def test_deduplicate_vitals(self):
        vitals = [
            {"type": "weight", "date_iso": "2021-11-22", "value": 105.7},
            {"type": "weight", "date_iso": "2021-11-22", "value": 105.7},  # dup
            {"type": "weight", "date_iso": "2021-12-01", "value": 106.0},  # diff date
            {"type": "height", "date_iso": "2021-11-22", "value": 73.0},
        ]
        result = deduplicate_vitals(vitals)
        assert len(result) == 3

    def test_deduplicate_immunizations(self):
        imms = [
            {"name": "Influenza", "date_iso": "2024-10-15"},
            {"name": "influenza", "date_iso": "2024-10-15"},  # case dup
            {"name": "COVID-19", "date_iso": "2023-09-20"},
        ]
        result = deduplicate_immunizations(imms)
        assert len(result) == 2

    def test_deduplicate_allergies(self):
        allergies = [
            {"allergen": "Penicillin", "reaction": "Rash"},
            {"allergen": "penicillin", "reaction": "Hives"},  # dup by allergen
            {"allergen": "Sulfa drugs", "reaction": "Rash"},
        ]
        result = deduplicate_allergies(allergies)
        assert len(result) == 2

    def test_deduplicate_social_history(self):
        entries = [
            {"category": "tobacco_smoking_status", "value": "Never smoker"},
            {"category": "Tobacco_Smoking_Status", "value": "never smoker"},  # dup
            {"category": "sex_assigned_at_birth", "value": "Male"},
        ]
        result = deduplicate_social_history(entries)
        assert len(result) == 2

    def test_deduplicate_family_history(self):
        entries = [
            {"relation": "Father", "condition": "Colon Cancer"},
            {"relation": "father", "condition": "colon cancer"},  # dup
            {"relation": "Mother", "condition": "Diabetes"},
        ]
        result = deduplicate_family_history(entries)
        assert len(result) == 2

    def test_deduplicate_mental_status(self):
        entries = [
            {"observation": "PHQ-2 Q1", "response": "Not at all", "date_iso": "2021-11-22"},
            {"observation": "phq-2 q1", "response": "not at all", "date_iso": "2021-11-22"},  # dup
            {"observation": "PHQ-2 Q2", "response": "Several days", "date_iso": "2021-11-22"},
        ]
        result = deduplicate_mental_status(entries)
        assert len(result) == 2
