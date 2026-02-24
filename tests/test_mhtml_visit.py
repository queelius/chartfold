"""Tests for MyChart MHTML parser and adapter."""

import base64
import email
import email.mime.image
import email.mime.multipart
import email.mime.text
import quopri
from pathlib import Path

import pytest

from chartfold.adapters.mhtml_visit_adapter import (
    _infer_modality,
    _parser_counts,
    mychart_to_unified,
    save_images,
)
from chartfold.db import ChartfoldDB
from chartfold.sources.mhtml_visit import (
    ParsedVisit,
    StudyRef,
    _extract_uuid_from_url,
    _normalize_date,
    _parse_display_date,
    parse_mhtml,
)


# --- Fixtures ---


def _make_mhtml(html_body: str, images: dict[str, bytes] | None = None) -> bytes:
    """Build a minimal MHTML file for testing.

    Args:
        html_body: The HTML content (will be quoted-printable encoded).
        images: Dict of UUID -> image bytes to include as MIME parts.
    """
    msg = email.mime.multipart.MIMEMultipart("related")
    msg["Subject"] = "MyChart - Past Visit Details"
    msg["MIME-Version"] = "1.0"

    # HTML part
    html_part = email.mime.text.MIMEText(html_body, "html", "utf-8")
    html_part.replace_header("Content-Transfer-Encoding", "quoted-printable")
    # Re-encode as QP
    html_bytes = html_body.encode("utf-8")
    html_part.set_payload(quopri.encodestring(html_bytes).decode("ascii"))
    msg.attach(html_part)

    # Image parts
    for uuid, data in (images or {}).items():
        img_part = email.mime.image.MIMEImage(data, "png")
        img_part.add_header(
            "Content-Location",
            f"https://www.mypatientchart.org/MyChart/Image/Load?fileName={uuid}",
        )
        msg.attach(img_part)

    return msg.as_bytes()


# Two distinct tiny valid 1x1 PNGs (different pixels → different content hash)
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
    "nGNgYPgPAAEDAQAIicLsAAAABJRU5ErkJggg=="
)
_TINY_PNG_2 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4"
    "nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)

_SAMPLE_HTML = """<!DOCTYPE html>
<html>
<head><title>MyChart - Past Visit Details</title></head>
<body>
<h1 class="_PageHeading _readOnlyText _heading">Office Visit - Feb 05, 2026</h1>
<div class="_Text _readOnlyText subtitle">with Benjamin Tan, MD at WashU Medicine Oncology</div>

<div data-copy-context="NOTE|123">
<div class="p0" data-paragraph="0"><span class="s0">Oncology Return/Follow Up Visit</span></div>
<div class="p1" data-paragraph="1"><span class="s1">&nbsp;</span></div>
<div class="p1" data-paragraph="2"><span class="s2">RADIOLOGY REVIEW:</span></div>
<div class="p1" data-paragraph="3"><span class="s0">MRI/CT 1/15/2026</span></div>
<div class="p1" data-paragraph="4"><span class="s1">No new enhancing hepatic lesion.</span></div>
<div class="p1" data-paragraph="5"><span class="s1"><img src="https://www.mypatientchart.org/MyChart/Image/Load?fileName=aaa11111-2222-3333-4444-555566667777" alt="untitled image" width="576" height="450"></span></div>
<div class="p1" data-paragraph="6"><span class="s0">PET/FDG 11/19/2025</span></div>
<div class="p1" data-paragraph="7"><span class="s1">No evidence of hypermetabolic disease.</span></div>
<div class="p1" data-paragraph="8"><span class="s1"><img src="https://www.mypatientchart.org/MyChart/Image/Load?fileName=bbb22222-3333-4444-5555-666677778888" alt="untitled image"></span></div>
<div class="p1" data-paragraph="9"><span class="s0">CT Chest 8/28/2024</span></div>
<div class="p1" data-paragraph="10"><span class="s1">Stable pulmonary nodules.</span></div>
</div>
</body>
</html>"""


@pytest.fixture
def sample_mhtml(tmp_path):
    """Create a sample MHTML file with visit data and images."""
    images = {
        "aaa11111-2222-3333-4444-555566667777": _TINY_PNG,
        "bbb22222-3333-4444-5555-666677778888": _TINY_PNG_2,
    }
    mhtml_bytes = _make_mhtml(_SAMPLE_HTML, images)
    mhtml_path = tmp_path / "visit.mhtml"
    mhtml_path.write_bytes(mhtml_bytes)
    return str(mhtml_path)


