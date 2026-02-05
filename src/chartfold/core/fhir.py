"""FHIR R4 Bundle parser for structured EHR data extraction."""

from __future__ import annotations

import base64
import json
import re
from collections import defaultdict
from html.parser import HTMLParser
from typing import Any

from chartfold.core.utils import parse_iso_date


class _HTMLTextExtractor(HTMLParser):
    """Extract plain text from HTML, collapsing whitespace."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._parts)).strip()


def decode_presented_form(data_b64: str, content_type: str = "") -> str:
    """Decode a base64 presentedForm attachment and extract text.

    Handles text/html, text/plain, and application/xhtml+xml.
    """
    if not data_b64:
        return ""
    try:
        raw = base64.b64decode(data_b64)
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return ""

    if "html" in content_type.lower() or "xhtml" in content_type.lower():
        extractor = _HTMLTextExtractor()
        try:
            extractor.feed(text)
            return extractor.get_text()
        except Exception:
            return text
    return text


def parse_fhir_bundle(filepath: str) -> dict[str, Any]:
    """Parse a FHIR Bundle JSON and extract all resource types.

    Returns a dict with keys: patient, observations, conditions,
    diagnostic_reports, medication_requests, encounters, immunizations,
    practitioners, resource_counts.
    """
    with open(filepath) as f:
        bundle = json.load(f)

    entries = bundle.get("entry", [])
    resources: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        res = entry.get("resource", {})
        rtype = res.get("resourceType", "Unknown")
        resources[rtype].append(res)

    data: dict[str, Any] = {
        "patient": None,
        "observations": [],
        "conditions": [],
        "diagnostic_reports": [],
        "medication_requests": [],
        "encounters": [],
        "immunizations": [],
        "practitioners": {},
        "resource_counts": {k: len(v) for k, v in resources.items()},
    }

    # Patient
    patients = resources.get("Patient", [])
    if patients:
        p = patients[0]
        name = p.get("name", [{}])[0]
        data["patient"] = {
            "name": f"{' '.join(name.get('given', []))} {name.get('family', '')}",
            "dob": p.get("birthDate", ""),
            "gender": p.get("gender", ""),
            "id": p.get("id", ""),
        }

    # Practitioners
    for pr in resources.get("Practitioner", []):
        name = pr.get("name", [{}])[0]
        pname = f"{' '.join(name.get('given', []))} {name.get('family', '')}"
        data["practitioners"][f"Practitioner/{pr.get('id', '')}"] = pname

    # Observations
    for obs in resources.get("Observation", []):
        data["observations"].append(_parse_observation(obs))

    # Conditions
    for cond in resources.get("Condition", []):
        data["conditions"].append(_parse_condition(cond))

    # DiagnosticReports
    for dr in resources.get("DiagnosticReport", []):
        data["diagnostic_reports"].append(_parse_diagnostic_report(dr))

    # MedicationRequests
    for med in resources.get("MedicationRequest", []):
        data["medication_requests"].append(_parse_medication_request(med))

    # Encounters
    for enc in resources.get("Encounter", []):
        data["encounters"].append(_parse_encounter(enc))

    # Immunizations
    for imm in resources.get("Immunization", []):
        data["immunizations"].append(_parse_immunization(imm))

    return data


def _parse_observation(obs: dict) -> dict:
    code = obs.get("code", {})
    codings = code.get("coding", [])
    display = codings[0].get("display", "") if codings else ""
    loinc = next(
        (c.get("code", "") for c in codings if "loinc" in c.get("system", "").lower()),
        "",
    )

    value = None
    unit = ""
    if "valueQuantity" in obs:
        vq = obs["valueQuantity"]
        value = vq.get("value")
        unit = vq.get("unit", "")
    elif "valueString" in obs:
        value = obs["valueString"]
    elif "valueCodeableConcept" in obs:
        value = obs["valueCodeableConcept"].get("text", "")

    ref_range = ""
    ref_ranges = obs.get("referenceRange", [])
    if ref_ranges:
        ref_range = ref_ranges[0].get("text", "")
        if not ref_range:
            low = ref_ranges[0].get("low", {}).get("value", "")
            high = ref_ranges[0].get("high", {}).get("value", "")
            if low != "" or high != "":
                ref_range = f"{low}-{high}"

    eff_dt = obs.get("effectiveDateTime", "")
    if not eff_dt:
        period = obs.get("effectivePeriod", {})
        eff_dt = period.get("start", "")

    category = ""
    cats = obs.get("category", [])
    if cats:
        cat_codings = cats[0].get("coding", [])
        if cat_codings:
            category = cat_codings[0].get("code", "")

    interpretation = ""
    interps = obs.get("interpretation", [])
    if interps:
        interp_codings = interps[0].get("coding", [])
        if interp_codings:
            interpretation = interp_codings[0].get("code", "")

    notes = [note.get("text", "") for note in obs.get("note", [])]

    return {
        "text": code.get("text", display),
        "display": display,
        "loinc": loinc,
        "value": value,
        "unit": unit,
        "ref_range": ref_range,
        "date": eff_dt,
        "date_iso": parse_iso_date(eff_dt),
        "category": category,
        "interpretation": interpretation,
        "status": obs.get("status", ""),
        "notes": notes,
    }


def _parse_condition(cond: dict) -> dict:
    code = cond.get("code", {})
    codings = code.get("coding", [])
    icd_code = ""
    icd_system = ""
    for c in codings:
        sys_url = c.get("system", "")
        if "icd" in sys_url.lower():
            icd_code = c.get("code", "")
            icd_system = sys_url
            break

    clinical_status = ""
    cs = cond.get("clinicalStatus", {})
    cs_codings = cs.get("coding", [])
    if cs_codings:
        clinical_status = cs_codings[0].get("code", "")

    onset = cond.get("onsetDateTime", "")
    if not onset:
        onset = cond.get("onsetPeriod", {}).get("start", "")
    if not onset:
        onset = str(cond.get("onsetString", ""))

    return {
        "text": code.get("text", ""),
        "icd_code": icd_code,
        "icd_system": icd_system,
        "clinical_status": clinical_status,
        "onset": onset,
    }


def _parse_diagnostic_report(dr: dict) -> dict:
    code = dr.get("code", {})
    cat = dr.get("category", [{}])[0].get("coding", [{}])[0].get("display", "")
    eff = dr.get("effectiveDateTime", "")
    if not eff:
        period = dr.get("effectivePeriod", {})
        eff = period.get("start", "")

    results_refs = [r.get("reference", "") for r in dr.get("result", [])]
    presented = []
    decoded_text = ""
    for pf in dr.get("presentedForm", []):
        ct = pf.get("contentType", "")
        data_b64 = pf.get("data", "")
        text = decode_presented_form(data_b64, ct)
        presented.append(
            {
                "content_type": ct,
                "data_length": len(data_b64),
                "decoded_text": text,
            }
        )
        if text and not decoded_text:
            decoded_text = text

    return {
        "text": code.get("text", ""),
        "category": cat,
        "date": eff,
        "date_iso": parse_iso_date(eff),
        "status": dr.get("status", ""),
        "result_refs": results_refs,
        "presented_form": presented,
        "full_text": decoded_text,
    }


def _parse_medication_request(med: dict) -> dict:
    med_code = med.get("medicationCodeableConcept", {})
    return {
        "text": med_code.get("text", ""),
        "status": med.get("status", ""),
        "intent": med.get("intent", ""),
        "authored_on": med.get("authoredOn", ""),
        "authored_iso": parse_iso_date(med.get("authoredOn", "")),
        "dosage": [d.get("text", "") for d in med.get("dosageInstruction", [])],
    }


def _parse_encounter(enc: dict) -> dict:
    period = enc.get("period", {})
    enc_type = enc.get("type", [{}])[0].get("text", "")
    # Extract encounter identifier (e.g., V00003676858 for MEDITECH)
    identifiers = enc.get("identifier", [])
    enc_id = identifiers[0].get("value", "") if identifiers else ""
    return {
        "type": enc_type,
        "start": period.get("start", ""),
        "end": period.get("end", ""),
        "status": enc.get("status", ""),
        "start_iso": parse_iso_date(period.get("start", "")),
        "encounter_id": enc_id,
    }


def _parse_immunization(imm: dict) -> dict:
    vaccine = imm.get("vaccineCode", {})
    codings = vaccine.get("coding", [])
    cvx_code = next(
        (c.get("code", "") for c in codings if "cvx" in c.get("system", "").lower()),
        "",
    )
    return {
        "name": vaccine.get("text", codings[0].get("display", "") if codings else ""),
        "cvx_code": cvx_code,
        "date": imm.get("occurrenceDateTime", ""),
        "date_iso": parse_iso_date(imm.get("occurrenceDateTime", "")),
        "status": imm.get("status", ""),
        "lot": imm.get("lotNumber", ""),
    }
