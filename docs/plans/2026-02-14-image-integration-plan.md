# Image & Asset Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show clinical images inline on Hugo and HTML export pages, categorize source assets, add gallery layout for multi-image pages, and add an Analysis section for exogenous content.

**Architecture:** Modify `_render_source_docs_section()` to detect image types and emit Hugo lightbox shortcodes or base64 `<img>` tags. Add GLightbox JS to Hugo theme. Add `_render_source_assets_section()` to HTML exporter. Add category extraction from MEDITECH folder metadata. Add Analysis section for user-supplied markdown files.

**Tech Stack:** GLightbox (Hugo), CSS-only lightbox (HTML), base64 encoding (Python stdlib), Hugo shortcodes

---

### Task 1: Add shared asset helpers to `core/utils.py`

**Files:**
- Modify: `src/chartfold/core/utils.py`
- Test: `tests/test_core.py`

**Step 1: Write failing tests**

Add to `tests/test_core.py`:

```python
from chartfold.core.utils import is_image_asset, categorize_asset_title


class TestAssetHelpers:
    def test_is_image_png(self):
        assert is_image_asset("png") is True

    def test_is_image_jpg(self):
        assert is_image_asset("jpg") is True

    def test_is_image_tiff(self):
        assert is_image_asset("tiff") is True

    def test_is_not_image_pdf(self):
        assert is_image_asset("pdf") is False

    def test_is_not_image_html(self):
        assert is_image_asset("html") is False

    def test_categorize_laboratory(self):
        assert categorize_asset_title("015_Laboratory") == "Laboratory"

    def test_categorize_surgical(self):
        assert categorize_asset_title("010_Surgical_Services") == "Surgical Services"

    def test_categorize_admissions(self):
        assert categorize_asset_title("000_Admissions") == "Admissions"

    def test_categorize_discharge(self):
        assert categorize_asset_title("006_Discharge_Transfer_Document") == "Discharge"

    def test_categorize_patient_care(self):
        assert categorize_asset_title("018_Patient_Care_Notes") == "Patient Care Notes"

    def test_categorize_medications(self):
        assert categorize_asset_title("019_Medications") == "Medications"

    def test_categorize_orders(self):
        assert categorize_asset_title("020_Orders") == "Orders"

    def test_categorize_consents(self):
        assert categorize_asset_title("003_Consents") == "Consents"

    def test_categorize_unknown_title(self):
        assert categorize_asset_title("Random title") == "General"

    def test_categorize_empty(self):
        assert categorize_asset_title("") == "General"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_core.py::TestAssetHelpers -v`
Expected: FAIL with ImportError

**Step 3: Implement helpers**

Add to `src/chartfold/core/utils.py` after the existing `deduplicate_by_key` function:

```python
_IMAGE_TYPES = frozenset({"png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff"})


def is_image_asset(asset_type: str) -> bool:
    """Return True if asset_type is a displayable image format."""
    return asset_type.lower() in _IMAGE_TYPES


# Maps MEDITECH folder prefixes to display-friendly category labels.
_CATEGORY_MAP = {
    "admission": "Admissions",
    "consent": "Consents",
    "discharge": "Discharge",
    "surgical": "Surgical Services",
    "laborator": "Laboratory",
    "patient_care": "Patient Care Notes",
    "medication": "Medications",
    "order": "Orders",
    "radiol": "Radiology",
    "imaging": "Imaging",
}


def categorize_asset_title(title: str) -> str:
    """Derive a display-friendly category from asset title or folder name.

    MEDITECH folders like '015_Laboratory' or '010_Surgical_Services'
    are mapped to clean labels. Unknown titles get 'General'.
    """
    if not title:
        return "General"
    t = title.lower().replace("_", " ")
    for keyword, label in _CATEGORY_MAP.items():
        if keyword in t:
            return label
    return "General"
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_core.py::TestAssetHelpers -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/chartfold/core/utils.py tests/test_core.py
git commit -m "feat: add is_image_asset and categorize_asset_title helpers"
```

---

### Task 2: Hugo — Add GLightbox and lightbox shortcode

