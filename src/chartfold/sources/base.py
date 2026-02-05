"""Base classes and interfaces for EHR source parsers."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SourceConfig:
    """Configuration for an EHR source — section names, file patterns, etc."""

    name: str
    # Section title mappings (source-specific title -> canonical name)
    lab_sections: list[str] = field(default_factory=list)
    medication_sections: list[str] = field(default_factory=list)
    problem_sections: list[str] = field(default_factory=list)
    note_sections: list[str] = field(default_factory=list)
    # File discovery
    file_pattern: str = r".*\.xml$"
    # Document model
    cumulative_doc_ids: list[str] = field(default_factory=list)
    # Whether to use recovery mode for XML parsing
    recover_xml: bool = False


class DocumentDiscovery(Protocol):
    """Protocol for finding and enumerating clinical documents."""

    def discover(self, input_dir: str) -> list[str]:
        """Return sorted list of file paths to process."""
        ...


def discover_files(input_dir: str, pattern: str) -> list[str]:
    """Find files matching a regex pattern in a directory."""
    files = []
    for f in os.listdir(input_dir):
        if re.match(pattern, f, re.IGNORECASE):
            files.append(os.path.join(input_dir, f))
    return sorted(files)


# Pre-built source configs
EPIC_CONFIG = SourceConfig(
    name="Epic",
    lab_sections=["Results"],
    medication_sections=["Medications"],
    problem_sections=["Active Problems"],
    note_sections=[
        "Progress Notes",
        "H&P Notes",
        "Discharge Summaries",
        "OR Notes",
        "Anesthesia Record",
        "Miscellaneous Notes",
    ],
    file_pattern=r"DOC\d{4}\.XML",
    cumulative_doc_ids=["DOC0001", "DOC0002"],
    recover_xml=False,
)

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


def detect_source(input_dir: str) -> str | None:
    """Auto-detect the EHR source type from directory contents.

    Returns 'epic', 'meditech', 'athena', or None if unrecognized.
    """
    try:
        entries = os.listdir(input_dir)
    except OSError:
        return None

    # MEDITECH: has "US Core FHIR Resources.json" or a CCDA/ directory with UUID-named XML
    if "US Core FHIR Resources.json" in entries:
        return "meditech"
    if "CCDA" in entries and os.path.isdir(os.path.join(input_dir, "CCDA")):
        return "meditech"

    # athena: has Document_XML/ with AmbulatorySummary, or directly has AmbulatorySummary XML
    if "Document_XML" in entries and os.path.isdir(os.path.join(input_dir, "Document_XML")):
        for f in os.listdir(os.path.join(input_dir, "Document_XML")):
            if re.search(r"AmbulatorySummary.*\.xml$", f, re.IGNORECASE):
                return "athena"
    for f in entries:
        if re.search(r"AmbulatorySummary.*\.xml$", f, re.IGNORECASE):
            return "athena"

    # Epic: has DOC####.XML files directly
    for f in entries:
        if re.match(r"DOC\d{4}\.XML", f, re.IGNORECASE):
            return "epic"

    # Epic: IHE_XDM subdirectory structure (e.g., IHE_XDM/Alexander1/DOC0001.XML)
    if "IHE_XDM" in entries and os.path.isdir(os.path.join(input_dir, "IHE_XDM")):
        xdm_dir = os.path.join(input_dir, "IHE_XDM")
        for sub in os.listdir(xdm_dir):
            sub_path = os.path.join(xdm_dir, sub)
            if os.path.isdir(sub_path):
                for f in os.listdir(sub_path):
                    if re.match(r"DOC\d{4}\.XML", f, re.IGNORECASE):
                        return "epic"

    return None


def resolve_epic_dir(input_dir: str) -> str:
    """If input_dir is a top-level Epic export with IHE_XDM/, return the actual DOC dir."""
    entries = os.listdir(input_dir)
    # Already has DOC files directly
    for f in entries:
        if re.match(r"DOC\d{4}\.XML", f, re.IGNORECASE):
            return input_dir
    # Check IHE_XDM subdirectory
    xdm_dir = os.path.join(input_dir, "IHE_XDM")
    if os.path.isdir(xdm_dir):
        for sub in os.listdir(xdm_dir):
            sub_path = os.path.join(xdm_dir, sub)
            if os.path.isdir(sub_path):
                for f in os.listdir(sub_path):
                    if re.match(r"DOC\d{4}\.XML", f, re.IGNORECASE):
                        return sub_path
    return input_dir


MEDITECH_CONFIG = SourceConfig(
    name="MEDITECH",
    lab_sections=[
        "Relevant Diagnostic Tests and/or Laboratory Data",
        "Labs",
    ],
    medication_sections=[
        "Medications",
        "Patient Medication List",
        "Hospital Discharge Medications",
    ],
    problem_sections=["Problem List", "Problems"],
    note_sections=[
        "History & Physical Note",
        "Progress Note",
        "Discharge Summary Note",
        "Consultation Note",
        "Hospital Discharge Instructions",
        "Plan of Care",
        "Plan of Treatment",
        "Chief Complaint and Reason for Visit",
        "Assessments",
        "Reason for Referral",
    ],
    file_pattern=r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.xml",
    cumulative_doc_ids=[],  # MEDITECH: all docs are per-encounter with cumulative snapshots
    recover_xml=True,
)
