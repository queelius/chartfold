# Bidirectional Linked Sources Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `--linked-sources` produce structured, bidirectional output — source assets grouped by encounter date on the sources index page with back-links to clinical records, and inline "Source Documents" sections on clinical detail pages linking to the raw EHR files.

**Architecture:** Add a helper `_build_asset_lookup(db)` that queries `source_assets` and builds two indexes: (1) `by_ref` mapping `(ref_table, ref_id)` to asset lists, and (2) `by_date_source` mapping `(encounter_date, source)` to asset lists. Pass `linked_sources=True` and the asset lookup through the existing generation functions so detail pages can render a "Source Documents" section. Rewrite `_generate_linked_sources` to group by date with back-links.

**Tech Stack:** Python, SQLite, Hugo markdown generation (existing stack, no new deps)

---

### Task 1: Add `_build_asset_lookup` helper + tests

**Files:**
- Modify: `src/chartfold/hugo/generate.py` (add helper near top)
- Test: `tests/test_hugo.py`

**Step 1: Write the failing test**

In `tests/test_hugo.py`, add a new test class:

```python
class TestAssetLookup:
    def test_build_asset_lookup_by_ref(self, loaded_db, tmp_path):
        """Assets with ref_table/ref_id appear in by_ref lookup."""
        loaded_db.conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, "
            "file_size_kb, title, ref_table, ref_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("test_source", "pdf", "/tmp/report.pdf", "report.pdf",
             10, "Lab Report", "lab_results", 1),
        )
        loaded_db.conn.commit()

        from chartfold.hugo.generate import _build_asset_lookup
        lookup = _build_asset_lookup(loaded_db)

        assert ("lab_results", 1) in lookup["by_ref"]
        assets = lookup["by_ref"][("lab_results", 1)]
        assert len(assets) == 1
        assert assets[0]["file_name"] == "report.pdf"

    def test_build_asset_lookup_by_date_source(self, loaded_db, tmp_path):
        """Assets with encounter_date+source appear in by_date_source lookup."""
        loaded_db.conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, "
            "file_size_kb, title, encounter_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test_source", "pdf", "/tmp/visit.pdf", "visit.pdf",
             20, "Visit Doc", "2025-01-15"),
        )
        loaded_db.conn.commit()

        from chartfold.hugo.generate import _build_asset_lookup
        lookup = _build_asset_lookup(loaded_db)

        assert ("2025-01-15", "test_source") in lookup["by_date_source"]

    def test_build_asset_lookup_empty_db(self, loaded_db):
        """Empty source_assets returns empty lookups."""
        from chartfold.hugo.generate import _build_asset_lookup
        lookup = _build_asset_lookup(loaded_db)

        assert lookup["by_ref"] == {}
        assert lookup["by_date_source"] == {}
        assert lookup["by_date"] == {}
        assert lookup["all"] == []
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hugo.py::TestAssetLookup -v`
Expected: FAIL — `ImportError: cannot import name '_build_asset_lookup'`

**Step 3: Write minimal implementation**

In `src/chartfold/hugo/generate.py`, add after the `HUGO_TEMPLATE_DIR` line:

```python
def _build_asset_lookup(db: ChartfoldDB) -> dict:
    """Query source_assets and build indexes for bidirectional linking.

    Returns dict with keys:
        - all: list of all asset rows
        - by_ref: {(ref_table, ref_id): [asset_rows]} for direct-linked assets
        - by_date_source: {(encounter_date, source): [asset_rows]} for date-matched
        - by_date: {encounter_date: [asset_rows]} for date-only grouping
    """
    assets = db.query(
        "SELECT id, source, asset_type, file_path, file_name, "
        "file_size_kb, title, encounter_date, encounter_id, "
        "ref_table, ref_id, metadata "
        "FROM source_assets ORDER BY source, encounter_date, file_name"
    )

    by_ref: dict[tuple, list] = {}
    by_date_source: dict[tuple, list] = {}
    by_date: dict[str, list] = {}

    for a in assets:
        # Index by direct reference
        if a.get("ref_table") and a.get("ref_id"):
            key = (a["ref_table"], a["ref_id"])
            by_ref.setdefault(key, []).append(a)

        # Index by (date, source)
        if a.get("encounter_date"):
            ds_key = (a["encounter_date"], a["source"])
            by_date_source.setdefault(ds_key, []).append(a)
            by_date.setdefault(a["encounter_date"], []).append(a)

    return {
        "all": assets,
        "by_ref": by_ref,
        "by_date_source": by_date_source,
        "by_date": by_date,
    }
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_hugo.py::TestAssetLookup -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/chartfold/hugo/generate.py tests/test_hugo.py
git commit -m "feat(hugo): add _build_asset_lookup for bidirectional source linking"
```