@pytest.fixture
def parsed_visit(sample_mhtml):
    """Parse the sample MHTML file."""
    return parse_mhtml(sample_mhtml)


# --- Unit tests for helpers ---


class TestHelpers:
    def test_normalize_date_mdy(self):
        assert _normalize_date("1/15/2026") == "2026-01-15"

    def test_normalize_date_full(self):
        assert _normalize_date("11/19/2025") == "2025-11-19"

    def test_normalize_date_single_digits(self):
        assert _normalize_date("8/5/2024") == "2024-08-05"

    def test_parse_display_date_short_month(self):
        assert _parse_display_date("Feb 05, 2026") == "2026-02-05"

    def test_parse_display_date_full_month(self):
        assert _parse_display_date("January 15, 2026") == "2026-01-15"

    def test_extract_uuid_from_url(self):
        url = "https://www.mypatientchart.org/MyChart/Image/Load?fileName=aaa11111-2222-3333-4444-555566667777"
        assert _extract_uuid_from_url(url) == "aaa11111-2222-3333-4444-555566667777"

    def test_extract_uuid_from_url_no_match(self):
        assert _extract_uuid_from_url("https://example.com/foo") == ""

    def test_infer_modality_mri(self):
        assert _infer_modality("MRI Abdomen Pelvis") == "MRI"

    def test_infer_modality_pet(self):
        assert _infer_modality("PET/FDG") == "PET"

    def test_infer_modality_ct(self):
        assert _infer_modality("CT Chest") == "CT"

    def test_infer_modality_mri_ct_combo(self):
        assert _infer_modality("MRI/CT") == "MRI"

    def test_infer_modality_unknown(self):
        assert _infer_modality("Something Weird") == ""


# --- Parser tests ---


class TestMhtmlParser:
    def test_parses_visit_date(self, parsed_visit):
        assert parsed_visit.visit_date == "2026-02-05"

    def test_parses_visit_type(self, parsed_visit):
        assert parsed_visit.visit_type == "Office Visit"

    def test_parses_provider(self, parsed_visit):
        assert parsed_visit.provider == "Benjamin Tan, MD"

    def test_parses_facility(self, parsed_visit):
        assert parsed_visit.facility == "WashU Medicine Oncology"

    def test_parses_note_title(self, parsed_visit):
        assert parsed_visit.note_title == "Oncology Return/Follow Up Visit"

    def test_extracts_note_text(self, parsed_visit):
        assert "RADIOLOGY REVIEW:" in parsed_visit.note_text
        assert "No new enhancing hepatic lesion." in parsed_visit.note_text

    def test_extracts_images(self, parsed_visit):
        assert len(parsed_visit.images) == 2
        assert "aaa11111-2222-3333-4444-555566667777" in parsed_visit.images
        assert "bbb22222-3333-4444-5555-666677778888" in parsed_visit.images

    def test_image_data_is_png(self, parsed_visit):
        for uuid, data in parsed_visit.images.items():
            assert data[:4] == b"\x89PNG"

    def test_identifies_study_refs(self, parsed_visit):
        assert len(parsed_visit.study_refs) >= 2
        names = [s.study_name for s in parsed_visit.study_refs]
        assert "MRI/CT" in names
        assert "PET/FDG" in names

    def test_study_dates_normalized(self, parsed_visit):
        dates = {s.study_name: s.study_date for s in parsed_visit.study_refs}
        assert dates["MRI/CT"] == "2026-01-15"
        assert dates["PET/FDG"] == "2025-11-19"

    def test_images_linked_to_studies(self, parsed_visit):
        mri_study = next(s for s in parsed_visit.study_refs if s.study_name == "MRI/CT")
        assert "aaa11111-2222-3333-4444-555566667777" in mri_study.image_uuids

        pet_study = next(s for s in parsed_visit.study_refs if s.study_name == "PET/FDG")
        assert "bbb22222-3333-4444-5555-666677778888" in pet_study.image_uuids

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_mhtml(str(tmp_path / "nonexistent.mhtml"))

    def test_empty_mhtml(self, tmp_path):
        """MHTML with no HTML body should return empty ParsedVisit."""
        msg = email.mime.multipart.MIMEMultipart("related")
        msg["Subject"] = "Test"
        path = tmp_path / "empty.mhtml"
        path.write_bytes(msg.as_bytes())
        result = parse_mhtml(str(path))
        assert result.visit_date == ""
        assert result.images == {}

    def test_mhtml_without_images(self, tmp_path):
        """MHTML with HTML but no image parts."""
        mhtml_bytes = _make_mhtml(_SAMPLE_HTML, images={})
        path = tmp_path / "noimg.mhtml"
        path.write_bytes(mhtml_bytes)
        result = parse_mhtml(str(path))
        assert result.visit_date == "2026-02-05"
        assert len(result.images) == 0
        # Study refs should still be detected from the HTML text
        assert len(result.study_refs) >= 2


