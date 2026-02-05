"""athenahealth/SIHF CDA source parser.

Handles athenahealth-generated CDA ambulatory summary exports.
Key characteristics:
- Single large CDA document per patient (AmbulatorySummary_alltime)
- Results table: columns [Created Date, Observation Date, Name (panel), Description (test),
  Value, Unit, Range, Abnormal Flag, ...]
- Vitals: separate table per encounter date, weight in grams
- Past Encounters: multi-row (continuation rows lack encounter ID)
- Mental Status: question/answer tables + PHQ-2/PHQ-9 score tables
"""

import os
import re

from chartfold.core.cda import NS, el_text, get_sections, get_title, parse_doc
from chartfold.core.utils import normalize_date_to_iso
from chartfold.sources.base import SourceConfig, discover_files


ATHENA_CONFIG = SourceConfig(
    name="athena_sihf",
    lab_sections=["Results"],
    medication_sections=["Medications"],
    problem_sections=["Problems"],
    note_sections=["Assessment", "Plan of Treatment", "Notes", "Reason for Referral"],
    file_pattern=r".*AmbulatorySummary.*\.xml$",
    cumulative_doc_ids=[],
    recover_xml=False,
)


def process_athena_export(input_dir: str, config: SourceConfig | None = None) -> dict:
    """Parse athenahealth CDA export and return structured data.

    Args:
        input_dir: Directory containing the CDA XML and optional PDF/XSL.
    """
    config = config or ATHENA_CONFIG

    data = {
        "source": config.name,
        "input_dir": os.path.abspath(input_dir),
        "patient": None,
        "documents": [],
        "encounters": [],
        "lab_results": [],
        "vitals": [],
        "medications": [],
        "conditions": [],
        "procedures": [],
        "immunizations": [],
        "allergies": [],
        "social_history": [],
        "family_history": [],
        "mental_status": [],
        "clinical_notes": [],
        "errors": [],
    }

    # Find XML files — check Document_XML subdirectory first
    xml_dir = os.path.join(input_dir, "Document_XML")
    if not os.path.isdir(xml_dir):
        xml_dir = input_dir

    files = discover_files(xml_dir, config.file_pattern)
    if not files:
        print(f"No athena files found in {xml_dir}")
        return data

    print(f"Found {len(files)} athena document(s)")

    for filepath in files:
        try:
            root = parse_doc(filepath, recover=config.recover_xml)
        except Exception as e:
            data["errors"].append({"file": filepath, "error": str(e)})
            print(f"  ERROR: {e}")
            continue

        title = get_title(root)
        sections = get_sections(root)
        fname = os.path.basename(filepath)
        size_kb = os.path.getsize(filepath) // 1024

        data["documents"].append(
            {
                "doc_id": fname,
                "title": title,
                "encounter_date": "",
                "size_kb": size_kb,
                "file_path": os.path.abspath(filepath),
            }
        )

        print(f"  {fname}: {title}, {len(sections)} sections, {size_kb}KB")
        print(f"    Sections: {', '.join(sections.keys())}")

        # Patient demographics
        data["patient"] = _extract_patient(root)

        # Lab results
        for sec_name in config.lab_sections:
            if sec_name in sections:
                data["lab_results"].extend(_extract_results(sections[sec_name]))

        # Vitals
        if "Vitals" in sections:
            data["vitals"].extend(_extract_vitals(sections["Vitals"]))

        # Medications
        if "Medications" in sections:
            data["medications"].extend(_extract_medications(sections["Medications"]))

        # Problems / Conditions
        if "Problems" in sections:
            data["conditions"].extend(_extract_problems(sections["Problems"]))

        # Procedures
        if "Procedures" in sections:
            data["procedures"].extend(_extract_procedures(sections["Procedures"]))

        # Allergies
        if "Allergies" in sections:
            data["allergies"].extend(_extract_allergies(sections["Allergies"]))

        # Immunizations
        if "Immunizations" in sections:
            data["immunizations"].extend(_extract_immunizations(sections["Immunizations"]))

        # Social History
        if "Social History" in sections:
            data["social_history"].extend(_extract_social_history(sections["Social History"]))

        # Family History
        if "Family History" in sections:
            data["family_history"].extend(_extract_family_history(sections["Family History"]))

        # Mental Status
        if "Mental Status" in sections:
            data["mental_status"].extend(_extract_mental_status(sections["Mental Status"]))

        # Past Encounters
        if "Past Encounters" in sections:
            data["encounters"].extend(_extract_encounters(sections["Past Encounters"]))

        # Clinical notes
        for sec_name in config.note_sections:
            if sec_name in sections:
                text_el = sections[sec_name].find(f"{{{NS}}}text")
                if text_el is not None:
                    text = el_text(text_el)
                    if text.strip() and len(text.strip()) > 20:
                        data["clinical_notes"].append(
                            {
                                "type": sec_name,
                                "content": text.strip(),
                                "date": "",
                            }
                        )

    print(
        f"\nathena extraction: {len(data['lab_results'])} labs, "
        f"{len(data['vitals'])} vitals, {len(data['medications'])} meds, "
        f"{len(data['conditions'])} conditions, {len(data['encounters'])} encounters"
    )

    return data