---

### Task 2: Add `_render_source_docs_section` helper + tests

**Files:**
- Modify: `src/chartfold/hugo/generate.py`
- Test: `tests/test_hugo.py`

**Step 1: Write the failing test**

```python
class TestRenderSourceDocs:
    def test_render_with_ref_match(self):
        """Direct ref_table/ref_id match renders source doc links."""
        from chartfold.hugo.generate import _render_source_docs_section
        asset_lookup = {
            "by_ref": {
                ("encounters", 5): [
                    {"id": 1, "file_name": "visit.pdf", "asset_type": "pdf",
                     "file_size_kb": 42, "source": "epic", "title": "Visit Summary"},
                ],
            },
            "by_date_source": {},
        }
        result = _render_source_docs_section(
            asset_lookup, {1: "/sources/epic/1_visit.pdf"},
            ref_table="encounters", ref_id=5,
        )
        assert "Source Documents" in result
        assert "visit.pdf" in result or "Visit Summary" in result
        assert "/sources/epic/1_visit.pdf" in result

    def test_render_with_date_source_fallback(self):
        """When no ref match, falls back to date+source matching."""
        from chartfold.hugo.generate import _render_source_docs_section
        asset_lookup = {
            "by_ref": {},
            "by_date_source": {
                ("2025-01-15", "epic"): [
                    {"id": 2, "file_name": "labs.pdf", "asset_type": "pdf",
                     "file_size_kb": 18, "source": "epic", "title": ""},
                ],
            },
        }
        result = _render_source_docs_section(
            asset_lookup, {2: "/sources/epic/2_labs.pdf"},
            date="2025-01-15", source="epic",
        )
        assert "labs.pdf" in result
        assert "/sources/epic/2_labs.pdf" in result

    def test_render_no_matches_returns_empty(self):
        """When no assets match, returns empty string."""
        from chartfold.hugo.generate import _render_source_docs_section
        asset_lookup = {"by_ref": {}, "by_date_source": {}}
        result = _render_source_docs_section(
            asset_lookup, {},
            ref_table="encounters", ref_id=999,
        )
        assert result == ""

    def test_render_deduplicates(self):
        """Asset appearing in both ref and date match is shown only once."""
        from chartfold.hugo.generate import _render_source_docs_section
        shared_asset = {"id": 1, "file_name": "report.pdf", "asset_type": "pdf",
                        "file_size_kb": 10, "source": "epic", "title": ""}
        asset_lookup = {
            "by_ref": {("encounters", 5): [shared_asset]},
            "by_date_source": {("2025-01-15", "epic"): [shared_asset]},
        }
        result = _render_source_docs_section(
            asset_lookup, {1: "/sources/epic/1_report.pdf"},
            ref_table="encounters", ref_id=5,
            date="2025-01-15", source="epic",
        )
        assert result.count("report.pdf") == 1
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hugo.py::TestRenderSourceDocs -v`
Expected: FAIL — `ImportError`

**Step 3: Write minimal implementation**

