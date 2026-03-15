# SPA Enhancements Design (v1.3)

**Date:** 2026-03-15
**Scope:** Three new features for the HTML SPA export

## Feature 1: Print Summary Section

**Problem:** Patients need a concise printable summary to hand to a new doctor or bring to an appointment. The current SPA has no print-optimized view.

**Solution:** A new "Print Summary" sidebar section.

**Content (all queried from sql.js at render time):**
- Patient demographics (name, DOB)
- Active medications (from `medications` where status is active or no stop_date)
- Recent labs with trend indicators (↑↓→ comparing last two values per test)
- Active conditions
- Last 3 encounters (date, type, facility)

**UI:**
- Renders like any other SPA section (uses `UI.el`, `UI.sectionHeader`, `UI.table`)
- "Print" button at the top calls `window.print()`
- Existing `@media print` in `styles.css` already hides sidebar/nav/header. Only compact formatting rules for the summary content are needed (smaller fonts, one-page layout).

**Changes:**
- `sections.js`: Add `Sections.print_summary` function
- `app.js`: Add sidebar entry `{ id: "print_summary", label: "Print Summary", table: null, group: "Tools" }`
- `styles.css`: Add `@media print` rules for compact summary formatting (not sidebar hiding — already handled)

**No Python changes.** Data is already in the embedded database.

## Feature 2: Visit Prep Section

**Problem:** The MCP server has `get_visit_prep` and `get_visit_diff`, but the HTML SPA doesn't surface this functionality. Patients can't see "what's new since my last visit" in the exported file.

**Solution:** A new "Visit Prep" sidebar section with auto-detected date.

**Behavior:**
1. On load, query `SELECT MAX(encounter_date) FROM encounters` to find the most recent encounter
2. Pre-fill a date input with that date (handle empty encounters table — default to 6 months ago)
3. Render a diff of everything new since that date:
   - New lab results (test_name, value, unit, result_date, source)
   - New encounters (encounter_date, encounter_type, facility)
   - New/changed medications (name, status, start_date, stop_date — `WHERE start_date >= ? OR stop_date >= ?`)
   - New imaging reports (study_name, study_date, source)
   - New clinical notes (note_date, note_type, author, `SUBSTR(content, 1, 200)`)
   - New conditions (condition_name, onset_date, source)
   - New procedures (name, procedure_date, source)
   - New pathology reports (report_date, specimen, source)
   - New genetic variants (gene, variant_type, classification, collection_date)
4. Each category is a subsection with a count badge, only shown if count > 0
5. Date input is editable — changing it re-queries and re-renders

**Queries use `>=` to match `visit_diff.py` semantics** (includes same-day data):
```sql
SELECT test_name, value, unit, result_date, source FROM lab_results WHERE result_date >= ? ORDER BY result_date DESC
SELECT encounter_date, encounter_type, facility, source FROM encounters WHERE encounter_date >= ? ORDER BY encounter_date DESC
SELECT name, status, start_date, stop_date, source FROM medications WHERE start_date >= ? OR stop_date >= ? ORDER BY start_date DESC
SELECT study_name, study_date, source FROM imaging_reports WHERE study_date >= ? ORDER BY study_date DESC
SELECT note_date, note_type, author, SUBSTR(content, 1, 200) AS preview FROM clinical_notes WHERE note_date >= ? ORDER BY note_date DESC
SELECT condition_name, onset_date, source FROM conditions WHERE onset_date >= ? ORDER BY onset_date DESC
SELECT name, procedure_date, source FROM procedures WHERE procedure_date >= ? ORDER BY procedure_date DESC
SELECT report_date, specimen, source FROM pathology_reports WHERE report_date >= ? ORDER BY report_date DESC
SELECT gene, variant_type, classification, collection_date FROM genetic_variants WHERE collection_date >= ? ORDER BY collection_date DESC
```

