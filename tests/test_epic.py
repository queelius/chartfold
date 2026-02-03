"""Tests for Epic source parser."""

import os
import tempfile

import pytest
from lxml import etree

from chartfold.core.cda import NS
from chartfold.sources.epic import (
    _classify_result,
    _extract_cea,
    _extract_epic_result_items,
    _extract_epic_medications,
    _extract_epic_problems,
    _extract_epic_vitals,
    _extract_epic_immunizations,
    _extract_epic_allergies,
    _extract_epic_social_history,
    _extract_epic_procedures,
    OID_RXNORM,
    OID_SNOMED,
    OID_ICD10CM,
    OID_CVX,
)


# Sample Epic Results section with CEA panel
EPIC_RESULTS_XML = f"""<section xmlns="{NS}">
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
        <table>
          <tbody>
            <tr>
              <td>LAB GENERAL</td>
            </tr>
          </tbody>
        </table>
      </item>
      <item>
        <caption>CT CHEST W CONTRAST - Final result (01/15/2026  11:00 AM CST)</caption>
        <table>
          <tbody>
            <tr>
              <td>Report</td>
              <td>Stable pulmonary nodules</td>
              <td/>
            </tr>
          </tbody>
        </table>
        <table>
          <tbody>
            <tr>
              <td>IMG RADIOLOGY</td>
            </tr>
          </tbody>
        </table>
      </item>
      <item>
        <caption>SURGICAL PATHOLOGY REPORT - Final result (12/24/2025  3:00 PM CST)</caption>
        <table>
          <tbody>
            <tr>
              <td>Report</td>
              <td>Metastatic adenocarcinoma</td>
              <td/>
            </tr>
          </tbody>
        </table>
      </item>
    </list>
  </text>
</section>"""


class TestEpicResultItems:
    @pytest.fixture
    def results_section(self):
        from lxml import etree
        return etree.fromstring(EPIC_RESULTS_XML)

    def test_extract_items(self, results_section):
        items = _extract_epic_result_items(results_section)
        assert len(items) == 3

    def test_cea_panel(self, results_section):
        items = _extract_epic_result_items(results_section)
        cea = items[0]
        assert cea["panel"] == "CEA"
        assert cea["date"] == "01/15/2026"
        assert cea["time"] == "10:30 AM CST"
        assert len(cea["components"]) == 1
        assert cea["components"][0]["name"] == "CEA"
        assert cea["components"][0]["value"] == "1.8"

    def test_imaging_classification(self, results_section):
        items = _extract_epic_result_items(results_section)
        ct = items[1]
        assert _classify_result(ct) == "imaging"

    def test_pathology_classification(self, results_section):
        items = _extract_epic_result_items(results_section)
        path = items[2]
        assert _classify_result(path) == "pathology"

    def test_lab_classification(self, results_section):
        items = _extract_epic_result_items(results_section)
        cea = items[0]
        assert _classify_result(cea) == "lab"


class TestCEAExtraction:
    def test_extract_cea(self):
        items = [
            {
                "panel": "CEA",
                "date": "01/15/2026",
                "time": "10:30 AM CST",
                "components": [{"name": "CEA", "value": "1.8", "ref_range": "0.0-5.0"}],
                "result_type": "LAB GENERAL",
                "full_text": "CEA 1.8",
            },
            {
                "panel": "COMPREHENSIVE METABOLIC",
                "date": "01/15/2026",
                "time": "10:30 AM CST",
                "components": [{"name": "Glucose", "value": "95", "ref_range": "70-100"}],
                "result_type": "LAB GENERAL",
                "full_text": "Glucose 95",
            },
        ]
        cea = _extract_cea(items)
        assert len(cea) == 1
        assert cea[0]["value"] == "1.8"
        assert cea[0]["date"] == "01/15/2026"

    def test_dedup_same_date(self):
        items = [
            {
                "panel": "CEA",
                "date": "01/15/2026",
                "time": "10:30 AM CST",
                "components": [{"name": "CEA", "value": "1.8", "ref_range": "0.0-5.0"}],
                "result_type": "LAB GENERAL",
                "full_text": "",
            },
            {
                "panel": "CEA",
                "date": "01/15/2026",
                "time": "10:30 AM CST",
                "components": [{"name": "CEA", "value": "1.8", "ref_range": "0.0-5.0"}],
                "result_type": "LAB GENERAL",
                "full_text": "",
            },
        ]
        cea = _extract_cea(items)
        assert len(cea) == 1


