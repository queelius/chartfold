"""MEDITECH Expanse CCDA source parser.

Handles MEDITECH Expanse 2.2 EHI exports with:
- UUID-named CCDA XML files
- HTML <table><thead><tbody> lab structure
- FHIR JSON Bundle for structured data
- NDJSON Table of Contents for document index
"""

import json
import os
import re
from collections import defaultdict
from datetime import datetime

from chartfold.core.cda import (
    NS,
    el_text,
    format_date,
    get_encounter_date,
    get_sections,
    get_title,
    parse_doc,
    section_text,
)
from chartfold.core.fhir import parse_fhir_bundle
from chartfold.core.utils import deduplicate_by_key, parse_narrative_date
from chartfold.sources.base import MEDITECH_CONFIG, SourceConfig, discover_files


def process_meditech_export(input_dir: str, config: SourceConfig | None = None) -> dict:
    """Parse a full MEDITECH EHI export (CCDA + FHIR + NDJSON TOC).

    Args:
        input_dir: Root directory of the MEDITECH export.
        config: Optional source configuration override.

    Returns:
        Dict with fhir_data, ccda_data, toc_data, and merged results.
    """
    config = config or MEDITECH_CONFIG

    result = {
        "source": config.name,
        "input_dir": os.path.abspath(input_dir),
        "fhir_data": None,
        "ccda_data": None,
        "toc_data": [],
    }

    # FHIR Bundle
    fhir_path = os.path.join(input_dir, "US Core FHIR Resources.json")
    if os.path.exists(fhir_path):
        print("Parsing FHIR Bundle...")
        result["fhir_data"] = parse_fhir_bundle(fhir_path)
        patient = result["fhir_data"].get("patient")
        if patient:
            print(f"  Patient: {patient['name']}")
        print(f"  Resources: {result['fhir_data']['resource_counts']}")

    # CCDA files
    ccda_dir = os.path.join(input_dir, "CCDA")
    if os.path.isdir(ccda_dir):
        print("Parsing CCDA files...")
        result["ccda_data"] = _parse_all_ccdas(ccda_dir, config)

    # NDJSON TOC
    toc_path = os.path.join(input_dir, "Table of Contents.ndjson")
    if os.path.exists(toc_path):
        print("Parsing Table of Contents...")
        result["toc_data"] = _parse_toc(toc_path)
        print(f"  Document references: {len(result['toc_data'])}")

    return result


def _parse_all_ccdas(ccda_dir: str, config: SourceConfig) -> dict:
    """Parse all CCDA files and return aggregated data."""
    agg = {
        "documents": [],
        "all_labs": [],
        "all_procedures": [],
        "all_problems": [],
        "all_medications": [],
        "all_notes": [],
        "all_vitals": [],
        "all_immunizations": [],
        "all_allergies": [],
        "all_social_history": [],
        "all_family_history": [],
        "all_mental_status": [],
        "errors": [],
    }

    files = discover_files(ccda_dir, config.file_pattern)
    print(f"  Found {len(files)} CCDA files")

    for filepath in files:
        fname = os.path.basename(filepath)
        doc = _parse_single_ccda(filepath, config)

        if doc is None or ("error" in doc and not doc.get("sections")):
            error_msg = doc.get("error", "parse returned None") if doc else "parse returned None"
            agg["errors"].append({"filename": fname, "error": error_msg})
            continue

        enc_date = doc["encounter_date"]
        date_fmt = ""
        if enc_date and len(enc_date) >= 8:
            try:
                date_fmt = datetime.strptime(enc_date[:8], "%Y%m%d").strftime("%m/%d/%Y")
            except ValueError:
                date_fmt = enc_date

        agg["documents"].append({
            "filename": fname,
            "title": doc["title"],
            "encounter_date": enc_date,
            "encounter_date_fmt": date_fmt,
            "section_names": list(doc["sections"].keys()),
            "lab_count": len(doc["labs"]),
            "note_count": len(doc["notes"]),
            "file_path": os.path.abspath(filepath),
        })

        for lab in doc["labs"]:
            lab["source_file"] = fname
            lab["encounter_date"] = enc_date
            agg["all_labs"].append(lab)

        for proc in doc["procedures"]:
            proc["source_file"] = fname
            agg["all_procedures"].append(proc)

        for prob in doc["problems"]:
            prob["source_file"] = fname
            agg["all_problems"].append(prob)

        for med in doc["medications"]:
            med["source_file"] = fname
            agg["all_medications"].append(med)

        for note_type, note_text in doc["notes"].items():
            agg["all_notes"].append({
                "type": note_type,
                "text": note_text,
                "source_file": fname,
                "encounter_date": enc_date,
                "encounter_date_fmt": date_fmt,
            })

        for vital in doc["vitals"]:
            vital["source_file"] = fname
            vital["encounter_date"] = enc_date
            agg["all_vitals"].append(vital)

        for imm in doc["immunizations"]:
            imm["source_file"] = fname
            agg["all_immunizations"].append(imm)

        for allergy in doc["allergies"]:
            allergy["source_file"] = fname
            agg["all_allergies"].append(allergy)

        for sh in doc["social_history"]:
            sh["source_file"] = fname
            agg["all_social_history"].append(sh)

        for fh in doc["family_history"]:
            fh["source_file"] = fname
            agg["all_family_history"].append(fh)

        for ms in doc["mental_status"]:
            ms["source_file"] = fname
            ms["encounter_date"] = enc_date
            agg["all_mental_status"].append(ms)

        print(f"  {fname[:12]}...: {date_fmt or 'no date'}, "
              f"{len(doc['sections'])} sections, "
              f"{len(doc['labs'])} labs, {len(doc['notes'])} notes")

    return agg