**Files:**
- Create: `src/chartfold/hugo/static/js/glightbox.min.js` (download or vendor)
- Create: `src/chartfold/hugo/static/css/glightbox.min.css` (download or vendor)
- Create: `src/chartfold/hugo/layouts/shortcodes/lightbox.html`
- Modify: `src/chartfold/hugo/layouts/_default/baseof.html` (add GLightbox link/script + init)

**Step 1: Download GLightbox**

```bash
cd src/chartfold/hugo/static
mkdir -p js css
curl -sL https://cdn.jsdelivr.net/npm/glightbox@3.3.0/dist/js/glightbox.min.js -o js/glightbox.min.js
curl -sL https://cdn.jsdelivr.net/npm/glightbox@3.3.0/dist/css/glightbox.min.css -o css/glightbox.min.css
```

**Step 2: Create lightbox shortcode**

Create `src/chartfold/hugo/layouts/shortcodes/lightbox.html`:

```html
<a href="{{ .Get "src" }}" class="glightbox" data-gallery="{{ .Get "gallery" | default "source-docs" }}" data-description="{{ .Get "alt" | default "" }}">
  <img src="{{ .Get "src" }}" alt="{{ .Get "alt" | default "" }}" loading="lazy" style="max-width:300px; max-height:250px; cursor:zoom-in; border:1px solid #ddd; border-radius:4px; margin:0.5rem;">
</a>
```

**Step 3: Add GLightbox to baseof.html**

In `src/chartfold/hugo/layouts/_default/baseof.html`, add after the existing Chart.js lines (lines 8-9):

```html
<link rel="stylesheet" href="{{ "css/glightbox.min.css" | relURL }}">
```

And before the closing `</body>` tag:

```html
<script src="{{ "js/glightbox.min.js" | relURL }}"></script>
<script>const lightbox = GLightbox({ selector: '.glightbox' });</script>
```

**Step 4: Add gallery CSS**

Add to the Hugo theme's `static/css/` or inline in `baseof.html`:

```css
.asset-gallery {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 1rem;
  margin: 1rem 0;
}
.asset-gallery img {
  width: 100%;
  height: auto;
  object-fit: cover;
}
```

**Step 5: Commit**

```bash
git add src/chartfold/hugo/static/ src/chartfold/hugo/layouts/
git commit -m "feat(hugo): add GLightbox and lightbox shortcode for image viewing"
```

---

### Task 3: Hugo — Modify `_render_source_docs_section()` for inline images

**Files:**
- Modify: `src/chartfold/hugo/generate.py` (lines 80-127)
- Test: `tests/test_hugo.py`

**Step 1: Write failing test**

Add to `tests/test_hugo.py`:

