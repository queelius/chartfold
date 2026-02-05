"""Epic CDA R2 XML source parser.

Handles Epic/Cerner MyChart exports using the IHE XDM format.
Key characteristics:
- DOC####.XML naming convention
- 2 cumulative docs (DOC0001/DOC0002) + N per-encounter docs
- Results section uses <list><item><caption><table> structure
- Panel captions: "PANEL - Final result (MM/DD/YYYY H:MM AM TZ)"
"""

import os
import re
from collections import defaultdict

from chartfold.core.cda import (
    NS,
    el_text,
    extract_encounter_info,
    format_date,
    get_encounter_date,
    get_sections,
    get_title,
    parse_doc,
    section_text,
)
from chartfold.sources.base import EPIC_CONFIG, SourceConfig, discover_files


def process_epic_documents(input_dir: str, config: SourceConfig | None = None) -> dict:
    """Parse all Epic CDA documents and return structured data."""
    config = config or EPIC_CONFIG

    data = {
        "source": config.name,
        "input_dir": os.path.abspath(input_dir),
        "inventory": [],
        "cea_values": [],
        "lab_results": [],
        "imaging_reports": [],
        "pathology_reports": [],
        "clinical_notes": [],
        "medications": [],
        "problems": [],
        "vitals": [],
        "immunizations": [],
        "allergies": [],
        "social_history": [],
        "procedures": [],
        "encounter_timeline": [],
        "errors": [],
    }

    files = discover_files(input_dir, config.file_pattern)
    # Sort by numeric ID
    files.sort(key=lambda f: int(re.search(r"\d+", os.path.basename(f)).group()))

    print(f"Found {len(files)} Epic documents to process")

    cumulative_items = []

    for filepath in files:
        doc_file = os.path.basename(filepath)
        doc_id = doc_file.replace(".XML", "")

        try:
            root = parse_doc(filepath, recover=config.recover_xml)
            title = get_title(root)
            enc_date = get_encounter_date(root)
            sections = get_sections(root)
            enc_info = extract_encounter_info(root)
            size_kb = os.path.getsize(filepath) // 1024

            section_names = list(sections.keys())
            data["inventory"].append({
                "doc_id": doc_id,
                "date": format_date(enc_date) if enc_date else "N/A (cumulative)",
                "title": title,
                "size_kb": size_kb,
                "sections": section_names,
                "authors": enc_info.get("authors", []),
                "facility": enc_info.get("facility", ""),
                "file_path": os.path.abspath(filepath),
            })

            if enc_date:
                data["encounter_timeline"].append({
                    "date": enc_date,
                    "date_fmt": format_date(enc_date),
                    "doc_id": doc_id,
                    "title": title,
                    "key_sections": [
                        s for s in section_names
                        if s not in (
                            "Allergies", "Immunizations", "Social History",
                            "Last Filed Vital Signs", "Insurance",
                            "Advance Directives", "Care Teams",
                        )
                    ],
                    "facility": enc_info.get("facility", ""),
                })

            # Results from cumulative docs
            if doc_id in config.cumulative_doc_ids:
                for sec_name in config.lab_sections:
                    if sec_name in sections:
                        items = _extract_epic_result_items(sections[sec_name])
                        for item in items:
                            item["source_doc"] = doc_id
                        cumulative_items.extend(items)

            # Clinical notes from encounter-specific docs
            for note_name in config.note_sections:
                if note_name in sections:
                    text = section_text(sections[note_name])
                    if text.strip():
                        data["clinical_notes"].append({
                            "doc_id": doc_id,
                            "date": format_date(enc_date) if enc_date else "N/A",
                            "section": note_name,
                            "text": text,
                        })

            # Structured medications and problems from DOC0002
            if doc_id == "DOC0002":
                for sec_name in config.medication_sections:
                    if sec_name in sections:
                        data["medications"] = _extract_epic_medications(sections[sec_name])
                        break

                for sec_name in config.problem_sections:
                    if sec_name in sections:
                        data["problems"] = _extract_epic_problems(sections[sec_name])
                        break

                # Vitals
                if "Last Filed Vital Signs" in sections:
                    data["vitals"] = _extract_epic_vitals(sections["Last Filed Vital Signs"])

                # Immunizations
                if "Immunizations" in sections:
                    data["immunizations"] = _extract_epic_immunizations(sections["Immunizations"])

                # Allergies
                if "Allergies" in sections:
                    data["allergies"] = _extract_epic_allergies(sections["Allergies"])

                # Social History
                if "Social History" in sections:
                    data["social_history"] = _extract_epic_social_history(sections["Social History"])

            # Procedures from ALL docs that have them (encounter-specific)
            if "Procedures" in sections:
                procs = _extract_epic_procedures(sections["Procedures"])
                for p in procs:
                    p["source_doc"] = doc_id
                data["procedures"].extend(procs)

            print(f"  {doc_id}: {title}, {enc_date or 'cumulative'}, "
                  f"{len(sections)} sections, {size_kb}KB")

        except Exception as e:
            data["errors"].append({"doc_id": doc_id, "error": str(e)})
            print(f"  ERROR {doc_id}: {e}")

    # Process cumulative items
    print(f"\nProcessing {len(cumulative_items)} result items from cumulative docs...")
    data["cea_values"] = _extract_cea(cumulative_items)
    data["lab_results"] = _extract_labs(cumulative_items)
    data["imaging_reports"] = _extract_imaging(cumulative_items)
    data["pathology_reports"] = _extract_pathology(cumulative_items)

    data["encounter_timeline"].sort(key=lambda x: x["date"], reverse=True)
    return data


