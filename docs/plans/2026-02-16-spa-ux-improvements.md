# SPA UX Improvements — Clinical Utility First

**Date**: 2026-02-16
**Approach**: A — "Clinical Utility First"
**Goal**: Make the HTML SPA export more useful for clinical decision-making without visual redesign.

---

## 1. Analysis Section Overhaul

**Problem**: First analysis renders full markdown (~300 lines) in an expanded card, pushing all other content off screen. No metadata shown (category, status, tags, dates).

**Design**:
- All analyses render as **summary cards** (collapsed by default)
- Each card shows: title, category badge, status badge (current=green, archived=gray), date, summary text (from DB `summary` column)
- Tag chips shown below summary
- Click card to expand full markdown content via `<details>`
- Archived analyses grouped separately under a "Archived" heading (collapsed `<details>`)
- Query `frontmatter` JSON for status: `json_extract(frontmatter, '$.status')`

**Data flow**:
```
analyses table → query with category, summary, frontmatter → render cards
                                                            → json_extract status
                                                            → split current vs archived
```

## 2. Overview Dashboard Enhancement

**Problem**: Raw ISO timestamp in topbar, cards show only counts with no temporal context.

**Design**:
- Format `loaded_at` timestamp to human-readable: "Last updated: Feb 16, 2026"
- Each overview card shows latest record date below count (e.g., "156 results" + "Latest: Feb 5, 2026")
  - Query: `SELECT MAX(date_col) FROM table` per section
  - Date columns vary by table: `result_date`, `encounter_date`, `procedure_date`, `study_date`, etc.
- Add **Recent Activity** card below the card grid:
  - Last 10 events across labs, imaging, procedures, encounters
  - UNION query ordered by date DESC
  - Each row: date, event type badge, description, source
  - Clickable rows navigate to relevant section

## 3. Conditions: Fill Empty Names

**Problem**: ~15 rows have empty `condition_name` (MEDITECH records with only ICD-10 codes).

**Design**:
- In the conditions table renderer, when `condition_name` is empty/null:
  - Display ICD-10 code as the name text
  - Append a gray "code only" badge
- No backend changes needed — pure rendering logic

## 4. Medications: Cross-Source Reconciliation View

**Problem**: Duplicate medications from different sources shown as separate entries. No way to see discrepancies.

**Design**:
- Add a **third tab** "Reconciliation" alongside active medications and other status groups
- Group medications by normalized name (`name.toLowerCase().trim()`)
- For each group with >1 source:
  - Show medication name as header
  - Show per-source status as badges (e.g., "epic: Active" green, "meditech: Completed" gray)
  - Flag discrepancies with orange "Status differs" badge
- Groups with only 1 source shown in a simpler list below
- Tab bar: [Active Medications] [All Medications] [Reconciliation]

## 5. SQL Console: Schema Reference

**Problem**: SQL Console has 3 example query chips but no way to see table/column names when writing custom queries.

**Design**:
- Add a collapsible **"Schema Reference"** `<details>` block above the textarea
- On open, queries `sqlite_master` for all user tables, then `PRAGMA table_info(table)` for each
- Renders as compact list: table name (bold) followed by comma-separated column names with types
- Example rendering:
  ```
  lab_results (id INTEGER, test_name TEXT, value TEXT, value_numeric REAL, unit TEXT, ...)
  medications (id INTEGER, name TEXT, sig TEXT, route TEXT, status TEXT, ...)
  ```
- Cached after first render (schema doesn't change within a session)

## 6. Dark Mode

**Problem**: No dark mode support. CSS custom properties already in place.

**Design**:
- Add `@media (prefers-color-scheme: dark)` block to `styles.css`
- Override CSS custom properties:
  ```
  --bg: #1c1c1e
  --surface: #2c2c2e
  --text: #f5f5f7
  --text-secondary: #98989d
  --border: #38383a
  ```
- Chart tooltip, code blocks, and filter bar backgrounds also need dark overrides
- Canvas charts: text fill colors read from CSS variables via `getComputedStyle()`
  - Or: use hardcoded dark-friendly colors (simpler, charts already use `#86868b` for labels)
  - Decision: Keep chart colors hardcoded for now — they're already neutral enough

---

## Files Changed

| File | Change |
|------|--------|
| `src/chartfold/spa/js/sections.js` | Analysis overhaul, overview enhancement, conditions fix, medications reconciliation |
| `src/chartfold/spa/css/styles.css` | Dark mode `@media` block |
| `tests/test_spa_export.py` | Tests for new rendering behaviors |

## Not In Scope

- Visual redesign / layout changes
- Source documents section improvements (opaque filenames)
- Cross-linking between sections (imaging ↔ procedures)
- Sidebar icons
- Animation / transitions
