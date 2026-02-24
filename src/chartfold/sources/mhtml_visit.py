"""Parse Epic MyChart MHTML files (Past Visit Details pages).

MHTML (RFC 2557) is a multipart MIME archive saved by Chromium browsers.
The first part is quoted-printable HTML; subsequent parts are base64-encoded
images (PNGs) referenced via MyChart/Image/Load?fileName=<UUID> URLs.

This parser extracts:
- Visit metadata (date, type, provider, facility)
- Full clinical note text (from data-paragraph divs)
- Clinical images with UUID keys and decoded bytes
- Study references (modality + date) extracted from note headings
"""

from __future__ import annotations

import email
import email.policy
import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import html as lxml_html


@dataclass
class StudyRef:
    """A reference to an imaging study found in the clinical note text."""

    study_name: str  # e.g., "MRI/CT", "PET/FDG", "MRI Abdomen Pelvis"
    study_date: str  # ISO YYYY-MM-DD
    raw_header: str  # Original text: "MRI/CT 1/15/2026"
    paragraph_idx: int  # Position in note paragraphs
    image_uuids: list[str] = field(default_factory=list)


@dataclass
class ParsedVisit:
    """Parsed output from an MHTML MyChart visit page."""

    visit_date: str = ""  # ISO YYYY-MM-DD
    visit_type: str = ""  # "Office Visit", etc.
    provider: str = ""
    facility: str = ""
    note_text: str = ""  # Full clinical note as plain text
    note_title: str = ""  # e.g., "Oncology Return/Follow Up Visit"
    study_refs: list[StudyRef] = field(default_factory=list)
    images: dict[str, bytes] = field(default_factory=dict)  # UUID -> raw bytes


# Pattern: modality name followed by M/D/YYYY or M/DD/YYYY date
_STUDY_HEADER_RE = re.compile(
    r"^((?:MRI|CT|PET|US|XR|MRA|CTA|PET/CT|PET/FDG|MRI/CT|Ultrasound|X-ray)"
    r"(?:\s+\w[\w\s/]*?)?)\s+"
    r"(\d{1,2}/\d{1,2}/\d{4})$"
)

# Broader pattern for study-like headers: any text ending with a date
_STUDY_HEADER_BROAD_RE = re.compile(
    r"^(.+?)\s+(\d{1,2}/\d{1,2}/\d{4})$"
)


def _normalize_date(date_str: str) -> str:
    """Convert M/D/YYYY to YYYY-MM-DD."""
    match = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", date_str)
    if match:
        month, day, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return date_str


def _extract_uuid_from_url(url: str) -> str:
    """Extract the UUID from a MyChart Image/Load URL."""
    match = re.search(r"fileName=([a-f0-9-]{36})", url)
    return match.group(1) if match else ""