def _extract_epic_result_items(section) -> list[dict]:
    """Extract structured result items from an Epic Results section.

    Epic Results sections use: <text><list><item><caption>PANEL - Final result (date)</caption>
    <table><tbody><tr><td>Component</td><td>Value</td><td>RefRange</td></tr></tbody></table>
    """
    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return []

    items = []
    for item in text_el.findall(f".//{{{NS}}}item"):
        caption_el = item.find(f"{{{NS}}}caption")
        if caption_el is None:
            continue
        caption = el_text(caption_el)

        m = re.match(
            r"(.+?)\s*-\s*(?:Final|Preliminary)\s+result\s*\((\d{2}/\d{2}/\d{4})\s+(\d+:\d+\s*[AP]M\s*\w+)\)",
            caption,
        )
        if not m:
            continue

        panel_name = m.group(1).strip()
        panel_date = m.group(2)
        panel_time = m.group(3).strip()

        components = []
        tables = item.findall(f"{{{NS}}}table")
        if tables:
            for row in tables[0].findall(f".//{{{NS}}}tbody/{{{NS}}}tr"):
                style = row.get("styleCode", "")
                if "xmergeUp" in style:
                    continue
                tds = row.findall(f"{{{NS}}}td")
                if len(tds) >= 3:
                    comp_name = el_text(tds[0])
                    comp_value = el_text(tds[1])
                    comp_ref = el_text(tds[2])
                    if comp_name and comp_value:
                        components.append({
                            "name": comp_name,
                            "value": comp_value,
                            "ref_range": comp_ref,
                        })

        result_type = ""
        for table in tables:
            for row in table.findall(f".//{{{NS}}}tbody/{{{NS}}}tr"):
                for td in row.findall(f"{{{NS}}}td"):
                    td_text = el_text(td)
                    if td_text.startswith(("LAB ", "IMG ", "ANESTHESIA", "LAB PATHOLOGY")):
                        result_type = td_text
                        break
                if result_type:
                    break
            if result_type:
                break

        items.append({
            "panel": panel_name,
            "date": panel_date,
            "time": panel_time,
            "components": components,
            "result_type": result_type,
            "full_text": el_text(item),
        })

    return items


def _classify_result(item: dict) -> str:
    """Classify a result item as 'lab', 'imaging', 'pathology', or 'other'."""
    rt = item["result_type"].upper()
    panel = item["panel"].upper()

    if "SURGICAL PATHOLOGY" in panel or "SCAN - PATHOLOGY" in panel:
        return "pathology"
    if rt.startswith("IMG ") or rt.startswith("IMG_"):
        return "imaging"
    if any(kw in panel for kw in ("MRI ", "CT ", "PET", "XR ", "CHEST ", "US ")):
        if "CREATININE" in panel or "CT BODY OUTSIDE CONSULT" in panel:
            return "other"
        if rt.startswith("LAB "):
            return "lab"
        return "imaging"
    if rt.startswith("LAB "):
        return "lab"
    if "PATHOLOGY" in rt:
        return "pathology"
    return "lab"