```python
def _render_source_docs_section(
    asset_lookup: dict,
    asset_url_map: dict[int, str],
    ref_table: str = "",
    ref_id: int | None = None,
    date: str = "",
    source: str = "",
) -> str:
    """Render a '### Source Documents' section for a clinical detail page.

    Matches assets by direct ref first, then falls back to date+source.
    Returns empty string if no matching assets found.
    """
    matched: list[dict] = []
    seen_ids: set[int] = set()

    # Priority 1: direct ref match
    if ref_table and ref_id is not None:
        for a in asset_lookup.get("by_ref", {}).get((ref_table, ref_id), []):
            if a["id"] not in seen_ids:
                matched.append(a)
                seen_ids.add(a["id"])

    # Priority 2: date + source fallback
    if date and source:
        for a in asset_lookup.get("by_date_source", {}).get((date, source), []):
            if a["id"] not in seen_ids:
                matched.append(a)
                seen_ids.add(a["id"])

    if not matched:
        return ""

    lines = ["### Source Documents", ""]
    for a in matched:
        url = asset_url_map.get(a["id"])
        if not url:
            continue
        display = a.get("title") or a["file_name"]
        size = f"{a['file_size_kb']} KB" if a.get("file_size_kb") else ""
        detail = f" ({a['asset_type']}" + (f", {size}" if size else "") + ")"
        lines.append(f"- [{display}]({url}){detail}")

    # If no URLs resolved, return empty
    if len(lines) <= 2:
        return ""

    return "\n".join(lines)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_hugo.py::TestRenderSourceDocs -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/chartfold/hugo/generate.py tests/test_hugo.py
git commit -m "feat(hugo): add _render_source_docs_section helper"
```

---

### Task 3: Rewrite `_generate_linked_sources` to group by date with back-links

**Files:**
- Modify: `src/chartfold/hugo/generate.py` — replace `_generate_linked_sources`
- Test: `tests/test_hugo.py`

**Step 1: Write the failing tests**

Add to `TestLinkedSources`:

```python
    def test_linked_sources_grouped_by_date(self, loaded_db, tmp_path):
        """Sources page groups assets under encounter date headings."""
        asset_dir = tmp_path / "assets"
        asset_dir.mkdir()
        f1 = asset_dir / "jan_visit.pdf"
        f1.write_text("content1")
        f2 = asset_dir / "feb_visit.pdf"
        f2.write_text("content2")

        loaded_db.conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, "
            "file_size_kb, title, encounter_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test_source", "pdf", str(f1), "jan_visit.pdf", 5, "Jan Visit", "2025-01-15"),
        )
        loaded_db.conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, "
            "file_size_kb, title, encounter_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test_source", "pdf", str(f2), "feb_visit.pdf", 8, "Feb Visit", "2025-02-20"),
        )
        loaded_db.conn.commit()

        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir), linked_sources=True)

        content = (hugo_dir / "content" / "sources.md").read_text()
        # Should have date headings
        assert "2025-01-15" in content
        assert "2025-02-20" in content
        # Dates should appear as headings (## prefix)
        assert "## 2025-02-20" in content
        assert "## 2025-01-15" in content

    def test_linked_sources_undated_section(self, loaded_db, tmp_path):
        """Assets without encounter_date go in 'Undated' section."""
        asset_dir = tmp_path / "assets"
        asset_dir.mkdir()
        f1 = asset_dir / "style.xsl"
        f1.write_text("xsl content")

        loaded_db.conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, "
            "file_size_kb, title) VALUES (?, ?, ?, ?, ?, ?)",
            ("test_source", "xsl", str(f1), "style.xsl", 3, "Stylesheet"),
        )
        loaded_db.conn.commit()

        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir), linked_sources=True)

        content = (hugo_dir / "content" / "sources.md").read_text()
        assert "Undated" in content
        assert "style.xsl" in content or "Stylesheet" in content

    def test_linked_sources_backlinks_to_encounters(self, loaded_db, tmp_path):
        """Assets on dates with encounters show back-links to encounter pages."""
        asset_dir = tmp_path / "assets"
        asset_dir.mkdir()
        f1 = asset_dir / "visit.pdf"
        f1.write_text("content")

        loaded_db.conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, "
            "file_size_kb, title, encounter_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test_source", "pdf", str(f1), "visit.pdf", 5, "Visit Doc", "2025-01-15"),
        )
        loaded_db.conn.commit()

        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir), linked_sources=True)

        content = (hugo_dir / "content" / "sources.md").read_text()
        # loaded_db has an encounter on 2025-01-15, so should have a back-link
        assert "/encounters/" in content
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_hugo.py::TestLinkedSources::test_linked_sources_grouped_by_date tests/test_hugo.py::TestLinkedSources::test_linked_sources_undated_section tests/test_hugo.py::TestLinkedSources::test_linked_sources_backlinks_to_encounters -v`
Expected: FAIL (flat table, no date headings)

