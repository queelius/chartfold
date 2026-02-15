# HTML5 SPA Export Redesign — Design Document

**Date:** 2026-02-14
**Status:** Approved

## Goal

Replace the current static HTML export with a data-driven single-page application that embeds the SQLite database directly in the browser using sql.js (SQLite compiled to WebAssembly). The result is a single, self-contained HTML file that provides a clinical dashboard UI, full SQL queryability, and a built-in SQL console.

## Design Philosophy

Chartfold is intentionally "dumb" — it stores raw clinical data and provides queryability. Intelligence lives in Claude Code (via MCP). The HTML export serves two roles:

1. **Raw data browser** — a well-organized, searchable interface for exploring clinical data
2. **Analysis host** — renders markdown files produced by Claude Code sessions alongside the data

The export must remain a **single self-contained HTML file** for portability (pagevault password protection, email, local viewing).

## Architecture: Embedded SQLite via sql.js

### Data Flow

```
Python (export_html.py)                Browser (JS)

1. Read chartfold.db as bytes         4. Decode base64 to bytes
2. gzip compress                      5. Decompress gzip (DecompressionStream)
3. base64 encode                      6. new SQL.Database(uint8array)
4. Embed in HTML template             7. db.exec("SELECT ...") per view
                                      8. User navigates - SQL on demand
                                      9. SQL Console - arbitrary queries
```

### Why SQLite Instead of JSON

| Dimension | JSON blob | Embedded SQLite |
|-----------|-----------|-----------------|
| Python export code | Serialize each table (~200 lines) | gzip+base64 of db bytes (~5 lines) |
| Adding new tables | Update serializer + JS renderer | Zero changes |
| Query flexibility | JS array filter/sort | Full SQL in browser |
| Data fidelity | Whatever we serialize | Perfect — actual DB |
| MCP parity | Separate code paths | Same SQL queries |
| Interactive SQL | Hard | Trivial textarea |

### Size Budget

| Component | Raw | Gzipped+Base64 |
|-----------|-----|----------------|
| sql.js WASM | ~1.2 MB | ~550 KB |
| SQLite DB (typical) | ~2-5 MB | ~800 KB - 2 MB |
| JS app + CSS | ~50 KB | ~50 KB (inline) |
| **Total** | | **~1.4 - 2.6 MB** |

Gzip compression is key: SQLite DBs compress 60-70% due to repetitive text (test names, source names, dates). The browser decompresses using the native DecompressionStream API (zero-library) or a small inline decompressor as fallback.

### Loading Sequence

1. HTML loads, shows skeleton/spinner
2. JS decodes base64 WASM, initializes sql.js engine (~200ms)
3. JS decodes base64 DB, decompresses gzip, opens DB (~100ms)
4. JS queries overview counts, renders dashboard
5. User navigates — sections render on demand via SQL

## Layout and Navigation

```
+--------------------------------------------------+
|  Chartfold    Patient Name    Generated: date     |  Top bar (fixed)
+------------+-------------------------------------+
|            |                                     |
|  Overview  |                                     |
|  -----     |     [Active Section Content]        |
|  Conditions|                                     |
|  Meds   94 |     Tables, cards, charts           |
|  Labs  1650|     rendered via SQL queries         |
|  Encounters|                                     |
|  Imaging 40|                                     |
|  Pathology |                                     |
|  Allergies |                                     |
|  Notes  158|                                     |
|  Procedures|                                     |
|  Vitals 306|                                     |
|  Immunize  |                                     |
|  -----     |                                     |
|  Sources   |                                     |
|  Analysis  |                                     |
|  SQL       |                                     |
|            |                                     |
+------------+-------------------------------------+
```

- **Sidebar** (240px, fixed left): Section links with record counts, active section highlighted with blue left border. Collapsible on mobile via hamburger.
- **Top bar** (fixed): App name, patient context, generation date.
- **Content area** (fluid, scrollable): Only active section rendered in DOM.

### Color Palette (Apple Health / Clinical Dashboard)

- Background: #f5f5f7 (Apple gray)
- Cards/content: #ffffff
- Sidebar: #ffffff with right border
- Primary accent: #0071e3 (Apple blue)
- Text: #1d1d1f (near-black)
- Secondary text: #86868b
- Abnormal/alert: #ff3b30 (Apple red)
- Normal/good: #34c759 (Apple green)