def _extract_cea(items: list[dict]) -> list[dict]:
    cea_entries = []
    seen_dates = set()
    for item in items:
        if item["panel"].upper().startswith("CEA"):
            date = item["date"]
            if date in seen_dates:
                continue
            seen_dates.add(date)
            for comp in item["components"]:
                if comp["name"].upper() == "CEA":
                    cea_entries.append({
                        "date": date,
                        "value": comp["value"],
                        "ref_range": comp["ref_range"],
                    })
                    break
    return sorted(cea_entries, key=lambda x: x["date"])


def _extract_labs(items: list[dict]) -> list[dict]:
    labs = []
    seen = set()
    for item in items:
        if _classify_result(item) != "lab":
            continue
        key = (item["panel"], item["date"])
        if key in seen:
            continue
        seen.add(key)
        labs.append({
            "panel": item["panel"],
            "date": item["date"],
            "time": item["time"],
            "components": item["components"],
            "result_type": item["result_type"],
        })
    return sorted(labs, key=lambda x: x["date"], reverse=True)


def _extract_imaging(items: list[dict]) -> list[dict]:
    reports = []
    seen = set()
    for item in items:
        if _classify_result(item) != "imaging":
            continue
        key = (item["panel"][:40], item["date"])
        if key in seen:
            continue
        seen.add(key)

        text = item["full_text"]
        impression = ""
        imp_match = re.search(
            r"IMPRESSION:\s*(.*?)(?:Electronically signed|Dictated by|Authorizing Provider)",
            text, re.DOTALL,
        )
        if not imp_match:
            imp_match = re.search(
                r"Impressions\d{2}/\d{2}/\d{4}\s+\d+:\d+\s*[AP]M\s*\w+\s*(.*?)(?:Electronically signed|Dictated by|Authorizing Provider|Narrative)",
                text, re.DOTALL,
            )
        if imp_match:
            impression = imp_match.group(1).strip()
            impression = re.sub(r"^\d{2}/\d{2}/\d{4}\s+\d+:\d+\s*[AP]M\s*\w+\s*", "", impression)

        findings = ""
        find_match = re.search(
            r"FINDINGS[:\s]*(.*?)(?:IMPRESSION|Electronically signed|Dictated by)",
            text, re.DOTALL | re.IGNORECASE,
        )
        if find_match:
            findings = find_match.group(1).strip()

        reports.append({
            "study": item["panel"],
            "date": item["date"],
            "time": item["time"],
            "impression": impression,
            "findings": findings,
            "full_text": text,
        })
    return sorted(reports, key=lambda x: x["date"], reverse=True)


def _extract_pathology(items: list[dict]) -> list[dict]:
    reports = []
    seen = set()
    for item in items:
        if _classify_result(item) != "pathology":
            continue
        key = (item["panel"][:40], item["date"])
        if key in seen:
            continue
        seen.add(key)

        text = item["full_text"]

        diagnosis = ""
        diag_match = re.search(
            r"Diagnosis:\s*(.*?)(?:gp/|laha/|bao2/|abpa/|Report Electronically|Gross Description|Microscopic|Comment|By this signature)",
            text, re.DOTALL | re.IGNORECASE,
        )
        if diag_match:
            diagnosis = diag_match.group(1).strip()

        gross = ""
        gross_match = re.search(
            r"Gross Description:\s*(.*?)(?:Microscopic Description|Comment|By this signature|PA\(s\):|abpa/|bao2/)",
            text, re.DOTALL | re.IGNORECASE,
        )
        if gross_match:
            gross = gross_match.group(1).strip()

        micro = ""
        micro_match = re.search(
            r"Microscopic Description:\s*(.*?)(?:Comment|By this signature|Addendum|Diagnosis:)",
            text, re.DOTALL | re.IGNORECASE,
        )
        if micro_match:
            micro = micro_match.group(1).strip()

        reports.append({
            "panel": item["panel"],
            "date": item["date"],
            "diagnosis": diagnosis,
            "gross": gross,
            "microscopic": micro,
            "full_text": text,
        })
    return sorted(reports, key=lambda x: x["date"], reverse=True)


