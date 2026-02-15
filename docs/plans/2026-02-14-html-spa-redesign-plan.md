# HTML5 SPA Export Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the static HTML export with a single-file SPA that embeds the SQLite database via sql.js (WebAssembly), providing a clinical dashboard with sidebar navigation, interactive charts, paginated tables, and a built-in SQL console.

**Architecture:** Python reads the chartfold.db file, gzip-compresses it, base64-encodes it, and embeds it in an HTML template alongside vendored sql.js (WASM+JS) and the application JS/CSS. The browser decodes and decompresses on load, then all UI rendering is driven by live SQL queries against the in-memory database. No external dependencies, no build step, single self-contained HTML file.

**Tech Stack:** Python 3.11+ (export), sql.js v1.14.0 (SQLite-to-WASM), vanilla JS (SPA), Canvas API (charts), CSS Grid/Flexbox (layout)

**Design Doc:** `docs/plans/2026-02-14-html-spa-redesign-design.md`

---

## File Structure

```
src/chartfold/spa/
    __init__.py
    export.py           # Python: read DB, gzip, base64, assemble HTML
    vendor/
        sql-wasm.js     # sql.js loader (from v1.14.0 release)
        sql-wasm.wasm   # sql.js WASM binary (from v1.14.0 release)
    js/
        app.js          # Entry point: init DB, start router
        db.js           # DB layer: decode, decompress, query wrapper
        router.js       # Sidebar nav + section switching
        ui.js           # Primitives: table, card, badge, pagination, el
        chart.js        # Canvas chart renderer with hover/tooltips
        markdown.js     # Minimal markdown-to-HTML converter
        sections.js     # All section renderers
    css/
        styles.css      # Apple Health-inspired stylesheet
tests/
    test_spa_export.py  # Python-side tests
```

The Python export reads all JS files from `js/` in dependency order, concatenates them into one `<script>` block, reads CSS from `css/styles.css`, and assembles the final HTML document.

---

### Task 1: Vendor sql.js and Create Package Structure

**Files:**
- Create: `src/chartfold/spa/__init__.py`
- Create: `src/chartfold/spa/vendor/` (download sql.js files)
- Test: manual verification

**Step 1: Create the spa package directory structure**

```bash
mkdir -p src/chartfold/spa/vendor src/chartfold/spa/js src/chartfold/spa/css
touch src/chartfold/spa/__init__.py
```

**Step 2: Download sql.js v1.14.0 WASM distribution**

```bash
cd src/chartfold/spa/vendor
curl -L -o sqljs-wasm.zip https://github.com/sql-js/sql.js/releases/download/v1.14.0/sqljs-wasm.zip
unzip sqljs-wasm.zip
rm sqljs-wasm.zip
ls -la sql-wasm.js sql-wasm.wasm
```

Expected: `sql-wasm.js` (~90KB) and `sql-wasm.wasm` (~800KB) present.

**Step 3: Verify sql.js works with a quick test**

Create a temporary test HTML file, open in browser, verify sql.js initializes. Delete the test file after.

**Step 4: Add vendor files to .gitignore or commit them**

Since these are vendored dependencies (not generated), commit them to the repo. Add a README note in the vendor directory:

Create `src/chartfold/spa/vendor/README.md`:
```markdown
# Vendored Dependencies

## sql.js v1.14.0
- Source: https://github.com/sql-js/sql.js/releases/tag/v1.14.0
- Files: sql-wasm.js, sql-wasm.wasm
- License: MIT
- Purpose: SQLite database engine compiled to WebAssembly for in-browser SQL queries
```

**Step 5: Commit**

```bash
git add src/chartfold/spa/
git commit -m "feat(spa): vendor sql.js v1.14.0 WASM distribution"
```

---

### Task 2: Python Export Foundation

**Files:**
- Create: `src/chartfold/spa/export.py`
- Create: `tests/test_spa_export.py`

This task builds the Python side: read DB, gzip, base64, embed in HTML template. The HTML will initially just show "Loading..." then "Database loaded with N tables" to prove the pipeline works end-to-end.