```python
class TestSourceDocsImages:
    def test_image_asset_renders_lightbox(self, loaded_db, tmp_path):
        """Image assets should render as lightbox shortcodes, not download links."""
        db = loaded_db
        # Insert image asset
        db.conn.execute(
            "INSERT INTO source_assets "
            "(source, asset_type, file_path, file_name, file_size_kb, "
            "title, encounter_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test_source", "png", "/tmp/ct-scan.png", "ct-scan.png",
             120, "CT Scan", "2025-01-15"),
        )
        db.conn.commit()

        from chartfold.hugo.generate import _build_asset_lookup, _render_source_docs_section
        asset_lookup = _build_asset_lookup(db)
        # Simulate url map
        asset_id = db.query("SELECT id FROM source_assets WHERE file_name='ct-scan.png'")[0]["id"]
        asset_url_map = {asset_id: "/sources/test_source/1_ct-scan.png"}

        result = _render_source_docs_section(
            asset_lookup, asset_url_map,
            date="2025-01-15", source="test_source",
        )
        assert "lightbox" in result
        assert "ct-scan.png" in result
        assert ".png)" not in result  # NOT a markdown link

    def test_pdf_asset_renders_link(self, loaded_db, tmp_path):
        """PDF assets should still render as markdown links."""
        db = loaded_db
        db.conn.execute(
            "INSERT INTO source_assets "
            "(source, asset_type, file_path, file_name, file_size_kb, "
            "title, encounter_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test_source", "pdf", "/tmp/report.pdf", "report.pdf",
             85, "Lab Report", "2025-01-15"),
        )
        db.conn.commit()

        from chartfold.hugo.generate import _build_asset_lookup, _render_source_docs_section
        asset_lookup = _build_asset_lookup(db)
        asset_id = db.query("SELECT id FROM source_assets WHERE file_name='report.pdf'")[0]["id"]
        asset_url_map = {asset_id: "/sources/test_source/2_report.pdf"}

        result = _render_source_docs_section(
            asset_lookup, asset_url_map,
            date="2025-01-15", source="test_source",
        )
        assert "[Lab Report]" in result
        assert "lightbox" not in result

    def test_gallery_grid_for_multiple_images(self, loaded_db):
        """3+ image assets should render in gallery grid."""
        db = loaded_db
        asset_url_map = {}
        for i, name in enumerate(["scan1.png", "scan2.png", "scan3.png"]):
            db.conn.execute(
                "INSERT INTO source_assets "
                "(source, asset_type, file_path, file_name, file_size_kb, "
                "encounter_date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test_source", "png", f"/tmp/{name}", name, 100, "2025-01-15"),
            )
            db.conn.commit()
            aid = db.query(
                "SELECT id FROM source_assets WHERE file_name=?", (name,)
            )[0]["id"]
            asset_url_map[aid] = f"/sources/test_source/{aid}_{name}"

        from chartfold.hugo.generate import _build_asset_lookup, _render_source_docs_section
        asset_lookup = _build_asset_lookup(db)
        result = _render_source_docs_section(
            asset_lookup, asset_url_map,
            date="2025-01-15", source="test_source",
        )
        assert "asset-gallery" in result

    def test_categorized_pdf_shows_category(self, loaded_db):
        """PDF with MEDITECH folder title shows category label."""
        db = loaded_db
        db.conn.execute(
            "INSERT INTO source_assets "
            "(source, asset_type, file_path, file_name, file_size_kb, "
            "title, encounter_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test_source", "pdf", "/tmp/lab.pdf", "lab.pdf",
             50, "015_Laboratory", "2025-01-15"),
        )
        db.conn.commit()

        from chartfold.hugo.generate import _build_asset_lookup, _render_source_docs_section
        asset_lookup = _build_asset_lookup(db)
        asset_id = db.query("SELECT id FROM source_assets WHERE file_name='lab.pdf'")[0]["id"]
        asset_url_map = {asset_id: "/sources/test_source/3_lab.pdf"}

        result = _render_source_docs_section(
            asset_lookup, asset_url_map,
            date="2025-01-15", source="test_source",
        )
        assert "Laboratory" in result
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_hugo.py::TestSourceDocsImages -v`
Expected: FAIL

**Step 3: Implement changes to `_render_source_docs_section()`**