# ---------------------------------------------------------------------------
# Code system OID constants
# ---------------------------------------------------------------------------
OID_RXNORM = "2.16.840.1.113883.6.88"
OID_SNOMED = "2.16.840.1.113883.6.96"
OID_ICD10CM = "2.16.840.1.113883.6.90"
OID_LOINC = "2.16.840.1.113883.6.1"
OID_CVX = "2.16.840.1.113883.12.292"
OID_NCI_ROUTE = "2.16.840.1.113883.3.26.1.1"

# LOINC code -> canonical vital type
_VITAL_LOINC_MAP = {
    "8480-6": "bp_systolic",
    "8462-4": "bp_diastolic",
    "8867-4": "heart_rate",
    "8310-5": "temperature",
    "9279-1": "respiratory_rate",
    "59408-5": "spo2",
    "3141-9": "weight",
    "8302-2": "height",
    "39156-5": "bmi",
}

# LOINC code -> social history category
_SOCIAL_LOINC_MAP = {
    "72166-2": "tobacco_smoking_status",
    "76689-9": "sex_assigned_at_birth",
}


def _resolve_text_reference(section, ref_value: str) -> str:
    """Look up a text reference like '#med188' in the section's <text> element.

    The reference value has the form ``#ID`` — we search for a
    ``<content ID="ID">`` element inside the section's ``<text>`` block.
    """
    if not ref_value:
        return ""
    ref_id = ref_value.lstrip("#")
    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return ""
    # Epic uses various element types for text references:
    # <content>, <paragraph>, <td> — search for any element with matching ID.
    for tag in ("content", "paragraph", "td"):
        el = text_el.find(f".//{{{NS}}}{tag}[@ID='{ref_id}']")
        if el is not None:
            return el_text(el)
    return ""


# ---------------------------------------------------------------------------
# 1. Medications
# ---------------------------------------------------------------------------

def _extract_epic_medications(section) -> list[dict]:
    """Extract structured medication entries from an Epic Medications section.

    Parses ``<entry><substanceAdministration>`` elements with coded drug
    information from ``manufacturedMaterial/code``.
    """
    results = []
    for entry in section.findall(f"{{{NS}}}entry"):
        sa = entry.find(f"{{{NS}}}substanceAdministration")
        if sa is None:
            continue

        # Status
        status_el = sa.find(f"{{{NS}}}statusCode")
        status = status_el.get("code", "") if status_el is not None else ""

        # Effective time (start/stop)
        start_date = ""
        stop_date = ""
        eff = sa.find(f"{{{NS}}}effectiveTime")
        if eff is not None:
            low = eff.find(f"{{{NS}}}low")
            if low is not None and low.get("nullFlavor") is None:
                start_date = low.get("value", "")
            high = eff.find(f"{{{NS}}}high")
            if high is not None and high.get("nullFlavor") is None:
                stop_date = high.get("value", "")

        # Route
        route_el = sa.find(f"{{{NS}}}routeCode")
        route = route_el.get("displayName", "") if route_el is not None else ""

        # Dose
        dose_el = sa.find(f"{{{NS}}}doseQuantity")
        dose_value = ""
        dose_unit = ""
        if dose_el is not None:
            dose_value = dose_el.get("value", "")
            dose_unit = dose_el.get("unit", "")

        # Drug code from manufacturedMaterial/code
        name = ""
        rxnorm = ""
        code_el = sa.find(
            f".//{{{NS}}}manufacturedMaterial/{{{NS}}}code"
        )
        if code_el is not None:
            # Try displayName first
            name = code_el.get("displayName", "")
            # RxNorm code
            if code_el.get("codeSystem") == OID_RXNORM:
                rxnorm = code_el.get("code", "")
            # Fallback name: look up referenced text
            if not name:
                orig_ref = code_el.find(f"{{{NS}}}originalText/{{{NS}}}reference")
                if orig_ref is not None:
                    name = _resolve_text_reference(section, orig_ref.get("value", ""))

        # Build sig from dose + route
        sig_parts = []
        if dose_value:
            sig_parts.append(f"{dose_value} {dose_unit}".strip())
        if route:
            sig_parts.append(route)
        sig = ", ".join(sig_parts) if sig_parts else ""

        results.append({
            "name": name,
            "rxnorm": rxnorm,
            "status": status,
            "route": route,
            "dose": f"{dose_value} {dose_unit}".strip() if dose_value else "",
            "sig": sig,
            "start_date": start_date,
            "stop_date": stop_date,
        })

    return results