def _extract_patient(root) -> dict:
    """Extract patient demographics from recordTarget."""
    patient = {"name": "", "dob": "", "gender": "", "mrn": "", "address": "", "phone": ""}

    record_target = root.find(f".//{{{NS}}}recordTarget/{{{NS}}}patientRole")
    if record_target is None:
        return patient

    # Name
    given = record_target.find(f".//{{{NS}}}patient/{{{NS}}}name/{{{NS}}}given")
    family = record_target.find(f".//{{{NS}}}patient/{{{NS}}}name/{{{NS}}}family")
    if given is not None and family is not None:
        patient["name"] = f"{given.text or ''} {family.text or ''}".strip()

    # DOB
    birth = record_target.find(f".//{{{NS}}}patient/{{{NS}}}birthTime")
    if birth is not None:
        patient["dob"] = normalize_date_to_iso(birth.get("value", ""))

    # Gender
    gender_el = record_target.find(f".//{{{NS}}}patient/{{{NS}}}administrativeGenderCode")
    if gender_el is not None:
        patient["gender"] = gender_el.get("displayName", "").lower()

    # MRN (first id extension)
    id_el = record_target.find(f"{{{NS}}}id")
    if id_el is not None:
        patient["mrn"] = id_el.get("extension", "")

    # Address
    addr = record_target.find(f"{{{NS}}}addr")
    if addr is not None:
        street = addr.find(f"{{{NS}}}streetAddressLine")
        city = addr.find(f"{{{NS}}}city")
        state = addr.find(f"{{{NS}}}state")
        zip_code = addr.find(f"{{{NS}}}postalCode")
        parts = [
            (street.text or "").strip() if street is not None else "",
            (city.text or "").strip() if city is not None else "",
            (state.text or "").strip() if state is not None else "",
            (zip_code.text or "").strip() if zip_code is not None else "",
        ]
        patient["address"] = ", ".join(p for p in parts if p)

    # Phone
    for telecom in record_target.findall(f"{{{NS}}}telecom"):
        val = telecom.get("value", "")
        if val.startswith("tel:"):
            patient["phone"] = val.replace("tel:", "").strip()
            break

    return patient