# ---------------------------------------------------------------------------
# Medication extraction tests
# ---------------------------------------------------------------------------

MEDICATION_XML = f"""<section xmlns="{NS}">
  <text>
    <content ID="med1">Ondansetron 8mg Oral Tablet</content>
  </text>
  <entry>
    <substanceAdministration classCode="SBADM" moodCode="EVN">
      <statusCode code="active"/>
      <effectiveTime xsi:type="IVL_TS" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
        <low value="20240115"/>
        <high value="20250601"/>
      </effectiveTime>
      <routeCode code="C38288" codeSystem="2.16.840.1.113883.3.26.1.1"
                 displayName="Oral"/>
      <doseQuantity value="1" unit="{{tbl}}"/>
      <consumable>
        <manufacturedProduct>
          <manufacturedMaterial>
            <code code="312087" codeSystem="{OID_RXNORM}"
                  displayName="Ondansetron 8 MG Oral Tablet"/>
          </manufacturedMaterial>
        </manufacturedProduct>
      </consumable>
    </substanceAdministration>
  </entry>
  <entry>
    <substanceAdministration classCode="SBADM" moodCode="EVN">
      <statusCode code="active"/>
      <consumable>
        <manufacturedProduct>
          <manufacturedMaterial>
            <code code="200328" codeSystem="{OID_RXNORM}">
              <originalText><reference value="#med1"/></originalText>
            </code>
          </manufacturedMaterial>
        </manufacturedProduct>
      </consumable>
    </substanceAdministration>
  </entry>
</section>"""


class TestEpicMedicationExtraction:
    @pytest.fixture
    def med_section(self):
        return etree.fromstring(MEDICATION_XML)

    def test_basic_medication(self, med_section):
        meds = _extract_epic_medications(med_section)
        assert len(meds) == 2
        assert meds[0]["name"] == "Ondansetron 8 MG Oral Tablet"
        assert meds[0]["rxnorm"] == "312087"
        assert meds[0]["status"] == "active"

    def test_dates(self, med_section):
        meds = _extract_epic_medications(med_section)
        assert meds[0]["start_date"] == "20240115"
        assert meds[0]["stop_date"] == "20250601"

    def test_route_and_dose(self, med_section):
        meds = _extract_epic_medications(med_section)
        assert meds[0]["route"] == "Oral"
        assert "1" in meds[0]["dose"]

    def test_name_from_reference(self, med_section):
        meds = _extract_epic_medications(med_section)
        # Second entry has no displayName, should resolve from text reference
        assert meds[1]["name"] == "Ondansetron 8mg Oral Tablet"

    def test_empty_section(self):
        empty = etree.fromstring(f'<section xmlns="{NS}"></section>')
        assert _extract_epic_medications(empty) == []

    def test_no_effectiveTime(self):
        xml = f"""<section xmlns="{NS}">
          <entry>
            <substanceAdministration classCode="SBADM" moodCode="EVN">
              <statusCode code="completed"/>
              <consumable>
                <manufacturedProduct>
                  <manufacturedMaterial>
                    <code code="999999" codeSystem="{OID_RXNORM}"
                          displayName="Test Drug"/>
                  </manufacturedMaterial>
                </manufacturedProduct>
              </consumable>
            </substanceAdministration>
          </entry>
        </section>"""
        meds = _extract_epic_medications(etree.fromstring(xml))
        assert len(meds) == 1
        assert meds[0]["start_date"] == ""
        assert meds[0]["stop_date"] == ""


# ---------------------------------------------------------------------------
# Problem extraction tests
# ---------------------------------------------------------------------------