def _parse_single_ccda(filepath: str, config: SourceConfig) -> dict | None:
    """Parse a single MEDITECH CCDA XML file."""
    try:
        root = parse_doc(filepath, recover=config.recover_xml)
    except Exception as e:
        return {"error": str(e), "filename": os.path.basename(filepath)}

    doc = {
        "filename": os.path.basename(filepath),
        "title": get_title(root),
        "encounter_date": get_encounter_date(root),
        "sections": get_sections(root),
        "labs": [],
        "procedures": [],
        "problems": [],
        "medications": [],
        "notes": {},
        "vitals": [],
        "immunizations": [],
        "allergies": [],
        "social_history": [],
        "family_history": [],
        "mental_status": [],
    }

    # Labs
    for sec_name in config.lab_sections:
        if sec_name in doc["sections"]:
            doc["labs"].extend(_extract_meditech_labs(doc["sections"][sec_name]))

    # Procedures
    if "Procedures" in doc["sections"]:
        doc["procedures"] = _extract_table_rows(
            doc["sections"]["Procedures"],
            key_headers={"procedure": "name", "date": "date_raw", "status": "status", "provider": "provider"},
        )
        for proc in doc["procedures"]:
            if "date_raw" in proc:
                proc["date_iso"] = parse_narrative_date(proc["date_raw"])

    # Problems
    for sec_name in config.problem_sections:
        if sec_name in doc["sections"]:
            doc["problems"].extend(
                _extract_table_rows(
                    doc["sections"][sec_name],
                    key_headers={"problem": "name", "condition": "name", "date": "date", "status": "status"},
                )
            )

    # Medications
    for sec_name in config.medication_sections:
        if sec_name in doc["sections"]:
            doc["medications"].extend(
                _extract_table_rows(
                    doc["sections"][sec_name],
                    key_headers={
                        "medication": "name", "dose": "dose", "strength": "dose",
                        "route": "route", "freq": "frequency", "schedule": "frequency",
                        "date": "date", "start": "date", "status": "status",
                        "instruction": "instructions", "sig": "instructions",
                    },
                )
            )

    # Clinical notes
    for sec_name in config.note_sections:
        if sec_name in doc["sections"]:
            text = section_text(doc["sections"][sec_name])
            if text.strip() and len(text.strip()) > 20:
                doc["notes"][sec_name] = text

    # Vitals
    if "Vital Signs" in doc["sections"]:
        doc["vitals"] = _extract_meditech_vitals(doc["sections"]["Vital Signs"])

    # Immunizations
    if "Immunizations" in doc["sections"]:
        doc["immunizations"] = _extract_meditech_immunizations(doc["sections"]["Immunizations"])

    # Allergies
    for name in ("Allergies, Adverse Reactions, Alerts", "Allergies"):
        if name in doc["sections"]:
            doc["allergies"] = _extract_meditech_allergies(doc["sections"][name])
            break

    # Social History
    if "Social History" in doc["sections"]:
        doc["social_history"] = _extract_meditech_social_history(doc["sections"]["Social History"])

    # Family History
    for name in ("Family History", "Family history"):
        if name in doc["sections"]:
            doc["family_history"] = _extract_meditech_family_history(doc["sections"][name])
            break

    # Mental Status
    if "Mental Status" in doc["sections"]:
        doc["mental_status"] = _extract_meditech_mental_status(doc["sections"]["Mental Status"])

    return doc