# ---------------------------------------------------------------------------
# 2. Problems / Conditions
# ---------------------------------------------------------------------------

def _extract_epic_problems(section) -> list[dict]:
    """Extract structured problem entries from an Epic Active Problems section.

    Parses ``<entry><act><entryRelationship><observation>`` structures with
    coded diagnoses (SNOMED, ICD-10) and status observations.
    """
    results = []
    for entry in section.findall(f"{{{NS}}}entry"):
        act = entry.find(f"{{{NS}}}act")
        if act is None:
            continue

        # Onset date from act effectiveTime/low
        onset_date = ""
        eff = act.find(f"{{{NS}}}effectiveTime")
        if eff is not None:
            low = eff.find(f"{{{NS}}}low")
            if low is not None and low.get("nullFlavor") is None:
                onset_date = low.get("value", "")

        # Find the observation inside entryRelationship
        obs = act.find(
            f"{{{NS}}}entryRelationship/{{{NS}}}observation"
        )
        if obs is None:
            continue

        # Value element — holds SNOMED code and translations
        value_el = obs.find(f"{{{NS}}}value")
        name = ""
        snomed = ""
        icd10 = ""

        if value_el is not None:
            # SNOMED from value element itself
            if value_el.get("codeSystem") == OID_SNOMED:
                snomed = value_el.get("code", "")

            # Name: check translations first for displayName
            for trans in value_el.findall(f"{{{NS}}}translation"):
                dn = trans.get("displayName", "")
                if dn and not name:
                    name = dn
                if trans.get("codeSystem") == OID_ICD10CM:
                    icd10 = trans.get("code", "")
                    if not name:
                        name = trans.get("displayName", "")

            # Fallback name from value displayName
            if not name:
                name = value_el.get("displayName", "")

            # Fallback name from originalText reference
            if not name:
                orig_ref = value_el.find(f"{{{NS}}}originalText/{{{NS}}}reference")
                if orig_ref is not None:
                    name = _resolve_text_reference(section, orig_ref.get("value", ""))

        # Status from nested status observation (code "33999-4")
        status = ""
        for er in obs.findall(f"{{{NS}}}entryRelationship"):
            inner_obs = er.find(f"{{{NS}}}observation")
            if inner_obs is not None:
                code_el = inner_obs.find(f"{{{NS}}}code")
                if code_el is not None and code_el.get("code") == "33999-4":
                    status_val = inner_obs.find(f"{{{NS}}}value")
                    if status_val is not None:
                        status = status_val.get("displayName", "")
                    break

        results.append({
            "name": name,
            "icd10": icd10,
            "snomed": snomed,
            "status": status,
            "onset_date": onset_date,
        })

    return results


# ---------------------------------------------------------------------------
# 3. Vitals
# ---------------------------------------------------------------------------

def _extract_epic_vitals(section) -> list[dict]:
    """Extract structured vital signs from an Epic Last Filed Vital Signs section.

    Parses ``<entry><organizer><component><observation>`` elements and maps
    LOINC codes to canonical vital types.
    """
    results = []
    for entry in section.findall(f"{{{NS}}}entry"):
        organizer = entry.find(f"{{{NS}}}organizer")
        if organizer is None:
            continue
        for component in organizer.findall(f"{{{NS}}}component"):
            obs = component.find(f"{{{NS}}}observation")
            if obs is None:
                continue

            # LOINC code and display name
            code_el = obs.find(f"{{{NS}}}code")
            loinc = ""
            display_name = ""
            if code_el is not None:
                loinc = code_el.get("code", "")
                display_name = code_el.get("displayName", "")
                if not display_name:
                    orig = code_el.find(f"{{{NS}}}originalText")
                    if orig is not None:
                        display_name = el_text(orig)

            # Map LOINC to vital type
            vital_type = _VITAL_LOINC_MAP.get(loinc, display_name)

            # Value (PQ — physical quantity)
            value_el = obs.find(f"{{{NS}}}value")
            value = None
            unit = ""
            if value_el is not None and value_el.get("nullFlavor") is None:
                raw_val = value_el.get("value", "")
                unit = value_el.get("unit", "")
                if raw_val:
                    try:
                        value = float(raw_val)
                    except (ValueError, TypeError):
                        pass

            # Date
            eff_el = obs.find(f"{{{NS}}}effectiveTime")
            date = ""
            if eff_el is not None:
                date = eff_el.get("value", "")

            if vital_type and value is not None:
                results.append({
                    "type": vital_type,
                    "value": value,
                    "unit": unit,
                    "date": date,
                })

    return results