**Step 3: Rewrite `_generate_linked_sources`**

Replace the existing function with:

```python
def _generate_linked_sources(content: Path, static: Path, db: ChartfoldDB) -> dict[int, str]:
    """Copy source assets into static/sources/ and generate grouped sources index.

    Returns:
        asset_url_map: {asset_id: relative_url} for use by detail page generators.
    """
    assets = db.query(
        "SELECT id, source, asset_type, file_path, file_name, "
        "file_size_kb, title, encounter_date, ref_table, ref_id "
        "FROM source_assets ORDER BY source, encounter_date, file_name"
    )
    if not assets:
        _write_page(content / "sources.md", "Source Documents",
                     "*No source assets available.*")
        return {}

    sources_dir = static / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    # Copy files
    asset_url_map: dict[int, str] = {}
    for a in assets:
        src_path = Path(a["file_path"])
        if not src_path.exists():
            continue
        dest_name = f"{a['id']}_{a['file_name']}"
        dest_subdir = sources_dir / a["source"]
        dest_subdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_subdir / dest_name)
        asset_url_map[a["id"]] = f"/sources/{a['source']}/{dest_name}"

    # Query related clinical records for back-links
    encounters_by_date = {}
    for e in db.query("SELECT id, encounter_date, encounter_type, facility FROM encounters"):
        d = e.get("encounter_date", "")
        if d:
            encounters_by_date.setdefault(d, []).append(e)

    procedures_by_date = {}
    for p in db.query("SELECT id, procedure_date, name FROM procedures"):
        d = p.get("procedure_date", "")
        if d:
            procedures_by_date.setdefault(d, []).append(p)

    notes_by_date = {}
    for n in db.query("SELECT id, note_date, note_type FROM clinical_notes"):
        d = n.get("note_date", "")
        if d:
            notes_by_date.setdefault(d, []).append(n)

    # Group assets by date
    dated: dict[str, list] = {}
    undated: list = []
    for a in assets:
        if a["id"] not in asset_url_map:
            continue
        if a.get("encounter_date"):
            dated.setdefault(a["encounter_date"], []).append(a)
        else:
            undated.append(a)

    # Build page content
    md_parts = []

    # Dated groups (newest first)
    for date in sorted(dated.keys(), reverse=True):
        group = dated[date]
        md_parts.append(f"## {date}")

        # Back-links to clinical records on this date
        backlinks = []
        for e in encounters_by_date.get(date, []):
            etype = e.get("encounter_type", "") or "Encounter"
            backlinks.append(f"[{etype}](/encounters/{e['id']}/)")
        for p in procedures_by_date.get(date, []):
            backlinks.append(f"[{p['name']}](/surgical/{p['id']}/)")
        for n in notes_by_date.get(date, []):
            ntype = n.get("note_type", "") or "Note"
            backlinks.append(f"[{ntype}](/notes/{n['id']}/)")

        if backlinks:
            md_parts.append("**Related:** " + " &bull; ".join(backlinks))
            md_parts.append("")

        rows = []
        for a in group:
            url = asset_url_map[a["id"]]
            display = a.get("title") or a["file_name"]
            size_str = f"{a['file_size_kb']} KB" if a.get("file_size_kb") else ""
            rows.append([
                (display, url),
                a["asset_type"],
                size_str,
                a["source"],
            ])
        table = _make_linked_table(["Document", "Type", "Size", "Source"], rows, link_col=0)
        md_parts.append(table)
        md_parts.append("")

    # Undated section
    if undated:
        md_parts.append("## Undated")
        rows = []
        for a in undated:
            url = asset_url_map[a["id"]]
            display = a.get("title") or a["file_name"]
            size_str = f"{a['file_size_kb']} KB" if a.get("file_size_kb") else ""
            rows.append([
                (display, url),
                a["asset_type"],
                size_str,
                a["source"],
            ])
        table = _make_linked_table(["Document", "Type", "Size", "Source"], rows, link_col=0)
        md_parts.append(table)

    _write_page(content / "sources.md", "Source Documents", "\n".join(md_parts))
    return asset_url_map
```