def _extract_meditech_labs(section) -> list[dict]:
    """Extract lab results from MEDITECH's HTML table structure."""
    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return []

    labs = []
    for table in text_el.findall(f".//{{{NS}}}table"):
        headers = []
        thead = table.find(f"{{{NS}}}thead")
        if thead is not None:
            for th in thead.findall(f".//{{{NS}}}th"):
                headers.append(el_text(th).lower().strip())

        if not headers:
            continue

        col_map = {}
        for i, h in enumerate(headers):
            if "test" in h:
                col_map["test"] = i
            elif "date" in h or "time" in h:
                col_map["date"] = i
            elif h in ("result",):
                col_map["result"] = i
            elif "interp" in h:
                col_map["interp"] = i
            elif "ref" in h or "range" in h:
                col_map["ref_range"] = i
            elif "comment" in h:
                col_map["comment"] = i
            elif "site" in h or "performing" in h:
                col_map["site"] = i

        for tbody in table.findall(f".//{{{NS}}}tbody"):
            for tr in tbody.findall(f"{{{NS}}}tr"):
                tds = tr.findall(f"{{{NS}}}td")
                if len(tds) < 3:
                    continue

                row = {}
                for key, idx in col_map.items():
                    if idx < len(tds):
                        row[key] = el_text(tds[idx])

                if "test" in row and "result" in row and row["result"]:
                    date_str = row.get("date", "")
                    date_iso = parse_narrative_date(date_str)
                    if not date_iso and date_str:
                        m = re.match(r"(\w+\s+\d+,?\s*\d{4})", date_str)
                        if m:
                            date_iso = parse_narrative_date(m.group(1))

                    result_text = row["result"].strip()
                    value = result_text
                    unit = ""
                    m = re.match(r"([\d.]+)\s+(.+)", result_text)
                    if m:
                        value = m.group(1)
                        unit = m.group(2)

                    labs.append({
                        "test": row["test"],
                        "date_raw": date_str,
                        "date_iso": date_iso,
                        "value": value,
                        "unit": unit,
                        "result_raw": result_text,
                        "interpretation": row.get("interp", ""),
                        "ref_range": row.get("ref_range", ""),
                        "comment": row.get("comment", ""),
                        "site": row.get("site", ""),
                    })

    return labs


def _extract_table_rows(section, key_headers: dict[str, str]) -> list[dict]:
    """Generic table row extractor for MEDITECH sections.

    Args:
        section: CDA section element.
        key_headers: Mapping of header keyword -> output field name.
            First column is always used as the primary name field.
    """
    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return []

    rows = []
    for table in text_el.findall(f".//{{{NS}}}table"):
        headers = []
        thead = table.find(f"{{{NS}}}thead")
        if thead is not None:
            for th in thead.findall(f".//{{{NS}}}th"):
                headers.append(el_text(th).lower().strip())

        for tbody in table.findall(f".//{{{NS}}}tbody"):
            for tr in tbody.findall(f"{{{NS}}}tr"):
                tds = tr.findall(f"{{{NS}}}td")
                if not tds:
                    continue
                row = {"name": el_text(tds[0])}
                for i, h in enumerate(headers[1:], 1):
                    if i < len(tds):
                        val = el_text(tds[i])
                        for keyword, field_name in key_headers.items():
                            if keyword in h and field_name != "name":
                                row[field_name] = val
                                break
                if row["name"]:
                    rows.append(row)

    # Fallback to list items if no table found
    if not rows:
        for item in text_el.findall(f".//{{{NS}}}item"):
            text = el_text(item)
            if text.strip():
                rows.append({"name": text.strip()})

    return rows