PROBLEM_XML = f"""<section xmlns="{NS}">
  <text>
    <content ID="prob1">Colon cancer</content>
  </text>
  <entry>
    <act classCode="ACT" moodCode="EVN">
      <effectiveTime>
        <low value="20211122"/>
      </effectiveTime>
      <entryRelationship typeCode="SUBJ">
        <observation classCode="OBS" moodCode="EVN">
          <value xsi:type="CD"
                 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                 code="363406005" codeSystem="{OID_SNOMED}"
                 displayName="Malignant neoplasm of colon">
            <translation code="C18.9" codeSystem="{OID_ICD10CM}"
                         displayName="Colon cancer"/>
          </value>
          <entryRelationship typeCode="REFR">
            <observation classCode="OBS" moodCode="EVN">
              <code code="33999-4" codeSystem="{OID_SNOMED}"/>
              <value xsi:type="CD"
                     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                     displayName="Active"/>
            </observation>
          </entryRelationship>
        </observation>
      </entryRelationship>
    </act>
  </entry>
  <entry>
    <act classCode="ACT" moodCode="EVN">
      <entryRelationship typeCode="SUBJ">
        <observation classCode="OBS" moodCode="EVN">
          <value xsi:type="CD"
                 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                 code="38341003" codeSystem="{OID_SNOMED}"
                 displayName="Hypertension"/>
        </observation>
      </entryRelationship>
    </act>
  </entry>
</section>"""


class TestEpicProblemExtraction:
    @pytest.fixture
    def prob_section(self):
        return etree.fromstring(PROBLEM_XML)

    def test_basic_problem(self, prob_section):
        probs = _extract_epic_problems(prob_section)
        assert len(probs) == 2
        assert probs[0]["snomed"] == "363406005"
        assert probs[0]["icd10"] == "C18.9"
        assert probs[0]["onset_date"] == "20211122"

    def test_status_from_observation(self, prob_section):
        probs = _extract_epic_problems(prob_section)
        assert probs[0]["status"] == "Active"

    def test_name_from_translation(self, prob_section):
        probs = _extract_epic_problems(prob_section)
        # Name should come from translation displayName first
        assert probs[0]["name"] == "Colon cancer"

    def test_name_fallback_to_value(self, prob_section):
        probs = _extract_epic_problems(prob_section)
        # Second entry has no translation, falls back to value displayName
        assert probs[1]["name"] == "Hypertension"

    def test_empty_section(self):
        empty = etree.fromstring(f'<section xmlns="{NS}"></section>')
        assert _extract_epic_problems(empty) == []

    def test_no_onset_date(self, prob_section):
        probs = _extract_epic_problems(prob_section)
        # Second entry has no effectiveTime
        assert probs[1]["onset_date"] == ""


# ---------------------------------------------------------------------------
# Vital extraction tests
# ---------------------------------------------------------------------------

VITAL_XML = f"""<section xmlns="{NS}"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <entry>
    <organizer classCode="CLUSTER" moodCode="EVN">
      <component>
        <observation classCode="OBS" moodCode="EVN">
          <code code="8480-6" codeSystem="{OID_SNOMED}"
                displayName="Systolic blood pressure"/>
          <effectiveTime value="20250115"/>
          <value xsi:type="PQ" value="130" unit="mmHg"/>
        </observation>
      </component>
      <component>
        <observation classCode="OBS" moodCode="EVN">
          <code code="3141-9" codeSystem="{OID_SNOMED}"
                displayName="Body weight"/>
          <effectiveTime value="20250115"/>
          <value xsi:type="PQ" value="82.5" unit="kg"/>
        </observation>
      </component>
      <component>
        <observation classCode="OBS" moodCode="EVN">
          <code code="8310-5" codeSystem="{OID_SNOMED}"
                displayName="Body temperature"/>
          <value xsi:type="PQ" nullFlavor="NA"/>
        </observation>
      </component>
    </organizer>
  </entry>
</section>"""