**Changes:**
- `sections.js`: Add `Sections.visit_prep` function
- `app.js`: Add sidebar entry in the "Tools" group

**No Python changes.** All queries run against the embedded sql.js database.

## Feature 3: Inline Charts in Chat

**Problem:** The AI chat returns text-only responses. When a user asks "show me my CEA trend," they get a text table instead of a visual chart. The SPA already has `ChartRenderer.line()` for rendering canvas charts.

**Solution:** Add a `render_chart` tool to the chat agent loop.

**Tool schema:**
```json
{
  "name": "render_chart",
  "description": "Render a line chart inline in the chat. Use after querying time-series lab data to visualize trends.",
  "input_schema": {
    "type": "object",
    "properties": {
      "title": { "type": "string", "description": "Chart title" },
      "y_label": { "type": "string", "description": "Y-axis label (units)" },
      "data": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "date": { "type": "string", "description": "ISO date (YYYY-MM-DD)" },
            "value": { "type": "number" },
            "source": { "type": "string" }
          },
          "required": ["date", "value"]
        }
      },
      "ref_range": {
        "type": "object",
        "properties": {
          "low": { "type": "number" },
          "high": { "type": "number" }
        }
      }
    },
    "required": ["title", "data"]
  }
}
```

**Rendering flow:**
1. LLM calls `render_chart` with structured data
2. `_executeRenderChart(input)` maps tool input to ChartRenderer format:
   - Each `{date, value, source}` → `{x: date, y: value, source: source}` (ChartRenderer expects `pt.x` and `pt.y`)
   - `input.y_label` → `opts.yLabel`
   - `input.ref_range` → `opts.refRange`
3. Creates a canvas element, calls `ChartRenderer.line(canvas, [dataset], opts)`
4. Renders a title above the chart, wraps both in a `chat-chart` div, appends to `messagesEl`
5. Tool returns `"Chart rendered: {title}"` so the LLM knows it succeeded

**System prompt update:** Add a brief section describing the `render_chart` tool and when to use it (time-series lab data, trends over time). Instruct the LLM to first query the data with `run_sql`, then call `render_chart` with the results.

**Changes:**
- `chat.js`: Add `render_chart` tool definition to `_agentLoop`, add `_executeRenderChart` method, render chart inline in message area
- `chat_prompt.py`: Add chart tool description to system prompt
- `chat.css`: Add `.chat-chart` styling (width constraints, margin)

## Testing Strategy

**Feature 1 (Print Summary):**
- Test in `test_spa_export.py` that `print_summary` appears in the exported HTML
- Test that print button exists in the HTML

**Feature 2 (Visit Prep):**
- Test in `test_spa_export.py` that `visit_prep` appears in the exported HTML
- Test that the visit prep queries are present in the JS

**Feature 3 (Inline Charts):**
- Test in `test_spa_export.py` that `render_chart` appears in the ai_chat HTML export
- Test in `test_chat_prompt.py` that the system prompt mentions `render_chart`

All features are JS-only (except the system prompt update) and follow the existing structural test pattern — verify presence in exported HTML.

## Files Changed

| File | Feature | Change |
|------|---------|--------|
| `src/chartfold/spa/js/sections.js` | 1, 2 | Add `print_summary` and `visit_prep` sections |
| `src/chartfold/spa/js/app.js` | 1, 2 | Add sidebar entries |
| `src/chartfold/spa/css/styles.css` | 1 | `@media print` compact formatting for summary |
| `src/chartfold/spa/js/chat.js` | 3 | Add `render_chart` tool + `_executeRenderChart` |
| `src/chartfold/spa/css/chat.css` | 3 | `.chat-chart` inline chart styling |
| `src/chartfold/spa/chat_prompt.py` | 3 | Add chart tool to system prompt |
| `tests/test_spa_export.py` | 1, 2, 3 | Structural tests for all 3 features |
| `tests/test_chat_prompt.py` | 3 | Test render_chart in system prompt |