# --- Adapter tests ---


class TestMychartAdapter:
    def test_creates_encounter(self, parsed_visit):
        records = mychart_to_unified(parsed_visit, source="mychart")
        assert len(records.encounters) == 1
        enc = records.encounters[0]
        assert enc.encounter_date == "2026-02-05"
        assert enc.encounter_type == "Office Visit"
        assert enc.provider == "Benjamin Tan, MD"
        assert enc.facility == "WashU Medicine Oncology"

    def test_creates_clinical_note(self, parsed_visit):
        records = mychart_to_unified(parsed_visit, source="mychart")
        assert len(records.clinical_notes) == 1
        note = records.clinical_notes[0]
        assert note.note_date == "2026-02-05"
        assert note.author == "Benjamin Tan, MD"
        assert "RADIOLOGY REVIEW:" in note.content

    def test_creates_imaging_reports(self, parsed_visit):
        records = mychart_to_unified(parsed_visit, source="mychart")
        assert len(records.imaging_reports) >= 2
        names = {r.study_name for r in records.imaging_reports}
        assert "MRI/CT" in names
        assert "PET/FDG" in names

    def test_imaging_report_modalities(self, parsed_visit):
        records = mychart_to_unified(parsed_visit, source="mychart")
        modalities = {r.study_name: r.modality for r in records.imaging_reports}
        assert modalities["MRI/CT"] == "MRI"
        assert modalities["PET/FDG"] == "PET"

    def test_creates_source_assets(self, parsed_visit):
        records = mychart_to_unified(parsed_visit, source="mychart", image_dir="/tmp/img")
        assert len(records.source_assets) == 2
        for asset in records.source_assets:
            assert asset.asset_type == "png"
            assert asset.source == "mychart"
            assert asset.file_path.startswith("/tmp/img/")
            assert asset.encounter_date == "2026-02-05"

    def test_asset_filenames_are_content_hashes(self, parsed_visit):
        """Filenames should be content hashes, not UUIDs."""
        records = mychart_to_unified(parsed_visit, source="mychart")
        for asset in records.source_assets:
            # Content hash: 16 hex chars + .png
            assert len(asset.file_name) == 20  # 16 hex + ".png"
            assert asset.file_name.endswith(".png")
            # Should NOT be a UUID pattern
            assert "-" not in asset.file_name

    def test_duplicate_image_content_deduped(self):
        """Two UUIDs with identical bytes should produce one asset."""
        visit = ParsedVisit(
            visit_date="2026-01-01",
            images={
                "uuid-1111-aaaa": _TINY_PNG,
                "uuid-2222-bbbb": _TINY_PNG,  # Same bytes as uuid-1111
            },
        )
        records = mychart_to_unified(visit, source="mychart")
        assert len(records.source_assets) == 1

    def test_different_image_content_kept(self):
        """Two UUIDs with different bytes should produce two assets."""
        visit = ParsedVisit(
            visit_date="2026-01-01",
            images={
                "uuid-1111-aaaa": _TINY_PNG,
                "uuid-2222-bbbb": _TINY_PNG_2,
            },
        )
        records = mychart_to_unified(visit, source="mychart")
        assert len(records.source_assets) == 2

    def test_source_name_propagated(self, parsed_visit):
        records = mychart_to_unified(parsed_visit, source="mychart_washu")
        assert records.source == "mychart_washu"
        assert all(r.source == "mychart_washu" for r in records.encounters)
        assert all(r.source == "mychart_washu" for r in records.imaging_reports)

    def test_parser_counts(self, parsed_visit):
        counts = _parser_counts(parsed_visit)
        assert counts["encounters"] == 1
        assert counts["clinical_notes"] == 1
        assert counts["source_assets"] == 2
        assert counts["imaging_reports"] >= 2

    def test_save_images(self, parsed_visit, tmp_path):
        image_dir = str(tmp_path / "images")
        saved = save_images(parsed_visit, image_dir)
        assert len(saved) == 2
        for uuid, path in saved.items():
            assert Path(path).is_file()
            assert Path(path).read_bytes()[:4] == b"\x89PNG"

    def test_save_images_deduplicates(self, tmp_path):
        """save_images should write one file for duplicate image content."""
        visit = ParsedVisit(
            images={
                "uuid-aaaa": _TINY_PNG,
                "uuid-bbbb": _TINY_PNG,  # Same bytes
                "uuid-cccc": _TINY_PNG_2,  # Different bytes
            }
        )
        image_dir = str(tmp_path / "images")
        saved = save_images(visit, image_dir)
        assert len(saved) == 3  # All UUIDs get entries
        # But two UUIDs should point to the same file
        paths = set(saved.values())
        assert len(paths) == 2  # Only 2 unique files on disk

    def test_empty_visit(self):
        """Empty ParsedVisit should produce empty UnifiedRecords."""
        empty = ParsedVisit()
        records = mychart_to_unified(empty, source="mychart")
        assert len(records.encounters) == 0
        assert len(records.clinical_notes) == 0
        assert len(records.imaging_reports) == 0
        assert len(records.source_assets) == 0


