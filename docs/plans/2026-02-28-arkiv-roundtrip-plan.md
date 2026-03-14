# Arkiv Round-Trip Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make arkiv the primary backup/restore format by migrating export to the arkiv spec (README.md + schema.yaml), adding source asset export with optional base64 embedding, building `import_arkiv.py`, and removing the JSON export/import path.

**Architecture:** The export side replaces `manifest.json` with spec-compliant `README.md` (YAML frontmatter) + `schema.yaml`, and adds source asset export (files to `media/` or base64 inline via `--embed`). The import side reverses `_row_to_record()` to reconstruct DB rows, uses topological sort for FK-ordered insertion with ID remapping, unfolds tags from metadata, and restores source asset files. The JSON export/import module (`export_full.py`) is deleted entirely.

**Tech Stack:** Python 3.11+, `pyyaml`, `sqlite3`, `base64`, `pytest`

**Design Doc:** `docs/plans/2026-02-28-arkiv-roundtrip-design.md`

---

## Task 1: Move topological sort helpers from export_full.py to db.py

The JSON importer has `_discover_tables`, `_discover_fk_graph`, and `_topological_sort` which we need for arkiv import. Move them to `db.py` before deleting `export_full.py` so the import module can use them.

**Files:**
- Modify: `src/chartfold/db.py` (add 3 functions at module level, after the `_UNIQUE_KEYS` dict)
- Modify: `src/chartfold/export_full.py` (import from db.py instead of defining locally)
- Modify: `tests/test_export_full.py` (update imports)
- Test: `tests/test_export_full.py` (existing tests still pass)

**Step 1: Write test to verify imports from new location**

Add to `tests/test_export_full.py` near the top imports:

```python
# Verify the helpers are accessible from db.py (future-proofing for after export_full deletion)
from chartfold.db import _discover_fk_graph, _discover_tables, _topological_sort
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_export_full.py -v -x 2>&1 | head -30`
Expected: ImportError — `_discover_tables` not in `chartfold.db`

**Step 3: Move the three functions to db.py**

Add these three functions to `src/chartfold/db.py` after the `_UNIQUE_KEYS` dict (around line 84), before `class TableStats`:

```python
# ---------------------------------------------------------------------------
# Schema introspection helpers (used by import)
# ---------------------------------------------------------------------------


def _discover_tables(db: ChartfoldDB) -> list[str]:
    """All user tables from sqlite_master, excluding sqlite_ internals."""
    rows = db.query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    )
    return [r["name"] for r in rows]


def _discover_fk_graph(
    db: ChartfoldDB, tables: list[str]
) -> dict[str, list[tuple[str, str, str]]]:
    """FK graph via PRAGMA foreign_key_list().

    Returns {child_table: [(fk_col, parent_table, parent_col), ...]}.
    Only includes relationships where both tables are in the provided list.
    """
    table_set = set(tables)
    graph: dict[str, list[tuple[str, str, str]]] = {}
    for table in tables:
        fks = db.query(f"PRAGMA foreign_key_list({table})")
        for fk in fks:
            parent = fk["table"]
            if parent in table_set:
                graph.setdefault(table, []).append((fk["from"], parent, fk["to"]))
    return graph


def _topological_sort(
    tables: list[str], fk_graph: dict[str, list[tuple[str, str, str]]]
) -> list[str]:
    """Sort tables so parents come before children (Kahn's algorithm)."""
    in_degree: dict[str, int] = dict.fromkeys(tables, 0)
    children: dict[str, list[str]] = {t: [] for t in tables}

    for child, fk_list in fk_graph.items():
        parents = {fk[1] for fk in fk_list}
        for parent in parents:
            if parent != child and parent in in_degree:
                in_degree[child] = in_degree.get(child, 0) + 1
                children.setdefault(parent, []).append(child)

    queue = [t for t in tables if in_degree[t] == 0]
    result = []

    while queue:
        queue.sort()
        node = queue.pop(0)
        result.append(node)
        for child in children.get(node, []):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    remaining = [t for t in tables if t not in set(result)]
    remaining.sort()
    result.extend(remaining)
    return result
```

Note: `_discover_tables` and `_discover_fk_graph` reference `ChartfoldDB` — they'll be module-level functions that accept a `ChartfoldDB` instance. Place them after the class definition, or use a forward reference. The simplest approach: place them **after** the `ChartfoldDB` class definition at the end of the file.

**Step 4: Update export_full.py to import from db.py**

In `src/chartfold/export_full.py`, replace the local definitions of `_discover_tables`, `_discover_fk_graph`, and `_topological_sort` with imports:

```python
from chartfold.db import (
    ChartfoldDB,
    _discover_fk_graph,
    _discover_tables,
    _topological_sort,
)
```

Delete the function bodies from `export_full.py` (lines 28-92).

**Step 5: Run all tests**

Run: `python -m pytest tests/test_export_full.py tests/test_export_arkiv.py -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/chartfold/db.py src/chartfold/export_full.py tests/test_export_full.py
git commit -m "refactor: move topo sort helpers from export_full to db.py"
```

---

## Task 2: Migrate export archive format to README.md + schema.yaml

Replace `manifest.json` output with arkiv spec-compliant `README.md` (YAML frontmatter listing collections) and `schema.yaml` (per-collection metadata schema).

**Files:**
- Modify: `src/chartfold/export_arkiv.py:359-414` (rewrite `export_arkiv()` to write README.md + schema.yaml)
- Modify: `tests/test_export_arkiv.py` (update integration tests)

**Step 1: Write failing tests for new archive format**

Replace the integration tests in `tests/test_export_arkiv.py::TestExportArkiv` to expect `README.md` + `schema.yaml` instead of `manifest.json`:

