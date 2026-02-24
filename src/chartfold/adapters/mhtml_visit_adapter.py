"""Convert parsed MyChart MHTML data into UnifiedRecords.

Takes the output of sources.mychart_mhtml.parse_mhtml() and produces
UnifiedRecords ready for load_source(replace=False) — granular import
that adds to the existing database without removing anything.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from chartfold.models import (
    ClinicalNote,
    EncounterRecord,
    ImagingReport,
    SourceAsset,
    UnifiedRecords,
)
from chartfold.sources.mhtml_visit import ParsedVisit


# Map study name prefixes to imaging modalities
_MODALITY_MAP: dict[str, str] = {
    "mri": "MRI",
    "ct": "CT",
    "pet": "PET",
    "pet/fdg": "PET",
    "pet/ct": "PET",
    "mri/ct": "MRI",
    "us": "US",
    "ultrasound": "US",
    "xr": "XR",
    "x-ray": "XR",
    "mra": "MRA",
    "cta": "CTA",
    "mammogram": "MG",
    "dexa": "DEXA",
}


def _infer_modality(study_name: str) -> str:
    """Infer imaging modality from study name."""
    lower = study_name.lower()
    # Check multi-word prefixes first
    for prefix, modality in sorted(_MODALITY_MAP.items(), key=lambda x: -len(x[0])):
        if lower.startswith(prefix):
            return modality
    return ""


def _parser_counts(data: ParsedVisit) -> dict[str, int]:
    """Count records in parser output before adapter transformation."""
    return {
        "encounters": 1 if data.visit_date else 0,
        "clinical_notes": 1 if data.note_text else 0,
        "imaging_reports": len(data.study_refs),
        "source_assets": len(data.images),
    }


def mychart_to_unified(
    data: ParsedVisit,
    source: str = "mychart",
    image_dir: str = "",
) -> UnifiedRecords:
    """Convert parsed MyChart MHTML data to UnifiedRecords.

    Args:
        data: Parsed visit data from parse_mhtml().
        source: Source identifier for provenance.
        image_dir: Directory where extracted images have been saved.
                   If empty, source_assets will have placeholder paths.

    Returns:
        UnifiedRecords ready for load_source(replace=False).
    """
    records = UnifiedRecords(source=source)

    # 1. Encounter
    if data.visit_date:
        records.encounters.append(
            EncounterRecord(
                source=source,
                encounter_date=data.visit_date,
                encounter_type=data.visit_type or "Office Visit",
                facility=data.facility,
                provider=data.provider,
            )
        )

    # 2. Clinical note
    if data.note_text:
        records.clinical_notes.append(
            ClinicalNote(
                source=source,
                note_type="visit_note",
                author=data.provider,
                note_date=data.visit_date,
                content=data.note_text,
                content_format="text",
            )
        )

    # 3. Imaging reports from study references
    for study in data.study_refs:
        modality = _infer_modality(study.study_name)
        records.imaging_reports.append(
            ImagingReport(
                source=source,
                study_name=study.study_name,
                modality=modality,
                study_date=study.study_date,
            )
        )

    # 4. Source assets for images — deduplicate by content hash
    image_dir_path = Path(image_dir) if image_dir else None
    seen_hashes: set[str] = set()

    for uuid, image_bytes in data.images.items():
        content_hash = hashlib.sha256(image_bytes).hexdigest()[:16]
        if content_hash in seen_hashes:
            continue  # Same image already added from this MHTML
        seen_hashes.add(content_hash)

        file_name = f"{content_hash}.png"
        if image_dir_path:
            file_path = str(image_dir_path / file_name)
        else:
            file_path = file_name

        # Find which study this image belongs to
        ref_study = None
        for study in data.study_refs:
            if uuid in study.image_uuids:
                ref_study = study
                break

        metadata: dict = {"uuid": uuid}
        if ref_study:
            metadata["study_name"] = ref_study.study_name
            metadata["study_date"] = ref_study.study_date

        records.source_assets.append(
            SourceAsset(
                source=source,
                asset_type="png",
                file_path=file_path,
                file_name=file_name,
                file_size_kb=len(image_bytes) // 1024,
                content_type="image/png",
                title=ref_study.raw_header if ref_study else "",
                encounter_date=data.visit_date,
                metadata=json.dumps(metadata) if metadata else "",
            )
        )

    return records


def save_images(data: ParsedVisit, output_dir: str) -> dict[str, str]:
    """Save extracted images to disk, deduplicating by content hash.

    Args:
        data: Parsed visit data containing images.
        output_dir: Directory to save images into.

    Returns:
        Dict of UUID -> saved file path.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    saved: dict[str, str] = {}
    for uuid, image_bytes in data.images.items():
        content_hash = hashlib.sha256(image_bytes).hexdigest()[:16]
        file_path = out / f"{content_hash}.png"
        if not file_path.exists():
            file_path.write_bytes(image_bytes)
        saved[uuid] = str(file_path)

    return saved
