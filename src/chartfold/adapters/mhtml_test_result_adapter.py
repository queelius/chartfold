"""Convert parsed MyChart test-result MHTML data into UnifiedRecords.

Takes the output of sources.mhtml_test_result.parse_test_result_mhtml() and
produces UnifiedRecords ready for load_source(replace=False).

Genomic panel results map to:
- TMB, MSI, interpretation → LabResult records
- Each variant → GeneticVariant record
"""

from __future__ import annotations

import re

from chartfold.models import (
    GeneticVariant,
    LabResult,
    UnifiedRecords,
)
from chartfold.sources.mhtml_test_result import ParsedTestResult


def _parse_vaf(raw: str) -> float | None:
    """Parse VAF string like '53.2%' to float 53.2."""
    match = re.match(r"([\d.]+)\s*%?", raw.strip())
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def _parse_numeric(raw: str) -> float | None:
    """Parse a numeric string, returning None if not parseable."""
    try:
        return float(raw.strip())
    except (ValueError, AttributeError):
        return None


def _parser_counts(data: ParsedTestResult) -> dict[str, int]:
    """Count records in parser output before adapter transformation."""
    lab_count = 0
    if data.tmb_value:
        lab_count += 1
    if data.msi_status:
        lab_count += 1
    if data.overall_interpretation:
        lab_count += 1
    return {
        "lab_results": lab_count,
        "genetic_variants": len(data.variants),
    }


def test_result_to_unified(
    data: ParsedTestResult,
    source: str = "mychart_tempus",
) -> UnifiedRecords:
    """Convert parsed test-result MHTML data to UnifiedRecords.

    Args:
        data: Parsed test result from parse_test_result_mhtml().
        source: Source identifier for provenance.

    Returns:
        UnifiedRecords ready for load_source(replace=False).
    """
    records = UnifiedRecords(source=source)

    panel_name = f"{data.test_name} - {data.panel}" if data.panel else data.test_name

    # 1. TMB as lab result
    if data.tmb_value:
        records.lab_results.append(
            LabResult(
                source=source,
                test_name="Tumor Mutational Burden",
                value=data.tmb_value,
                value_numeric=_parse_numeric(data.tmb_value),
                unit=data.tmb_unit,
                panel_name=panel_name,
                result_date=data.result_date,
                status=data.status,
            )
        )

    # 2. MSI as lab result
    if data.msi_status:
        records.lab_results.append(
            LabResult(
                source=source,
                test_name="Microsatellite Instability",
                value=data.msi_status,
                panel_name=panel_name,
                result_date=data.result_date,
                status=data.status,
            )
        )

    # 3. Overall interpretation as lab result
    if data.overall_interpretation:
        records.lab_results.append(
            LabResult(
                source=source,
                test_name="Genomic Panel Interpretation",
                value=data.overall_interpretation,
                panel_name=panel_name,
                result_date=data.result_date,
                status=data.status,
            )
        )

    # 4. Genetic variants
    for v in data.variants:
        records.genetic_variants.append(
            GeneticVariant(
                source=source,
                gene=v.gene,
                variant_type=v.variant_type,
                assessment=v.assessment,
                classification=v.classification,
                variant_origin=v.variant_origin,
                vaf=_parse_vaf(v.vaf),
                dna_change=v.dna_change,
                protein_change=v.protein_change,
                transcript=v.transcript,
                analysis_method=v.analysis_method,
                test_name=data.panel or data.test_name,
                specimen=data.specimen,
                collection_date=data.collection_date,
                result_date=data.result_date,
                lab_name=data.lab_name,
                provider=data.provider,
            )
        )

    return records