```python
class TestExportArkiv:
    """Integration tests for the main export_arkiv function."""

    def test_export_arkiv_creates_readme(self, tmp_path):
        """Export creates README.md with YAML frontmatter listing collections."""
        import yaml
        from chartfold.export_arkiv import export_arkiv

        db_path = str(tmp_path / "test.db")
        db = ChartfoldDB(db_path)
        db.init_schema()
        records = UnifiedRecords(
            source="test_source",
            lab_results=[
                LabResult(
                    source="test_source", test_name="CEA",
                    value="5.8", value_numeric=5.8, unit="ng/mL",
                    result_date="2025-01-15",
                ),
            ],
        )
        db.load_source(records)

        output_dir = str(tmp_path / "arkiv-out")
        export_arkiv(db, output_dir)
        db.close()

        readme_path = os.path.join(output_dir, "README.md")
        assert os.path.exists(readme_path)
        assert not os.path.exists(os.path.join(output_dir, "manifest.json"))

        # Parse YAML frontmatter
        with open(readme_path) as f:
            content = f.read()

        assert content.startswith("---\n")
        parts = content.split("---\n", 2)
        frontmatter = yaml.safe_load(parts[1])

        assert frontmatter["name"] == "Chartfold clinical data export"
        assert "datetime" in frontmatter
        assert "generator" in frontmatter
        assert "chartfold" in frontmatter["generator"]

        # Contents list
        contents = frontmatter["contents"]
        paths = {c["path"] for c in contents}
        assert "lab_results.jsonl" in paths

        # Each content entry has path and description
        for entry in contents:
            assert "path" in entry
            assert "description" in entry

    def test_export_arkiv_creates_schema_yaml(self, tmp_path):
        """Export creates schema.yaml with per-collection metadata schemas."""
        import yaml
        from chartfold.export_arkiv import export_arkiv

        db_path = str(tmp_path / "test.db")
        db = ChartfoldDB(db_path)
        db.init_schema()
        records = UnifiedRecords(
            source="test_source",
            lab_results=[
                LabResult(
                    source="test_source", test_name="CEA",
                    value="5.8", value_numeric=5.8, unit="ng/mL",
                    result_date="2025-01-15",
                ),
            ],
        )
        db.load_source(records)

        output_dir = str(tmp_path / "arkiv-out")
        export_arkiv(db, output_dir)
        db.close()

        schema_path = os.path.join(output_dir, "schema.yaml")
        assert os.path.exists(schema_path)

        with open(schema_path) as f:
            schema = yaml.safe_load(f)

        assert "lab_results" in schema
        assert "record_count" in schema["lab_results"]
        assert "metadata_keys" in schema["lab_results"]
        assert "test_name" in schema["lab_results"]["metadata_keys"]

    def test_export_arkiv_readme_markdown_body(self, tmp_path):
        """README.md has a markdown body after the YAML frontmatter."""
        from chartfold.export_arkiv import export_arkiv

        db_path = str(tmp_path / "test.db")
        db = ChartfoldDB(db_path)
        db.init_schema()

        output_dir = str(tmp_path / "arkiv-out")
        export_arkiv(db, output_dir)
        db.close()

        with open(os.path.join(output_dir, "README.md")) as f:
            content = f.read()

        # Should have markdown heading after frontmatter
        assert "# Chartfold Clinical Data Export" in content
```

Keep the existing `test_export_arkiv_exclude_notes`, `test_export_arkiv_note_tags_folded`, `test_export_arkiv_empty_db` tests but update them to check `README.md` instead of `manifest.json`.

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_export_arkiv.py::TestExportArkiv -v -x 2>&1 | head -20`
Expected: FAIL — `manifest.json` still created, `README.md` missing

**Step 3: Implement README.md + schema.yaml output**

In `src/chartfold/export_arkiv.py`, add `import yaml` at the top and rewrite the `export_arkiv()` function. Replace the manifest JSON block (lines 404-413) with:

```python
import yaml

def export_arkiv(
    db: ChartfoldDB,
    output_dir: str,
    include_notes: bool = True,
    embed: bool = False,
) -> str:
    """Export database to arkiv format (JSONL + README.md + schema.yaml).

    Args:
        db: Database connection.
        output_dir: Directory to write output files.
        include_notes: Include personal notes and analyses.
        embed: If True, base64-encode source asset content inline.

    Returns the output directory path.
    """
    os.makedirs(output_dir, exist_ok=True)

    tables_to_export = [
        t for t in _TIMESTAMP_FIELDS
        if t not in _EXCLUDED_TABLES
        and (include_notes or t not in _NOTE_TABLES)
    ]

    contents = []  # for README.md frontmatter
    schema_data = {}  # for schema.yaml

    for table in tables_to_export:
        ts_field = _TIMESTAMP_FIELDS[table]

        if table in _TAG_CONFIG:
            tag_table, tag_fk = _TAG_CONFIG[table]
            records = _export_table_with_tags(
                db, table, tag_table, tag_fk, ts_field, output_dir
            )
        else:
            records = _export_table(db, table, ts_field, output_dir)

        if records is None:
            continue

        schema = _build_schema(records)

        contents.append({
            "path": f"{table}.jsonl",
            "description": _COLLECTION_DESCRIPTIONS.get(table, table),
        })

        schema_data[table] = {
            "record_count": len(records),
            **schema,
        }

    # Write README.md with YAML frontmatter
    frontmatter = {
        "name": "Chartfold clinical data export",
        "description": "Clinical records from Epic, MEDITECH, and athenahealth",
        "datetime": date.today().isoformat(),
        "generator": f"chartfold v{_get_version()}",
        "contents": contents,
    }

    readme_path = os.path.join(output_dir, "README.md")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("---\n")
        yaml.dump(frontmatter, f, default_flow_style=False, sort_keys=False)
        f.write("---\n\n")
        f.write(f"# Chartfold Clinical Data Export\n\n")
        f.write(f"Exported from chartfold database on {date.today().isoformat()}.\n")

    # Write schema.yaml
    schema_path = os.path.join(output_dir, "schema.yaml")
    with open(schema_path, "w", encoding="utf-8") as f:
        yaml.dump(schema_data, f, default_flow_style=False, sort_keys=False)

    return output_dir


def _get_version() -> str:
    """Get chartfold version string."""
    try:
        from importlib.metadata import version
        return version("chartfold")
    except Exception:
        return "dev"
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_export_arkiv.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/chartfold/export_arkiv.py tests/test_export_arkiv.py
git commit -m "feat: migrate arkiv export to README.md + schema.yaml (arkiv spec)"
```

---

## Task 3: Add source asset export with `--embed` flag

Export `source_assets` table records as proper arkiv records with their actual MIME types. Default mode copies files to `media/` directory. `--embed` mode base64-encodes file content inline.

**Files:**
- Modify: `src/chartfold/export_arkiv.py` (add `_export_source_assets()`, remove `source_assets` from `_EXCLUDED_TABLES`, wire into `export_arkiv()`)
- Test: `tests/test_export_arkiv.py` (add source asset export tests)

**Step 1: Write failing tests**

Add these tests to `tests/test_export_arkiv.py`:

```python
import base64


@pytest.fixture
def db_with_assets(tmp_db, tmp_path):
    """DB with source assets that reference real files."""
    # Create fake source files
    media_src = tmp_path / "source_files"
    media_src.mkdir()
    (media_src / "scan.png").write_bytes(b"\x89PNG fake image data")
    (media_src / "report.pdf").write_bytes(b"%PDF fake pdf data")

    tmp_db.conn.execute(
        """INSERT INTO source_assets
           (source, asset_type, file_path, file_name, file_size_kb,
            content_type, title, encounter_date, ref_table, ref_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("test_source", "png", str(media_src / "scan.png"), "scan.png",
         1, "image/png", "CT Abdomen", "2025-01-15", "imaging_reports", 7),
    )
    tmp_db.conn.execute(
        """INSERT INTO source_assets
           (source, asset_type, file_path, file_name, file_size_kb,
            content_type, title)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("test_source", "pdf", str(media_src / "report.pdf"), "report.pdf",
         2, "application/pdf", "Lab Report"),
    )
    tmp_db.conn.commit()
    return tmp_db


