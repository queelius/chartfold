"""Asset discovery for tracking non-parsed source files.

Discovers PDFs, images, and other files in EHR export directories that
chartfold doesn't parse but wants to track for provenance.
"""

import json
import os
import re
from pathlib import Path

from chartfold.models import SourceAsset

# File extensions handled by source parsers (skip these)
PARSED_EXTENSIONS = {".xml", ".json", ".ndjson"}

# Asset type classification by extension
EXTENSION_TO_TYPE = {
    ".pdf": "pdf",
    ".png": "png",
    ".jpg": "jpg",
    ".jpeg": "jpg",
    ".gif": "gif",
    ".bmp": "bmp",
    ".tiff": "tiff",
    ".tif": "tiff",
    ".html": "html",
    ".htm": "html",
    ".xsl": "xsl",
    ".xslt": "xsl",
    ".css": "css",
    ".txt": "txt",
    ".rtf": "rtf",
    ".doc": "doc",
    ".docx": "docx",
}

# MIME types by asset type
TYPE_TO_MIME = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "html": "text/html",
    "xsl": "application/xslt+xml",
    "css": "text/css",
    "txt": "text/plain",
    "rtf": "application/rtf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# Patterns for files to always skip (metadata, system files)
SKIP_PATTERNS = [
    r"^\..*",  # Hidden files
    r".*\.DS_Store$",
    r"Thumbs\.db$",
]


def discover_source_assets(input_dir: str, source: str) -> list[SourceAsset]:
    """Walk input_dir recursively and return SourceAsset for each non-parsed file.

    Args:
        input_dir: Root directory of the EHR export.
        source: Source identifier (e.g., "epic_anderson", "meditech_anderson").

    Returns:
        List of SourceAsset instances for PDFs, images, and other non-parsed files.
    """
    assets: list[SourceAsset] = []
    input_path = Path(input_dir).resolve()

    for root, _dirs, files in os.walk(input_path):
        for filename in files:
            filepath = Path(root) / filename
            ext = filepath.suffix.lower()

            # Skip parsed file types
            if ext in PARSED_EXTENSIONS:
                continue

            # Skip system/hidden files
            if any(re.match(pat, filename) for pat in SKIP_PATTERNS):
                continue

            # Get asset type from extension
            asset_type = EXTENSION_TO_TYPE.get(ext, ext.lstrip(".") or "unknown")
            content_type = TYPE_TO_MIME.get(asset_type, "")

            # Get file size
            try:
                file_size_kb = filepath.stat().st_size // 1024
            except OSError:
                file_size_kb = 0

            # Extract metadata from directory path
            rel_path = filepath.relative_to(input_path)
            title, encounter_id, encounter_date = _extract_path_metadata(rel_path, source)

            assets.append(SourceAsset(
                source=source,
                asset_type=asset_type,
                file_path=str(filepath),
                file_name=filename,
                file_size_kb=file_size_kb,
                content_type=content_type,
                title=title,
                encounter_date=encounter_date,
                encounter_id=encounter_id,
            ))

    return assets


def _extract_path_metadata(rel_path: Path, source: str) -> tuple[str, str, str]:
    """Extract title, encounter_id, and encounter_date from relative path.

    Args:
        rel_path: Path relative to input_dir.
        source: Source identifier.

    Returns:
        (title, encounter_id, encounter_date) tuple.
    """
    parts = rel_path.parts
    title = ""
    encounter_id = ""
    encounter_date = ""

    if "meditech" in source.lower():
        # MEDITECH: V00003336701_SOME-NAME_01-Jan-2024/015_Laboratory/file.pdf
        # First part is encounter folder with ID, name, and date
        if parts:
            enc_folder = parts[0]
            # Extract encounter ID (V########)
            enc_match = re.match(r"(V\d+)", enc_folder)
            if enc_match:
                encounter_id = enc_match.group(1)
            # Extract date from folder name
            date_match = re.search(r"(\d{2})-([A-Za-z]{3})-(\d{4})", enc_folder)
            if date_match:
                day, month, year = date_match.groups()
                encounter_date = _parse_meditech_date(f"{day}-{month}-{year}")

            # Second part may be category like "015_Laboratory"
            if len(parts) > 1:
                cat_folder = parts[1]
                # Strip leading numbers like "015_"
                cat_match = re.match(r"\d+_(.+)", cat_folder)
                if cat_match:
                    title = cat_match.group(1).replace("_", " ")
                else:
                    title = cat_folder.replace("_", " ")

    elif "epic" in source.lower():
        # Epic: typically flat structure, use filename as title
        title = rel_path.stem.replace("_", " ")

    elif "athena" in source.lower():
        # athena: Document_XML/file.xml structure, use parent as category
        if len(parts) > 1:
            title = parts[0].replace("_", " ")

    return title, encounter_id, encounter_date


def _parse_meditech_date(date_str: str) -> str:
    """Parse MEDITECH date like '30-Jan-2026' to ISO format."""
    months = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04",
        "may": "05", "jun": "06", "jul": "07", "aug": "08",
        "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    }
    match = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})", date_str)
    if match:
        day, month, year = match.groups()
        month_num = months.get(month.lower(), "01")
        return f"{year}-{month_num}-{day}"
    return ""


def enrich_assets_from_meditech_toc(
    assets: list[SourceAsset],
    toc_data: list[dict],
    input_dir: str,
) -> list[SourceAsset]:
    """Enrich MEDITECH assets with metadata from Table of Contents NDJSON.

    The TOC contains entries like:
    {
        "description": "...",
        "docStatus": "current",
        "date": "2024-01-30",
        "content": [{"attachment": {"url": "path/to/file.pdf", "title": "...", ...}}]
    }

    Args:
        assets: List of discovered SourceAsset instances.
        toc_data: Parsed TOC from _parse_toc() in meditech.py.
        input_dir: Root directory of the MEDITECH export.

    Returns:
        The same assets list with enriched metadata (modified in place).
    """
    # Build lookup from relative URL path to TOC entry
    toc_lookup: dict[str, dict] = {}
    for entry in toc_data:
        url = entry.get("url", "")
        if url:
            # TOC URLs are relative paths like "V.../015_.../file.pdf"
            toc_lookup[url] = entry

    input_path = Path(input_dir).resolve()

    for asset in assets:
        # Get relative path from asset
        asset_path = Path(asset.file_path)
        try:
            rel_path = asset_path.relative_to(input_path)
        except ValueError:
            continue

        # Check TOC for this file
        rel_str = str(rel_path)
        toc_entry = toc_lookup.get(rel_str)
        if toc_entry:
            # Enrich with TOC metadata
            if toc_entry.get("title") and not asset.title:
                asset.title = toc_entry["title"]
            if toc_entry.get("date") and not asset.encounter_date:
                asset.encounter_date = toc_entry["date"]
            if toc_entry.get("content_type") and not asset.content_type:
                asset.content_type = toc_entry["content_type"]
            if toc_entry.get("description"):
                # Store extra metadata in JSON blob
                meta = {"description": toc_entry["description"]}
                if toc_entry.get("status"):
                    meta["status"] = toc_entry["status"]
                asset.metadata = json.dumps(meta)

    return assets