## JS Component Architecture

```
+---------------------------------------------+
|  Router                                      |
|  Maps sidebar clicks to section renderers    |
+---------------------------------------------+
|  Section Renderers                           |
|  overview(), conditions(), labs(),           |
|  encounters(), imaging(), pathology(),       |
|  medications(), notes(), procedures(),       |
|  vitals(), immunizations(), sources(),       |
|  analysis(), sqlConsole()                    |
+---------------------------------------------+
|  UI Primitives                               |
|  table(cols, rows, opts)  card(title, body)  |
|  chart(canvas, datasets)  badge(text, color) |
|  pagination(total, page)  markdown(text)     |
+---------------------------------------------+
|  DB Layer                                    |
|  query(sql, params) -> [{...}, ...]          |
|  (thin wrapper around sql.js)                |
+---------------------------------------------+
```

Each section renderer: (db, containerEl, config) -> void. Runs SQL, builds DOM with primitives, appends to container. Pure function, testable.

## Section Designs

### Overview (Dashboard Landing)

- Summary cards in a grid: record counts per table
- Recent activity: last 5 encounters/results as mini-timeline
- Key lab sparklines: tiny trend lines for configured key_tests (click goes to full chart)
- Alerts: abnormal labs from last 30 days, flagged prominently

### Conditions

- Table with status badges (Active = green pill, Resolved = gray)
- Grouped: active first, resolved collapsed
- ICD-10 codes as subtle gray badges

### Medications

- Grouped by status: Active, then Discontinued, then Completed
- Card layout per medication: name bold, sig underneath, route/dates as metadata
- Cross-source indicator if same med from multiple sources

### Lab Trends (Charts)

- Canvas-based line charts (custom renderer, improved from current)
- Hover tooltips: exact value + date + source on mouseover
- Reference range shading: light band showing normal range
- Date axis labels and source legend
- Clickable points link to lab table

### Lab Results Table

- Paginated: 50 per page with page controls
- Filter bar: test name dropdown, abnormal-only toggle, date range
- Sticky column headers
- Abnormal row highlighting: subtle background tint

### Encounters

- Timeline view: vertical timeline with cards, grouped by date
- Provider, facility, type as metadata; reason as body text
- Expandable to show linked notes, imaging, procedures from that date

### Imaging and Pathology

- Richer cards with clear visual hierarchy
- Linked asset thumbnails on card (existing feature)
- Impression text with blue left border accent

### Clinical Notes

- Compact list: type/author/date, expandable to full text
- Search within notes

### Source Documents

- Grouped by date, then category within date
- Collapsible groups (not 144 flat rows)

### Analysis (Claude Code Output)

- First-class tab in sidebar
- Markdown rendered with good typography
- Multiple analysis files as sub-sections or accordion
- Embedded via --analysis-dir CLI flag

### SQL Console

- Monospace textarea for query input
- Run button + Ctrl+Enter shortcut
- Results rendered as sortable table
- Query history (sessionStorage)
- Pre-loaded example query chips: "Recent abnormal labs", "Active meds", "Encounter timeline"

## Image / Asset Handling

- **Default**: File path links (works when viewing locally)
- **--embed-images flag**: Base64 encode images into a separate script block as JSON. Keyed by asset ID. JS looks up base64 data when rendering cards.
- DB stores file_path references, not binary blobs — keeps DB clean
- Recognized image formats: PNG, JPG, JPEG, GIF, BMP, TIF, TIFF

## Configuration

Reads chartfold.toml for:
- key_tests — which lab tests get sparklines and trend charts
- key_tests.aliases — cross-source test name normalization
- Future: section ordering, default filters, dashboard layout

## Print Support

- Print CSS renders all visible sections to DOM, hides sidebar
- Sidebar becomes table of contents in print
- Print button in top bar triggers window.print()

## Constraints

- **Single file**: All CSS, JS, WASM, and data inline. No external dependencies.
- **Offline**: No network requests. Works from local filesystem.
- **pagevault compatible**: Can be password-protected for sharing.
- **No build step**: The JS is vanilla — no React, no bundler, no npm. Python generates the complete file.