Also update the call site in `generate_site` to capture the return value:

```python
        # Source documents
        if linked_sources:
            asset_lookup = _build_asset_lookup(db)
            asset_url_map = _generate_linked_sources(content, out / "static", db)
        else:
            asset_lookup = None
            asset_url_map = {}
            _write_page(content / "sources.md", "Source Documents",
                        "*Source documents not included. "
                        "Run with `--linked-sources` to copy EHR assets into the site.*")
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_hugo.py::TestLinkedSources -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/chartfold/hugo/generate.py tests/test_hugo.py
git commit -m "feat(hugo): rewrite _generate_linked_sources with date grouping and back-links"
```

---

### Task 4: Thread `asset_lookup` + `asset_url_map` through detail page generators

**Files:**
- Modify: `src/chartfold/hugo/generate.py` — update signatures of `_generate_encounters`, `_generate_clinical_notes`, `_generate_pathology`, `_generate_surgical`, `_generate_imaging` and their call sites in `generate_site`
- Test: `tests/test_hugo.py`

**Step 1: Write the failing test**

```python
    def test_encounter_detail_shows_source_docs(self, loaded_db, tmp_path):
        """Encounter detail page includes source documents when linked."""
        asset_dir = tmp_path / "assets"
        asset_dir.mkdir()
        f1 = asset_dir / "visit_summary.pdf"
        f1.write_text("pdf content")

        # Insert asset linked by encounter_date matching the fixture encounter
        loaded_db.conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, "
            "file_size_kb, title, encounter_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test_source", "pdf", str(f1), "visit_summary.pdf", 15,
             "Visit Summary PDF", "2025-01-15"),
        )
        loaded_db.conn.commit()

        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir), linked_sources=True)

        # Find the encounter detail page
        enc_pages = list((hugo_dir / "content" / "encounters").glob("[0-9]*.md"))
        assert len(enc_pages) >= 1
        content = enc_pages[0].read_text()
        assert "Source Documents" in content
        assert "visit_summary.pdf" in content or "Visit Summary PDF" in content
```

Add this test to `TestLinkedSources`.

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hugo.py::TestLinkedSources::test_encounter_detail_shows_source_docs -v`
Expected: FAIL (no "Source Documents" section on detail page)

**Step 3: Update `generate_site` and detail generators**

In `generate_site`, pass the lookup/map to detail generators:

```python
        # Encounters
        _generate_encounters(content, data, db,
                             asset_lookup=asset_lookup, asset_url_map=asset_url_map)

        # ... similar for other generators that produce detail pages:
        _generate_clinical_notes(content, data, db,
                                 asset_lookup=asset_lookup, asset_url_map=asset_url_map)
        _generate_pathology(content, data, db,
                            asset_lookup=asset_lookup, asset_url_map=asset_url_map)
        _generate_surgical(content, data, db,
                           asset_lookup=asset_lookup, asset_url_map=asset_url_map)
        _generate_imaging(content, data, db,
                          asset_lookup=asset_lookup, asset_url_map=asset_url_map)
```

Update each function signature to accept optional `asset_lookup` and `asset_url_map` parameters (defaulting to `None` / `{}`).

In each detail page's body construction, append:

```python
        if asset_lookup and asset_url_map:
            source_docs = _render_source_docs_section(
                asset_lookup, asset_url_map,
                ref_table="encounters", ref_id=eid,
                date=date, source=e.get("source", ""),
            )
            if source_docs:
                body += "\n\n---\n\n" + source_docs
