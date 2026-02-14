"""Shared utility functions for date parsing, deduplication, etc."""

from __future__ import annotations

import os
import re
from typing import Any, Callable

_MONTHS = {
    "january": "01",
    "february": "02",
    "march": "03",
    "april": "04",
    "may": "05",
    "june": "06",
    "july": "07",
    "august": "08",
    "september": "09",
    "october": "10",
    "november": "11",
    "december": "12",
}


def normalize_date_to_iso(dt_str: str) -> str:
    """Convert any common clinical date format to ISO 8601 YYYY-MM-DD.

    Supported formats:
    - YYYYMMDD (CDA effectiveTime): "20211123"
    - YYYYMMDDHHMMSS-ZZZZ (CDA with time+tz): "20220201073445-0600"
    - MM/DD/YYYY (Epic narrative): "01/15/2026"
    - Month DDth, YYYY (MEDITECH narrative): "November 23rd, 2021 2:37pm"
    - YYYY-MM-DD (already ISO): "2025-06-30"
    - YYYY-MM-DDTHH:MM:SS+ZZ:ZZ (FHIR ISO): "2025-06-30T13:25:00+00:00"

    Returns empty string for empty/unparseable input.
    """
    if not dt_str or not dt_str.strip():
        return ""
    s = dt_str.strip()

    # Already ISO: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS...
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # MM/DD/YYYY
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"

    # YYYYMMDD with optional time and timezone
    m = re.match(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # Narrative: "November 23rd, 2021" or "November 23, 2021 2:37pm"
    result = parse_narrative_date(s)
    if result:
        return result

    return ""


def parse_iso_date(dt_str: str) -> str:
    """Extract YYYY-MM-DD from ISO datetime string."""
    if not dt_str:
        return ""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", dt_str)
    return m.group(1) if m else dt_str[:10]


def parse_narrative_date(text: str) -> str:
    """Parse dates like 'November 23rd, 2021 2:37pm' -> '2021-11-23'.

    Handles ordinal suffixes (1st, 2nd, 3rd, 4th, etc.).
    """
    # "November 23rd, 2021" or "November 23, 2021"
    m = re.match(
        r"(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})",
        text.strip(),
        re.IGNORECASE,
    )
    if m:
        month_str = m.group(1).lower()
        day = int(m.group(2))
        year = m.group(3)
        month = _MONTHS.get(month_str)
        if month:
            return f"{year}-{month}-{day:02d}"
    return ""


def try_parse_numeric(value: str) -> float | None:
    """Try to parse a lab value string as a float.

    Handles leading operators like '<', '>', '<=', '>='.
    Returns None if not parseable.
    """
    if not value:
        return None
    cleaned = re.sub(r"^[<>=]+\s*", "", value.strip())
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def derive_source_name(input_dir: str, source_type: str) -> str:
    """Derive a source name from the input directory path and source type.

    Examples:
        "/path/to/anderson/" + "epic" -> "epic_anderson"
        "/path/to/siteman/CCDA/" + "meditech" -> "meditech_siteman"
        "~/exports/sihf_jan26/" + "athena" -> "athena_sihf_jan26"

    The directory name is normalized to lowercase with spaces/special chars
    replaced by underscores.
    """
    # Get the deepest non-empty directory name
    path = os.path.normpath(input_dir)
    dir_name = os.path.basename(path)

    # If the dirname is a common subdirectory, go up one level
    common_subdirs = {"ccda", "document_xml", "ihe_xdm", "alexander1"}
    if dir_name.lower() in common_subdirs:
        dir_name = os.path.basename(os.path.dirname(path))

    # Normalize: lowercase, replace non-alphanumeric with underscore, collapse
    normalized = re.sub(r"[^a-z0-9]+", "_", dir_name.lower())
    normalized = normalized.strip("_")

    if not normalized:
        normalized = "unknown"

    return f"{source_type}_{normalized}"


def deduplicate_by_key(
    items: list[dict[str, Any]],
    key_func: Callable[[dict[str, Any]], tuple[Any, ...]],
    sort_key: Callable[[dict[str, Any]], Any] | None = None,
    reverse: bool = False,
) -> list[dict[str, Any]]:
    """Deduplicate a list of dicts using a key function.

    Args:
        items: List of dicts to deduplicate.
        key_func: Function that returns a hashable key for each item.
        sort_key: Optional sort key function for the result.
        reverse: Sort in reverse order.
    """
    seen = set()
    result = []
    for item in items:
        k = key_func(item)
        if k in seen:
            continue
        seen.add(k)
        result.append(item)
    if sort_key:
        result.sort(key=sort_key, reverse=reverse)
    return result


IMAGE_MIME_TYPES: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tif": "image/tiff",
    "tiff": "image/tiff",
}


def is_image_asset(asset_type: str) -> bool:
    """Return True if asset_type is a displayable image format."""
    return asset_type.lower() in IMAGE_MIME_TYPES


_CATEGORY_MAP = {
    "admission": "Admissions",
    "consent": "Consents",
    "discharge": "Discharge",
    "surgical": "Surgical Services",
    "laborator": "Laboratory",
    "patient care": "Patient Care Notes",
    "medication": "Medications",
    "order": "Orders",
    "radiol": "Radiology",
    "imaging": "Imaging",
}


def categorize_asset_title(title: str) -> str:
    """Derive a display-friendly category from asset title or folder name.

    MEDITECH folders like '015_Laboratory' or '010_Surgical_Services'
    are mapped to clean labels. Unknown titles get 'General'.
    """
    if not title:
        return "General"
    t = title.lower().replace("_", " ")
    for keyword, label in _CATEGORY_MAP.items():
        if keyword in t:
            return label
    return "General"