# --- Integration tests: load into DB ---


class TestMychartDbIntegration:
    def test_granular_load_does_not_delete(self, tmp_db, parsed_visit):
        """replace=False should not affect existing data from other sources."""
        from chartfold.models import ImagingReport, UnifiedRecords

        # First load some epic data
        epic = UnifiedRecords(
            source="epic",
            imaging_reports=[
                ImagingReport(
                    source="epic",
                    study_name="MRI Brain",
                    study_date="2025-08-28",
                    modality="MRI",
                    impression="Normal findings",
                ),
            ],
        )
        tmp_db.load_source(epic)

        # Now load mychart data (granular)
        records = mychart_to_unified(parsed_visit, source="mychart", image_dir="/tmp")
        tmp_db.load_source(records, replace=False)

        # Both sources should coexist
        all_imaging = tmp_db.query("SELECT * FROM imaging_reports ORDER BY source")
        sources = {r["source"] for r in all_imaging}
        assert "epic" in sources
        assert "mychart" in sources

    def test_reimport_updates_not_duplicates(self, tmp_db, parsed_visit):
        """Loading same MHTML twice with replace=False should update, not duplicate."""
        records = mychart_to_unified(parsed_visit, source="mychart", image_dir="/tmp")

        tmp_db.load_source(records, replace=False)
        count_first = len(tmp_db.query("SELECT * FROM imaging_reports WHERE source='mychart'"))

        tmp_db.load_source(records, replace=False)
        count_second = len(tmp_db.query("SELECT * FROM imaging_reports WHERE source='mychart'"))

        assert count_first == count_second

    def test_load_creates_load_log(self, tmp_db, parsed_visit):
        records = mychart_to_unified(parsed_visit, source="mychart", image_dir="/tmp")
        tmp_db.load_source(records, replace=False)

        logs = tmp_db.query("SELECT * FROM load_log WHERE source='mychart'")
        assert len(logs) == 1
        assert logs[0]["imaging_reports_count"] >= 2
        assert logs[0]["source_assets_count"] == 2

    def test_cross_visit_image_dedup(self, tmp_db):
        """Same image in two visit pages should not produce duplicate assets."""
        # Visit 1: has image A and image B
        visit1 = ParsedVisit(
            visit_date="2026-02-05",
            images={
                "uuid-visit1-img-a": _TINY_PNG,
                "uuid-visit1-img-b": _TINY_PNG_2,
            },
            study_refs=[
                StudyRef(
                    study_name="MRI Brain",
                    study_date="2026-01-15",
                    raw_header="MRI Brain 1/15/2026",
                    paragraph_idx=0,
                    image_uuids=["uuid-visit1-img-a"],
                ),
            ],
        )
        # Visit 2: same images with different UUIDs (as MyChart generates)
        visit2 = ParsedVisit(
            visit_date="2026-01-15",
            images={
                "uuid-visit2-img-a": _TINY_PNG,   # Same bytes as visit1's img-a
                "uuid-visit2-img-b": _TINY_PNG_2,  # Same bytes as visit1's img-b
            },
            study_refs=[
                StudyRef(
                    study_name="MRI Brain",
                    study_date="2026-01-15",
                    raw_header="MRI Brain 1/15/2026",
                    paragraph_idx=0,
                    image_uuids=["uuid-visit2-img-a"],
                ),
            ],
        )

        records1 = mychart_to_unified(visit1, source="mychart")
        records2 = mychart_to_unified(visit2, source="mychart")

        tmp_db.load_source(records1, replace=False)
        tmp_db.load_source(records2, replace=False)

        # Should only have 2 unique assets, not 4
        assets = tmp_db.query("SELECT * FROM source_assets WHERE source='mychart'")
        assert len(assets) == 2