class TestEpicVitalExtraction:
    @pytest.fixture
    def vital_section(self):
        return etree.fromstring(VITAL_XML)

    def test_vital_mapped_to_type(self, vital_section):
        vitals = _extract_epic_vitals(vital_section)
        types = [v["type"] for v in vitals]
        assert "bp_systolic" in types

    def test_vital_value_and_unit(self, vital_section):
        vitals = _extract_epic_vitals(vital_section)
        bp = next(v for v in vitals if v["type"] == "bp_systolic")
        assert bp["value"] == 130.0
        assert bp["unit"] == "mmHg"

    def test_vital_date(self, vital_section):
        vitals = _extract_epic_vitals(vital_section)
        bp = next(v for v in vitals if v["type"] == "bp_systolic")
        assert bp["date"] == "20250115"

    def test_null_value_skipped(self, vital_section):
        vitals = _extract_epic_vitals(vital_section)
        # The temperature entry has nullFlavor, should be skipped
        types = [v["type"] for v in vitals]
        assert "temperature" not in types

    def test_weight_extraction(self, vital_section):
        vitals = _extract_epic_vitals(vital_section)
        wt = next(v for v in vitals if v["type"] == "weight")
        assert wt["value"] == 82.5
        assert wt["unit"] == "kg"

    def test_empty_section(self):
        empty = etree.fromstring(f'<section xmlns="{NS}"></section>')
        assert _extract_epic_vitals(empty) == []


# ---------------------------------------------------------------------------
# Immunization extraction tests
# ---------------------------------------------------------------------------

IMMUNIZATION_XML = f"""<section xmlns="{NS}"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <text>
    <content ID="imm1">Influenza vaccine</content>
  </text>
  <entry>
    <substanceAdministration classCode="SBADM" moodCode="EVN">
      <statusCode code="completed"/>
      <effectiveTime value="20241015"/>
      <consumable>
        <manufacturedProduct>
          <manufacturedMaterial>
            <code code="158" codeSystem="{OID_CVX}"
                  displayName="Influenza, injectable, quadrivalent"/>
            <lotNumberText>ABC123</lotNumberText>
          </manufacturedMaterial>
        </manufacturedProduct>
      </consumable>
    </substanceAdministration>
  </entry>
  <entry>
    <substanceAdministration classCode="SBADM" moodCode="EVN"
                             negationInd="true">
      <statusCode code="completed"/>
      <effectiveTime value="20240101"/>
      <consumable>
        <manufacturedProduct>
          <manufacturedMaterial>
            <code code="999" codeSystem="{OID_CVX}"
                  displayName="Declined Vaccine"/>
          </manufacturedMaterial>
        </manufacturedProduct>
      </consumable>
    </substanceAdministration>
  </entry>
  <entry>
    <substanceAdministration classCode="SBADM" moodCode="INT">
      <statusCode code="active"/>
      <consumable>
        <manufacturedProduct>
          <manufacturedMaterial>
            <code code="140" codeSystem="{OID_CVX}"
                  displayName="Influenza, injectable, preservative free"/>
          </manufacturedMaterial>
        </manufacturedProduct>
      </consumable>
    </substanceAdministration>
  </entry>
</section>"""


class TestEpicImmunizationExtraction:
    @pytest.fixture
    def imm_section(self):
        return etree.fromstring(IMMUNIZATION_XML)

    def test_basic_immunization(self, imm_section):
        imms = _extract_epic_immunizations(imm_section)
        assert len(imms) == 1
        assert imms[0]["name"] == "Influenza, injectable, quadrivalent"
        assert imms[0]["cvx_code"] == "158"
        assert imms[0]["date"] == "20241015"
        assert imms[0]["status"] == "completed"
        assert imms[0]["lot"] == "ABC123"

    def test_negation_skipped(self, imm_section):
        imms = _extract_epic_immunizations(imm_section)
        # Only 1 result: the negated entry and the INT entry are skipped
        assert len(imms) == 1
        names = [i["name"] for i in imms]
        assert "Declined Vaccine" not in names

    def test_non_evn_skipped(self, imm_section):
        imms = _extract_epic_immunizations(imm_section)
        names = [i["name"] for i in imms]
        assert "Influenza, injectable, preservative free" not in names

    def test_empty_section(self):
        empty = etree.fromstring(f'<section xmlns="{NS}"></section>')
        assert _extract_epic_immunizations(empty) == []


# ---------------------------------------------------------------------------
# Allergy extraction tests
# ---------------------------------------------------------------------------