def _extract_meditech_vitals(section) -> list[dict]:
    """Extract vital signs from MEDITECH's HTML table structure.

    Table headers: "Vital Reading", "Result", "Reference Range", "Collection Date/Time".
    """
    VITAL_NAME_MAP = {
        "height": "height",
        "weight": "weight",
        "body temperature": "temperature",
        "heart rate": "heart_rate",
        "respiratory rate": "respiratory_rate",
        "oxygen saturation": "spo2",
        "bp systolic": "bp_systolic",
        "bp diastolic": "bp_diastolic",
        "bmi": "bmi",
    }

    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return []

    vitals = []
    for table in text_el.findall(f".//{{{NS}}}table"):
        headers = []
        thead = table.find(f"{{{NS}}}thead")
        if thead is not None:
            for th in thead.findall(f".//{{{NS}}}th"):
                headers.append(el_text(th).lower().strip())

        if not headers:
            continue

        col_map = {}
        for i, h in enumerate(headers):
            if "vital" in h or "reading" in h:
                col_map["name"] = i
            elif "result" in h:
                col_map["result"] = i
            elif "ref" in h or "range" in h:
                col_map["ref_range"] = i
            elif "date" in h or "time" in h:
                col_map["date"] = i

        for tbody in table.findall(f".//{{{NS}}}tbody"):
            for tr in tbody.findall(f"{{{NS}}}tr"):
                tds = tr.findall(f"{{{NS}}}td")
                if len(tds) < 2:
                    continue

                row = {}
                for key, idx in col_map.items():
                    if idx < len(tds):
                        row[key] = el_text(tds[idx])

                vital_name = row.get("name", "").strip()
                result_text = row.get("result", "").strip()
                if not vital_name or not result_text:
                    continue

                vital_type = VITAL_NAME_MAP.get(vital_name.lower(), "")
                if not vital_type:
                    continue

                value = None
                unit = ""
                m = re.match(r"([\d.]+)\s*(.*)", result_text)
                if m:
                    try:
                        value = float(m.group(1))
                    except ValueError:
                        pass
                    unit = m.group(2).strip()
                    # Clean up bracketed units like [degF] or [in_i]
                    if unit.startswith("[") and unit.endswith("]"):
                        unit = unit[1:-1]

                date_str = row.get("date", "")
                date_iso = parse_narrative_date(date_str) if date_str else ""

                vitals.append({
                    "type": vital_type,
                    "value": value,
                    "unit": unit,
                    "date_iso": date_iso,
                    "ref_range": row.get("ref_range", ""),
                })

    return vitals


def _extract_meditech_immunizations(section) -> list[dict]:
    """Extract immunizations from MEDITECH's HTML table.

    Headers: "Immunization", "Event Date", "Not Given Reason",
             "Dose Number", "Manufacturer", "Lot Number".
    """
    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return []

    immunizations = []
    for table in text_el.findall(f".//{{{NS}}}table"):
        headers = []
        thead = table.find(f"{{{NS}}}thead")
        if thead is not None:
            for th in thead.findall(f".//{{{NS}}}th"):
                headers.append(el_text(th).lower().strip())

        if not headers:
            continue

        col_map = {}
        for i, h in enumerate(headers):
            if "immunization" in h or "vaccine" in h:
                col_map["name"] = i
            elif "date" in h:
                col_map["date"] = i
            elif "lot" in h:
                col_map["lot"] = i
            elif "manufacturer" in h:
                col_map["manufacturer"] = i

        for tbody in table.findall(f".//{{{NS}}}tbody"):
            for tr in tbody.findall(f"{{{NS}}}tr"):
                tds = tr.findall(f"{{{NS}}}td")
                if not tds:
                    continue

                row = {}
                for key, idx in col_map.items():
                    if idx < len(tds):
                        row[key] = el_text(tds[idx])

                name = row.get("name", "").strip()
                if not name:
                    continue

                date_raw = row.get("date", "")
                date_iso = parse_narrative_date(date_raw) if date_raw else ""

                immunizations.append({
                    "name": name,
                    "date_raw": date_raw,
                    "date_iso": date_iso,
                    "lot": row.get("lot", ""),
                    "manufacturer": row.get("manufacturer", ""),
                })

    return immunizations