```

Use the appropriate `ref_table` for each generator:
- `_generate_encounters` → `ref_table="encounters"`, `ref_id=eid`
- `_generate_clinical_notes` → `ref_table="clinical_notes"`, `ref_id=nid`
- `_generate_pathology` → `ref_table="pathology_reports"`, `ref_id=rid`
- `_generate_surgical` → `ref_table="procedures"`, `ref_id=proc_id`
- `_generate_imaging` → `ref_table="imaging_reports"`, `ref_id=rid`

For the date parameter, use the record's date field. For source, use the record's source field.

**Step 4: Run tests**

Run: `python -m pytest tests/test_hugo.py -v`
Expected: All PASS (new test + all existing tests still pass)

**Step 5: Commit**

```bash
git add src/chartfold/hugo/generate.py tests/test_hugo.py
git commit -m "feat(hugo): thread asset lookup into detail pages for inline source doc links"
```

---

### Task 5: Add integration tests for bidirectional linking

**Files:**
- Test: `tests/test_hugo.py`

**Step 1: Write integration tests**

```python
class TestBidirectionalLinking:
    def test_sources_page_links_to_encounter_and_vice_versa(self, loaded_db, tmp_path):
        """Sources page links to encounter; encounter page links to source doc."""
        asset_dir = tmp_path / "assets"
        asset_dir.mkdir()
        f1 = asset_dir / "visit.pdf"
        f1.write_text("pdf")

        loaded_db.conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, "
            "file_size_kb, title, encounter_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test_source", "pdf", str(f1), "visit.pdf", 5, "Visit", "2025-01-15"),
        )
        loaded_db.conn.commit()

        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir), linked_sources=True)

        # Sources page should back-link to encounter
        sources_content = (hugo_dir / "content" / "sources.md").read_text()
        assert "/encounters/" in sources_content

        # Encounter detail page should link to source doc
        enc_pages = list((hugo_dir / "content" / "encounters").glob("[0-9]*.md"))
        assert len(enc_pages) >= 1
        enc_content = enc_pages[0].read_text()
        assert "/sources/" in enc_content

    def test_without_linked_sources_no_source_doc_sections(self, loaded_db, tmp_path):
        """Without --linked-sources, detail pages have no Source Documents section."""
        asset_dir = tmp_path / "assets"
        asset_dir.mkdir()
        f1 = asset_dir / "visit.pdf"
        f1.write_text("pdf")

        loaded_db.conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, "
            "file_size_kb, title, encounter_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test_source", "pdf", str(f1), "visit.pdf", 5, "Visit", "2025-01-15"),
        )
        loaded_db.conn.commit()

        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir), linked_sources=False)

        enc_pages = list((hugo_dir / "content" / "encounters").glob("[0-9]*.md"))
        for p in enc_pages:
            assert "Source Documents" not in p.read_text()

    def test_direct_ref_match_overrides_date_match(self, loaded_db, tmp_path):
        """Asset with ref_table/ref_id shows on the right detail page, not just any same-date page."""
        asset_dir = tmp_path / "assets"
        asset_dir.mkdir()
        f1 = asset_dir / "specific_lab.pdf"
        f1.write_text("pdf")

        # Get the encounter ID from the DB
        enc_rows = loaded_db.query("SELECT id FROM encounters LIMIT 1")
        enc_id = enc_rows[0]["id"] if enc_rows else 1

        loaded_db.conn.execute(
            "INSERT INTO source_assets (source, asset_type, file_path, file_name, "
            "file_size_kb, title, encounter_date, ref_table, ref_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("test_source", "pdf", str(f1), "specific_lab.pdf", 5,
             "Specific Lab Report", "2025-01-15", "encounters", enc_id),
        )
        loaded_db.conn.commit()

        hugo_dir = tmp_path / "site"
        generate_site(loaded_db.db_path, str(hugo_dir), linked_sources=True)

        enc_page = hugo_dir / "content" / "encounters" / f"{enc_id}.md"
        assert enc_page.exists()
        content = enc_page.read_text()
        assert "Specific Lab Report" in content or "specific_lab.pdf" in content
```

**Step 2: Run tests**

Run: `python -m pytest tests/test_hugo.py::TestBidirectionalLinking -v`
Expected: All PASS (these exercise the full pipeline)

**Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add tests/test_hugo.py
git commit -m "test(hugo): add integration tests for bidirectional source linking"
```

---

### Task 6: Run coverage and verify

**Step 1: Run coverage**

Run: `python -m pytest tests/ --cov=chartfold.hugo.generate --cov-report=term-missing`

Check that `_build_asset_lookup`, `_render_source_docs_section`, and the new `_generate_linked_sources` have good coverage. Add targeted tests for any uncovered branches found.

**Step 2: Final commit**

```bash
git add -A
git commit -m "test(hugo): complete coverage for bidirectional linked sources"
```