ALLERGY_XML = f"""<section xmlns="{NS}"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <entry>
    <act classCode="ACT" moodCode="EVN">
      <statusCode code="active"/>
      <entryRelationship typeCode="SUBJ">
        <observation classCode="OBS" moodCode="EVN">
          <participant typeCode="CSM">
            <participantRole classCode="MANU">
              <playingEntity classCode="MMAT">
                <code code="7980" displayName="Penicillin"/>
              </playingEntity>
            </participantRole>
          </participant>
          <entryRelationship typeCode="MFST">
            <observation classCode="OBS" moodCode="EVN">
              <value xsi:type="CD" displayName="Rash"/>
            </observation>
          </entryRelationship>
          <entryRelationship typeCode="SUBJ">
            <observation classCode="OBS" moodCode="EVN">
              <value xsi:type="CD" displayName="moderate"/>
            </observation>
          </entryRelationship>
        </observation>
      </entryRelationship>
    </act>
  </entry>
  <entry>
    <act classCode="ACT" moodCode="EVN">
      <statusCode code="active"/>
      <entryRelationship typeCode="SUBJ">
        <observation classCode="OBS" moodCode="EVN" negationInd="true">
          <participant typeCode="CSM">
            <participantRole classCode="MANU">
              <playingEntity classCode="MMAT">
                <code code="0" displayName="No Known Allergies"/>
              </playingEntity>
            </participantRole>
          </participant>
        </observation>
      </entryRelationship>
    </act>
  </entry>
  <entry>
    <act classCode="ACT" moodCode="EVN">
      <statusCode code="active"/>
      <entryRelationship typeCode="SUBJ">
        <observation classCode="OBS" moodCode="EVN">
          <participant typeCode="CSM">
            <participantRole classCode="MANU">
              <playingEntity classCode="MMAT">
                <code code="1191" displayName="Aspirin"/>
              </playingEntity>
            </participantRole>
          </participant>
        </observation>
      </entryRelationship>
    </act>
  </entry>
</section>"""


class TestEpicAllergyExtraction:
    @pytest.fixture
    def allergy_section(self):
        return etree.fromstring(ALLERGY_XML)

    def test_basic_allergy(self, allergy_section):
        allergies = _extract_epic_allergies(allergy_section)
        pen = next(a for a in allergies if a["allergen"] == "Penicillin")
        assert pen["reaction"] == "Rash"
        assert pen["severity"] == "moderate"
        assert pen["status"] == "active"

    def test_negation_skipped(self, allergy_section):
        allergies = _extract_epic_allergies(allergy_section)
        names = [a["allergen"] for a in allergies]
        assert "No Known Allergies" not in names

    def test_missing_reaction(self, allergy_section):
        allergies = _extract_epic_allergies(allergy_section)
        aspirin = next(a for a in allergies if a["allergen"] == "Aspirin")
        assert aspirin["reaction"] == ""

    def test_empty_section(self):
        empty = etree.fromstring(f'<section xmlns="{NS}"></section>')
        assert _extract_epic_allergies(empty) == []

    def test_count_excludes_negated(self, allergy_section):
        allergies = _extract_epic_allergies(allergy_section)
        # Penicillin and Aspirin, but not "No Known Allergies" (negated)
        assert len(allergies) == 2


# ---------------------------------------------------------------------------
# Social history extraction tests
# ---------------------------------------------------------------------------

SOCIAL_HISTORY_XML = f"""<section xmlns="{NS}"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <entry>
    <observation classCode="OBS" moodCode="EVN">
      <code code="72166-2" codeSystem="{OID_SNOMED}"
            displayName="Tobacco smoking status"/>
      <effectiveTime value="20250115"/>
      <value xsi:type="CD" displayName="Never smoker"
             code="266919005" codeSystem="{OID_SNOMED}"/>
    </observation>
  </entry>
  <entry>
    <observation classCode="OBS" moodCode="EVN">
      <code code="76689-9" codeSystem="{OID_SNOMED}"
            displayName="Sex assigned at birth"/>
      <value xsi:type="CD" displayName="Male"
             code="M" codeSystem="2.16.840.1.113883.5.1"/>
    </observation>
  </entry>
  <entry>
    <observation classCode="OBS" moodCode="EVN">
      <code code="11367-0" codeSystem="{OID_SNOMED}"
            displayName="History of tobacco use"/>
      <value xsi:type="CD" displayName="Non-smoker"/>
    </observation>
  </entry>
</section>"""


