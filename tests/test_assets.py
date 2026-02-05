"""Tests for source asset tracking functionality."""

import json
import os
import tempfile

import pytest

from chartfold.db import ChartfoldDB
from chartfold.models import DocumentRecord, SourceAsset, UnifiedRecords
from chartfold.sources.assets import (
    EXTENSION_TO_TYPE,
    PARSED_EXTENSIONS,
    discover_source_assets,
    enrich_assets_from_meditech_toc,
)


class TestAssetDiscovery:
    """Tests for discover_source_assets function."""

    def test_discovers_pdf_files(self, tmp_path):
        """Should discover PDF files in directory."""
        # Create some test files
        (tmp_path / "document.pdf").write_bytes(b"PDF content here")
        (tmp_path / "image.png").write_bytes(b"PNG content")

        assets = discover_source_assets(str(tmp_path), "test_source")

        assert len(assets) == 2
        pdf_asset = next(a for a in assets if a.asset_type == "pdf")
        assert pdf_asset.file_name == "document.pdf"
        assert pdf_asset.source == "test_source"
        assert pdf_asset.content_type == "application/pdf"

    def test_skips_parsed_files(self, tmp_path):
        """Should skip XML, JSON, and NDJSON files that source parsers handle."""
        (tmp_path / "document.pdf").write_bytes(b"PDF")
        (tmp_path / "parsed.xml").write_bytes(b"<xml/>")
        (tmp_path / "data.json").write_bytes(b"{}")
        (tmp_path / "toc.ndjson").write_bytes(b"")

        assets = discover_source_assets(str(tmp_path), "test_source")

        # Should only find the PDF
        assert len(assets) == 1
        assert assets[0].asset_type == "pdf"

    def test_skips_hidden_files(self, tmp_path):
        """Should skip hidden files and system files."""
        (tmp_path / "document.pdf").write_bytes(b"PDF")
        (tmp_path / ".hidden").write_bytes(b"hidden")
        (tmp_path / ".DS_Store").write_bytes(b"mac")

        assets = discover_source_assets(str(tmp_path), "test_source")

        assert len(assets) == 1
        assert assets[0].file_name == "document.pdf"

    def test_discovers_nested_files(self, tmp_path):
        """Should discover files in nested directories."""
        subdir = tmp_path / "subdir" / "nested"
        subdir.mkdir(parents=True)
        (tmp_path / "root.pdf").write_bytes(b"PDF")
        (subdir / "nested.pdf").write_bytes(b"PDF")

        assets = discover_source_assets(str(tmp_path), "test_source")

        assert len(assets) == 2
        file_names = {a.file_name for a in assets}
        assert file_names == {"root.pdf", "nested.pdf"}

    def test_captures_file_size(self, tmp_path):
        """Should capture file size in KB."""
        content = b"x" * 5000  # 5000 bytes ~ 4KB
        (tmp_path / "large.pdf").write_bytes(content)

        assets = discover_source_assets(str(tmp_path), "test_source")

        assert len(assets) == 1
        assert assets[0].file_size_kb == 4  # 5000 // 1024 = 4

    def test_handles_multiple_image_types(self, tmp_path):
        """Should handle various image file types."""
        (tmp_path / "image.png").write_bytes(b"PNG")
        (tmp_path / "photo.jpg").write_bytes(b"JPG")
        (tmp_path / "photo2.jpeg").write_bytes(b"JPEG")
        (tmp_path / "diagram.gif").write_bytes(b"GIF")

        assets = discover_source_assets(str(tmp_path), "test_source")

        assert len(assets) == 4
        types = {a.asset_type for a in assets}
        assert types == {"png", "jpg", "gif"}  # jpeg normalized to jpg


class TestMeditechPathMetadata:
    """Tests for MEDITECH-specific path metadata extraction."""

    def test_extracts_encounter_id_from_path(self, tmp_path):
        """Should extract encounter ID from MEDITECH folder names."""
        enc_dir = tmp_path / "V00003336701_SMITH_JOHN_30-Jan-2024" / "015_Laboratory"
        enc_dir.mkdir(parents=True)
        (enc_dir / "report.pdf").write_bytes(b"PDF")

        assets = discover_source_assets(str(tmp_path), "meditech_anderson")

        assert len(assets) == 1
        assert assets[0].encounter_id == "V00003336701"
        assert assets[0].encounter_date == "2024-01-30"
        assert assets[0].title == "Laboratory"

    def test_extracts_category_from_numbered_folder(self, tmp_path):
        """Should extract category from numbered folder names like 015_Laboratory."""
        enc_dir = tmp_path / "V00001234567_DOE_30-Dec-2025" / "020_Radiology"
        enc_dir.mkdir(parents=True)
        (enc_dir / "scan.pdf").write_bytes(b"PDF")

        assets = discover_source_assets(str(tmp_path), "meditech_source")

        assert len(assets) == 1
        assert assets[0].title == "Radiology"