**Step 1: Write the failing test**

Create `tests/test_spa_export.py` with these tests:
- `test_generates_html_file` - export produces an HTML file
- `test_contains_sql_wasm_js` - HTML contains the sql.js loader
- `test_contains_embedded_wasm` - HTML contains base64 WASM in `id="sqljs-wasm"` tag
- `test_contains_embedded_db` - HTML contains gzipped+base64 DB in `id="chartfold-db"` tag
- `test_embedded_db_is_decodable` - extract base64, decode, decompress, verify SQLite header bytes
- `test_contains_app_js` - HTML contains application JS
- `test_contains_app_css` - HTML contains CSS

The decodability test should: extract the base64 string from the chartfold-db script tag, base64 decode it, gzip decompress it, and verify the first 16 bytes are `b"SQLite format 3\x00"`.

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_spa_export.py -v
```

**Step 3: Implement the export function**

Create `src/chartfold/spa/export.py` with function `export_spa(db_path, output_path, config_path="", analysis_dir="", embed_images=False)`:

1. Read DB file as bytes
2. Gzip compress with `gzip.compress(data, compresslevel=9)`
3. Base64 encode the compressed bytes
4. Read WASM binary, base64 encode it (no gzip - it's already compressed)
5. Read sql-wasm.js loader text
6. Concatenate all JS files from `js/` in dependency order
7. Read CSS from `css/styles.css`
8. Assemble HTML template with all data in script tags
9. Write to output file

Data embedding format in HTML:
```html
<script id="sqljs-wasm" type="application/base64">[base64 of WASM]</script>
<script id="chartfold-db" type="application/gzip+base64">[gzip+base64 of DB]</script>
<script id="chartfold-config" type="application/json">[config JSON]</script>
<script id="chartfold-analysis" type="application/json">[analysis JSON]</script>
<script id="chartfold-images" type="application/json">[images JSON]</script>
<script>[sql-wasm.js content]</script>
<script id="app-js">[concatenated app JS]</script>
```

Also implement helper functions:
- `_load_config_json(path)` - load TOML, convert to JSON string
- `_load_analysis_json(dir)` - load markdown files, strip frontmatter, return JSON array
- `_load_images_json(db_path)` - query source_assets, base64 encode image files, return JSON map keyed by asset ID

**Step 4: Create placeholder JS and CSS files**

Create minimal stubs for all JS files (`db.js`, `ui.js`, `markdown.js`, `chart.js`, `sections.js`, `router.js`, `app.js`) and `styles.css`. The `db.js` stub should contain the full DB initialization code (base64 decode, gzip decompress via DecompressionStream, sql.js init, query wrapper). The `app.js` stub should call DB.init() then display table names and counts to prove the pipeline works.

**Step 5: Run tests**

```bash
python -m pytest tests/test_spa_export.py -v
```

**Step 6: Manual smoke test in browser**

```bash
cd dev && python -c "from chartfold.spa.export import export_spa; export_spa('chartfold.db', 'spa_test.html')"
```

Open spa_test.html in browser. Should see table list with counts.

**Step 7: Commit**

```bash
git add src/chartfold/spa/ tests/test_spa_export.py
git commit -m "feat(spa): Python export foundation with embedded SQLite DB via sql.js"
```

---

### Task 3: CSS Layout + Sidebar Shell

**Files:**
- Modify: `src/chartfold/spa/css/styles.css`
- Modify: `src/chartfold/spa/js/app.js`

Build the full Apple Health-inspired layout: fixed top bar, fixed sidebar (240px left), and fluid content area.

**Color palette (CSS custom properties):**
- `--bg`: #f5f5f7, `--surface`: #ffffff, `--text`: #1d1d1f
- `--text-secondary`: #86868b, `--border`: #d2d2d7, `--accent`: #0071e3
- `--red`: #ff3b30, `--green`: #34c759, `--orange`: #ff9500

**CSS classes needed:**
- `.topbar` - fixed, 56px height, white with bottom border
- `.sidebar` - fixed left, 240px, scrollable, white with right border
- `.sidebar-item` - nav link with left border highlight when active
- `.content` - margin-left: 240px, margin-top: 56px, padded
- `.card-grid` - CSS grid, auto-fill minmax(180px, 1fr)
- `.card` - rounded white card with border
- `.clinical-card` - larger card for imaging/pathology/notes
- `.table-container` - overflow-x auto wrapper
- `table` - full width, rounded, sortable headers
- `.badge` variants: green, gray, red, blue, orange
- `.pagination` - flex centered with page buttons
- `.filter-bar` - flex wrapped row of filter controls
- `.chart-container` - white rounded card for charts
- `.sql-console` - textarea + run button styling
- `.analysis-content` - markdown rendering with nice typography
- Print media query: hide sidebar/topbar, full-width content
- Mobile (max-width 768px): sidebar slides, hamburger menu

**Update app.js** to render the layout shell:
- After DB.init(), build topbar with "Chartfold" title and generation date from load_log
- Build sidebar placeholder with section labels
- Build content area showing a simple "Welcome" message

**Verify in browser, commit.**

```bash
git commit -m "feat(spa): Apple Health-inspired layout with topbar, sidebar, content area"
```

---

### Task 4: UI Primitives

**Files:**
- Modify: `src/chartfold/spa/js/ui.js`

Build reusable UI components (~200-250 lines):

- `UI.el(tag, attrs, children)` - DOM element factory. Attrs: className, textContent, innerHTML, on* events, HTML attributes. Children: strings or elements.
- `UI.table(columns, rows, opts)` - sortable table. Columns: `[{key, label, format?}]`. Rows: array of objects. Opts: sortable (bool), onSort callback. Click header to toggle ascending/descending sort. Numeric detection for sort type.
- `UI.card(title, meta, body)` - clinical card component.
- `UI.badge(text, variant)` - pill badge. Variants: green, gray, red, blue, orange.
- `UI.pagination(total, pageSize, currentPage, onPage)` - page controls. Prev/Next buttons, page numbers (max 7 with ellipsis), "Page X of Y" info.
- `UI.filterBar(filters, onChange)` - filter row. Each filter: `{type: 'select'|'checkbox'|'date', label, key, options?}`. Calls onChange with filter state object.
- `UI.sparkline(values, width, height, color)` - tiny canvas line chart. No axes, just the line.
- `UI.empty(message)` - empty state placeholder with gray text.

**Verify by temporarily rendering a test table in app.js. Commit.**

```bash
git commit -m "feat(spa): UI primitives - table, card, badge, pagination, sparkline, filter bar"
```

---

### Task 5: Router + Sidebar Navigation

**Files:**
- Modify: `src/chartfold/spa/js/router.js`
- Modify: `src/chartfold/spa/js/app.js`

**Router implementation:**
- `Router.init(contentEl)` - store content element reference
- `Router.register(id, label, group, count, renderFn)` - register a section
- `Router.buildSidebar(sidebarEl)` - build nav items from registered sections
- `Router.navigate(sectionId)` - clear content, call renderFn, update sidebar active state, set URL hash
- On load, check `location.hash` to navigate to bookmarked section

**Sidebar sections to register (in order):**

Group "":
- overview: "Overview" (no count)

Group "Clinical":
- conditions: "Conditions" (COUNT from conditions)
- medications: "Medications" (COUNT from medications)
- labs: "Lab Results" (COUNT from lab_results)
- encounters: "Encounters" (COUNT from encounters)
- imaging: "Imaging" (COUNT from imaging_reports)
- pathology: "Pathology" (COUNT from pathology_reports)
- allergies: "Allergies" (COUNT from allergies)
- notes: "Clinical Notes" (COUNT from clinical_notes)
- procedures: "Procedures" (COUNT from procedures)
- vitals: "Vitals" (COUNT from vitals)
- immunizations: "Immunizations" (COUNT from immunizations)

Group "Tools":
- sources: "Source Documents" (COUNT from source_assets)
- analysis: "Analysis" (count of analysis entries)
- sql: "SQL Console" (no count, show icon)

**In app.js:** After DB.init(), register all sections with placeholder renderers (just show section name + count). Wire sidebar clicks. Default to overview.

**Verify clicking through sections in browser. Commit.**

```bash
git commit -m "feat(spa): sidebar router with section navigation and URL hash bookmarking"
```

---

### Task 6: Overview Dashboard

**Files:**
- Modify: `src/chartfold/spa/js/sections.js`

**Render three blocks:**

1. **Summary cards** - grid of count cards for each table (same query as sidebar counts, displayed as large-number cards)

2. **Key lab sparklines** - for each test in `config.key_tests.tests`, query recent values and render `UI.sparkline()`. Show test name + most recent value + sparkline. Click navigates to labs section.

3. **Alerts** - abnormal labs from last 30 days:
```sql
SELECT test_name, value, interpretation, result_date, source
FROM lab_results
WHERE interpretation IN ('H','L','HH','LL','HIGH','LOW','ABNORMAL','A')
  AND result_date >= date('now', '-30 days')