def _extract_meditech_allergies(section) -> list[dict]:
    """Extract allergies from MEDITECH section.

    Checks for "No known allergies" text or negationInd="true" entries.
    """
    text_el = section.find(f"{{{NS}}}text")
    if text_el is not None:
        raw_text = el_text(text_el).lower()
        if "no known" in raw_text:
            # Check if there's a real table — if not, it's just the "no known" text
            tables = text_el.findall(f".//{{{NS}}}table")
            if not tables:
                return []

    # Check structured entries for negationInd
    for entry in section.findall(f".//{{{NS}}}entry"):
        obs = entry.find(f".//{{{NS}}}observation")
        if obs is not None and obs.get("negationInd") == "true":
            return []
        act = entry.find(f".//{{{NS}}}act")
        if act is not None:
            inner_obs = act.find(f".//{{{NS}}}observation")
            if inner_obs is not None and inner_obs.get("negationInd") == "true":
                return []

    # Parse from HTML table if present
    allergies = []
    if text_el is not None:
        for table in text_el.findall(f".//{{{NS}}}table"):
            headers = []
            thead = table.find(f"{{{NS}}}thead")
            if thead is not None:
                for th in thead.findall(f".//{{{NS}}}th"):
                    headers.append(el_text(th).lower().strip())

            col_map = {}
            for i, h in enumerate(headers):
                if "allergen" in h or "substance" in h or "allergy" in h:
                    col_map["allergen"] = i
                elif "reaction" in h:
                    col_map["reaction"] = i
                elif "severity" in h:
                    col_map["severity"] = i
                elif "status" in h:
                    col_map["status"] = i

            for tbody in table.findall(f".//{{{NS}}}tbody"):
                for tr in tbody.findall(f"{{{NS}}}tr"):
                    tds = tr.findall(f"{{{NS}}}td")
                    if not tds:
                        continue

                    row = {}
                    for key, idx in col_map.items():
                        if idx < len(tds):
                            row[key] = el_text(tds[idx])

                    # If no column map matched, use first column as allergen
                    allergen = row.get("allergen", "")
                    if not allergen and tds:
                        allergen = el_text(tds[0])
                    if allergen.strip():
                        allergies.append({
                            "allergen": allergen.strip(),
                            "reaction": row.get("reaction", ""),
                            "severity": row.get("severity", ""),
                            "status": row.get("status", ""),
                        })

    return allergies


def _extract_meditech_social_history(section) -> list[dict]:
    """Extract social history from structured CDA entry/observation elements.

    Maps LOINC codes:
    - 72166-2 -> tobacco_smoking_status
    - 76689-9 -> sex_assigned_at_birth
    """
    LOINC_MAP = {
        "72166-2": "tobacco_smoking_status",
        "76689-9": "sex_assigned_at_birth",
    }

    entries = []
    for entry in section.findall(f".//{{{NS}}}entry"):
        obs = entry.find(f".//{{{NS}}}observation")
        if obs is None:
            continue

        code_el = obs.find(f"{{{NS}}}code")
        loinc = ""
        display = ""
        if code_el is not None:
            loinc = code_el.get("code", "")
            display = code_el.get("displayName", "")

        category = LOINC_MAP.get(loinc, display or loinc)

        value_el = obs.find(f"{{{NS}}}value")
        value = ""
        if value_el is not None:
            value = value_el.get("displayName", "") or el_text(value_el)

        date_iso = ""
        eff_time = obs.find(f"{{{NS}}}effectiveTime")
        if eff_time is not None:
            raw = eff_time.get("value", "")
            if raw:
                date_iso = parse_narrative_date(raw) if not raw[:1].isdigit() else ""
                if not date_iso and len(raw) >= 8 and raw[:8].isdigit():
                    date_iso = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"

        if category or value:
            entries.append({
                "category": category,
                "value": value,
                "loinc": loinc,
                "date_iso": date_iso,
            })

    return entries


