"""Imported source-asset media: durable storage beside the DB.

Arkiv import copies every asset's bytes into ``<db dir>/media/`` under a
name derived from the row's durable ``unique_id`` and stores the path
*relative to the DB directory*. EHR-loaded assets keep absolute paths.
Every reader goes through ``health_memex.media.resolve_asset_path``.

All data here is synthetic.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest
import yaml

from health_memex.db import HealthMemexDB
from health_memex.export_arkiv import export_arkiv
from health_memex.import_arkiv import import_arkiv
from health_memex.media import (
    MediaStoreError,
    media_file_name,
    media_root,
    resolve_asset_path,
    store_media,
)

UID_A = "0123456789abcdef"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_asset(db: HealthMemexDB, path: Path, *, source: str = "epic_test", **extra) -> None:
    cols = {
        "source": source,
        "asset_type": path.suffix.lstrip(".").lower() or "bin",
        "file_path": str(path),
        "file_name": path.name,
        "file_size_kb": 0,
        "content_type": "application/octet-stream",
        **extra,
    }
    names = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    db.conn.execute(f"INSERT INTO source_assets ({names}) VALUES ({marks})", list(cols.values()))
    db.conn.commit()


def _source_db(tmp_path: Path) -> tuple[str, dict[str, bytes]]:
    """A DB with three EHR-style assets (absolute paths), two of them
    byte-identical within one source (the Epic duplicated-stylesheet case)."""
    ehr = tmp_path / "ehr"
    (ehr / "a").mkdir(parents=True)
    (ehr / "b").mkdir(parents=True)
    files = {
        "a/STYLE.XSL": b"<xsl>same</xsl>",
        "b/STYLE.XSL": b"<xsl>same</xsl>",
        "a/Scan.PNG": b"\x89PNG synthetic",
    }
    for rel, data in files.items():
        (ehr / rel).write_bytes(data)
    db_path = str(tmp_path / "src" / "src.db")
    with HealthMemexDB(db_path) as db:
        db.init_schema()
        for rel in files:
            _insert_asset(db, ehr / rel)
    with HealthMemexDB(db_path) as db:
        db.init_schema()  # backfill unique_id, as a real DB would have
        rows = db.query("SELECT unique_id, file_path FROM source_assets")
    return db_path, {r["unique_id"]: Path(r["file_path"]).read_bytes() for r in rows}


def _assets(db_path: str) -> list[dict]:
    with HealthMemexDB(db_path) as db:
        return db.query("SELECT * FROM source_assets ORDER BY unique_id")


def _write_bundle(archive_dir: Path, records: list[dict], media: dict[str, bytes] | None = None):
    archive_dir.mkdir(parents=True, exist_ok=True)
    if media:
        (archive_dir / "media").mkdir()
        for name, data in media.items():
            (archive_dir / "media" / name).write_bytes(data)
    front = {
        "name": "synthetic",
        "datetime": "2026-10-19",
        "generator": "test",
        "contents": [{"path": "source_assets.jsonl", "description": "Assets"}],
    }
    (archive_dir / "README.md").write_text("---\n" + yaml.dump(front) + "---\n\n# t\n")
    (archive_dir / "source_assets.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))


def _asset_record(uri: str, *, uid: str | None = UID_A, name: str = "scan.png", **extra):
    meta = {
        "table": "source_assets",
        "source": "test",
        "asset_type": "png",
        "file_name": name,
        **extra,
    }
    if uid is not None:
        meta["unique_id"] = uid
    return {"mimetype": "image/png", "uri": uri, "metadata": meta}


# ---------------------------------------------------------------------------
# resolve_asset_path
# ---------------------------------------------------------------------------


class TestResolveAssetPath:
    def test_absolute_returned_as_is(self, tmp_path):
        p = tmp_path / "elsewhere" / "x.pdf"
        assert resolve_asset_path(str(tmp_path / "h.db"), str(p)) == p

    def test_absolute_without_db(self, tmp_path):
        p = tmp_path / "x.pdf"
        assert resolve_asset_path(None, str(p)) == p

    def test_relative_resolves_against_db_dir(self, tmp_path):
        got = resolve_asset_path(str(tmp_path / "h.db"), "media/abc.png")
        assert got == (tmp_path / "media" / "abc.png").resolve()

    def test_relative_escaping_db_dir_is_none(self, tmp_path):
        assert resolve_asset_path(str(tmp_path / "d" / "h.db"), "../outside.png") is None

    def test_relative_symlink_escaping_db_dir_is_none(self, tmp_path):
        (tmp_path / "d" / "media").mkdir(parents=True)
        (tmp_path / "secret").write_bytes(b"s")
        (tmp_path / "d" / "media" / "x.png").symlink_to(tmp_path / "secret")
        assert resolve_asset_path(str(tmp_path / "d" / "h.db"), "media/x.png") is None

    def test_relative_without_db_dir_is_none(self):
        assert resolve_asset_path(":memory:", "media/abc.png") is None
        assert resolve_asset_path(None, "media/abc.png") is None

    def test_empty_is_none(self, tmp_path):
        assert resolve_asset_path(str(tmp_path / "h.db"), "") is None


# ---------------------------------------------------------------------------
# media_file_name / store_media
# ---------------------------------------------------------------------------


class TestMediaFileName:
    def test_uid_plus_lowercased_ext(self):
        assert media_file_name(UID_A, "Scan.PNG") == f"{UID_A}.png"

    def test_no_ext(self):
        assert media_file_name(UID_A, "README") == UID_A

    def test_unsafe_ext_omitted(self):
        assert media_file_name(UID_A, "x.p/ng") == UID_A
        assert media_file_name(UID_A, "x.p ng") == UID_A

    @pytest.mark.parametrize(
        "bad", ["", "../../etc/passwd", "0123456789ABCDEF", "0123456789abcde", "a/b", None, 7]
    )
    def test_rejects_non_hex_uid(self, bad):
        with pytest.raises(MediaStoreError):
            media_file_name(bad, "x.png")


class TestStoreMedia:
    def test_writes_file(self, tmp_path):
        dest = store_media(tmp_path / "media", "f.png", b"abc")
        assert dest == tmp_path / "media" / "f.png"
        assert dest.read_bytes() == b"abc"

    def test_same_bytes_skips_rewrite(self, tmp_path):
        dest = store_media(tmp_path / "media", "f.png", b"abc")
        before = dest.stat().st_ino
        store_media(tmp_path / "media", "f.png", b"abc")
        assert dest.stat().st_ino == before  # not replaced

    def test_different_bytes_overwrites(self, tmp_path):
        dest = store_media(tmp_path / "media", "f.png", b"abc")
        store_media(tmp_path / "media", "f.png", b"xyz")
        assert dest.read_bytes() == b"xyz"

    def test_no_temp_leftovers(self, tmp_path):
        store_media(tmp_path / "media", "f.png", b"abc")
        store_media(tmp_path / "media", "f.png", b"abc")
        store_media(tmp_path / "media", "f.png", b"xyz")
        assert sorted(os.listdir(tmp_path / "media")) == ["f.png"]

    def test_refuses_symlinked_media_dir(self, tmp_path):
        (tmp_path / "real").mkdir()
        (tmp_path / "media").symlink_to(tmp_path / "real")
        with pytest.raises(MediaStoreError):
            store_media(tmp_path / "media", "f.png", b"abc")
        assert not (tmp_path / "real" / "f.png").exists()

    def test_refuses_symlinked_destination(self, tmp_path):
        (tmp_path / "media").mkdir()
        victim = tmp_path / "victim"
        victim.write_bytes(b"keep")
        (tmp_path / "media" / "f.png").symlink_to(victim)
        with pytest.raises(MediaStoreError):
            store_media(tmp_path / "media", "f.png", b"abc")
        assert victim.read_bytes() == b"keep"

    @pytest.mark.parametrize("name", ["../f.png", "a/f.png", "", "."])
    def test_refuses_non_basename(self, tmp_path, name):
        with pytest.raises(MediaStoreError):
            store_media(tmp_path / "media", name, b"abc")


# ---------------------------------------------------------------------------
# Round trip: export (dir / zip / tar.gz) -> import into a fresh DB
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bundle_name", ["bundle_dir", "bundle.zip", "bundle.tar.gz"])
@pytest.mark.parametrize("embed", [False, True])
def test_round_trip_preserves_ids_and_bytes(tmp_path, bundle_name, embed):
    src_db, src_bytes = _source_db(tmp_path)
    bundle = str(tmp_path / bundle_name)
    with HealthMemexDB(src_db) as db:
        export_arkiv(db, bundle, embed=embed)

    dest_db = tmp_path / "dest" / "health_memex.db"
    result = import_arkiv(bundle, str(dest_db))
    assert result["success"], result["errors"]
    assert result["errors"] == []

    rows = _assets(str(dest_db))
    # Durable IDs are identical to the source DB.
    assert {r["unique_id"] for r in rows} == set(src_bytes)
    for r in rows:
        # Stored relative to the DB dir, named by the row's unique_id.
        assert not os.path.isabs(r["file_path"])
        ext = Path(r["file_name"]).suffix.lower()
        assert r["file_path"] == f"media/{r['unique_id']}{ext}"
        resolved = resolve_asset_path(str(dest_db), r["file_path"])
        assert resolved is not None and resolved.is_file()
        assert resolved.parent == (dest_db.parent / "media").resolve()
        assert resolved.read_bytes() == src_bytes[r["unique_id"]]

    # Identical bytes on distinct rows are stored per row (no cross-row dedupe).
    assert len(os.listdir(dest_db.parent / "media")) == 3


def test_bundle_temp_dir_gone_files_still_present(tmp_path):
    """The regression: zip/tar imports used to point into a deleted temp dir."""
    src_db, _ = _source_db(tmp_path)
    bundle = str(tmp_path / "b.zip")
    with HealthMemexDB(src_db) as db:
        export_arkiv(db, bundle)
    dest_db = str(tmp_path / "dest.db")
    assert import_arkiv(bundle, dest_db)["success"]
    for r in _assets(dest_db):
        assert "health_memex_arkiv_import_" not in r["file_path"]
        p = resolve_asset_path(dest_db, r["file_path"])
        assert p is not None and p.is_file()


def test_directory_import_survives_bundle_deletion(tmp_path):
    import shutil

    src_db, src_bytes = _source_db(tmp_path)
    bundle = tmp_path / "bundle_dir"
    with HealthMemexDB(src_db) as db:
        export_arkiv(db, str(bundle))
    dest_db = str(tmp_path / "dest.db")
    assert import_arkiv(str(bundle), dest_db)["success"]
    shutil.rmtree(bundle)
    for r in _assets(dest_db):
        p = resolve_asset_path(dest_db, r["file_path"])
        assert p is not None and p.read_bytes() == src_bytes[r["unique_id"]]


def test_reexport_of_imported_db_bundles_media(tmp_path):
    src_db, src_bytes = _source_db(tmp_path)
    first = str(tmp_path / "first.zip")
    with HealthMemexDB(src_db) as db:
        export_arkiv(db, first)
    mid_db = str(tmp_path / "mid" / "mid.db")
    assert import_arkiv(first, mid_db)["success"]

    second = str(tmp_path / "second.tar.gz")
    with HealthMemexDB(mid_db) as db:
        export_arkiv(db, second)
    final_db = str(tmp_path / "final" / "final.db")
    result = import_arkiv(second, final_db)
    assert result["success"], result["errors"]
    assert result["counts"]["source_assets"] == 3

    rows = _assets(final_db)
    assert {r["unique_id"] for r in rows} == set(src_bytes)
    for r in rows:
        p = resolve_asset_path(final_db, r["file_path"])
        assert p is not None and p.read_bytes() == src_bytes[r["unique_id"]]


# ---------------------------------------------------------------------------
# Re-import idempotency (upsert keyed on unique_id)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bundle_name", ["bundle_dir", "bundle.zip"])
def test_merge_reimport_is_idempotent(tmp_path, bundle_name):
    src_db, _ = _source_db(tmp_path)
    bundle = str(tmp_path / bundle_name)
    with HealthMemexDB(src_db) as db:
        export_arkiv(db, bundle)
    dest_db = str(tmp_path / "dest.db")
    assert import_arkiv(bundle, dest_db)["success"]
    before = _assets(dest_db)

    result = import_arkiv(bundle, dest_db, merge=True)
    assert result["success"], result["errors"]
    after = _assets(dest_db)
    assert len(after) == 3
    assert [(r["id"], r["unique_id"], r["file_path"]) for r in after] == [
        (r["id"], r["unique_id"], r["file_path"]) for r in before
    ]
    assert len(os.listdir(tmp_path / "media")) == 3


def test_overwrite_reimport_reuses_media(tmp_path):
    src_db, _ = _source_db(tmp_path)
    bundle = str(tmp_path / "b.zip")
    with HealthMemexDB(src_db) as db:
        export_arkiv(db, bundle)
    dest_db = str(tmp_path / "dest.db")
    assert import_arkiv(bundle, dest_db)["success"]
    assert import_arkiv(bundle, dest_db, overwrite=True)["success"]
    assert len(_assets(dest_db)) == 3
    assert len(os.listdir(tmp_path / "media")) == 3


def test_reimport_with_changed_bytes_overwrites(tmp_path):
    """The row's content is authoritative: a re-import carrying different
    bytes for the same unique_id replaces the stored file."""
    a = tmp_path / "a"
    _write_bundle(a, [_asset_record("file://media/scan.png")], {"scan.png": b"old"})
    b = tmp_path / "b"
    _write_bundle(b, [_asset_record("file://media/scan.png")], {"scan.png": b"new"})
    dest_db = str(tmp_path / "dest.db")
    assert import_arkiv(str(a), dest_db)["success"]
    assert import_arkiv(str(b), dest_db, merge=True)["success"]
    (row,) = _assets(dest_db)
    assert resolve_asset_path(dest_db, row["file_path"]).read_bytes() == b"new"


# ---------------------------------------------------------------------------
# Hand-written bundles: base64, legacy rows, refusals
# ---------------------------------------------------------------------------


def test_base64_embedded_asset(tmp_path):
    rec = _asset_record("health-memex:source_assets/1")
    rec["content"] = base64.b64encode(b"inline bytes").decode()
    bundle = tmp_path / "b"
    _write_bundle(bundle, [rec])
    dest_db = str(tmp_path / "dest.db")
    result = import_arkiv(str(bundle), dest_db)
    assert result["success"], result["errors"]
    (row,) = _assets(dest_db)
    assert row["unique_id"] == UID_A
    assert row["file_path"] == f"media/{UID_A}.png"
    assert resolve_asset_path(dest_db, row["file_path"]).read_bytes() == b"inline bytes"
    # Nothing written into the bundle.
    assert not (bundle / "media").exists()


def test_invalid_unique_id_rejected(tmp_path):
    bundle = tmp_path / "b"
    _write_bundle(
        bundle,
        [_asset_record("file://media/scan.png", uid="../../../etc/x")],
        {"scan.png": b"x"},
    )
    dest_db = str(tmp_path / "dest.db")
    result = import_arkiv(str(bundle), dest_db)
    assert result["counts"]["source_assets"] == 0
    assert any("unique_id" in e for e in result["errors"])
    assert _assets(dest_db) == []
    assert not (tmp_path / "etc").exists()


def test_legacy_record_without_unique_id_gets_stable_id(tmp_path):
    """Pre-durable-ID bundles carry no unique_id: one is minted from the
    natural key over the bundle-relative path, so re-import is idempotent."""
    bundle = tmp_path / "b"
    _write_bundle(bundle, [_asset_record("file://media/scan.png", uid=None)], {"scan.png": b"x"})
    dest_db = str(tmp_path / "dest.db")
    assert import_arkiv(str(bundle), dest_db)["success"]
    (row,) = _assets(dest_db)
    assert row["file_path"] == f"media/{row['unique_id']}.png"
    assert import_arkiv(str(bundle), dest_db, merge=True)["success"]
    (again,) = _assets(dest_db)
    assert again["unique_id"] == row["unique_id"]


def test_media_traversal_refused(tmp_path):
    (tmp_path / "secret.png").write_bytes(b"secret")
    bundle = tmp_path / "b"
    _write_bundle(bundle, [_asset_record("file://media/../../secret.png")], {"ok.png": b"ok"})
    dest_db = str(tmp_path / "dest" / "dest.db")
    result = import_arkiv(str(bundle), dest_db)
    assert result["counts"]["source_assets"] == 0
    assert result["errors"]
    assert not (tmp_path / "dest" / "media").exists() or not os.listdir(tmp_path / "dest" / "media")


def test_media_symlink_in_bundle_refused(tmp_path):
    (tmp_path / "secret").write_bytes(b"secret")
    bundle = tmp_path / "b"
    _write_bundle(bundle, [_asset_record("file://media/scan.png")], {"ok.png": b"ok"})
    (bundle / "media" / "scan.png").symlink_to(tmp_path / "secret")
    dest_db = str(tmp_path / "dest" / "dest.db")
    result = import_arkiv(str(bundle), dest_db)
    assert result["counts"]["source_assets"] == 0
    assert result["errors"]


def test_symlinked_target_media_dir_refused(tmp_path):
    bundle = tmp_path / "b"
    _write_bundle(bundle, [_asset_record("file://media/scan.png")], {"scan.png": b"x"})
    (tmp_path / "dest").mkdir()
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "dest" / "media").symlink_to(tmp_path / "elsewhere")
    result = import_arkiv(str(bundle), str(tmp_path / "dest" / "dest.db"))
    assert result["counts"]["source_assets"] == 0
    assert result["errors"]
    assert os.listdir(tmp_path / "elsewhere") == []


def test_record_without_media_or_content_reported(tmp_path):
    bundle = tmp_path / "b"
    _write_bundle(bundle, [_asset_record("file://media/missing.png")], {"other.png": b"x"})
    dest_db = str(tmp_path / "dest.db")
    result = import_arkiv(str(bundle), dest_db)
    assert result["success"]
    assert result["counts"]["source_assets"] == 0
    assert any("missing.png" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# :memory: and explicit media_dir
# ---------------------------------------------------------------------------


def test_memory_db_with_assets_refused(tmp_path):
    bundle = tmp_path / "b"
    _write_bundle(bundle, [_asset_record("file://media/scan.png")], {"scan.png": b"x"})
    result = import_arkiv(str(bundle), ":memory:")
    assert result["success"] is False
    assert any("media_dir" in e for e in result["errors"])


def test_media_root_memory_requires_explicit_dir(tmp_path):
    with pytest.raises(MediaStoreError, match="media_dir"):
        media_root(":memory:")
    assert media_root(":memory:", str(tmp_path / "m")) == tmp_path / "m"
    assert media_root(str(tmp_path / "x" / "h.db")) == tmp_path / "x" / "media"


def test_explicit_media_dir_outside_db_dir_stored_absolute(tmp_path):
    bundle = tmp_path / "b"
    _write_bundle(bundle, [_asset_record("file://media/scan.png")], {"scan.png": b"x"})
    media = tmp_path / "shared_media"
    dest_db = str(tmp_path / "db" / "dest.db")
    assert import_arkiv(str(bundle), dest_db, media_dir=str(media))["success"]
    (row,) = _assets(dest_db)
    assert row["file_path"] == str((media / f"{UID_A}.png").resolve())
    assert resolve_asset_path(dest_db, row["file_path"]).read_bytes() == b"x"


# ---------------------------------------------------------------------------
# Readers route through the resolver
# ---------------------------------------------------------------------------


def test_spa_image_loader_resolves_relative_paths(tmp_path):
    from health_memex.spa.export import _load_images_json

    bundle = tmp_path / "b"
    _write_bundle(bundle, [_asset_record("file://media/scan.png")], {"scan.png": b"\x89PNG"})
    dest_db = str(tmp_path / "dest.db")
    assert import_arkiv(str(bundle), dest_db)["success"]
    images = json.loads(_load_images_json(dest_db))
    assert list(images.values()) == [
        "data:image/png;base64," + base64.b64encode(b"\x89PNG").decode()
    ]


def test_export_resolves_relative_path_from_other_cwd(tmp_path, monkeypatch):
    bundle = tmp_path / "b"
    _write_bundle(bundle, [_asset_record("file://media/scan.png")], {"scan.png": b"bytes"})
    dest_db = str(tmp_path / "dest.db")
    assert import_arkiv(str(bundle), dest_db)["success"]
    elsewhere = tmp_path / "cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    out = tmp_path / "out"
    with HealthMemexDB(dest_db) as db:
        export_arkiv(db, str(out))
    assert (out / "media" / "scan.png").read_bytes() == b"bytes"


def test_cli_import_media_dir_and_warnings(tmp_path):
    import subprocess
    import sys

    bundle = tmp_path / "b"
    _write_bundle(
        bundle,
        [
            _asset_record("file://media/scan.png"),
            _asset_record("file://media/gone.png", uid="fedcba9876543210", name="gone.png"),
        ],
        {"scan.png": b"x"},
    )
    media = tmp_path / "m"
    db_path = str(tmp_path / "db" / "h.db")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "health_memex",
            "import",
            str(bundle),
            "--db",
            db_path,
            "--media-dir",
            str(media),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (media / f"{UID_A}.png").read_bytes() == b"x"
    assert "Warnings:" in result.stdout and "gone.png" in result.stdout


def test_invalid_base64_reported(tmp_path):
    rec = _asset_record("health-memex:source_assets/1")
    rec["content"] = "not base64!!"
    bundle = tmp_path / "b"
    _write_bundle(bundle, [rec])
    result = import_arkiv(str(bundle), str(tmp_path / "dest.db"))
    assert result["counts"]["source_assets"] == 0
    assert any("base64" in e for e in result["errors"])
