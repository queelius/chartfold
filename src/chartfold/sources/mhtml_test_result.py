"""Parse Epic MyChart MHTML files (Test Result Detail pages).

Handles genomic test results like Tempus XF panels. The HTML structure
uses component cards for lab values (TMB, MSI) and an accordion list
for individual genetic variants.

Key HTML patterns:
- OrderMetadataLabelValue: provider, collection/result date, specimen, status
- ComponentCardHeader + NonNumericResultComponent: TMB, MSI, interpretation
- _AccordionItem > textGroup > span.title: "GENE - p.X123Y - c.456A>G Type"
- SingleVariant > LabelledItem > span.label + sibling: variant details
- labLine: resulting laboratory name
"""

from __future__ import annotations

import email
import email.policy
import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import html as lxml_html

from chartfold.sources.mhtml_visit import _parse_display_date


@dataclass
class ParsedVariant:
    """A single genetic variant extracted from the HTML."""

    gene: str = ""
    variant_type: str = ""  # Missense variant, Frameshift, etc.
    assessment: str = ""  # Detected, Not Detected
    classification: str = ""
    variant_origin: str = ""
    vaf: str = ""  # Raw "53.2%"
    dna_change: str = ""
    protein_change: str = ""
    transcript: str = ""
    analysis_method: str = ""


@dataclass
class ParsedTestResult:
    """Parsed output from a MyChart test-result MHTML page."""

    test_name: str = ""  # "TEMPUS XF"
    panel: str = ""  # "523 gene liquid biopsy"
    collection_date: str = ""  # ISO YYYY-MM-DD
    result_date: str = ""  # ISO YYYY-MM-DD
    provider: str = ""
    specimen: str = ""
    status: str = ""  # Final, Preliminary, etc.
    lab_name: str = ""  # TEMPUS LAB
    reason: str = ""
    diseases_assessed: str = ""
    overall_interpretation: str = ""
    tmb_value: str = ""  # "2.2"
    tmb_unit: str = ""  # "m/MB"
    msi_status: str = ""  # "MSI-High not detected"
    treatment_implications: str = ""
    low_coverage_regions: str = ""
    portal_url: str = ""
    variants: list[ParsedVariant] = field(default_factory=list)