class TestMeditechTocEnrichment:
    """Tests for MEDITECH TOC enrichment."""

    def test_enriches_assets_from_toc(self, tmp_path):
        """Should enrich assets with TOC metadata."""
        # Create asset file
        (tmp_path / "report.pdf").write_bytes(b"PDF content")

        # Create initial asset
        assets = discover_source_assets(str(tmp_path), "meditech_source")

        # TOC data
        toc_data = [
            {
                "url": "report.pdf",
                "title": "Discharge Summary",
                "date": "2025-01-30",
                "content_type": "application/pdf",
                "description": "Patient discharge paperwork",
                "status": "current",
            }
        ]

        enriched = enrich_assets_from_meditech_toc(assets, toc_data, str(tmp_path))

        assert len(enriched) == 1
        assert enriched[0].title == "Discharge Summary"
        assert enriched[0].encounter_date == "2025-01-30"
        meta = json.loads(enriched[0].metadata)
        assert meta["description"] == "Patient discharge paperwork"

    def test_handles_unmatched_assets(self, tmp_path):
        """Should leave unmatched assets unchanged."""
        (tmp_path / "unlisted.pdf").write_bytes(b"PDF")

        assets = discover_source_assets(str(tmp_path), "meditech_source")
        toc_data = [{"url": "other.pdf", "title": "Other"}]

        enriched = enrich_assets_from_meditech_toc(assets, toc_data, str(tmp_path))

        assert len(enriched) == 1
        assert enriched[0].title == ""  # Not enriched


class TestSourceAssetModel:
    """Tests for SourceAsset dataclass."""

    def test_source_asset_defaults(self):
        """Should have sensible defaults."""
        asset = SourceAsset(
            source="test",
            asset_type="pdf",
            file_path="/path/to/file.pdf",
            file_name="file.pdf",
        )

        assert asset.file_size_kb == 0
        assert asset.content_type == ""
        assert asset.title == ""
        assert asset.encounter_date == ""
        assert asset.encounter_id == ""
        assert asset.doc_id == ""
        assert asset.ref_table == ""
        assert asset.ref_id is None
        assert asset.metadata == ""


class TestUnifiedRecordsWithAssets:
    """Tests for source_assets in UnifiedRecords."""

    def test_unified_records_includes_source_assets(self):
        """UnifiedRecords should have source_assets field."""
        records = UnifiedRecords(
            source="test",
            source_assets=[
                SourceAsset(
                    source="test",
                    asset_type="pdf",
                    file_path="/path/to/doc.pdf",
                    file_name="doc.pdf",
                )
            ],
        )

        assert len(records.source_assets) == 1
        assert records.source_assets[0].asset_type == "pdf"

    def test_counts_include_source_assets(self):
        """counts() should include source_assets."""
        records = UnifiedRecords(
            source="test",
            source_assets=[
                SourceAsset(source="test", asset_type="pdf", file_path="/a.pdf", file_name="a.pdf"),
                SourceAsset(source="test", asset_type="png", file_path="/b.png", file_name="b.png"),
            ],
        )

        counts = records.counts()
        assert counts["source_assets"] == 2