def _extract_results(section) -> list[dict]:
    """Extract lab results from athena Results section.

    athena columns: Created Date, Observation Date, Name (panel),
    Description (test), Value, Unit, Range, Abnormal Flag, ...
    """
    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return []

    results = []
    for table in text_el.findall(f".//{{{NS}}}table"):
        headers = _get_headers(table)
        if not headers:
            continue

        col_map = {}
        for i, h in enumerate(headers):
            hl = h.lower()
            if "observation" in hl and "date" in hl:
                col_map["obs_date"] = i
            elif "created" in hl and "date" in hl:
                col_map["created_date"] = i
            elif hl == "name":
                col_map["panel"] = i
            elif "description" in hl:
                col_map["test"] = i
            elif hl == "value":
                col_map["value"] = i
            elif hl == "unit":
                col_map["unit"] = i
            elif "range" in hl:
                col_map["range"] = i
            elif "abnormal" in hl:
                col_map["abnormal"] = i
            elif "note" in hl:
                col_map["note"] = i

        for row in _iter_rows(table):
            cells = [el_text(td) for td in row]
            if len(cells) < 5:
                continue

            test_name = (
                cells[col_map["test"]].strip()
                if "test" in col_map and col_map["test"] < len(cells)
                else ""
            )
            if not test_name:
                continue

            obs_date = cells[col_map.get("obs_date", 0)].strip() if "obs_date" in col_map else ""
            if not obs_date:
                obs_date = (
                    cells[col_map.get("created_date", 0)].strip()
                    if "created_date" in col_map
                    else ""
                )

            results.append(
                {
                    "test_name": test_name,
                    "panel_name": cells[col_map["panel"]].strip()
                    if "panel" in col_map and col_map["panel"] < len(cells)
                    else "",
                    "value": cells[col_map["value"]].strip()
                    if "value" in col_map and col_map["value"] < len(cells)
                    else "",
                    "unit": cells[col_map["unit"]].strip()
                    if "unit" in col_map and col_map["unit"] < len(cells)
                    else "",
                    "ref_range": cells[col_map["range"]].strip()
                    if "range" in col_map and col_map["range"] < len(cells)
                    else "",
                    "interpretation": cells[col_map["abnormal"]].strip()
                    if "abnormal" in col_map and col_map["abnormal"] < len(cells)
                    else "",
                    "date": normalize_date_to_iso(obs_date),
                    "loinc": "",
                }
            )

    return results


def _extract_vitals(section) -> list[dict]:
    """Extract vital signs from athena Vitals section.

    Each table has one encounter date. Columns are vital types.
    Weight is in grams (needs conversion to kg/lbs).
    BP column has systolic/diastolic as separate content elements.
    """
    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return []

    vitals = []
    for table in text_el.findall(f".//{{{NS}}}table"):
        headers = _get_headers(table)
        if not headers:
            continue

        # Map header names to vital types
        vital_cols = {}
        date_col = None
        for i, h in enumerate(headers):
            hl = h.lower()
            if "date" in hl:
                date_col = i
            elif "height" in hl:
                vital_cols[i] = "height"
            elif "mass" in hl or "bmi" in hl:
                vital_cols[i] = "bmi"
            elif "weight" in hl:
                vital_cols[i] = "weight"
            elif "respiratory" in hl:
                vital_cols[i] = "respiratory_rate"
            elif "temperature" in hl:
                vital_cols[i] = "temperature"
            elif "oxygen" in hl or "saturation" in hl:
                vital_cols[i] = "spo2"
            elif "heart" in hl:
                vital_cols[i] = "heart_rate"
            elif "systolic" in hl or "diastolic" in hl or "blood pressure" in hl.replace("  ", " "):
                vital_cols[i] = "blood_pressure"

        for row in _iter_rows(table):
            cells = row.findall(f"{{{NS}}}td")
            if not cells or len(cells) < 2:
                continue

            recorded_date = ""
            if date_col is not None and date_col < len(cells):
                recorded_date = normalize_date_to_iso(el_text(cells[date_col]).strip())

            for col_idx, vital_type in vital_cols.items():
                if col_idx >= len(cells):
                    continue
                cell = cells[col_idx]
                cell_text = el_text(cell).strip()
                if not cell_text:
                    continue

                if vital_type == "blood_pressure":
                    # BP has content elements like "122/" and "72 mm[Hg]"
                    contents = cell.findall(f".//{{{NS}}}content")
                    if len(contents) >= 2:
                        sys_text = el_text(contents[0]).strip().rstrip("/")
                        dia_text = el_text(contents[1]).strip()
                        sys_val = _parse_vital_value(sys_text)
                        dia_val, _dia_unit = _parse_vital_value_unit(dia_text)
                        if sys_val is not None:
                            vitals.append(
                                {
                                    "type": "bp_systolic",
                                    "value": sys_val,
                                    "unit": "mm[Hg]",
                                    "date": recorded_date,
                                }
                            )
                        if dia_val is not None:
                            vitals.append(
                                {
                                    "type": "bp_diastolic",
                                    "value": dia_val,
                                    "unit": "mm[Hg]",
                                    "date": recorded_date,
                                }
                            )
                    else:
                        # Fallback: parse "120/80 mm[Hg]"
                        m = re.match(r"(\d+)\s*/\s*(\d+)", cell_text)
                        if m:
                            vitals.append(
                                {
                                    "type": "bp_systolic",
                                    "value": float(m.group(1)),
                                    "unit": "mm[Hg]",
                                    "date": recorded_date,
                                }
                            )
                            vitals.append(
                                {
                                    "type": "bp_diastolic",
                                    "value": float(m.group(2)),
                                    "unit": "mm[Hg]",
                                    "date": recorded_date,
                                }
                            )
                elif vital_type == "weight":
                    val, unit = _parse_vital_value_unit(cell_text)
                    if val is not None:
                        # Convert grams to kg
                        if unit == "g":
                            val = round(val / 1000.0, 2)
                            unit = "kg"
                        vitals.append(
                            {"type": "weight", "value": val, "unit": unit, "date": recorded_date}
                        )
                else:
                    val, unit = _parse_vital_value_unit(cell_text)
                    if val is not None:
                        vitals.append(
                            {"type": vital_type, "value": val, "unit": unit, "date": recorded_date}
                        )

    return vitals