class TestSourceAssetExport:
    def test_source_assets_exported_to_media(self, db_with_assets, tmp_path):
        """Default mode copies files to media/ and uses file:// URIs."""
        from chartfold.export_arkiv import export_arkiv

        output_dir = str(tmp_path / "arkiv-out")
        export_arkiv(db_with_assets, output_dir)

        # JSONL file exists
        jsonl_path = os.path.join(output_dir, "source_assets.jsonl")
        assert os.path.exists(jsonl_path)

        with open(jsonl_path) as f:
            records = [json.loads(line) for line in f]

        assert len(records) == 2

        # Check record structure
        png_rec = next(r for r in records if "scan.png" in r.get("uri", ""))
        assert png_rec["mimetype"] == "image/png"
        assert png_rec["uri"] == "file://media/scan.png"
        assert "content" not in png_rec
        assert png_rec["metadata"]["title"] == "CT Abdomen"
        assert png_rec["metadata"]["ref_table"] == "imaging_reports"

        # Media files copied
        assert os.path.exists(os.path.join(output_dir, "media", "scan.png"))
        assert os.path.exists(os.path.join(output_dir, "media", "report.pdf"))

    def test_source_assets_embedded_base64(self, db_with_assets, tmp_path):
        """--embed mode inlines base64 content."""
        from chartfold.export_arkiv import export_arkiv

        output_dir = str(tmp_path / "arkiv-out")
        export_arkiv(db_with_assets, output_dir, embed=True)

        jsonl_path = os.path.join(output_dir, "source_assets.jsonl")
        with open(jsonl_path) as f:
            records = [json.loads(line) for line in f]

        png_rec = next(r for r in records if "scan.png" in r.get("uri", ""))
        assert "content" in png_rec
        decoded = base64.b64decode(png_rec["content"])
        assert decoded == b"\x89PNG fake image data"

        # Media dir should still exist with files (URI still references them)
        assert os.path.exists(os.path.join(output_dir, "media", "scan.png"))

    def test_source_assets_missing_file_skipped(self, tmp_db, tmp_path):
        """Assets whose source files don't exist are skipped gracefully."""
        from chartfold.export_arkiv import export_arkiv

        tmp_db.conn.execute(
            """INSERT INTO source_assets
               (source, asset_type, file_path, file_name, file_size_kb, content_type)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("test", "png", "/nonexistent/file.png", "file.png", 1, "image/png"),
        )
        tmp_db.conn.commit()

        output_dir = str(tmp_path / "arkiv-out")
        export_arkiv(tmp_db, output_dir)

        jsonl_path = os.path.join(output_dir, "source_assets.jsonl")
        if os.path.exists(jsonl_path):
            with open(jsonl_path) as f:
                records = [json.loads(line) for line in f]
            # Record still exported but no media file
            assert len(records) == 1
            assert not os.path.exists(os.path.join(output_dir, "media", "file.png"))

    def test_source_assets_in_readme_contents(self, db_with_assets, tmp_path):
        """source_assets.jsonl listed in README.md frontmatter contents."""
        import yaml
        from chartfold.export_arkiv import export_arkiv

        output_dir = str(tmp_path / "arkiv-out")
        export_arkiv(db_with_assets, output_dir)

        with open(os.path.join(output_dir, "README.md")) as f:
            content = f.read()
        parts = content.split("---\n", 2)
        frontmatter = yaml.safe_load(parts[1])

        paths = {c["path"] for c in frontmatter["contents"]}
        assert "source_assets.jsonl" in paths
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_export_arkiv.py::TestSourceAssetExport -v -x 2>&1 | head -20`
Expected: FAIL — source_assets still in `_EXCLUDED_TABLES`

**Step 3: Implement source asset export**

In `src/chartfold/export_arkiv.py`:

1. Remove `"source_assets"` from `_EXCLUDED_TABLES`
2. Add `_TIMESTAMP_FIELDS["source_assets"] = "encounter_date"` (it's not there currently)
3. Add `_COLLECTION_DESCRIPTIONS["source_assets"] = "Source documents (PDFs, images) from EHR exports"`
4. Add `_export_source_assets()` function:

```python
import base64
import shutil


def _export_source_assets(
    db: ChartfoldDB,
    output_dir: str,
    embed: bool = False,
) -> list[dict[str, Any]] | None:
    """Export source_assets as arkiv records with actual MIME types.

    Default mode: copy files to media/ subdirectory, use file://media/ URIs.
    Embed mode: also base64-encode content inline per arkiv spec.
    """
    rows = db.query("SELECT * FROM source_assets")
    if not rows:
        return None

    media_dir = os.path.join(output_dir, "media")
    os.makedirs(media_dir, exist_ok=True)

    records = []
    for row in rows:
        file_name = row["file_name"]
        file_path = row["file_path"]
        mime = row.get("content_type") or f"application/octet-stream"

        record: dict[str, Any] = {
            "mimetype": mime,
            "uri": f"file://media/{file_name}",
        }

        # Timestamp
        ts = row.get("encounter_date")
        if ts:
            record["timestamp"] = ts

        # Copy file to media/ if it exists
        src_path = Path(file_path)
        if src_path.is_file():
            dest = os.path.join(media_dir, file_name)
            shutil.copy2(str(src_path), dest)

            # Embed mode: base64 inline
            if embed:
                with open(str(src_path), "rb") as bf:
                    record["content"] = base64.b64encode(bf.read()).decode("ascii")

        # Build metadata (skip file_path — replaced by URI)
        metadata: dict[str, Any] = {"table": "source_assets"}
        skip_keys = {"id", "file_path", "content_type"}
        for col, val in row.items():
            if col in skip_keys:
                continue
            if val is None or (isinstance(val, str) and val == ""):
                continue
            metadata[col] = val

        # Add ref_id_uri if ref_table and ref_id present
        if row.get("ref_table") and row.get("ref_id"):
            metadata["ref_id_uri"] = f"chartfold:{row['ref_table']}/{row['ref_id']}"

        record["metadata"] = metadata
        records.append(record)

    jsonl_path = os.path.join(output_dir, "source_assets.jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    return records
```

5. In `export_arkiv()`, handle `source_assets` specially before the main loop:

```python
    # Export source assets separately (different record format)
    if "source_assets" not in _EXCLUDED_TABLES:
        asset_records = _export_source_assets(db, output_dir, embed=embed)
        if asset_records is not None:
            schema = _build_schema(asset_records)
            contents.append({
                "path": "source_assets.jsonl",
                "description": _COLLECTION_DESCRIPTIONS.get("source_assets", "Source assets"),
            })
            schema_data["source_assets"] = {
                "record_count": len(asset_records),
                **schema,
            }
```

And exclude `source_assets` from the main table loop (it has its own export path).

**Step 4: Run tests**

Run: `python -m pytest tests/test_export_arkiv.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/chartfold/export_arkiv.py tests/test_export_arkiv.py
git commit -m "feat: add source asset export with --embed base64 option"
```

---

## Task 4: Add `--embed` flag to CLI

Wire the `--embed` flag through the CLI to `export_arkiv()`.

**Files:**
- Modify: `src/chartfold/cli.py:137-146` (add `--embed` arg to arkiv parser)
- Modify: `src/chartfold/cli.py:695-702` (pass `embed=` to `export_arkiv()`)
- Test: `tests/test_export_arkiv.py` (add CLI test for `--embed`)

**Step 1: Write failing CLI test**

Add to `tests/test_export_arkiv.py::TestCLI`:

```python
    def test_cli_export_arkiv_embed(self, tmp_path):
        """CLI: chartfold export arkiv --embed works."""
        import subprocess
        import sys

        db_path = str(tmp_path / "test.db")
        db = ChartfoldDB(db_path)
        db.init_schema()

        # Create a real file for the source asset
        asset_file = tmp_path / "test.png"
        asset_file.write_bytes(b"\x89PNG test data")

        db.conn.execute(
            """INSERT INTO source_assets
               (source, asset_type, file_path, file_name, file_size_kb, content_type)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("test", "png", str(asset_file), "test.png", 1, "image/png"),
        )
        db.conn.commit()
        db.close()

        output_dir = str(tmp_path / "arkiv-out")
        result = subprocess.run(
            [sys.executable, "-m", "chartfold", "export", "arkiv",
             "--db", db_path, "--output", output_dir, "--embed"],
            check=False, capture_output=True, text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        # Verify base64 content is present
        jsonl_path = os.path.join(output_dir, "source_assets.jsonl")
        with open(jsonl_path) as f:
            rec = json.loads(f.readline())
        assert "content" in rec
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_export_arkiv.py::TestCLI::test_cli_export_arkiv_embed -v -x`
Expected: FAIL — `--embed` not recognized

**Step 3: Add --embed to CLI**

In `src/chartfold/cli.py`:

Add after line 146 (the `--exclude-notes` arg for arkiv):
```python
    arkiv_parser.add_argument(
        "--embed", action="store_true",
        help="Base64-encode source asset content inline (larger output, self-contained)"
    )
```

Update the arkiv branch in `_handle_export` (around line 698):
```python
        elif args.export_format == "arkiv":
            from chartfold.export_arkiv import export_arkiv

            path = export_arkiv(
                db,
                output_dir=args.output,
                include_notes=not args.exclude_notes,
                embed=args.embed,
            )
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_export_arkiv.py::TestCLI -v`
Expected: All PASS

**Step 5: Update the existing CLI test**

Update `test_cli_export_arkiv` to check for `README.md` instead of `manifest.json`:

```python
        assert os.path.exists(os.path.join(output_dir, "README.md"))
```

**Step 6: Run full export test suite**

Run: `python -m pytest tests/test_export_arkiv.py -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add src/chartfold/cli.py tests/test_export_arkiv.py
git commit -m "feat: add --embed flag for arkiv export CLI"
```

---

## Task 5: Create import_arkiv.py — core record-to-row logic

Build the import module with `_record_to_row()` (reverse of `_row_to_record()`), validation, and the main import pipeline.

**Files:**
- Create: `src/chartfold/import_arkiv.py`
- Create: `tests/test_import_arkiv.py`

**Step 1: Write failing tests for _record_to_row**

Create `tests/test_import_arkiv.py`:

```python
"""Tests for chartfold arkiv import."""

import json
import os

import pytest
import yaml

from chartfold.db import ChartfoldDB
from chartfold.models import LabResult, UnifiedRecords


class TestRecordToRow:
    """Test reversing arkiv records back to DB rows."""

    def test_basic_lab_record(self):
        from chartfold.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "chartfold:lab_results/42",
            "timestamp": "2025-01-15",
            "metadata": {
                "table": "lab_results",
                "source": "epic_anderson",
                "test_name": "CEA",
                "value": "5.8",
                "value_numeric": 5.8,
                "unit": "ng/mL",
                "ref_range": "0.0-3.0",
                "interpretation": "H",
                "result_date": "2025-01-15",
                "status": "final",
            },
        }

        table, old_id, row = _record_to_row(record)
        assert table == "lab_results"
        assert old_id == 42
        assert row["source"] == "epic_anderson"
        assert row["test_name"] == "CEA"
        assert row["value_numeric"] == 5.8
        assert "table" not in row  # synthetic field stripped

    def test_fk_uri_reversed(self):
        """procedure_uri should be reversed to procedure_id with old ID."""
        from chartfold.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "chartfold:pathology_reports/3",
            "timestamp": "2024-07-03",
            "metadata": {
                "table": "pathology_reports",
                "source": "test_surgical",
                "procedure_uri": "chartfold:procedures/10",
                "report_date": "2024-07-03",
                "specimen": "Right colon",
                "diagnosis": "Adenocarcinoma",
            },
        }

        table, old_id, row = _record_to_row(record)
        assert table == "pathology_reports"
        assert old_id == 3
        assert row["procedure_id"] == 10
        assert "procedure_uri" not in row

    def test_tags_extracted(self):
        """Tags in metadata should be extracted and returned separately."""
        from chartfold.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "chartfold:notes/1",
            "metadata": {
                "table": "notes",
                "title": "CEA Trend",
                "content": "CEA trending up",
                "created_at": "2025-01-15T10:00:00",
                "updated_at": "2025-01-15T10:00:00",
                "tags": ["cea", "oncology"],
            },
        }

        table, old_id, row = _record_to_row(record)
        assert table == "notes"
        assert "tags" not in row
        assert row["_tags"] == ["cea", "oncology"]

    def test_no_timestamp_field(self):
        """Records without timestamp should work fine."""
        from chartfold.import_arkiv import _record_to_row

        record = {
            "mimetype": "application/json",
            "uri": "chartfold:family_history/7",
            "metadata": {
                "table": "family_history",
                "source": "test",
                "relation": "Father",
                "condition": "Cancer",
            },
        }

        table, old_id, row = _record_to_row(record)
        assert table == "family_history"
        assert row["relation"] == "Father"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_import_arkiv.py::TestRecordToRow -v -x 2>&1 | head -15`
Expected: ModuleNotFoundError — `chartfold.import_arkiv` doesn't exist

**Step 3: Implement _record_to_row**

Create `src/chartfold/import_arkiv.py`:

```python
"""Import arkiv archives to recreate a chartfold database.

Reverses the export process: parses JSONL records, reconstructs DB rows,
resolves FK URIs to new autoincrement IDs, unfolds tags, and restores
source asset files.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from chartfold.db import (
    ChartfoldDB,
    _discover_fk_graph,
    _discover_tables,
    _topological_sort,
)
from chartfold.export_arkiv import _FK_FIELDS, _TAG_CONFIG

# Reverse FK mapping: uri_key -> (fk_col, parent_table)
_REVERSE_FK: dict[str, tuple[str, str]] = {
    uri_key: (fk_col, parent_table)
    for fk_col, (parent_table, uri_key) in _FK_FIELDS.items()
}

# Synthetic metadata keys to strip (not DB columns)
_SYNTHETIC_KEYS = {"table"}

# URI pattern: "chartfold:{table}/{id}"
_URI_PATTERN = re.compile(r"^chartfold:(\w+)/(\d+)$")


def _record_to_row(
    record: dict[str, Any],
) -> tuple[str, int | None, dict[str, Any]]:
    """Convert an arkiv record back to a DB row dict.

    Returns:
        (table_name, old_id_or_None, row_dict)
        row_dict may contain "_tags" key if tags were present in metadata.
    """
    metadata = dict(record.get("metadata", {}))
    table = metadata.pop("table", "")

    # Parse old ID from URI
    old_id: int | None = None
    uri = record.get("uri", "")
    m = _URI_PATTERN.match(uri)
    if m:
        old_id = int(m.group(2))

    # Reverse FK URIs: procedure_uri -> procedure_id
    for uri_key, (fk_col, _parent_table) in _REVERSE_FK.items():
        if uri_key in metadata:
            fk_uri = metadata.pop(uri_key)
            fk_match = _URI_PATTERN.match(fk_uri)
            if fk_match:
                metadata[fk_col] = int(fk_match.group(2))

    # Also reverse ref_id_uri for source_assets
    ref_id_uri = metadata.pop("ref_id_uri", None)
    if ref_id_uri:
        ref_match = _URI_PATTERN.match(ref_id_uri)
        if ref_match:
            metadata["ref_table"] = ref_match.group(1)
            metadata["ref_id"] = int(ref_match.group(2))

    # Extract tags (stored separately in tag tables)
    tags = metadata.pop("tags", None)

    # Remove any remaining synthetic keys
    for key in _SYNTHETIC_KEYS:
        metadata.pop(key, None)

    # Build row dict
    row = metadata
    if tags is not None:
        row["_tags"] = tags

    return table, old_id, row
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_import_arkiv.py::TestRecordToRow -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/chartfold/import_arkiv.py tests/test_import_arkiv.py
git commit -m "feat: add import_arkiv._record_to_row (reverse of _row_to_record)"
```

---

## Task 6: Implement validate_arkiv and import_arkiv functions

Add the validation and main import pipeline functions.

**Files:**
- Modify: `src/chartfold/import_arkiv.py` (add `validate_arkiv()` and `import_arkiv()`)
- Modify: `tests/test_import_arkiv.py` (add validation and import tests)

**Step 1: Write failing tests for validate_arkiv**

Add to `tests/test_import_arkiv.py`:

```python
class TestValidateArkiv:
    def test_valid_archive(self, tmp_path):
        """Valid archive passes validation."""
        from chartfold.import_arkiv import validate_arkiv

        _create_minimal_archive(tmp_path)

        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is True
        assert result["errors"] == []
        assert "lab_results" in result["summary"]

    def test_missing_readme(self, tmp_path):
        """Missing README.md fails validation."""
        from chartfold.import_arkiv import validate_arkiv

        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is False
        assert any("README.md" in e for e in result["errors"])

    def test_invalid_yaml_frontmatter(self, tmp_path):
        """Bad YAML frontmatter fails validation."""
        from chartfold.import_arkiv import validate_arkiv

        (tmp_path / "README.md").write_text("---\ninvalid: [unclosed\n---\n")
        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is False

    def test_invalid_jsonl(self, tmp_path):
        """Invalid JSONL line fails validation."""
        from chartfold.import_arkiv import validate_arkiv

        _create_minimal_archive(tmp_path)
        # Corrupt the JSONL
        (tmp_path / "lab_results.jsonl").write_text("not json\n")

        result = validate_arkiv(str(tmp_path))
        assert result["valid"] is False
        assert any("JSON" in e for e in result["errors"])


def _create_minimal_archive(archive_dir: Path) -> None:
    """Create a minimal valid arkiv archive for testing."""
    contents = [{"path": "lab_results.jsonl", "description": "Labs"}]
    frontmatter = {
        "name": "Test export",
        "datetime": "2026-02-28",
        "generator": "test",
        "contents": contents,
    }

    readme = "---\n" + yaml.dump(frontmatter, sort_keys=False) + "---\n\n# Test\n"
    (archive_dir / "README.md").write_text(readme)

    schema = {"lab_results": {"record_count": 1, "metadata_keys": {}}}
    (archive_dir / "schema.yaml").write_text(yaml.dump(schema))

    record = {
        "mimetype": "application/json",
        "uri": "chartfold:lab_results/1",
        "timestamp": "2025-01-15",
        "metadata": {
            "table": "lab_results",
            "source": "test",
            "test_name": "CEA",
            "value": "5.8",
            "value_numeric": 5.8,
            "result_date": "2025-01-15",
        },
    }
    (archive_dir / "lab_results.jsonl").write_text(json.dumps(record) + "\n")
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_import_arkiv.py::TestValidateArkiv -v -x`
Expected: FAIL — `validate_arkiv` doesn't exist

**Step 3: Implement validate_arkiv**

Add to `src/chartfold/import_arkiv.py`:

```python
def validate_arkiv(input_dir: str) -> dict:
    """Validate an arkiv archive without importing.

    Checks: README.md exists, frontmatter parses, JSONL files exist
    and contain valid JSON, schema.yaml parses.

    Returns dict with valid, errors, and summary (table -> record count).
    """
    errors: list[str] = []
    summary: dict[str, int] = {}
    input_path = Path(input_dir)

    # Check README.md
    readme_path = input_path / "README.md"
    if not readme_path.is_file():
        errors.append("README.md not found")
        return {"valid": False, "errors": errors, "summary": {}}

    # Parse YAML frontmatter
    try:
        frontmatter = _parse_readme_frontmatter(readme_path)
    except Exception as e:
        errors.append(f"Failed to parse README.md frontmatter: {e}")
        return {"valid": False, "errors": errors, "summary": {}}

    # Check schema.yaml (optional but validate if present)
    schema_path = input_path / "schema.yaml"
    if schema_path.is_file():
        try:
            with open(schema_path) as f:
                yaml.safe_load(f)
        except Exception as e:
            errors.append(f"Failed to parse schema.yaml: {e}")

    # Check JSONL files listed in contents
    contents = frontmatter.get("contents", [])
    for entry in contents:
        jsonl_file = entry.get("path", "")
        jsonl_path = input_path / jsonl_file
        if not jsonl_path.is_file():
            errors.append(f"JSONL file not found: {jsonl_file}")
            continue

        # Validate each line is valid JSON
        count = 0
        with open(jsonl_path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    json.loads(line)
                    count += 1
                except json.JSONDecodeError as e:
                    errors.append(
                        f"{jsonl_file} line {line_num}: invalid JSON: {e}"
                    )

        table = jsonl_file.replace(".jsonl", "")
        summary[table] = count

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "summary": summary,
    }


def _parse_readme_frontmatter(readme_path: Path) -> dict:
    """Parse YAML frontmatter from a README.md file."""
    with open(readme_path, encoding="utf-8") as f:
        content = f.read()

    if not content.startswith("---\n"):
        raise ValueError("README.md does not start with YAML frontmatter (---)")

    parts = content.split("---\n", 2)
    if len(parts) < 3:
        raise ValueError("README.md frontmatter not properly terminated (---)")

    return yaml.safe_load(parts[1])
```

**Step 4: Run validation tests**

Run: `python -m pytest tests/test_import_arkiv.py::TestValidateArkiv -v`
Expected: All PASS

**Step 5: Write failing tests for import_arkiv**

Add to `tests/test_import_arkiv.py`:

```python
class TestImportArkiv:
    def test_import_creates_database(self, tmp_path):
        """Import creates a new database from arkiv archive."""
        from chartfold.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)

        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path)

        assert result["success"] is True
        assert (tmp_path / "imported.db").exists()

        with ChartfoldDB(db_path) as db:
            labs = db.query("SELECT * FROM lab_results")
            assert len(labs) == 1
            assert labs[0]["test_name"] == "CEA"
            assert labs[0]["value_numeric"] == 5.8

    def test_import_validate_only(self, tmp_path):
        """validate_only=True checks without creating DB."""
        from chartfold.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)

        db_path = str(tmp_path / "imported.db")
        result = import_arkiv(str(archive_dir), db_path, validate_only=True)

        assert result["success"] is True
        assert not (tmp_path / "imported.db").exists()

    def test_import_refuses_overwrite(self, tmp_path):
        """Import refuses to overwrite existing DB without --overwrite."""
        from chartfold.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)

        db_path = str(tmp_path / "existing.db")
        # Create existing DB
        with ChartfoldDB(db_path) as db:
            db.init_schema()

        result = import_arkiv(str(archive_dir), db_path)
        assert result["success"] is False
        assert "already exists" in result["errors"][0]

    def test_import_overwrites_when_requested(self, tmp_path):
        """Import overwrites existing DB when overwrite=True."""
        from chartfold.import_arkiv import import_arkiv

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)

        db_path = str(tmp_path / "existing.db")
        with ChartfoldDB(db_path) as db:
            db.init_schema()

        result = import_arkiv(str(archive_dir), db_path, overwrite=True)
        assert result["success"] is True

        with ChartfoldDB(db_path) as db:
            labs = db.query("SELECT * FROM lab_results")
            assert len(labs) == 1
```

**Step 6: Implement import_arkiv**

Add to `src/chartfold/import_arkiv.py`:

```python
def import_arkiv(
    input_dir: str,
    db_path: str,
    validate_only: bool = False,
    overwrite: bool = False,
) -> dict:
    """Import an arkiv archive to recreate a chartfold database.

    Returns dict with success, errors, and per-table counts.
    """
    # Validate first
    validation = validate_arkiv(input_dir)
    if not validation["valid"]:
        return {
            "success": False,
            "errors": validation["errors"],
            "counts": {},
        }

    if validate_only:
        return {
            "success": True,
            "errors": [],
            "counts": validation["summary"],
            "validated_only": True,
        }

    # Check existing DB
    db_exists = Path(db_path).exists()
    if db_exists and not overwrite:
        return {
            "success": False,
            "errors": [f"Database already exists: {db_path}. Use --overwrite to replace."],
            "counts": {},
        }

    if db_exists and overwrite:
        Path(db_path).unlink()

    input_path = Path(input_dir)
    frontmatter = _parse_readme_frontmatter(input_path / "README.md")

    # Discover JSONL files from frontmatter
    jsonl_files: dict[str, Path] = {}
    for entry in frontmatter.get("contents", []):
        path_str = entry.get("path", "")
        table = path_str.replace(".jsonl", "")
        jsonl_path = input_path / path_str
        if jsonl_path.is_file():
            jsonl_files[table] = jsonl_path

    # Parse all records from JSONL files
    table_records: dict[str, list[tuple[int | None, dict]]] = {}
    for table, jsonl_path in jsonl_files.items():
        records = []
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)

                # Skip source asset records (handled separately)
                if raw.get("mimetype") != "application/json":
                    continue

                _table, old_id, row = _record_to_row(raw)
                records.append((old_id, row))

        if records:
            table_records[table] = records

    # Handle source_assets separately
    source_asset_records = _parse_source_asset_records(input_path, jsonl_files)

    # Create fresh DB and import
    counts: dict[str, int] = {}
    errors: list[str] = []

    with ChartfoldDB(db_path) as db:
        db.init_schema()

        # Discover import order from schema FK graph
        schema_tables = _discover_tables(db)
        fk_graph = _discover_fk_graph(db, schema_tables)
        import_order = _topological_sort(schema_tables, fk_graph)

        # ID remapping: table -> {old_id: new_id}
        id_map: dict[str, dict[int, int]] = {}

        # Get FK columns per table
        table_fk_map: dict[str, list[tuple[str, str, str]]] = fk_graph

        for table in import_order:
            if table not in table_records:
                counts[table] = 0
                continue

            records = table_records[table]
            id_map[table] = {}
            table_fks = table_fk_map.get(table, [])

            for old_id, row in records:
                # Extract tags before insert
                tags = row.pop("_tags", None)

                # Remap FK columns
                for fk_col, parent_table, _parent_col in table_fks:
                    old_fk = row.get(fk_col)
                    if old_fk is not None:
                        parent_map = id_map.get(parent_table, {})
                        if parent_map:
                            row[fk_col] = parent_map.get(old_fk, old_fk)

                # Filter to only known columns
                known_cols = _get_table_columns(db, table)
                filtered_row = {k: v for k, v in row.items() if k in known_cols}

                cols = list(filtered_row.keys())
                placeholders = ", ".join("?" for _ in cols)
                col_names = ", ".join(cols)

                cursor = db.conn.execute(
                    f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                    list(filtered_row.values()),
                )

                new_id = cursor.lastrowid
                if old_id is not None and new_id is not None:
                    id_map[table][old_id] = new_id

                # Insert tags
                if tags and new_id:
                    tag_config = _TAG_CONFIG.get(table)
                    if tag_config:
                        tag_table, tag_fk_col = tag_config
                        for tag in tags:
                            db.conn.execute(
                                f"INSERT OR IGNORE INTO {tag_table} ({tag_fk_col}, tag) VALUES (?, ?)",
                                (new_id, tag),
                            )

            db.conn.commit()
            counts[table] = len(records)

        # Import source assets
        if source_asset_records:
            sa_count = _import_source_assets(
                db, source_asset_records, input_path, id_map
            )
            counts["source_assets"] = sa_count

    return {
        "success": True,
        "errors": errors,
        "counts": counts,
    }


def _get_table_columns(db: ChartfoldDB, table: str) -> set[str]:
    """Get column names for a table (excluding 'id')."""
    rows = db.query(f"PRAGMA table_info({table})")
    return {r["name"] for r in rows if r["name"] != "id"}


def _parse_source_asset_records(
    input_path: Path,
    jsonl_files: dict[str, Path],
) -> list[dict[str, Any]]:
    """Parse source_assets JSONL records (non-application/json mimetypes)."""
    if "source_assets" not in jsonl_files:
        return []

    records = []
    with open(jsonl_files["source_assets"], encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            records.append(raw)
    return records


def _import_source_assets(
    db: ChartfoldDB,
    records: list[dict[str, Any]],
    input_path: Path,
    id_map: dict[str, dict[int, int]],
) -> int:
    """Import source asset records, restoring files from media/ or base64."""
    count = 0
    for raw in records:
        metadata = dict(raw.get("metadata", {}))
        metadata.pop("table", None)

        # Reverse ref_id_uri
        ref_id_uri = metadata.pop("ref_id_uri", None)
        if ref_id_uri:
            ref_match = _URI_PATTERN.match(ref_id_uri)
            if ref_match:
                ref_table = ref_match.group(1)
                old_ref_id = int(ref_match.group(2))
                metadata["ref_table"] = ref_table
                metadata["ref_id"] = id_map.get(ref_table, {}).get(old_ref_id, old_ref_id)

        # Restore file from base64 content or media/ directory
        file_name = metadata.get("file_name", "")
        uri = raw.get("uri", "")
        content_b64 = raw.get("content")

        file_path = metadata.get("file_path", "")
        if content_b64:
            # Decode base64 and write to file_path
            if file_path:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "wb") as bf:
                    bf.write(base64.b64decode(content_b64))
        elif uri.startswith("file://media/"):
            # Check if file exists in archive's media/ dir
            media_file = input_path / "media" / file_name
            if media_file.is_file() and file_path:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                shutil.copy2(str(media_file), file_path)

        # Insert into source_assets table
        known_cols = _get_table_columns(db, "source_assets")
        filtered = {k: v for k, v in metadata.items() if k in known_cols}

        if filtered:
            cols = list(filtered.keys())
            placeholders = ", ".join("?" for _ in cols)
            col_names = ", ".join(cols)
            db.conn.execute(
                f"INSERT INTO source_assets ({col_names}) VALUES ({placeholders})",
                list(filtered.values()),
            )
            count += 1

    db.conn.commit()
    return count
```

**Step 7: Run all import tests**

Run: `python -m pytest tests/test_import_arkiv.py -v`
Expected: All PASS

**Step 8: Commit**

```bash
git add src/chartfold/import_arkiv.py tests/test_import_arkiv.py
git commit -m "feat: add import_arkiv with validation, FK remapping, tag unfolding"
```

---

## Task 7: Add round-trip tests (export → import → verify)

The critical tests: export a populated database via arkiv, import to a fresh database, verify all data matches.

**Files:**
- Modify: `tests/test_import_arkiv.py` (add round-trip tests)

**Step 1: Write round-trip tests**

Add to `tests/test_import_arkiv.py`:

```python
from chartfold.models import (
    ConditionRecord,
    EncounterRecord,
    FamilyHistoryRecord,
    MedicationRecord,
    PathologyReport,
    ProcedureRecord,
)


class TestRoundTrip:
    """Export → import → verify cycle."""

    def _make_populated_db(self, tmp_path):
        """Create a database with comprehensive test data."""
        db_path = str(tmp_path / "source.db")
        db = ChartfoldDB(db_path)
        db.init_schema()

        records = UnifiedRecords(
            source="test_source",
            lab_results=[
                LabResult(
                    source="test_source", test_name="CEA",
                    value="5.8", value_numeric=5.8, unit="ng/mL",
                    ref_range="0.0-3.0", interpretation="H",
                    result_date="2025-01-15", status="final",
                ),
                LabResult(
                    source="test_source", test_name="Hemoglobin",
                    value="12.5", value_numeric=12.5, unit="g/dL",
                    result_date="2025-01-15",
                ),
            ],
            encounters=[
                EncounterRecord(
                    source="test_source", encounter_date="2025-01-15",
                    encounter_type="office visit", facility="Test Hospital",
                ),
            ],
            medications=[
                MedicationRecord(
                    source="test_source", name="Capecitabine",
                    status="active",
                ),
            ],
            conditions=[
                ConditionRecord(
                    source="test_source", condition_name="Colon cancer",
                    icd10_code="C18.9",
                ),
            ],
            procedures=[
                ProcedureRecord(
                    source="test_source", name="Right hemicolectomy",
                    procedure_date="2024-07-01",
                ),
            ],
            family_history=[
                FamilyHistoryRecord(
                    source="test_source", relation="Father",
                    condition="Heart Disease",
                ),
            ],
        )
        db.load_source(records)

        # Add pathology linked to procedure via FK
        procs = db.query("SELECT id FROM procedures")
        proc_id = procs[0]["id"]
        db.conn.execute(
            "INSERT INTO pathology_reports (source, procedure_id, report_date, specimen, diagnosis) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test_source", proc_id, "2024-07-03", "Right colon", "Adenocarcinoma"),
        )
        db.conn.commit()

        # Add personal notes with tags
        db.save_note(
            title="CEA Trend",
            content="CEA trending up",
            tags=["oncology", "cea"],
        )

        return db

    def test_round_trip_record_counts(self, tmp_path):
        """Record counts preserved through export → import."""
        from chartfold.export_arkiv import export_arkiv
        from chartfold.import_arkiv import import_arkiv

        db = self._make_populated_db(tmp_path)
        original_summary = db.summary()

        # Export
        archive_dir = str(tmp_path / "archive")
        export_arkiv(db, archive_dir)
        db.close()

        # Import
        import_db_path = str(tmp_path / "imported.db")
        result = import_arkiv(archive_dir, import_db_path)
        assert result["success"] is True

        # Compare counts
        with ChartfoldDB(import_db_path) as imported_db:
            imported_summary = imported_db.summary()

        for table in original_summary:
            if table in ("load_log", "documents", "note_tags", "analysis_tags"):
                continue  # Not preserved in round-trip
            assert original_summary[table] == imported_summary.get(table, 0), (
                f"Count mismatch for {table}: "
                f"original={original_summary[table]}, imported={imported_summary.get(table, 0)}"
            )

    def test_round_trip_data_values(self, tmp_path):
        """Data values preserved through export → import."""
        from chartfold.export_arkiv import export_arkiv
        from chartfold.import_arkiv import import_arkiv

        db = self._make_populated_db(tmp_path)

        archive_dir = str(tmp_path / "archive")
        export_arkiv(db, archive_dir)
        db.close()

        import_db_path = str(tmp_path / "imported.db")
        import_arkiv(archive_dir, import_db_path)

        with ChartfoldDB(import_db_path) as idb:
            labs = idb.query("SELECT * FROM lab_results WHERE test_name = 'CEA'")
            assert len(labs) == 1
            assert labs[0]["value_numeric"] == 5.8
            assert labs[0]["interpretation"] == "H"

            meds = idb.query("SELECT * FROM medications WHERE name = 'Capecitabine'")
            assert len(meds) == 1
            assert meds[0]["status"] == "active"

    def test_round_trip_fk_relationships(self, tmp_path):
        """FK relationships preserved through export → import."""
        from chartfold.export_arkiv import export_arkiv
        from chartfold.import_arkiv import import_arkiv

        db = self._make_populated_db(tmp_path)

        archive_dir = str(tmp_path / "archive")
        export_arkiv(db, archive_dir)
        db.close()

        import_db_path = str(tmp_path / "imported.db")
        import_arkiv(archive_dir, import_db_path)

        with ChartfoldDB(import_db_path) as idb:
            result = idb.query("""
                SELECT p.name AS proc_name, pr.diagnosis
                FROM pathology_reports pr
                JOIN procedures p ON pr.procedure_id = p.id
            """)
            assert len(result) == 1
            assert result[0]["proc_name"] == "Right hemicolectomy"
            assert result[0]["diagnosis"] == "Adenocarcinoma"

    def test_round_trip_notes_and_tags(self, tmp_path):
        """Notes and their tags preserved through export → import."""
        from chartfold.export_arkiv import export_arkiv
        from chartfold.import_arkiv import import_arkiv

        db = self._make_populated_db(tmp_path)

        archive_dir = str(tmp_path / "archive")
        export_arkiv(db, archive_dir)
        db.close()

        import_db_path = str(tmp_path / "imported.db")
        import_arkiv(archive_dir, import_db_path)

        with ChartfoldDB(import_db_path) as idb:
            notes = idb.search_notes_personal()
            assert len(notes) == 1
            assert notes[0]["title"] == "CEA Trend"
            assert set(notes[0]["tags"]) == {"oncology", "cea"}
```

**Step 2: Run round-trip tests**

Run: `python -m pytest tests/test_import_arkiv.py::TestRoundTrip -v`
Expected: All PASS (may require debugging — run iteratively)

**Step 3: Commit**

```bash
git add tests/test_import_arkiv.py
git commit -m "test: add arkiv round-trip tests (export → import → verify)"
```

---

## Task 8: Rewire CLI import command to use import_arkiv

Change the `import` CLI command from JSON to arkiv directory import.

**Files:**
- Modify: `src/chartfold/cli.py:148-157` (change import args from input_file to input_dir)
- Modify: `src/chartfold/cli.py:707-740` (rewrite `_handle_import` to call `import_arkiv`)
- Test: `tests/test_import_arkiv.py` (add CLI test)

**Step 1: Write failing CLI test**

Add to `tests/test_import_arkiv.py`:

```python
class TestImportCLI:
    def test_cli_import_arkiv(self, tmp_path):
        """CLI: chartfold import <dir> works end-to-end."""
        import subprocess
        import sys

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)

        db_path = str(tmp_path / "imported.db")
        result = subprocess.run(
            [sys.executable, "-m", "chartfold", "import",
             str(archive_dir), "--db", db_path],
            check=False, capture_output=True, text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Import successful" in result.stdout
        assert (tmp_path / "imported.db").exists()

    def test_cli_import_validate_only(self, tmp_path):
        """CLI: chartfold import --validate-only works."""
        import subprocess
        import sys

        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        _create_minimal_archive(archive_dir)

        db_path = str(tmp_path / "imported.db")
        result = subprocess.run(
            [sys.executable, "-m", "chartfold", "import",
             str(archive_dir), "--db", db_path, "--validate-only"],
            check=False, capture_output=True, text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Validation successful" in result.stdout
        assert not (tmp_path / "imported.db").exists()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_import_arkiv.py::TestImportCLI -v -x`
Expected: FAIL — CLI still expects JSON file

**Step 3: Rewrite CLI import**

In `src/chartfold/cli.py`:

1. Change the import parser (around line 148-157):

```python
    # --- import ---
    import_parser = sub.add_parser("import", help="Import data from arkiv archive")
    import_parser.add_argument("input_dir", help="Path to arkiv archive directory")
    import_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    import_parser.add_argument(
        "--validate-only", action="store_true", help="Validate without importing"
    )
    import_parser.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing database"
    )
```

2. Rewrite `_handle_import` (around line 707):

```python
def _handle_import(args):
    from chartfold.import_arkiv import import_arkiv, validate_arkiv

    if args.validate_only:
        result = validate_arkiv(args.input_dir)
        if result["valid"]:
            print("Validation successful!")
            print("\nTable counts:")
            for table, count in sorted(result["summary"].items()):
                if count > 0:
                    print(f"  {table:<25} {count:>6}")
            total = sum(result["summary"].values())
            print(f"\n  Total records: {total}")
        else:
            print("Validation failed:")
            for error in result["errors"]:
                print(f"  - {error}")
            sys.exit(1)
    else:
        result = import_arkiv(
            args.input_dir,
            args.db,
            validate_only=False,
            overwrite=args.overwrite,
        )

        if result["success"]:
            print(f"Import successful to {args.db}")
            print("\nRecords imported:")
            for table, count in sorted(result["counts"].items()):
                if count > 0:
                    print(f"  {table:<25} {count:>6}")
            total = sum(result["counts"].values())
            print(f"\n  Total records: {total}")
        else:
            print("Import failed:")
            for error in result["errors"]:
                print(f"  - {error}")
            sys.exit(1)
```

**Step 4: Run CLI tests**

Run: `python -m pytest tests/test_import_arkiv.py::TestImportCLI -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/chartfold/cli.py tests/test_import_arkiv.py
git commit -m "feat: rewire CLI import command to use arkiv archives"
```

---

## Task 9: Remove JSON export/import and export json CLI command

Delete `export_full.py`, `test_export_full.py`, and the `export json` CLI subcommand.

**Files:**
- Delete: `src/chartfold/export_full.py`
- Delete: `tests/test_export_full.py`
- Modify: `src/chartfold/cli.py` (remove `json` export subparser and handler branch)

**Step 1: Remove JSON CLI subcommand**

In `src/chartfold/cli.py`:

1. Delete the json parser block (lines 117-121):
```python
    # DELETE THESE LINES:
    json_parser = export_sub.add_parser("json", help="Export as JSON (full database dump)")
    json_parser.add_argument("--db", default=DEFAULT_DB, help=db_help)
    json_parser.add_argument("--output", default="chartfold_export.json", help="Output file path")
    json_parser.add_argument("--include-load-log", action="store_true", help="Include audit log")
    json_parser.add_argument("--exclude-notes", action="store_true", help="Exclude personal notes")
```

2. Delete the json branch in `_handle_export` (lines 675-683):
```python
    # DELETE THESE LINES:
    if args.export_format == "json":
        from chartfold.export_full import export_full_json
        path = export_full_json(...)
```

3. Update the usage message in `_handle_export` to remove json:
```python
        print("Usage: chartfold export <arkiv|html> [options]")
        print("\nSubcommands:")
        print("  arkiv      Export as arkiv universal record format")
        print("  html       Export as self-contained HTML SPA with embedded SQLite")
```

**Step 2: Delete files**

```bash
rm src/chartfold/export_full.py
rm tests/test_export_full.py
```

**Step 3: Run all tests to verify nothing breaks**

Run: `python -m pytest tests/ -v --tb=short 2>&1 | tail -20`
Expected: All PASS (minus the deleted test_export_full tests)

**Step 4: Check for any remaining imports of export_full**

Run: `grep -r "export_full" src/ tests/`
Expected: No results (if any found, fix them)

**Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove JSON export/import path (replaced by arkiv)"
```

---

## Task 10: Update documentation

Update CLAUDE.md and README.md to reflect the new arkiv-only export/import workflow.

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

**Step 1: Update CLAUDE.md**

In `CLAUDE.md`:

1. Remove all references to `export json`, `import data.json`, `export_full.py`
2. Update arkiv export commands to show `--embed` flag
3. Update import command to show directory input: `chartfold import <dir>`
4. Update project structure tree: remove `export_full.py`, add `import_arkiv.py`
5. Update "Export Modules" section: remove export_full.py, update export_arkiv.py description

Key changes:
```bash
# Export as arkiv (primary backup/restore format)
python -m chartfold export arkiv --output ./arkiv/
python -m chartfold export arkiv --output ./arkiv/ --embed          # inline base64 assets
python -m chartfold export arkiv --output ./arkiv/ --exclude-notes

# Import from arkiv archive (round-trip capable)
python -m chartfold import ./arkiv/ --db new_chartfold.db
python -m chartfold import ./arkiv/ --validate-only
python -m chartfold import ./arkiv/ --db existing.db --overwrite
```

**Step 2: Update README.md**

1. Remove `export json` from export examples
2. Add arkiv import examples
3. Update "Export formats" bullet: `Arkiv (JSONL + README.md + schema.yaml)`
4. Show `--embed` flag
5. Update project structure

**Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: update docs for arkiv-only export/import workflow"
```

---

## Task 11: Final verification

Run the full test suite and check coverage.

**Step 1: Run all tests**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All PASS

**Step 2: Run with coverage**

Run: `python -m pytest tests/ --cov=chartfold --cov-report=term-missing 2>&1 | tail -30`
Expected: Reasonable coverage for new files (`import_arkiv.py`, updated `export_arkiv.py`)

**Step 3: Run ruff**

Run: `ruff check src/ tests/`
Expected: 0 warnings

**Step 4: Verify no stale references**

Run: `grep -r "manifest.json\|export_full\|export json\|import.*json" src/ tests/ CLAUDE.md README.md`
Expected: No hits (or only in comments explaining the migration)

**Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "chore: final cleanup after arkiv round-trip implementation"
```