class TestDatabaseSourceAssets:
    """Tests for source_assets in database."""

    def test_loads_source_assets_to_db(self, tmp_db):
        """Should load source_assets into database."""
        records = UnifiedRecords(
            source="test_source",
            source_assets=[
                SourceAsset(
                    source="test_source",
                    asset_type="pdf",
                    file_path="/path/to/report.pdf",
                    file_name="report.pdf",
                    file_size_kb=150,
                    content_type="application/pdf",
                    title="Lab Report",
                    encounter_date="2025-01-15",
                    encounter_id="V123",
                ),
                SourceAsset(
                    source="test_source",
                    asset_type="png",
                    file_path="/path/to/image.png",
                    file_name="image.png",
                    file_size_kb=50,
                ),
            ],
        )

        counts = tmp_db.load_source(records)

        assert counts["source_assets"] == 2

        # Query to verify
        rows = tmp_db.query("SELECT * FROM source_assets ORDER BY file_name")
        assert len(rows) == 2
        assert rows[0]["file_name"] == "image.png"
        assert rows[1]["file_name"] == "report.pdf"
        assert rows[1]["encounter_date"] == "2025-01-15"

    def test_idempotent_reload_source_assets(self, tmp_db):
        """Should replace source_assets on reload."""
        records1 = UnifiedRecords(
            source="test_source",
            source_assets=[
                SourceAsset(source="test_source", asset_type="pdf", file_path="/a.pdf", file_name="a.pdf"),
                SourceAsset(source="test_source", asset_type="pdf", file_path="/b.pdf", file_name="b.pdf"),
            ],
        )
        tmp_db.load_source(records1)

        # Reload with different assets
        records2 = UnifiedRecords(
            source="test_source",
            source_assets=[
                SourceAsset(source="test_source", asset_type="pdf", file_path="/c.pdf", file_name="c.pdf"),
            ],
        )
        tmp_db.load_source(records2)

        rows = tmp_db.query("SELECT * FROM source_assets")
        assert len(rows) == 1
        assert rows[0]["file_name"] == "c.pdf"

    def test_summary_includes_source_assets(self, tmp_db):
        """summary() should include source_assets count."""
        records = UnifiedRecords(
            source="test_source",
            source_assets=[
                SourceAsset(source="test_source", asset_type="pdf", file_path="/a.pdf", file_name="a.pdf"),
            ],
        )
        tmp_db.load_source(records)

        summary = tmp_db.summary()
        assert "source_assets" in summary
        assert summary["source_assets"] == 1


class TestDocumentFilePath:
    """Tests for file_path on DocumentRecord."""

    def test_document_record_file_path(self, tmp_db):
        """DocumentRecord should have file_path stored."""
        records = UnifiedRecords(
            source="test_source",
            documents=[
                DocumentRecord(
                    source="test_source",
                    doc_id="DOC0001",
                    doc_type="CDA",
                    title="Test Doc",
                    file_path="/path/to/DOC0001.XML",
                    file_size_kb=100,
                ),
            ],
        )

        tmp_db.load_source(records)

        rows = tmp_db.query("SELECT doc_id, file_path FROM documents")
        assert len(rows) == 1
        assert rows[0]["file_path"] == "/path/to/DOC0001.XML"


class TestAdapterIntegration:
    """Tests that adapters produce file_path and source_assets."""

    def test_epic_adapter_adds_file_path(self, sample_epic_data, tmp_path):
        """Epic adapter should populate file_path from inventory."""
        from chartfold.adapters.epic_adapter import epic_to_unified

        # Add file_path and input_dir to sample data
        sample_epic_data["input_dir"] = str(tmp_path)
        for inv in sample_epic_data["inventory"]:
            inv["file_path"] = f"/path/to/{inv['doc_id']}.XML"

        records = epic_to_unified(sample_epic_data)

        # Check documents have file_path
        for doc in records.documents:
            assert doc.file_path.endswith(".XML")

    def test_meditech_adapter_adds_file_path(self, sample_meditech_data, tmp_path):
        """MEDITECH adapter should populate file_path from ccda_data."""
        from chartfold.adapters.meditech_adapter import meditech_to_unified

        # Add file_path and input_dir
        sample_meditech_data["input_dir"] = str(tmp_path)
        for doc in sample_meditech_data["ccda_data"]["documents"]:
            doc["file_path"] = f"/path/to/{doc['filename']}"

        records = meditech_to_unified(sample_meditech_data)

        for doc in records.documents:
            assert doc.file_path != ""

    def test_athena_adapter_adds_file_path(self, sample_athena_data, tmp_path):
        """athena adapter should populate file_path."""
        from chartfold.adapters.athena_adapter import athena_to_unified

        sample_athena_data["input_dir"] = str(tmp_path)
        for doc in sample_athena_data["documents"]:
            doc["file_path"] = f"/path/to/{doc['doc_id']}"

        records = athena_to_unified(sample_athena_data)

        for doc in records.documents:
            assert doc.file_path != ""


class TestExtensionClassification:
    """Tests for extension to asset type mapping."""

    def test_common_extensions_mapped(self):
        """Common extensions should be mapped to asset types."""
        assert EXTENSION_TO_TYPE[".pdf"] == "pdf"
        assert EXTENSION_TO_TYPE[".png"] == "png"
        assert EXTENSION_TO_TYPE[".jpg"] == "jpg"
        assert EXTENSION_TO_TYPE[".jpeg"] == "jpg"
        assert EXTENSION_TO_TYPE[".html"] == "html"
        assert EXTENSION_TO_TYPE[".xsl"] == "xsl"

    def test_parsed_extensions_skipped(self):
        """Parsed extensions should be in skip list."""
        assert ".xml" in PARSED_EXTENSIONS
        assert ".json" in PARSED_EXTENSIONS
        assert ".ndjson" in PARSED_EXTENSIONS