def _extract_medications(section) -> list[dict]:
    """Extract medications from athena Medications section."""
    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return []

    meds = []
    for table in text_el.findall(f".//{{{NS}}}table"):
        headers = _get_headers(table)
        if not headers:
            continue

        col_map = {}
        for i, h in enumerate(headers):
            hl = h.lower()
            if hl == "name":
                col_map["name"] = i
            elif "sig" in hl:
                col_map["sig"] = i
            elif "start" in hl and "date" in hl:
                col_map["start_date"] = i
            elif "stop" in hl and "date" in hl:
                col_map["stop_date"] = i
            elif "status" in hl:
                col_map["status"] = i

        for row in _iter_rows(table):
            cells = [el_text(td) for td in row]
            name = (
                cells[col_map["name"]].strip()
                if "name" in col_map and col_map["name"] < len(cells)
                else ""
            )
            if not name:
                continue

            meds.append(
                {
                    "name": name,
                    "sig": cells[col_map["sig"]].strip()
                    if "sig" in col_map and col_map["sig"] < len(cells)
                    else "",
                    "start_date": cells[col_map.get("start_date", -1)].strip()
                    if "start_date" in col_map and col_map["start_date"] < len(cells)
                    else "",
                    "stop_date": cells[col_map.get("stop_date", -1)].strip()
                    if "stop_date" in col_map and col_map["stop_date"] < len(cells)
                    else "",
                    "status": cells[col_map["status"]].strip()
                    if "status" in col_map and col_map["status"] < len(cells)
                    else "",
                }
            )

    return meds


def _extract_problems(section) -> list[dict]:
    """Extract conditions from athena Problems section."""
    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return []

    conditions = []
    for table in text_el.findall(f".//{{{NS}}}table"):
        headers = _get_headers(table)
        if not headers:
            continue

        col_map = {}
        for i, h in enumerate(headers):
            hl = h.lower()
            if hl == "name":
                col_map["name"] = i
            elif "snomed" in hl:
                col_map["snomed"] = i
            elif "status" in hl:
                col_map["status"] = i
            elif "onset" in hl:
                col_map["onset"] = i
            elif "resolution" in hl:
                col_map["resolution"] = i

        for row in _iter_rows(table):
            cells = [el_text(td) for td in row]
            name = (
                cells[col_map["name"]].strip()
                if "name" in col_map and col_map["name"] < len(cells)
                else ""
            )
            if not name:
                continue

            conditions.append(
                {
                    "name": name,
                    "snomed": cells[col_map["snomed"]].strip()
                    if "snomed" in col_map and col_map["snomed"] < len(cells)
                    else "",
                    "status": cells[col_map["status"]].strip().lower()
                    if "status" in col_map and col_map["status"] < len(cells)
                    else "",
                    "onset": cells[col_map["onset"]].strip()
                    if "onset" in col_map and col_map["onset"] < len(cells)
                    else "",
                }
            )

    return conditions


