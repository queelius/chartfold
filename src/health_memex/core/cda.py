"""CDA R2 XML parsing utilities shared across Epic and MEDITECH sources."""

import re
from datetime import datetime

from lxml import etree

NS = "urn:hl7-org:v3"


def parse_doc(filepath: str, recover: bool = False) -> etree._Element:
    """Parse a CDA XML file and return the root element.

    Args:
        filepath: Path to the XML file.
        recover: If True, use lxml's recovery mode for encoding issues.
    """
    if recover:
        parser = etree.XMLParser(recover=True, encoding="utf-8")
        with open(filepath, "rb") as f:
            return etree.parse(f, parser).getroot()
    return etree.parse(filepath).getroot()


def get_title(root: etree._Element) -> str:
    """Extract the document title."""
    el = root.find(f"{{{NS}}}title")
    return el.text.strip() if el is not None and el.text else "Unknown"


def get_encounter_date(root: etree._Element) -> str:
    """Extract the encounter date from encompassingEncounter.

    Returns YYYYMMDD string or empty string.
    """
    low = root.find(f".//{{{NS}}}encompassingEncounter/{{{NS}}}effectiveTime/{{{NS}}}low")
    if low is not None:
        val = low.get("value", "")
        return str(val)[:8] if val else ""
    eff = root.find(f".//{{{NS}}}encompassingEncounter/{{{NS}}}effectiveTime")
    if eff is not None:
        val = eff.get("value", "")
        return str(val)[:8] if val else ""
    return ""


def get_encounter_end_date(root: etree._Element) -> str:
    """Extract the encounter end date from encompassingEncounter.

    Returns YYYYMMDD string or empty string.
    """
    high = root.find(f".//{{{NS}}}encompassingEncounter/{{{NS}}}effectiveTime/{{{NS}}}high")
    if high is not None:
        val = high.get("value", "")
        return str(val)[:8] if val else ""
    return ""


def extract_patient_demographics(root: etree._Element) -> dict[str, str]:
    """Extract patient demographics from CDA recordTarget/patientRole.

    Returns dict with keys: name, date_of_birth, gender, mrn, address, phone.
    """
    info: dict[str, str] = {
        "name": "",
        "date_of_birth": "",
        "gender": "",
        "mrn": "",
        "address": "",
        "phone": "",
    }

    patient_role = root.find(f".//{{{NS}}}recordTarget/{{{NS}}}patientRole")
    if patient_role is None:
        return info

    # MRN from id element
    id_el = patient_role.find(f"{{{NS}}}id")
    if id_el is not None:
        info["mrn"] = id_el.get("extension", "")

    # Phone from telecom
    telecom = patient_role.find(f"{{{NS}}}telecom")
    if telecom is not None:
        info["phone"] = telecom.get("value", "").replace("tel:", "")

    # Address
    addr = patient_role.find(f"{{{NS}}}addr")
    if addr is not None:
        parts = []
        for tag in ("streetAddressLine", "city", "state", "postalCode"):
            el = addr.find(f"{{{NS}}}{tag}")
            if el is not None and el.text:
                parts.append(el.text.strip())
        info["address"] = ", ".join(parts)

    # Patient sub-element
    patient = patient_role.find(f"{{{NS}}}patient")
    if patient is not None:
        # Name
        name_el = patient.find(f"{{{NS}}}name")
        if name_el is not None:
            given = name_el.find(f"{{{NS}}}given")
            family = name_el.find(f"{{{NS}}}family")
            parts = []
            if given is not None and given.text:
                parts.append(given.text.strip())
            if family is not None and family.text:
                parts.append(family.text.strip())
            info["name"] = " ".join(parts)

        # Gender
        gender_el = patient.find(f"{{{NS}}}administrativeGenderCode")
        if gender_el is not None:
            info["gender"] = gender_el.get("displayName", gender_el.get("code", ""))

        # DOB
        birth_el = patient.find(f"{{{NS}}}birthTime")
        if birth_el is not None:
            info["date_of_birth"] = birth_el.get("value", "")

    return info


def format_date(dt_str: str) -> str:
    """Convert various date formats to MM/DD/YYYY.

    Handles:
    - ISO 8601: 2025-06-30T13:25:00+00:00
    - YYYYMMDD: 20211123
    - YYYY-MM-DD: 2025-06-30
    """
    if not dt_str:
        return ""
    cleaned = re.sub(r"[+-]\d{2}:\d{2}$", "", dt_str)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", cleaned)
    if m:
        return f"{m.group(2)}/{m.group(3)}/{m.group(1)}"
    if len(dt_str) >= 8 and dt_str[:8].isdigit():
        try:
            return datetime.strptime(dt_str[:8], "%Y%m%d").strftime("%m/%d/%Y")
        except ValueError:
            pass
    return dt_str


def get_sections(root: etree._Element) -> dict[str, etree._Element]:
    """Return a dict mapping section title -> section element."""
    result = {}
    for section in root.findall(f".//{{{NS}}}section"):
        title_el = section.find(f"{{{NS}}}title")
        if title_el is not None and title_el.text:
            result[title_el.text.strip()] = section
    return result


def section_text(section: etree._Element) -> str:
    """Extract readable text from a CDA section's <text> element."""
    text_el = section.find(f"{{{NS}}}text")
    if text_el is None:
        return ""
    result = etree.tostring(text_el, method="text", encoding="unicode")
    return str(result).strip()


def el_text(el: etree._Element | None) -> str:
    """Get text content of an element, stripping whitespace."""
    if el is None:
        return ""
    result = etree.tostring(el, method="text", encoding="unicode")
    return str(result).strip()


def extract_encounter_info(root: etree._Element) -> dict[str, str | list[str]]:
    """Extract encounter metadata (providers, facility)."""
    info: dict[str, str | list[str]] = {}
    facility = root.find(f".//{{{NS}}}encompassingEncounter//{{{NS}}}name")
    if facility is not None and facility.text:
        info["facility"] = facility.text.strip()

    authors = []
    for author in root.findall(f".//{{{NS}}}author"):
        given = author.find(f".//{{{NS}}}given")
        family = author.find(f".//{{{NS}}}family")
        if given is not None and family is not None:
            name = f"{given.text} {family.text}"
            suffix = author.find(f".//{{{NS}}}suffix")
            if suffix is not None and suffix.text:
                name += f", {suffix.text}"
            authors.append(name)
    info["authors"] = authors

    return info