class TestEpicSocialHistoryExtraction:
    @pytest.fixture
    def sh_section(self):
        return etree.fromstring(SOCIAL_HISTORY_XML)

    def test_tobacco_category(self, sh_section):
        items = _extract_epic_social_history(sh_section)
        tobacco = next(i for i in items if i["loinc"] == "72166-2")
        assert tobacco["category"] == "tobacco_smoking_status"

    def test_value_extraction(self, sh_section):
        items = _extract_epic_social_history(sh_section)
        tobacco = next(i for i in items if i["loinc"] == "72166-2")
        assert tobacco["value"] == "Never smoker"

    def test_unmapped_loinc(self, sh_section):
        items = _extract_epic_social_history(sh_section)
        other = next(i for i in items if i["loinc"] == "11367-0")
        # Unmapped LOINC should use the code displayName as category
        assert other["category"] == "History of tobacco use"

    def test_sex_at_birth(self, sh_section):
        items = _extract_epic_social_history(sh_section)
        sex = next(i for i in items if i["loinc"] == "76689-9")
        assert sex["category"] == "sex_assigned_at_birth"
        assert sex["value"] == "Male"

    def test_date_extraction(self, sh_section):
        items = _extract_epic_social_history(sh_section)
        tobacco = next(i for i in items if i["loinc"] == "72166-2")
        assert tobacco["date"] == "20250115"

    def test_empty_section(self):
        empty = etree.fromstring(f'<section xmlns="{NS}"></section>')
        assert _extract_epic_social_history(empty) == []


# ---------------------------------------------------------------------------
# Procedure extraction tests
# ---------------------------------------------------------------------------

PROCEDURE_XML = f"""<section xmlns="{NS}">
  <entry>
    <procedure classCode="PROC" moodCode="EVN">
      <code code="73761001" codeSystem="{OID_SNOMED}"
            displayName="Colonoscopy"/>
      <statusCode code="completed"/>
      <effectiveTime value="20211122"/>
      <performer>
        <assignedEntity>
          <assignedPerson>
            <name>
              <given>John</given>
              <family>Smith</family>
            </name>
          </assignedPerson>
        </assignedEntity>
      </performer>
    </procedure>
  </entry>
  <entry>
    <procedure classCode="PROC" moodCode="EVN">
      <code code="174041007" codeSystem="{OID_SNOMED}">
        <originalText>Right hemicolectomy with lymph node dissection</originalText>
      </code>
      <statusCode code="completed"/>
      <effectiveTime value="20240701"/>
    </procedure>
  </entry>
</section>"""


class TestEpicProcedureExtraction:
    @pytest.fixture
    def proc_section(self):
        return etree.fromstring(PROCEDURE_XML)

    def test_basic_procedure(self, proc_section):
        procs = _extract_epic_procedures(proc_section)
        assert len(procs) == 2
        assert procs[0]["name"] == "Colonoscopy"
        assert procs[0]["code_value"] == "73761001"
        assert procs[0]["code_system"] == OID_SNOMED
        assert procs[0]["date"] == "20211122"
        assert procs[0]["status"] == "completed"

    def test_provider(self, proc_section):
        procs = _extract_epic_procedures(proc_section)
        assert procs[0]["provider"] == "John Smith"

    def test_name_from_originalText(self, proc_section):
        procs = _extract_epic_procedures(proc_section)
        assert procs[1]["name"] == "Right hemicolectomy with lymph node dissection"

    def test_empty_section(self):
        empty = etree.fromstring(f'<section xmlns="{NS}"></section>')
        assert _extract_epic_procedures(empty) == []

    def test_no_provider(self, proc_section):
        procs = _extract_epic_procedures(proc_section)
        # Second entry has no performer
        assert procs[1]["provider"] == ""