def _extract_meditech_family_history(section) -> list[dict]:
    """Extract family history from MEDITECH section.

    First tries structured CDA organizer elements, then falls back to HTML table.
    Table headers: "Relationship", "Condition", "Age at Onset", "Recorded Date/Time".
    """
    entries = []

    # Try structured CDA entries first
    for entry in section.findall(f".//{{{NS}}}entry"):
        organizer = entry.find(f".//{{{NS}}}organizer")
        if organizer is None:
            continue

        # Get relation from relatedSubject/code
        relation = ""
        subject = organizer.find(f".//{{{NS}}}subject")
        if subject is not None:
            related = subject.find(f".//{{{NS}}}relatedSubject")
            if related is not None:
                code_el = related.find(f"{{{NS}}}code")
                if code_el is not None:
                    if code_el.get("nullFlavor"):
                        # Try originalText reference
                        orig = code_el.find(f"{{{NS}}}originalText")
                        if orig is not None:
                            relation = el_text(orig)
                    else:
                        relation = code_el.get("displayName", "")

        # Get conditions from components
        for component in organizer.findall(f".//{{{NS}}}component"):
            obs = component.find(f".//{{{NS}}}observation")
            if obs is None:
                continue
            value_el = obs.find(f"{{{NS}}}value")
            condition = ""
            if value_el is not None:
                condition = value_el.get("displayName", "") or el_text(value_el)
            if condition:
                entries.append({
                    "relation": relation or "Not Specified",
                    "condition": condition,
                })

    # Fallback: parse from HTML table
    if not entries:
        text_el = section.find(f"{{{NS}}}text")
        if text_el is not None:
            for table in text_el.findall(f".//{{{NS}}}table"):
                headers = []
                thead = table.find(f"{{{NS}}}thead")
                if thead is not None:
                    for th in thead.findall(f".//{{{NS}}}th"):
                        headers.append(el_text(th).lower().strip())

                col_map = {}
                for i, h in enumerate(headers):
                    if "relation" in h:
                        col_map["relation"] = i
                    elif "condition" in h:
                        col_map["condition"] = i

                for tbody in table.findall(f".//{{{NS}}}tbody"):
                    for tr in tbody.findall(f"{{{NS}}}tr"):
                        tds = tr.findall(f"{{{NS}}}td")
                        if not tds:
                            continue

                        row = {}
                        for key, idx in col_map.items():
                            if idx < len(tds):
                                row[key] = el_text(tds[idx])

                        relation = row.get("relation", "")
                        condition = row.get("condition", "")
                        if not relation and not condition and len(tds) >= 2:
                            relation = el_text(tds[0])
                            condition = el_text(tds[1])
                        if condition.strip():
                            entries.append({
                                "relation": relation.strip() or "Not Specified",
                                "condition": condition.strip(),
                            })

    return entries


def _extract_meditech_mental_status(section) -> list[dict]:
    """Extract mental status observations from MEDITECH section.

    Table headers: "Observation", "Response", "Date Recorded".
    Also checks structured entry/observation for coded data.
    """
    entries = []

    # Parse from HTML table
    text_el = section.find(f"{{{NS}}}text")
    if text_el is not None:
        for table in text_el.findall(f".//{{{NS}}}table"):
            headers = []
            thead = table.find(f"{{{NS}}}thead")
            if thead is not None:
                for th in thead.findall(f".//{{{NS}}}th"):
                    headers.append(el_text(th).lower().strip())

            if not headers:
                continue

            col_map = {}
            for i, h in enumerate(headers):
                if "observation" in h or "question" in h:
                    col_map["observation"] = i
                elif "response" in h or "answer" in h:
                    col_map["response"] = i
                elif "date" in h:
                    col_map["date"] = i

            for tbody in table.findall(f".//{{{NS}}}tbody"):
                for tr in tbody.findall(f"{{{NS}}}tr"):
                    tds = tr.findall(f"{{{NS}}}td")
                    if not tds:
                        continue

                    row = {}
                    for key, idx in col_map.items():
                        if idx < len(tds):
                            row[key] = el_text(tds[idx])

                    observation = row.get("observation", "").strip()
                    response = row.get("response", "").strip()
                    if not observation and not response:
                        continue

                    date_str = row.get("date", "")
                    date_iso = parse_narrative_date(date_str) if date_str else ""

                    entries.append({
                        "observation": observation,
                        "response": response,
                        "date_iso": date_iso,
                    })

    # Also check structured entries if no table data
    if not entries:
        for entry in section.findall(f".//{{{NS}}}entry"):
            obs = entry.find(f".//{{{NS}}}observation")
            if obs is None:
                continue

            code_el = obs.find(f"{{{NS}}}code")
            observation = ""
            if code_el is not None:
                observation = code_el.get("displayName", "")

            value_el = obs.find(f"{{{NS}}}value")
            response = ""
            if value_el is not None:
                response = value_el.get("displayName", "") or el_text(value_el)

            date_iso = ""
            eff_time = obs.find(f"{{{NS}}}effectiveTime")
            if eff_time is not None:
                raw = eff_time.get("value", "")
                if raw and len(raw) >= 8 and raw[:8].isdigit():
                    date_iso = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"

            if observation or response:
                entries.append({
                    "observation": observation,
                    "response": response,
                    "date_iso": date_iso,
                })

    return entries