def _extract_procedures(section) -> list[dict]:
    """Extract procedures from athena Procedures section."""
    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return []

    procedures = []
    for table in text_el.findall(f".//{{{NS}}}table"):
        headers = _get_headers(table)
        if not headers:
            continue

        col_map = {}
        for i, h in enumerate(headers):
            hl = h.lower()
            if hl == "name" or "procedure" in hl:
                col_map["name"] = i
            elif "date" in hl:
                col_map["date"] = i
            elif "snomed" in hl:
                col_map["snomed"] = i
            elif "status" in hl:
                col_map["status"] = i

        for row in _iter_rows(table):
            cells = [el_text(td) for td in row]
            name = (
                cells[col_map.get("name", 0)].strip()
                if "name" in col_map and col_map["name"] < len(cells)
                else ""
            )
            if not name:
                continue

            procedures.append(
                {
                    "name": name,
                    "date": cells[col_map["date"]].strip()
                    if "date" in col_map and col_map["date"] < len(cells)
                    else "",
                    "snomed": cells[col_map["snomed"]].strip()
                    if "snomed" in col_map and col_map["snomed"] < len(cells)
                    else "",
                }
            )

    return procedures


def _extract_allergies(section) -> list[dict]:
    """Extract allergies from athena Allergies section."""
    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return []

    allergies = []
    for table in text_el.findall(f".//{{{NS}}}table"):
        headers = _get_headers(table)
        if not headers:
            continue

        col_map = {}
        for i, h in enumerate(headers):
            hl = h.lower()
            if "substance" in hl or "allergen" in hl or hl == "name":
                col_map["allergen"] = i
            elif "reaction" in hl:
                col_map["reaction"] = i
            elif "severity" in hl:
                col_map["severity"] = i
            elif "status" in hl:
                col_map["status"] = i

        for row in _iter_rows(table):
            cells = [el_text(td) for td in row]
            allergen = (
                cells[col_map.get("allergen", 0)].strip()
                if "allergen" in col_map and col_map["allergen"] < len(cells)
                else ""
            )
            if not allergen:
                continue

            allergies.append(
                {
                    "allergen": allergen,
                    "reaction": cells[col_map["reaction"]].strip()
                    if "reaction" in col_map and col_map["reaction"] < len(cells)
                    else "",
                    "severity": cells[col_map["severity"]].strip()
                    if "severity" in col_map and col_map["severity"] < len(cells)
                    else "",
                    "status": cells[col_map["status"]].strip()
                    if "status" in col_map and col_map["status"] < len(cells)
                    else "active",
                }
            )

    return allergies


def _extract_immunizations(section) -> list[dict]:
    """Extract immunizations from athena Immunizations section."""
    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return []

    immunizations = []
    for table in text_el.findall(f".//{{{NS}}}table"):
        headers = _get_headers(table)
        if not headers:
            continue

        col_map = {}
        for i, h in enumerate(headers):
            hl = h.lower()
            if "vaccine" in hl or hl == "name":
                col_map["name"] = i
            elif "date" in hl and "admin" in hl:
                col_map["date"] = i
            elif "date" in hl:
                col_map.setdefault("date", i)
            elif "lot" in hl:
                col_map["lot"] = i
            elif "status" in hl:
                col_map["status"] = i

        for row in _iter_rows(table):
            cells = [el_text(td) for td in row]
            name = (
                cells[col_map.get("name", 0)].strip()
                if "name" in col_map and col_map["name"] < len(cells)
                else ""
            )
            if not name:
                continue

            immunizations.append(
                {
                    "name": name,
                    "date": cells[col_map["date"]].strip()
                    if "date" in col_map and col_map["date"] < len(cells)
                    else "",
                    "lot": cells[col_map["lot"]].strip()
                    if "lot" in col_map and col_map["lot"] < len(cells)
                    else "",
                    "status": cells[col_map["status"]].strip()
                    if "status" in col_map and col_map["status"] < len(cells)
                    else "",
                }
            )

    return immunizations


def _extract_social_history(section) -> list[dict]:
    """Extract social history from athena Social History section."""
    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return []

    entries = []
    for table in text_el.findall(f".//{{{NS}}}table"):
        headers = _get_headers(table)
        if not headers:
            continue

        for row in _iter_rows(table):
            cells = [el_text(td) for td in row]
            if len(cells) >= 2:
                category = cells[0].strip()
                value = cells[1].strip()
                if category and value:
                    entries.append({"category": category, "value": value})

    return entries