# ---------------------------------------------------------------------------
# 4. Immunizations
# ---------------------------------------------------------------------------

def _extract_epic_immunizations(section) -> list[dict]:
    """Extract structured immunization entries from an Epic Immunizations section.

    Parses ``<entry><substanceAdministration>`` with moodCode="EVN".
    Skips negated entries (negationInd="true").
    """
    results = []
    for entry in section.findall(f"{{{NS}}}entry"):
        sa = entry.find(f"{{{NS}}}substanceAdministration")
        if sa is None:
            continue

        # Skip negated entries
        if sa.get("negationInd", "false").lower() == "true":
            continue

        # Only events (administered), not orders/intents
        mood = sa.get("moodCode", "")
        if mood and mood != "EVN":
            continue

        # Status
        status_el = sa.find(f"{{{NS}}}statusCode")
        status = status_el.get("code", "") if status_el is not None else ""

        # Date
        eff_el = sa.find(f"{{{NS}}}effectiveTime")
        date = ""
        if eff_el is not None and eff_el.get("nullFlavor") is None:
            date = eff_el.get("value", "")

        # Vaccine info from manufacturedMaterial/code
        name = ""
        cvx_code = ""
        lot = ""
        mat = sa.find(f".//{{{NS}}}manufacturedMaterial")
        if mat is not None:
            code_el = mat.find(f"{{{NS}}}code")
            if code_el is not None:
                name = code_el.get("displayName", "")
                if code_el.get("codeSystem") == OID_CVX:
                    cvx_code = code_el.get("code", "")
                if not name:
                    orig_ref = code_el.find(f"{{{NS}}}originalText/{{{NS}}}reference")
                    if orig_ref is not None:
                        name = _resolve_text_reference(section, orig_ref.get("value", ""))

            lot_el = mat.find(f"{{{NS}}}lotNumberText")
            if lot_el is not None and lot_el.get("nullFlavor") is None:
                lot = el_text(lot_el)

        results.append({
            "name": name,
            "cvx_code": cvx_code,
            "date": date,
            "status": status,
            "lot": lot,
        })

    return results


# ---------------------------------------------------------------------------
# 5. Allergies
# ---------------------------------------------------------------------------

def _extract_epic_allergies(section) -> list[dict]:
    """Extract structured allergy entries from an Epic Allergies section.

    Parses ``<entry><act><entryRelationship><observation>`` structures.
    Skips observations with negationInd="true" (no known allergies).
    """
    results = []
    for entry in section.findall(f"{{{NS}}}entry"):
        act = entry.find(f"{{{NS}}}act")
        if act is None:
            continue

        # Status from act
        act_status_el = act.find(f"{{{NS}}}statusCode")
        act_status = act_status_el.get("code", "") if act_status_el is not None else ""

        obs = act.find(f"{{{NS}}}entryRelationship/{{{NS}}}observation")
        if obs is None:
            continue

        # Skip "no known allergies"
        if obs.get("negationInd", "false").lower() == "true":
            continue

        # Allergen from participant/participantRole/playingEntity/code
        allergen = ""
        playing = obs.find(
            f".//{{{NS}}}participant/{{{NS}}}participantRole/{{{NS}}}playingEntity/{{{NS}}}code"
        )
        if playing is not None:
            allergen = playing.get("displayName", "")
            if not allergen:
                allergen = el_text(playing)

        # Reaction from entryRelationship typeCode="MFST"
        reaction = ""
        for er in obs.findall(f"{{{NS}}}entryRelationship"):
            if er.get("typeCode") == "MFST":
                react_obs = er.find(f"{{{NS}}}observation")
                if react_obs is not None:
                    react_val = react_obs.find(f"{{{NS}}}value")
                    if react_val is not None:
                        reaction = react_val.get("displayName", "")
                break

        # Severity (from criticality-related entryRelationship)
        severity = ""
        for er in obs.findall(f"{{{NS}}}entryRelationship"):
            if er.get("typeCode") == "SUBJ":
                sev_obs = er.find(f"{{{NS}}}observation")
                if sev_obs is not None:
                    sev_val = sev_obs.find(f"{{{NS}}}value")
                    if sev_val is not None:
                        severity = sev_val.get("displayName", "")
                break

        if allergen:
            results.append({
                "allergen": allergen,
                "reaction": reaction,
                "severity": severity,
                "status": act_status,
            })

    return results