ORDER BY result_date DESC LIMIT 10
```

**Verify in browser. Commit.**

```bash
git commit -m "feat(spa): overview dashboard with summary cards, sparklines, and alerts"
```

---

### Task 7: Conditions + Medications Sections

**Files:**
- Modify: `src/chartfold/spa/js/sections.js`

**Conditions:**
- Query all, sort active first then by name
- Active conditions in a sortable table, resolved in collapsed details
- Status as badge (green=active, gray=resolved), ICD-10 as gray badge

**Medications:**
- Query all, group by status (Active, Discontinued, Completed)
- Active: clinical cards (name bold, sig below, route/dates as meta)
- Others: compact table
- Cross-source badge if same med name from multiple sources

**Commit.**

```bash
git commit -m "feat(spa): conditions with status badges + medications grouped by status"
```

---

### Task 8: Lab Trends Charts + Lab Results Table

**Files:**
- Modify: `src/chartfold/spa/js/chart.js`
- Modify: `src/chartfold/spa/js/sections.js`

**Chart renderer (chart.js) ~150 lines:**
- `Chart.line(canvas, datasets, opts)` - render line chart
- Features: time X-axis with date labels, Y-axis with gridlines, multiple datasets with colors, reference range shading (light band), data point circles, hover tooltip (positioned near cursor), responsive width

**Labs section has two sub-views via tabs: "Charts" and "Table"**

Charts sub-view:
- For each key test, query data grouped by source, render chart
- Show ref range note if ranges differ across sources

Table sub-view:
- Paginated (50 per page) sortable table
- Filter bar: test name dropdown, abnormal-only checkbox, date range
- Abnormal rows highlighted with subtle red background

**Commit.**

```bash
git commit -m "feat(spa): lab trend charts with tooltips and ref ranges + paginated filterable lab table"
```

---

### Task 9: Encounters + Imaging + Pathology

**Files:**
- Modify: `src/chartfold/spa/js/sections.js`

**Encounters:**
- Paginated table (20/page) sorted by date desc
- Type as badge, facility and provider as metadata

**Imaging:**
- Clinical cards sorted by date desc
- Modality badge, blue left-border on impression text
- Query linked assets from source_assets table

**Pathology:**
- Rich clinical cards with all structured fields
- Query linked assets

**Commit.**

```bash
git commit -m "feat(spa): encounters table + imaging and pathology cards with linked assets"
```

---

### Task 10: Remaining Clinical Sections

**Files:**
- Modify: `src/chartfold/spa/js/sections.js`

Implement simpler sections:
- Clinical Notes: cards with truncated content + "Show full" expand, search input
- Procedures: sortable table
- Vitals: sortable table
- Immunizations: sortable table
- Allergies: table (likely small)
- Social History: table
- Family History: table
- Mental Status: table
- Source Documents: grouped by date/category, collapsible groups, image thumbnails if embed_images

**Commit.**

```bash
git commit -m "feat(spa): notes, procedures, vitals, immunizations, allergies, history, sources"
```

---

### Task 11: Analysis Section + Markdown Renderer

**Files:**
- Modify: `src/chartfold/spa/js/markdown.js`
- Modify: `src/chartfold/spa/js/sections.js`

**Markdown renderer (~80 lines):**
Line-by-line parser supporting: headings, paragraphs, bold/italic/code inline, bullet and numbered lists, blockquotes, fenced code blocks, tables, links, horizontal rules.

**Analysis section:**
- Read from `chartfold-analysis` JSON block
- Render each file as expandable card with title and rendered markdown body
- If empty, show helpful message about --analysis-dir flag

**Commit.**

```bash
git commit -m "feat(spa): analysis section with markdown renderer for Claude Code output"
```

---

### Task 12: SQL Console

**Files:**
- Modify: `src/chartfold/spa/js/sections.js`

**Features:**
- Monospace textarea for SQL input
- "Run Query" button + Ctrl/Cmd+Enter keyboard shortcut
- Results as sortable table via UI.table()
- Query timing: "23 rows in 4ms"
- Error display in red for invalid SQL
- READ-ONLY enforcement: reject INSERT/UPDATE/DELETE/DROP/ALTER/CREATE
- Pre-loaded example query chips (clickable, fill textarea)
- Query history in sessionStorage (last 20 queries)

**Commit.**

```bash
git commit -m "feat(spa): interactive SQL console with examples, history, and read-only enforcement"
```

---

### Task 13: CLI Integration + Python Tests

**Files:**
- Modify: `src/chartfold/cli.py`
- Modify: `tests/test_spa_export.py`

**CLI changes:**
- `export html` now calls `export_spa()` by default
- Add `--classic` flag to use old `export_html.py` behavior
- Add `--embed-images` flag (SPA only)
- Pass config_path, analysis_dir, embed_images through

**Additional Python tests:**
- test_config_embedded_as_json - verify TOML is converted to JSON in output
- test_analysis_markdown_embedded - verify markdown files appear in JSON array
- test_embed_images_creates_json - verify image base64 map
- test_empty_database - export works with schema-only DB
- test_gzip_compression_reduces_size - verify DB is compressed
- test_missing_config_no_error - missing config file handled gracefully
- test_missing_analysis_dir_no_error - missing dir handled gracefully

**Run full test suite, commit.**

```bash
python -m pytest tests/ -v
git commit -m "feat(spa): CLI integration + comprehensive Python export tests"
```

---

### Task 14: Polish and Verification

**Files:**
- Various JS/CSS

**Items:**
- Global search input in topbar: filters current section's table/cards
- Print button in topbar: renders current section + triggers window.print()
- Mobile hamburger menu: toggles sidebar on narrow viewports
- Browser testing: Chrome, Firefox, Safari

**Full end-to-end verification:**
```bash
cd dev
python -m chartfold export html --full --db chartfold.db --output spa_full.html --config chartfold.toml
ls -lh spa_full.html
```

Open and verify all sections, charts, SQL console, navigation.

**Commit.**

```bash
git commit -m "feat(spa): polish - global search, print support, mobile responsive"
```

---

## Verification Checklist

After all tasks:

```bash
python -m pytest tests/ -v
```

Generate with real data and verify in browser:
- Loading spinner then dashboard
- Sidebar sections with counts
- Overview cards + sparklines + alerts
- Conditions grouped active/resolved
- Medications grouped by status
- Lab charts with hover + ref range bands
- Lab table pagination + filters
- Encounters table
- Imaging/pathology cards with linked assets
- Clinical notes with expand/collapse
- SQL console runs queries
- Analysis tab renders markdown
- URL hash navigation works
- Print hides sidebar
- Mobile hamburger works