def _parse_toc(filepath: str) -> list[dict]:
    """Parse Table of Contents NDJSON file."""
    documents = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
                content = doc.get("content", [{}])
                attachment = content[0].get("attachment", {}) if content else {}
                documents.append({
                    "description": doc.get("description", ""),
                    "status": doc.get("docStatus", ""),
                    "date": doc.get("date", ""),
                    "url": attachment.get("url", ""),
                    "title": attachment.get("title", ""),
                    "size": attachment.get("size", 0),
                    "content_type": attachment.get("contentType", ""),
                    "creation": attachment.get("creation", ""),
                })
            except json.JSONDecodeError:
                pass
    return documents


# Deduplication helpers for MEDITECH's cumulative snapshot model

def deduplicate_labs(labs: list[dict]) -> list[dict]:
    """Deduplicate labs across multiple CCDA files."""
    return deduplicate_by_key(
        labs,
        key_func=lambda l: (l["test"].lower().strip(), l["date_iso"], l["value"]),
        sort_key=lambda l: (l["date_iso"] or "0000", l["test"]),
    )


def deduplicate_procedures(procedures: list[dict]) -> list[dict]:
    return deduplicate_by_key(
        procedures,
        key_func=lambda p: (p["name"].lower().strip(), p.get("date_iso", "")),
        sort_key=lambda p: p.get("date_iso", "") or "0000",
    )


def deduplicate_problems(problems: list[dict]) -> list[dict]:
    return deduplicate_by_key(
        problems,
        key_func=lambda p: p["name"].lower().strip(),
    )


def deduplicate_medications(medications: list[dict]) -> list[dict]:
    return deduplicate_by_key(
        medications,
        key_func=lambda m: m["name"].lower().strip(),
    )


def deduplicate_notes(notes: list[dict]) -> list[dict]:
    """Keep longest version per (type, encounter_date)."""
    best = {}
    for note in notes:
        key = (note["type"], note["encounter_date"])
        if key not in best or len(note["text"]) > len(best[key]["text"]):
            best[key] = note
    return sorted(best.values(), key=lambda x: (x["encounter_date"] or "0000"), reverse=True)


def deduplicate_vitals(vitals: list[dict]) -> list[dict]:
    return deduplicate_by_key(
        vitals,
        key_func=lambda v: (v["type"], v.get("date_iso", ""), str(v.get("value", ""))),
    )


def deduplicate_immunizations(immunizations: list[dict]) -> list[dict]:
    return deduplicate_by_key(
        immunizations,
        key_func=lambda i: (i["name"].lower().strip(), i.get("date_iso", "")),
    )


def deduplicate_allergies(allergies: list[dict]) -> list[dict]:
    return deduplicate_by_key(
        allergies,
        key_func=lambda a: a.get("allergen", "").lower().strip(),
    )


def deduplicate_social_history(entries: list[dict]) -> list[dict]:
    return deduplicate_by_key(
        entries,
        key_func=lambda e: (e.get("category", "").lower(), e.get("value", "").lower()),
    )


def deduplicate_family_history(entries: list[dict]) -> list[dict]:
    return deduplicate_by_key(
        entries,
        key_func=lambda e: (e.get("relation", "").lower(), e.get("condition", "").lower()),
    )


def deduplicate_mental_status(entries: list[dict]) -> list[dict]:
    return deduplicate_by_key(
        entries,
        key_func=lambda e: (e.get("observation", "").lower(), e.get("response", "").lower(), e.get("date_iso", "")),
    )