def _extract_family_history(section) -> list[dict]:
    """Extract family history from athena Family History section."""
    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return []

    entries = []
    for table in text_el.findall(f".//{{{NS}}}table"):
        headers = _get_headers(table)
        if not headers:
            continue

        col_map = {}
        for i, h in enumerate(headers):
            hl = h.lower()
            if "relation" in hl or "family member" in hl:
                col_map["relation"] = i
            elif "diagnosis" in hl or "condition" in hl or "description" in hl or hl == "name":
                col_map["condition"] = i

        for row in _iter_rows(table):
            cells = [el_text(td) for td in row]
            relation = (
                cells[col_map.get("relation", 0)].strip()
                if "relation" in col_map and col_map["relation"] < len(cells)
                else ""
            )
            condition = (
                cells[col_map.get("condition", 1)].strip()
                if "condition" in col_map and col_map["condition"] < len(cells)
                else ""
            )
            if relation or condition:
                entries.append({"relation": relation, "condition": condition})

    return entries


def _extract_mental_status(section) -> list[dict]:
    """Extract mental health screenings from athena Mental Status section.

    Two table types:
    1. Question/Answer tables (e.g., "Do you feel stressed...": "Not at all")
    2. Score tables (Date, Assessment [PHQ-2/PHQ-9], Value [score])
       + individual question rows with answers
    """
    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return []

    entries = []
    for table in text_el.findall(f".//{{{NS}}}table"):
        headers = _get_headers(table)
        if not headers:
            continue

        header_types = [h.lower() for h in headers]

        if "question" in header_types and "answer" in header_types:
            # Type 1: Question/Answer with LastModified Time
            q_idx = header_types.index("question")
            a_idx = header_types.index("answer")
            time_idx = None
            for i, h in enumerate(header_types):
                if "lastmodified" in h and "time" in h:
                    time_idx = i
                    break

            for row in _iter_rows(table):
                cells = [el_text(td) for td in row]
                question = cells[q_idx].strip() if q_idx < len(cells) else ""
                answer = cells[a_idx].strip() if a_idx < len(cells) else ""
                date = ""
                if time_idx is not None and time_idx < len(cells):
                    date = cells[time_idx].strip()
                if question:
                    entries.append(
                        {
                            "instrument": "",
                            "question": question,
                            "answer": answer,
                            "score": None,
                            "total_score": None,
                            "date": normalize_date_to_iso(date),
                        }
                    )

        elif "assessment" in header_types:
            # Type 2: Date + Assessment + Value (PHQ scores + individual items)
            date_idx = header_types.index("date") if "date" in header_types else 0
            assess_idx = header_types.index("assessment")
            value_idx = header_types.index("value") if "value" in header_types else 2

            current_instrument = ""
            current_total = None
            current_date = ""

            for row in _iter_rows(table):
                cells = [el_text(td) for td in row]
                date_str = cells[date_idx].strip() if date_idx < len(cells) else ""
                assessment = cells[assess_idx].strip() if assess_idx < len(cells) else ""
                value = cells[value_idx].strip() if value_idx < len(cells) else ""

                if not assessment:
                    continue

                if date_str:
                    current_date = normalize_date_to_iso(date_str)

                # Check if this is a total score row (instrument name like "PHQ-2/PHQ-9")
                if re.match(r"PHQ|GAD|AUDIT|DAST", assessment, re.IGNORECASE):
                    current_instrument = assessment
                    try:
                        current_total = int(value)
                    except (ValueError, TypeError):
                        current_total = None
                    entries.append(
                        {
                            "instrument": current_instrument,
                            "question": "",
                            "answer": "",
                            "score": None,
                            "total_score": current_total,
                            "date": current_date,
                        }
                    )
                else:
                    # Individual question row
                    entries.append(
                        {
                            "instrument": current_instrument,
                            "question": assessment,
                            "answer": value,
                            "score": None,
                            "total_score": None,
                            "date": current_date,
                        }
                    )

    return entries


