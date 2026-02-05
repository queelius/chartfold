"""Cross-source pathology extraction and procedure linkage.

Extracts structured pathology information (diagnosis, gross, microscopic,
staging, margins) from clinical text. Links pathology reports to procedures
by date proximity and specimen/procedure name similarity.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def parse_pathology_sections(text: str) -> dict:
    """Parse a pathology report text into structured sections.

    Returns dict with keys: diagnosis, gross_description, microscopic_description,
    staging, margins, lymph_nodes, specimen.
    """
    result = {
        "diagnosis": "",
        "gross_description": "",
        "microscopic_description": "",
        "staging": "",
        "margins": "",
        "lymph_nodes": "",
        "specimen": "",
    }
    if not text:
        return result

    # Diagnosis
    diag = _extract_section(
        text,
        [
            r"(?:Final\s+)?Diagnosis[:\s]*",
            r"DIAGNOSIS[:\s]*",
            r"Pathologic\s+Diagnosis[:\s]*",
        ],
        [
            r"Gross\s+Description",
            r"GROSS\s+DESCRIPTION",
            r"Microscopic",
            r"Comment[:\s]",
            r"Clinical\s+Information",
            r"By\s+this\s+signature",
            r"Report\s+Electronically",
            r"\b[a-z]{2,4}/\b",  # initials like "gp/" or "laha/"
        ],
    )
    result["diagnosis"] = diag

    # Gross Description
    gross = _extract_section(
        text,
        [
            r"Gross\s+Description[:\s]*",
            r"GROSS\s+DESCRIPTION[:\s]*",
        ],
        [
            r"Microscopic\s+Description",
            r"MICROSCOPIC",
            r"Comment[:\s]",
            r"By\s+this\s+signature",
            r"PA\(s\):",
            r"\b[a-z]{2,4}/\b",
        ],
    )
    result["gross_description"] = gross

    # Microscopic Description
    micro = _extract_section(
        text,
        [
            r"Microscopic\s+Description[:\s]*",
            r"MICROSCOPIC[:\s]*",
        ],
        [
            r"Comment[:\s]",
            r"By\s+this\s+signature",
            r"Addendum",
            r"(?:Final\s+)?Diagnosis[:\s]",
        ],
    )
    result["microscopic_description"] = micro

    # Staging
    staging_patterns = [
        r"(pT\d[a-z]?N\d[a-z]?(?:M\d)?)",
        r"Stage\s+(I{1,3}V?[A-C]?\b)",
        r"AJCC\s+Stage[:\s]*(.*?)(?:\.|$)",
    ]
    for pat in staging_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            result["staging"] = m.group(1).strip()
            break

    # Margins
    margin_patterns = [
        r"(?:surgical\s+)?margins?[:\s]*(.*?)(?:\.|;|$)",
        r"(?:Positive|Negative|Close)\s+(?:deep\s+)?(?:radial\s+)?margins?",
        r"margins?\s+(?:are\s+)?(?:positive|negative|close|free|involved)",
    ]
    for pat in margin_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            result["margins"] = m.group(0).strip()
            break

    # Lymph nodes
    ln_patterns = [
        r"(\d+)\s*/\s*(\d+)\s+(?:lymph\s+)?(?:node|LN)s?\s+(?:positive|involved|with\s+(?:metasta|tumor))",
        r"(?:lymph\s+)?(?:node|LN)s?[:\s]*(\d+)\s*/\s*(\d+)\s+positive",
        r"(?:positive|negative)\s+(?:lymph\s+)?(?:node|LN)s?",
    ]
    for pat in ln_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            result["lymph_nodes"] = m.group(0).strip()
            break

    # Specimen
    spec_patterns = [
        r"Specimen[:\s]*\"?(.*?)\"?(?:\.|$)",
        r"Received[:\s]*(.*?)(?:\.|$)",
        r"Labeled[:\s]*\"(.*?)\"",
    ]
    for pat in spec_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            result["specimen"] = m.group(1).strip()
            break

    return result


def link_pathology_to_procedures(
    pathology_reports: list[dict],
    procedures: list[dict],
    max_days: int = 14,
) -> list[tuple[int, int]]:
    """Match pathology reports to procedures by date proximity and name similarity.

    Args:
        pathology_reports: List of dicts with 'id', 'report_date', 'specimen', 'diagnosis'
        procedures: List of dicts with 'id', 'procedure_date', 'name'
        max_days: Maximum days between procedure and pathology report

    Returns:
        List of (pathology_id, procedure_id) tuples.
    """
    links = []
    for path in pathology_reports:
        path_date = path.get("report_date", "")
        if not path_date:
            continue

        best_proc = None
        best_score = 0.0

        for proc in procedures:
            proc_date = proc.get("procedure_date", "")
            if not proc_date:
                continue

            # Check date proximity
            days = _days_between(path_date, proc_date)
            if days is None or days > max_days:
                continue

            # Score: closer dates score higher, name similarity adds bonus
            date_score = 1.0 - (days / max_days)
            name_score = _name_similarity(
                path.get("specimen", "") + " " + path.get("diagnosis", ""),
                proc.get("name", ""),
            )
            total_score = date_score * 0.6 + name_score * 0.4

            if total_score > best_score:
                best_score = total_score
                best_proc = proc

        if best_proc is not None and best_score > 0.2:
            links.append((path["id"], best_proc["id"]))

    return links


def _extract_section(text: str, start_patterns: list[str], end_patterns: list[str]) -> str:
    """Extract text between start and end patterns."""
    for start_pat in start_patterns:
        m = re.search(start_pat, text, re.IGNORECASE)
        if m:
            rest = text[m.end() :]
            # Find the nearest end pattern
            earliest_end = len(rest)
            for end_pat in end_patterns:
                em = re.search(end_pat, rest, re.IGNORECASE)
                if em and em.start() < earliest_end:
                    earliest_end = em.start()
            return rest[:earliest_end].strip()
    return ""


def _days_between(date1: str, date2: str) -> int | None:
    """Calculate absolute days between two ISO dates."""
    try:
        from datetime import date

        d1 = date.fromisoformat(date1)
        d2 = date.fromisoformat(date2)
        return abs((d1 - d2).days)
    except (ValueError, TypeError):
        return None


def _name_similarity(text1: str, text2: str) -> float:
    """Calculate name similarity using SequenceMatcher."""
    if not text1 or not text2:
        return 0.0
    return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()