def parse_test_result_mhtml(file_path: str) -> ParsedTestResult:
    """Parse an Epic MyChart Test Result Detail MHTML file.

    Args:
        file_path: Path to the .mhtml file.

    Returns:
        ParsedTestResult with extracted metadata, components, and variants.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"MHTML file not found: {file_path}")

    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=email.policy.default)

    html_body = ""
    for part in msg.walk():
        if part.get_content_type() == "text/html" and not html_body:
            payload = part.get_payload(decode=True)
            if payload:
                html_body = payload.decode("utf-8", errors="replace")

    result = ParsedTestResult()
    if html_body:
        _extract_from_html(html_body, result)
    return result


def _extract_from_html(html_body: str, result: ParsedTestResult) -> None:
    """Extract test result data from the HTML body."""
    try:
        doc = lxml_html.fromstring(html_body)
    except Exception:
        return

    _extract_test_name(doc, result)
    _extract_metadata(doc, result)
    _extract_lab_name(doc, result)
    _extract_components(doc, result)
    _extract_variants(doc, result)


def _extract_test_name(doc, result: ParsedTestResult) -> None:
    """Extract test name from h1 (e.g., 'TEMPUS XF')."""
    for h1 in doc.iter("h1"):
        cls = h1.get("class", "")
        if "_PageHeading" in cls:
            text = h1.text_content().strip()
            if text:
                result.test_name = text
                break


def _extract_metadata(doc, result: ParsedTestResult) -> None:
    """Extract metadata from OrderMetadataLabelValue divs."""
    for div in doc.xpath('.//div[contains(@class, "OrderMetadataLabelValue")]'):
        spans = div.xpath(".//span")
        if len(spans) < 2:
            continue
        label = spans[0].text_content().strip().rstrip(":")
        value = spans[1].text_content().strip()

        label_lower = label.lower()
        if "authorizing provider" in label_lower or "ordering provider" in label_lower:
            result.provider = value
        elif "collection date" in label_lower:
            result.collection_date = _parse_display_date(value)
        elif "result date" in label_lower:
            result.result_date = _parse_display_date(value)
        elif "specimen" in label_lower:
            result.specimen = value
        elif "result status" in label_lower:
            result.status = value


def _extract_lab_name(doc, result: ParsedTestResult) -> None:
    """Extract resulting lab name from labLine divs."""
    lab_lines = doc.xpath('.//div[contains(@class, "labLine")]')
    # Pattern: "Resulting lab:" label followed by emphasis line with lab name
    for i, div in enumerate(lab_lines):
        text = div.text_content().strip()
        if "resulting lab" in text.lower():
            # Next sibling with emphasis class is the lab name
            if i + 1 < len(lab_lines):
                cls = lab_lines[i + 1].get("class", "")
                if "emphasis" in cls:
                    result.lab_name = lab_lines[i + 1].text_content().strip()
            break


def _extract_components(doc, result: ParsedTestResult) -> None:
    """Extract component values (TMB, MSI, interpretation, etc.)."""
    # Build a map of component name -> value by finding ComponentCardHeader + value pairs
    components: dict[str, str] = {}
    for h3 in doc.xpath('.//h3[contains(@class, "componentHeading")]'):
        name = h3.text_content().strip()
        # Navigate: h3 -> parent (titleSection) -> grandparent (ComponentCardHeader)
        #                                       -> great-grandparent has sibling NonNumericResultComponent
        gp = _ancestor(h3, 2)
        ggp = _ancestor(h3, 3)
        if ggp is not None:
            # Find NonNumericResultComponent sibling
            for child in ggp:
                if "NonNumericResultComponent" in child.get("class", ""):
                    value_spans = child.xpath('.//span[contains(@class, "value") and not(contains(@class, "valueLabel"))]')
                    if value_spans:
                        components[name] = value_spans[0].text_content().strip()
                    break

    # Map component names to result fields
    for name, value in components.items():
        name_lower = name.lower()
        if "reason" in name_lower:
            result.reason = value
        elif "diseases assessed" in name_lower:
            result.diseases_assessed = value
        elif "overall interpretation" in name_lower:
            result.overall_interpretation = value
        elif "tumor mutational burden" in name_lower:
            result.tmb_value = value
            # Unit is in the ComponentCardHeader
            gp_candidates = doc.xpath(
                './/h3[contains(@class, "componentHeading")]'
            )
            for h3 in gp_candidates:
                if "tumor mutational burden" in h3.text_content().strip().lower():
                    header_parent = _ancestor(h3, 2)
                    if header_parent is not None:
                        header_text = header_parent.text_content()
                        # Unit appears after the heading text, e.g., "...View trendsm/MB"
                        match = re.search(r"View trends(\S+)", header_text)
                        if match:
                            result.tmb_unit = match.group(1).strip()
                    break
        elif "microsatellite instability" in name_lower:
            result.msi_status = value
        elif "treatment implications" in name_lower:
            result.treatment_implications = value
        elif "low coverage" in name_lower:
            result.low_coverage_regions = value
        elif "tempus portal" in name_lower:
            result.portal_url = value
        elif "description of ranges" in name_lower:
            result.panel = value


def _extract_variants(doc, result: ParsedTestResult) -> None:
    """Extract genetic variants from accordion items."""
    for item in doc.xpath('.//div[contains(@class, "_AccordionItem")]'):
        variant = ParsedVariant()

        # 1. Parse gene name, protein/dna change, type from accordion header
        # Format: "GENE - p.X123Y - c.456A>G Type\nAssessment: Status"
        title_span = item.xpath('.//span[contains(@class, "title")]')
        if title_span:
            _parse_variant_header(title_span[0].text_content().strip(), variant)

        assessment_span = item.xpath('.//span[contains(@class, "subtleStyle")]')
        if assessment_span:
            text = assessment_span[0].text_content().strip()
            match = re.match(r"Assessment:\s*(.+)", text)
            if match:
                variant.assessment = match.group(1).strip()

        # 2. Parse labelled items from variant details
        for label_div in item.xpath('.//div[contains(@class, "LabelledItem")]'):
            spans = label_div.xpath(".//span")
            if len(spans) < 2:
                continue
            label = spans[0].text_content().strip().rstrip(":")
            value = spans[1].text_content().strip()

            label_lower = label.lower()
            if "classification" in label_lower:
                variant.classification = value
            elif label_lower == "type":
                # Don't overwrite variant_type from header if this is "Simple"
                if not variant.variant_type:
                    variant.variant_type = value
            elif "variant source" in label_lower:
                variant.variant_origin = value
            elif "variant allele fraction" in label_lower:
                variant.vaf = value
            elif "dna change" in label_lower:
                # Prefer header-parsed dna_change, but use this as fallback
                if not variant.dna_change:
                    variant.dna_change = value
            elif "transcript" in label_lower:
                variant.transcript = value.split()[0] if value else ""  # "NM_003786 (RefSeq-T)" -> "NM_003786"
            elif "amino acid" in label_lower:
                if not variant.protein_change:
                    variant.protein_change = value
            elif "analysis method" in label_lower:
                variant.analysis_method = value

        if variant.gene:
            result.variants.append(variant)


def _parse_variant_header(header: str, variant: ParsedVariant) -> None:
    """Parse variant header like 'ABCC3 - p.A457T - c.1369G>A Missense variant'.

    Format: GENE - protein_change - dna_change variant_type
    """
    # Split on ' - ' to get parts
    parts = [p.strip() for p in header.split(" - ")]
    if not parts:
        return

    variant.gene = parts[0]

    if len(parts) >= 2:
        variant.protein_change = parts[1]

    if len(parts) >= 3:
        # Last part: "c.1369G>A Missense variant"
        last = parts[2]
        # Split at first space after the dna_change notation
        match = re.match(r"(c\.\S+)\s+(.*)", last)
        if match:
            variant.dna_change = match.group(1)
            variant.variant_type = match.group(2)
        else:
            variant.dna_change = last


def _ancestor(elem, levels: int):
    """Walk up the tree N levels. Returns None if tree is too shallow."""
    current = elem
    for _ in range(levels):
        current = current.getparent()
        if current is None:
            return None
    return current