def _extract_encounters(section) -> list[dict]:
    """Extract past encounters from athena Past Encounters section.

    Multi-row pattern: continuation rows (extra diagnoses) have empty leading cells.
    """
    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return []

    encounters = []
    for table in text_el.findall(f".//{{{NS}}}table"):
        headers = _get_headers(table)
        if not headers:
            continue

        col_map = {}
        for i, h in enumerate(headers):
            hl = h.lower()
            if "encounter id" in hl:
                col_map["id"] = i
            elif "performer" in hl:
                col_map["provider"] = i
            elif "location" in hl:
                col_map["facility"] = i
            elif "start" in hl and "date" in hl:
                col_map["start_date"] = i
            elif "closed" in hl or ("end" in hl and "date" in hl):
                col_map["end_date"] = i
            elif (
                "diagnosis" in hl
                and "snomed" not in hl
                and "icd" not in hl
                and "imo" not in hl
                and "note" not in hl
            ):
                col_map["diagnosis"] = i
            elif "snomed" in hl:
                col_map["snomed"] = i
            elif "icd10" in hl or "icd-10" in hl or "icd 10" in hl:
                col_map["icd10"] = i

        current_encounter = None
        for row in _iter_rows(table):
            cells = [el_text(td) for td in row]
            enc_id = (
                cells[col_map["id"]].strip()
                if "id" in col_map and col_map["id"] < len(cells)
                else ""
            )

            if enc_id:
                # New encounter
                if current_encounter is not None:
                    encounters.append(current_encounter)

                provider = (
                    cells[col_map["provider"]].strip()
                    if "provider" in col_map and col_map["provider"] < len(cells)
                    else ""
                )
                facility = (
                    cells[col_map["facility"]].strip()
                    if "facility" in col_map and col_map["facility"] < len(cells)
                    else ""
                )
                start = (
                    cells[col_map["start_date"]].strip()
                    if "start_date" in col_map and col_map["start_date"] < len(cells)
                    else ""
                )
                end = (
                    cells[col_map["end_date"]].strip()
                    if "end_date" in col_map and col_map["end_date"] < len(cells)
                    else ""
                )
                diagnosis = (
                    cells[col_map["diagnosis"]].strip()
                    if "diagnosis" in col_map and col_map["diagnosis"] < len(cells)
                    else ""
                )
                icd10 = (
                    cells[col_map["icd10"]].strip()
                    if "icd10" in col_map and col_map["icd10"] < len(cells)
                    else ""
                )

                current_encounter = {
                    "id": enc_id,
                    "provider": provider,
                    "facility": _clean_facility(facility),
                    "date": normalize_date_to_iso(start),
                    "end_date": normalize_date_to_iso(end),
                    "type": "office visit",
                    "reason": diagnosis,
                    "diagnoses": [{"name": diagnosis, "icd10": icd10}] if diagnosis else [],
                }
            elif current_encounter is not None:
                # Continuation row — additional diagnosis
                diagnosis = (
                    cells[col_map["diagnosis"]].strip()
                    if "diagnosis" in col_map and col_map["diagnosis"] < len(cells)
                    else ""
                )
                icd10 = (
                    cells[col_map["icd10"]].strip()
                    if "icd10" in col_map and col_map["icd10"] < len(cells)
                    else ""
                )
                if diagnosis:
                    current_encounter["diagnoses"].append({"name": diagnosis, "icd10": icd10})
                    current_encounter["reason"] += f"; {diagnosis}"

        if current_encounter is not None:
            encounters.append(current_encounter)

    return encounters


# ---- Helpers ----


def _get_headers(table) -> list[str]:
    """Extract column headers from a CDA table."""
    thead = table.find(f"{{{NS}}}thead")
    if thead is None:
        return []
    return [el_text(th).strip() for th in thead.findall(f".//{{{NS}}}th")]


def _iter_rows(table):
    """Iterate over <tbody><tr> elements in a CDA table."""
    for tbody in table.findall(f".//{{{NS}}}tbody"):
        for tr in tbody.findall(f"{{{NS}}}tr"):
            yield tr


def _parse_vital_value(text: str) -> float | None:
    """Parse a number from vital sign text."""
    m = re.match(r"([\d.]+)", text.strip())
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _parse_vital_value_unit(text: str) -> tuple[float | None, str]:
    """Parse value and unit from vital text like '185.42 cm' or '97.5 [degF]'."""
    m = re.match(r"([\d.]+)\s*(.*)", text.strip())
    if m:
        try:
            val = float(m.group(1))
            unit = m.group(2).strip()
            return val, unit
        except ValueError:
            pass
    return None, ""


def _clean_facility(text: str) -> str:
    """Clean up facility location text (remove address details)."""
    # Take just the first line/paragraph
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return lines[0] if lines else text.strip()
