# Design: Inline Image & Source Asset Integration

## Goal

Show clinical images (radiology scans, pathology specimens) inline on Hugo site pages and in the HTML exporter, with smart categorization of all source assets.

## Current State

- **Hugo generator**: Source assets are copied to `static/sources/` and linked as download links. Images are never rendered inline.
- **HTML exporter**: Zero source asset integration — no images, no PDFs, no links.
- **Source assets DB**: 384 assets tracked (375 MEDITECH PDFs + CT scan PNGs + pathology TIFs + stylesheets). Discovery, metadata, and encounter linking all work.

## Design

### 1. Hugo — Inline Images with GLightbox

**Modify `_render_source_docs_section()`** to detect image asset types and render inline thumbnails instead of download links.

Image assets (png/jpg/jpeg/gif/bmp/tif/tiff):
```
{{< lightbox src="/sources/meditech/43_ct-scan.png" alt="CT scan - 2024-05-21" >}}
```

PDF assets stay as categorized links:
```
- [lab-report.pdf](/sources/meditech/42_lab-report.pdf) (Laboratory, 85 KB)
```

**GLightbox** (~11 KB JS + ~4 KB CSS): Added to Hugo theme. Provides click-to-zoom, gallery navigation (prev/next for multiple images), and keyboard support.

**Hugo shortcode** `layouts/shortcodes/lightbox.html`:
```html
<a href="{{ .Get "src" }}" class="glightbox" data-gallery="source-docs">
  <img src="{{ .Get "src" }}" alt="{{ .Get "alt" }}" style="max-width:300px; cursor:zoom-in;">
</a>
```

### 2. HTML Exporter — Source Assets Integration

**Single-file approach**: Images base64-encoded as `<img>` data URIs. PDFs linked by relative path with a note about portability.

**Imaging/pathology card enhancement**: Each card gets a "Source Documents" sub-section with matched assets (same matching logic as Hugo: ref_table/ref_id first, date+source fallback).

**CSS-only lightbox**: Uses `:target` pseudo-class for click-to-zoom overlay. No external JS needed.

**New "Source Documents" section**: Collapsible section at bottom with all assets grouped by category.

**Size budget**: ~15-20 MB total (images base64'd ~5-15 MB + existing content ~200 KB + Chart.js ~50 KB).

### 3. Gallery Grid for Multi-Image Pages

When a detail page has **3+ image assets**, render a CSS grid gallery:
```css
.asset-gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 1rem; }
```

GLightbox handles gallery navigation automatically via shared `data-gallery` attribute.

For 1-2 images: inline with lightbox, no grid.
For 0 images (PDFs only): categorized link list.

### 4. Smart Asset Categorization

MEDITECH folder structure encodes categories (015_Laboratory, 010_Surgical_Services, etc.). TOC enrichment stores this in the `title` field.

**Category extraction helper** `_categorize_asset(asset)`:
1. Check `title` for known MEDITECH categories
2. Fall back to `asset_type` mapping (pdf → "Documents", png/jpg → "Images")
3. Map to display-friendly labels

**Hugo Source Documents page** enhanced: group by category first, then by date.

**HTML exporter Source Documents section**: same layout, collapsible per category.

### Category mapping

| MEDITECH Folder | Display Label |
|----------------|---------------|
| 000_Admissions | Admissions |
| 002_Admissions | Admissions |
| 003_Consents | Consents |
| 006_Discharge_Transfer_Document | Discharge |
| 010_Surgical_Services | Surgical Services |
| 015_Laboratory | Laboratory |
| 018_Patient_Care_Notes | Patient Care Notes |
| 019_Medications | Medications |
| 020_Orders | Orders |
| (unknown) | General |

## Files Modified

| File | Changes |
|------|---------|
| `hugo/generate.py` | Modify `_render_source_docs_section()` for image detection + gallery. Modify `_generate_linked_sources()` for category grouping. Add GLightbox init. |
| `export_html.py` | New `_render_source_assets_section()`. Modify imaging/pathology renderers. CSS lightbox. Base64 image embedding. |
| `core/utils.py` or new module | `_categorize_asset()`, `_is_image_asset()` helpers |
| Hugo theme | `lightbox.html` shortcode, GLightbox JS/CSS, gallery CSS |
| Tests | Asset categorization, image detection, HTML asset rendering |

## Not in Scope

- DICOM viewer (jotted as future idea)
- PDF.js in-browser rendering
- PDF thumbnail generation
- Embedding PDFs in single-file HTML (too large at 196 MB total)