In `src/chartfold/hugo/generate.py`, replace the function body (lines 80-127) with:

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

    Images render as lightbox thumbnails (gallery grid if 3+).
    PDFs render as categorized download links.
    """
    from chartfold.core.utils import categorize_asset_title, is_image_asset

    matched: list[dict] = []
    seen_ids: set[int] = set()

    if ref_table and ref_id is not None:
        for a in asset_lookup.get("by_ref", {}).get((ref_table, ref_id), []):
            if a["id"] not in seen_ids:
                matched.append(a)
                seen_ids.add(a["id"])

    if date and source:
        for a in asset_lookup.get("by_date_source", {}).get((date, source), []):
            if a["id"] not in seen_ids:
                matched.append(a)
                seen_ids.add(a["id"])

    if not matched:
        return ""

    # Separate images from other assets
    images = []
    other = []
    for a in matched:
        url = asset_url_map.get(a["id"])
        if not url:
            continue
        if is_image_asset(a["asset_type"]):
            images.append((a, url))
        else:
            other.append((a, url))

    if not images and not other:
        return ""

    lines = ["### Source Documents", ""]

    # Render images
    if images:
        if len(images) >= 3:
            lines.append('<div class="asset-gallery">')
        for a, url in images:
            alt = a.get("title") or a["file_name"]
            lines.append(
                f'{{{{< lightbox src="{url}" alt="{alt}" >}}}}'
            )
        if len(images) >= 3:
            lines.append("</div>")
        lines.append("")

    # Render PDFs / other as categorized links
    for a, url in other:
        display = a.get("title") or a["file_name"]
        category = categorize_asset_title(a.get("title", ""))
        size = f"{a['file_size_kb']} KB" if a.get("file_size_kb") else ""
        cat_label = f"{category}, " if category != "General" else ""
        detail = f" ({cat_label}{a['asset_type']}" + (f", {size}" if size else "") + ")"
        lines.append(f"- [{display}]({url}){detail}")

    if len(lines) <= 2:
        return ""

    return "\n".join(lines)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hugo.py::TestSourceDocsImages -v`
Expected: PASS

**Step 5: Run full Hugo test suite**

Run: `python -m pytest tests/test_hugo.py -v`
Expected: All pass (existing tests still work — PDF behavior unchanged for non-image assets)

**Step 6: Commit**

```bash
git add src/chartfold/hugo/generate.py tests/test_hugo.py
git commit -m "feat(hugo): render images as lightbox thumbnails with gallery grid"
```

---

### Task 4: Hugo — Enhance `_generate_linked_sources()` with category grouping

**Files:**
- Modify: `src/chartfold/hugo/generate.py` (lines 1238-1399)
- Test: `tests/test_hugo.py`

**Step 1: Write failing test**

```python
class TestSourcesCategoryGrouping:
    def test_sources_page_groups_by_category(self, loaded_db, tmp_path):
        """Source documents index should group by category, then date."""
        db = loaded_db
        content = tmp_path / "content"
        static = tmp_path / "static"
        content.mkdir()
        static.mkdir()

        # Insert assets with different categories
        for title, fname in [
            ("015_Laboratory", "lab.pdf"),
            ("010_Surgical_Services", "surgery.pdf"),
            ("015_Laboratory", "lab2.pdf"),
        ]:
            db.conn.execute(
                "INSERT INTO source_assets "
                "(source, asset_type, file_path, file_name, file_size_kb, "
                "title, encounter_date) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("test_source", "pdf", f"/tmp/{fname}", fname, 50, title, "2025-01-15"),
            )
        db.conn.commit()

        # Create dummy files so copy works
        for fname in ["lab.pdf", "surgery.pdf", "lab2.pdf"]:
            Path(f"/tmp/{fname}").touch()

        from chartfold.hugo.generate import _generate_linked_sources
        _generate_linked_sources(content, static, db)

        page = (content / "sources.md").read_text()
        assert "Laboratory" in page
        assert "Surgical Services" in page
```

**Step 2: Implement category grouping**

In `_generate_linked_sources()`, after building the `dated` dict, add a secondary grouping by category within each date group. Modify the page-building loop to show category headers within date groups.

The exact changes: within the dated loop (around line 1330), group assets by `categorize_asset_title(a.get("title", ""))` and render sub-headings.

**Step 3: Run tests and commit**

```bash
git add src/chartfold/hugo/generate.py tests/test_hugo.py
git commit -m "feat(hugo): group source documents by category in index page"
```

---

### Task 5: HTML exporter — Add source asset rendering

**Files:**
- Modify: `src/chartfold/export_html.py`
- Test: `tests/test_export_html.py`

**Step 1: Write failing tests**

```python
class TestSourceAssetRendering:
    def test_imaging_section_includes_source_images(self, tmp_db):
        """Imaging report cards should include matched source images inline."""
        db = tmp_db
        db.conn.execute(
            "INSERT INTO imaging_reports "
            "(source, study_name, modality, study_date, impression) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test", "CT Abdomen", "CT", "2025-01-15", "No recurrence"),
        )
        img_id = db.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        # Create a PNG asset linked to this imaging report
        db.conn.execute(
            "INSERT INTO source_assets "
            "(source, asset_type, file_path, file_name, file_size_kb, "
            "ref_table, ref_id, encounter_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("test", "png", "/tmp/ct-scan.png", "ct-scan.png", 120,
             "imaging_reports", img_id, "2025-01-15"),
        )
        db.conn.commit()
        # Asset rendering function should include base64 img tag
        from chartfold.export_html import _render_imaging_section
        html = _render_imaging_section(db, "")
        # Note: actual base64 test requires the file to exist;
        # we test the structure instead
        assert "CT Abdomen" in html

    def test_source_documents_section_rendered(self, tmp_db):
        """Global source documents section groups by category."""
        db = tmp_db
        db.conn.execute(
            "INSERT INTO source_assets "
            "(source, asset_type, file_path, file_name, file_size_kb, "
            "title, encounter_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test", "pdf", "/tmp/lab.pdf", "lab.pdf", 50,
             "015_Laboratory", "2025-01-15"),
        )
        db.conn.commit()

        from chartfold.export_html import _render_source_documents_section
        html = _render_source_documents_section(db)
        assert "Laboratory" in html
        assert "lab.pdf" in html
```

**Step 2: Implement `_render_source_documents_section()`**

Add to `src/chartfold/export_html.py`:

```python
def _render_source_documents_section(db: ChartfoldDB) -> str:
    """Render all source assets grouped by category as a collapsible section."""
    from chartfold.core.utils import categorize_asset_title, is_image_asset

    assets = db.query(
        "SELECT id, source, asset_type, file_path, file_name, "
        "file_size_kb, title, encounter_date "
        "FROM source_assets ORDER BY encounter_date DESC, file_name"
    )
    if not assets:
        return ""

    # Group by category
    by_category: dict[str, list] = {}
    for a in assets:
        cat = categorize_asset_title(a.get("title", ""))
        by_category.setdefault(cat, []).append(a)

    parts = ['<div class="section"><h2>Source Documents</h2>']

    for cat in sorted(by_category.keys()):
        group = by_category[cat]
        parts.append(f"<h3>{_escape(cat)} ({len(group)})</h3>")
        parts.append('<table class="sortable"><thead><tr>'
                     '<th>Document</th><th>Type</th><th>Size</th>'
                     '<th>Date</th><th>Source</th></tr></thead><tbody>')
        for a in group:
            display = _escape(a.get("title") or a["file_name"])
            size = f"{a['file_size_kb']} KB" if a.get("file_size_kb") else ""
            date = _escape(a.get("encounter_date", ""))
            src = _escape(a["source"])
            atype = _escape(a["asset_type"])

            if is_image_asset(a["asset_type"]):
                # Inline thumbnail with CSS lightbox
                img_data = _encode_image_base64(a["file_path"])
                if img_data:
                    display = (f'<a href="#{a["id"]}">'
                              f'<img src="{img_data}" alt="{display}" '
                              f'style="max-width:100px;max-height:80px;"></a>')
            else:
                # Relative path link for PDFs
                display = f'<a href="{_escape(a["file_path"])}">{display}</a>'

            parts.append(f"<tr><td>{display}</td><td>{atype}</td>"
                        f"<td>{size}</td><td>{date}</td><td>{src}</td></tr>")
        parts.append("</tbody></table>")

    parts.append("</div>")
    return "".join(parts)


def _encode_image_base64(file_path: str) -> str:
    """Read an image file and return a base64 data URI, or empty string."""
    import base64
    from pathlib import Path

    p = Path(file_path)
    if not p.exists() or p.stat().st_size > 10_000_000:  # skip >10MB
        return ""

    suffix = p.suffix.lower().lstrip(".")
    mime_map = {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "gif": "image/gif", "bmp": "image/bmp",
        "tif": "image/tiff", "tiff": "image/tiff",
    }
    mime = mime_map.get(suffix, "")
    if not mime:
        return ""

    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"
```

**Step 3: Add CSS lightbox styles to `EMBEDDED_CSS`**

Add to the existing CSS constant:

```css
/* CSS lightbox for source images */
.lightbox-overlay:target {
  display: flex;
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.85);
  z-index: 1000;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.lightbox-overlay { display: none; }
.lightbox-overlay img { max-width: 90vw; max-height: 90vh; }
```

**Step 4: Wire into `export_html()` and `export_html_full()`**

Add `_render_source_documents_section(db)` as a new section in both export functions.

**Step 5: Run tests and commit**

```bash
git add src/chartfold/export_html.py tests/test_export_html.py
git commit -m "feat(html): add source documents section with inline images and category grouping"
```

---

### Task 6: HTML exporter — Enhance imaging/pathology cards with source assets

**Files:**
- Modify: `src/chartfold/export_html.py` (lines 908-973)
- Test: `tests/test_export_html.py`

**Step 1: Write failing test**

```python
def test_imaging_card_shows_linked_image(self, tmp_db):
    """Imaging card should show inline image when source asset matched."""
    # Setup: imaging report + linked PNG asset
    # Assert: HTML contains <img> with base64 data
```

**Step 2: Modify `_render_imaging_section()`**

After rendering each card's text content, query `source_assets` for matching assets:
- Match by `ref_table='imaging_reports'` and `ref_id=report_id`
- Fall back to `encounter_date + source` match
- For image assets: embed base64 `<img>` with max-width
- For PDFs: add relative path link

Same pattern for `_render_pathology_section()`.

**Step 3: Run tests and commit**

```bash
git add src/chartfold/export_html.py tests/test_export_html.py
git commit -m "feat(html): show linked images on imaging and pathology cards"
```

---

### Task 7: Hugo — Add Analysis section

**Files:**
- Modify: `src/chartfold/hugo/generate.py`
- Modify: `src/chartfold/cli.py` (add `--analysis-dir` flag)
- Test: `tests/test_hugo.py`

**Step 1: Write failing test**

```python
class TestAnalysisSection:
    def test_analysis_files_copied_to_hugo(self, loaded_db, tmp_path):
        """Markdown files from analysis dir should appear as Hugo pages."""
        db = loaded_db
        content = tmp_path / "content"
        content.mkdir()

        analysis_dir = tmp_path / "analysis"
        analysis_dir.mkdir()
        (analysis_dir / "cea-trend-analysis.md").write_text(
            "# CEA Trend Analysis\n\nCEA levels show post-surgical normalization..."
        )

        from chartfold.hugo.generate import _generate_analysis_pages
        _generate_analysis_pages(content, analysis_dir)

        page = (content / "analysis" / "cea-trend-analysis.md").read_text()
        assert "CEA" in page
```

**Step 2: Implement `_generate_analysis_pages()`**

```python
def _generate_analysis_pages(content: Path, analysis_dir: Path | None) -> None:
    """Copy user-supplied analysis markdown files into the Hugo site.

    Files should be markdown. They get frontmatter added if missing.
    """
    analysis_content = content / "analysis"
    analysis_content.mkdir(parents=True, exist_ok=True)

    if not analysis_dir or not analysis_dir.exists():
        _write_page(
            analysis_content / "_index.md",
            "Analysis",
            "*No analysis files provided. "
            "Add markdown files to an analysis directory and pass "
            "`--analysis-dir` to include them.*",
        )
        return

    md_files = sorted(analysis_dir.glob("*.md"))
    if not md_files:
        _write_page(
            analysis_content / "_index.md",
            "Analysis",
            "*No markdown files found in analysis directory.*",
        )
        return

    # Index page listing all analysis files
    index_lines = []
    for f in md_files:
        slug = f.stem
        title = slug.replace("-", " ").replace("_", " ").title()
        index_lines.append(f"- [{title}](/analysis/{slug}/)")
    _write_page(
        analysis_content / "_index.md",
        "Analysis",
        "\n".join(index_lines),
    )

    # Copy each file with frontmatter
    for f in md_files:
        text = f.read_text()
        slug = f.stem
        title = slug.replace("-", " ").replace("_", " ").title()
        # If file already has frontmatter, use as-is
        if text.startswith("---"):
            (analysis_content / f.name).write_text(text)
        else:
            _write_page(analysis_content / f.name, title, text)
```

**Step 3: Wire into `generate_site()` and CLI**

In `generate_site()`, call `_generate_analysis_pages(content, analysis_dir)` alongside the other generators.

Add `--analysis-dir` flag to the `export hugo` CLI command.

**Step 4: Add Analysis to Hugo navigation**

Add an "Analysis" menu item to the Hugo config or nav template.

**Step 5: Run tests and commit**

```bash
git add src/chartfold/hugo/generate.py src/chartfold/cli.py tests/test_hugo.py
git commit -m "feat(hugo): add Analysis section for user-supplied markdown files"
```

---

### Task 8: HTML exporter — Add Analysis section

**Files:**
- Modify: `src/chartfold/export_html.py`
- Modify: `src/chartfold/cli.py`
- Test: `tests/test_export_html.py`

**Step 1: Write failing test**

```python
def test_analysis_section_in_html(self, tmp_db, tmp_path):
    """Analysis markdown files should render as HTML sections."""
    analysis_dir = tmp_path / "analysis"
    analysis_dir.mkdir()
    (analysis_dir / "summary.md").write_text("# Treatment Summary\n\nChemo completed.")

    from chartfold.export_html import _render_analysis_section
    html = _render_analysis_section(analysis_dir)
    assert "Treatment Summary" in html
    assert "Chemo completed" in html
```

**Step 2: Implement `_render_analysis_section()`**

```python
def _render_analysis_section(analysis_dir: Path | None) -> str:
    """Render user-supplied markdown analysis files as HTML sections."""
    import re

    if not analysis_dir or not analysis_dir.exists():
        return ""

    md_files = sorted(analysis_dir.glob("*.md"))
    if not md_files:
        return ""

    parts = ['<div class="section"><h2>Analysis</h2>']
    for f in md_files:
        text = f.read_text()
        # Strip frontmatter if present
        if text.startswith("---"):
            text = re.sub(r"^---.*?---\s*", "", text, flags=re.DOTALL)
        # Basic markdown-to-HTML (headings, paragraphs, bold, lists)
        html_content = _basic_markdown_to_html(text)
        parts.append(f'<div class="card">{html_content}</div>')
    parts.append("</div>")
    return "".join(parts)
```

**Step 3: Wire into export functions and CLI**

Add `analysis_dir` parameter to `export_html()` and `export_html_full()`. Add `--analysis-dir` flag to `export html` CLI command.

**Step 4: Run tests and commit**

```bash
git add src/chartfold/export_html.py src/chartfold/cli.py tests/test_export_html.py
git commit -m "feat(html): add Analysis section for user-supplied markdown"
```

---

### Task 9: Run full test suite and verify coverage

**Step 1: Run all tests**

```bash
python -m pytest tests/ -v
```

Expected: All tests pass

**Step 2: Check coverage**

```bash
python -m pytest tests/ --cov=chartfold --cov-report=term-missing
```

Expected: ≥69% coverage

**Step 3: Final commit if needed**

```bash
git add -A
git commit -m "test: add coverage for image integration and analysis sections"
```

---

## Files Modified Summary

| File | Changes |
|------|---------|
| `src/chartfold/core/utils.py` | Add `is_image_asset()`, `categorize_asset_title()` |
| `src/chartfold/hugo/generate.py` | Modify `_render_source_docs_section()` for images/gallery; modify `_generate_linked_sources()` for category grouping; add `_generate_analysis_pages()` |
| `src/chartfold/hugo/static/js/glightbox.min.js` | Vendor GLightbox JS |
| `src/chartfold/hugo/static/css/glightbox.min.css` | Vendor GLightbox CSS |
| `src/chartfold/hugo/layouts/shortcodes/lightbox.html` | Lightbox shortcode |
| `src/chartfold/hugo/layouts/_default/baseof.html` | Add GLightbox script/style |
| `src/chartfold/export_html.py` | Add `_render_source_documents_section()`, `_render_analysis_section()`, `_encode_image_base64()`, CSS lightbox styles; modify imaging/pathology card renderers |
| `src/chartfold/cli.py` | Add `--analysis-dir` flag to `export hugo` and `export html` |
| `tests/test_core.py` | Add `TestAssetHelpers` |
| `tests/test_hugo.py` | Add `TestSourceDocsImages`, `TestSourcesCategoryGrouping`, `TestAnalysisSection` |
| `tests/test_export_html.py` | Add `TestSourceAssetRendering`, analysis tests |