# --- Post-load linking tests ---


class TestPostLoadLinking:
    def test_links_assets_to_imaging_reports(self, tmp_db, parsed_visit):
        """_link_assets_to_imaging should set ref_table/ref_id on source_assets."""
        from chartfold.cli import _link_assets_to_imaging

        records = mychart_to_unified(parsed_visit, source="mychart", image_dir="/tmp")
        tmp_db.load_source(records, replace=False)

        # Before linking: assets have no ref_table/ref_id
        assets_before = tmp_db.query(
            "SELECT ref_table, ref_id FROM source_assets WHERE source='mychart'"
        )
        assert all(not a["ref_table"] for a in assets_before)

        linked = _link_assets_to_imaging(tmp_db, "mychart")
        assert linked == 2  # Two images, each linked to a study

        # After linking: assets should point to imaging_reports
        assets_after = tmp_db.query(
            "SELECT ref_table, ref_id FROM source_assets WHERE source='mychart'"
        )
        assert all(a["ref_table"] == "imaging_reports" for a in assets_after)
        assert all(a["ref_id"] is not None for a in assets_after)

    def test_linked_ref_ids_match_correct_reports(self, tmp_db, parsed_visit):
        """ref_id should point to the correct imaging_report by study_name."""
        from chartfold.cli import _link_assets_to_imaging

        records = mychart_to_unified(parsed_visit, source="mychart", image_dir="/tmp")
        tmp_db.load_source(records, replace=False)
        _link_assets_to_imaging(tmp_db, "mychart")

        # Get the linked assets with their report info
        linked = tmp_db.query(
            """
            SELECT sa.file_name, ir.study_name, ir.study_date
            FROM source_assets sa
            JOIN imaging_reports ir ON sa.ref_id = ir.id
            WHERE sa.source = 'mychart'
            """
        )
        study_names = {r["study_name"] for r in linked}
        assert "MRI/CT" in study_names
        assert "PET/FDG" in study_names

    def test_idempotent_linking(self, tmp_db, parsed_visit):
        """Running _link_assets_to_imaging twice should not change anything."""
        from chartfold.cli import _link_assets_to_imaging

        records = mychart_to_unified(parsed_visit, source="mychart", image_dir="/tmp")
        tmp_db.load_source(records, replace=False)

        linked_first = _link_assets_to_imaging(tmp_db, "mychart")
        assert linked_first == 2

        # Second run: already linked, should find nothing new
        linked_second = _link_assets_to_imaging(tmp_db, "mychart")
        assert linked_second == 0

    def test_no_linking_without_imaging_reports(self, tmp_db):
        """Assets without matching imaging_reports should not be linked."""
        from chartfold.cli import _link_assets_to_imaging
        from chartfold.models import SourceAsset, UnifiedRecords

        records = UnifiedRecords(
            source="mychart",
            source_assets=[
                SourceAsset(
                    source="mychart",
                    asset_type="png",
                    file_path="/tmp/orphan.png",
                    file_name="orphan.png",
                    metadata='{"study_name": "Nonexistent Study", "study_date": "2099-01-01"}',
                ),
            ],
        )
        tmp_db.load_source(records, replace=False)
        linked = _link_assets_to_imaging(tmp_db, "mychart")
        assert linked == 0


# --- Auto-detect tests ---


class TestAutoDetectMhtml:
    def test_auto_loads_mhtml_file(self, tmp_path, sample_mhtml):
        """chartfold load auto <file.mhtml> should auto-detect and load mychart."""
        from chartfold.cli import _load_auto
        from chartfold.db import ChartfoldDB

        db_path = str(tmp_path / "test.db")
        with ChartfoldDB(db_path) as db:
            db.init_schema()
            _load_auto(db, sample_mhtml)

            # Should have loaded encounter + imaging reports + assets
            encounters = db.query("SELECT * FROM encounters WHERE source='mychart'")
            assert len(encounters) == 1
            imaging = db.query("SELECT * FROM imaging_reports WHERE source='mychart'")
            assert len(imaging) >= 2
            assets = db.query("SELECT * FROM source_assets WHERE source='mychart'")
            assert len(assets) == 2