# ---------------------------------------------------------------------------
# 6. Social History
# ---------------------------------------------------------------------------

def _extract_epic_social_history(section) -> list[dict]:
    """Extract structured social history from an Epic Social History section.

    Parses ``<entry><observation>`` elements, mapping LOINC codes to
    standard categories.
    """
    results = []
    for entry in section.findall(f"{{{NS}}}entry"):
        obs = entry.find(f"{{{NS}}}observation")
        if obs is None:
            continue

        code_el = obs.find(f"{{{NS}}}code")
        loinc = ""
        category = ""
        if code_el is not None:
            loinc = code_el.get("code", "")
            category = code_el.get("displayName", "")

        # Map known LOINC to canonical category name
        canonical = _SOCIAL_LOINC_MAP.get(loinc)
        if canonical:
            category = canonical

        # Value
        value_el = obs.find(f"{{{NS}}}value")
        value = ""
        if value_el is not None:
            value = value_el.get("displayName", "")
            if not value:
                value = value_el.get("code", "")

        # Date
        eff_el = obs.find(f"{{{NS}}}effectiveTime")
        date = ""
        if eff_el is not None and eff_el.get("nullFlavor") is None:
            date = eff_el.get("value", "")

        results.append({
            "category": category,
            "value": value,
            "loinc": loinc,
            "date": date,
        })

    return results


# ---------------------------------------------------------------------------
# 7. Procedures
# ---------------------------------------------------------------------------

def _extract_epic_procedures(section) -> list[dict]:
    """Extract structured procedure entries from an Epic Procedures section.

    Parses ``<entry><procedure>`` elements with coded procedure information.
    """
    results = []
    for entry in section.findall(f"{{{NS}}}entry"):
        proc = entry.find(f"{{{NS}}}procedure")
        if proc is None:
            continue

        # Status
        status_el = proc.find(f"{{{NS}}}statusCode")
        status = status_el.get("code", "") if status_el is not None else ""

        # Code
        code_el = proc.find(f"{{{NS}}}code")
        name = ""
        code_value = ""
        code_system = ""
        if code_el is not None:
            code_value = code_el.get("code", "")
            code_system = code_el.get("codeSystem", "")
            name = code_el.get("displayName", "")
            if not name:
                orig = code_el.find(f"{{{NS}}}originalText")
                if orig is not None:
                    name = el_text(orig)

        # Date
        eff_el = proc.find(f"{{{NS}}}effectiveTime")
        date = ""
        if eff_el is not None and eff_el.get("nullFlavor") is None:
            date = eff_el.get("value", "")

        # Provider
        provider = ""
        perf = proc.find(
            f".//{{{NS}}}performer/{{{NS}}}assignedEntity/{{{NS}}}assignedPerson/{{{NS}}}name"
        )
        if perf is not None:
            given = perf.find(f"{{{NS}}}given")
            family = perf.find(f"{{{NS}}}family")
            parts = []
            if given is not None and given.text:
                parts.append(given.text.strip())
            if family is not None and family.text:
                parts.append(family.text.strip())
            provider = " ".join(parts)

        results.append({
            "name": name,
            "code_value": code_value,
            "code_system": code_system,
            "date": date,
            "status": status,
            "provider": provider,
        })

    return results