def parse_mhtml(file_path: str) -> ParsedVisit:
    """Parse an Epic MyChart Past Visit Details MHTML file.

    Args:
        file_path: Path to the .mhtml file.

    Returns:
        ParsedVisit with extracted metadata, note text, and images.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"MHTML file not found: {file_path}")

    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=email.policy.default)

    result = ParsedVisit()
    html_body = ""

    # Walk MIME parts: first is HTML, rest are images/resources
    for part in msg.walk():
        content_type = part.get_content_type()

        if content_type == "text/html" and not html_body:
            payload = part.get_payload(decode=True)
            if payload:
                html_body = payload.decode("utf-8", errors="replace")

        elif content_type.startswith("image/"):
            content_location = part.get("Content-Location", "")
            uuid = _extract_uuid_from_url(content_location)
            if uuid:
                image_data = part.get_payload(decode=True)
                if image_data:
                    result.images[uuid] = image_data

    if html_body:
        _extract_from_html(html_body, result)

    return result


def _extract_from_html(html_body: str, result: ParsedVisit) -> None:
    """Extract visit metadata and note content from the HTML body."""
    try:
        doc = lxml_html.fromstring(html_body)
    except Exception:
        return

    # 1. Visit header: <h1 class="_PageHeading ...">Office Visit - Feb 05, 2026</h1>
    for h1 in doc.iter("h1"):
        text = (h1.text_content() or "").strip()
        # Pattern: "Office Visit - Feb 05, 2026"
        match = re.match(r"(.+?)\s*-\s*(\w+ \d{1,2},\s*\d{4})", text)
        if match:
            result.visit_type = match.group(1).strip()
            # Parse "Feb 05, 2026" -> "2026-02-05"
            result.visit_date = _parse_display_date(match.group(2).strip())
            break

    # 2. Provider/facility: <div class="subtitle">with Benjamin Tan, MD at WashU...</div>
    # Use XPath: divs whose class contains "subtitle"
    subtitle_divs = doc.xpath('.//div[contains(@class, "subtitle")]')
    if not subtitle_divs:
        subtitle_divs = list(doc.iter("div"))
    for div in subtitle_divs:
        text = (div.text_content() or "").strip()
        match = re.match(r"with\s+(.+?)\s+at\s+(.+)", text)
        if match:
            result.provider = match.group(1).strip()
            result.facility = match.group(2).strip()
            break

    # 3. Clinical note from data-paragraph divs
    paragraphs: list[str] = []
    image_positions: list[tuple[int, str]] = []  # (paragraph_idx, uuid)

    for div in doc.xpath('.//div[@data-paragraph]'):
        para_idx = int(div.get("data-paragraph", "0"))
        text = (div.text_content() or "").strip()

        # Replace &nbsp; artifacts
        text = text.replace("\xa0", " ").strip()
        paragraphs.append(text)

        # Check for images in this paragraph
        for img in div.iter("img"):
            src = img.get("src", "")
            uuid = _extract_uuid_from_url(src)
            if uuid:
                image_positions.append((para_idx, uuid))

    result.note_text = "\n".join(paragraphs)

    # Extract note title from first non-empty paragraph
    for p in paragraphs:
        if p and p != " ":
            result.note_title = p
            break

    # 4. Identify study references from paragraphs
    current_study: StudyRef | None = None
    for i, text in enumerate(paragraphs):
        if not text or text == " ":
            continue

        # Check if this looks like a study header
        study_match = _STUDY_HEADER_RE.match(text)
        if not study_match:
            study_match = _STUDY_HEADER_BROAD_RE.match(text)
            # Only accept broad match if it starts with a plausible modality word
            if study_match and not _looks_like_study_name(study_match.group(1)):
                study_match = None

        if study_match:
            study_name = study_match.group(1).strip()
            date_str = _normalize_date(study_match.group(2))
            current_study = StudyRef(
                study_name=study_name,
                study_date=date_str,
                raw_header=text,
                paragraph_idx=i,
            )
            result.study_refs.append(current_study)

    # Associate images with their nearest preceding study
    for para_idx, uuid in image_positions:
        # Find the study that precedes this image
        best_study = None
        for study in result.study_refs:
            if study.paragraph_idx <= para_idx:
                best_study = study
        if best_study:
            best_study.image_uuids.append(uuid)


def _looks_like_study_name(text: str) -> bool:
    """Check if text looks like an imaging study name."""
    modality_words = {
        "mri", "ct", "pet", "us", "xr", "mra", "cta", "ultrasound",
        "x-ray", "xray", "mammogram", "dexa", "bone", "scan",
        "fluoroscopy", "angiography", "echocardiogram", "echo",
        "colonoscopy", "endoscopy", "eus", "ercp",
    }
    first_word = text.split()[0].lower().rstrip("/") if text else ""
    return first_word in modality_words or "/" in text.split()[0]


def _parse_display_date(date_str: str) -> str:
    """Parse 'Feb 05, 2026' or 'January 15, 2026' to ISO YYYY-MM-DD."""
    months = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04",
        "may": "05", "jun": "06", "jul": "07", "aug": "08",
        "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    }
    match = re.match(r"(\w+)\s+(\d{1,2}),?\s*(\d{4})", date_str.strip())
    if match:
        month_name, day, year = match.groups()
        month_num = months.get(month_name[:3].lower(), "01")
        return f"{year}-{month_num}-{int(day):02d}"
    return ""
