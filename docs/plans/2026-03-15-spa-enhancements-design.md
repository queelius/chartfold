# SPA Enhancements Design (v1.3)

**Date:** 2026-03-15
**Scope:** Three new features for the HTML SPA export

## Feature 5: Print Summary Section

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
- `@media print` CSS hides sidebar, nav, header — shows only the summary content
- Formatted for one printed page: compact tables, smaller fonts, no decorative elements

**Changes:**
- `sections.js`: Add `Sections.print_summary` function
- `app.js`: Add sidebar entry `{ id: "print_summary", label: "Print Summary", table: null, group: "Tools" }`
- `chat.css` or `styles.css`: Add `@media print` rules for the summary section

**No Python changes.** Data is already in the embedded database.

## Feature 3: Visit Prep Section

**Problem:** The MCP server has `get_visit_prep` and `get_visit_diff`, but the HTML SPA doesn't surface this functionality. Patients can't see "what's new since my last visit" in the exported file.

**Solution:** A new "Visit Prep" sidebar section with auto-detected date.

**Behavior:**
1. On load, query `SELECT MAX(encounter_date) FROM encounters` to find the most recent encounter
2. Pre-fill a date input with that date
3. Render a diff of everything new since that date:
   - New lab results (table: test, value, date, source)
   - New encounters (date, type, facility)
   - New/changed medications (name, status, start_date)
   - New imaging reports (study, date)
   - New clinical notes (date, type, author)
4. Each category is a subsection with a count badge
5. Date input is editable — changing it re-queries and re-renders

**Queries mirror `analysis/visit_diff.py` but run client-side:**
```sql
SELECT * FROM lab_results WHERE result_date > ? ORDER BY result_date DESC
SELECT * FROM encounters WHERE encounter_date > ? ORDER BY encounter_date DESC
SELECT * FROM medications WHERE start_date > ? ORDER BY start_date DESC
SELECT * FROM imaging_reports WHERE study_date > ? ORDER BY study_date DESC
SELECT * FROM clinical_notes WHERE note_date > ? ORDER BY note_date DESC
```

**Changes:**
- `sections.js`: Add `Sections.visit_prep` function
- `app.js`: Add sidebar entry in the "Tools" group

**No Python changes.** All queries run against the embedded sql.js database.

## Feature 2: Inline Charts in Chat

**Problem:** The AI chat returns text-only responses. When a user asks "show me my CEA trend," they get a text table instead of a visual chart. The SPA already has `ChartRenderer.line()` for rendering canvas charts.

**Solution:** Add a `render_chart` tool to the chat agent loop.

**Tool schema:**
```json
{
  "name": "render_chart",
  "description": "Render a line chart inline in the chat. Use after querying time-series lab data.",
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
2. `_executeRenderChart(input)` creates a canvas element, calls `ChartRenderer.line()` with a single dataset built from `input.data`
3. The canvas is wrapped in a `chat-chart` div and appended to `messagesEl`
4. Tool returns `"Chart rendered: {title}"` so the LLM knows it succeeded

**System prompt update:** Add a brief section describing the `render_chart` tool and when to use it (time-series lab data, medication timelines, etc.).

**Changes:**
- `chat.js`: Add `render_chart` tool definition to `_agentLoop`, add `_executeRenderChart` method, render chart inline in message area
- `chat_prompt.py`: Add chart tool description to system prompt
- `chat.css`: Add `.chat-chart` styling (width constraints, margin)

## Testing Strategy

**Feature 5 (Print Summary):**
- Test in `test_spa_export.py` that `print_summary` appears in the exported HTML
- Test that `@media print` rules exist in the CSS

**Feature 3 (Visit Prep):**
- Test in `test_spa_export.py` that `visit_prep` appears in the exported HTML

**Feature 2 (Inline Charts):**
- Test in `test_spa_export.py` that `render_chart` appears in the ai_chat HTML export
- Test in `test_chat_prompt.py` that the system prompt mentions `render_chart`

All features are JS-only (except the system prompt update) and follow the existing structural test pattern — verify presence in exported HTML.

## Files Changed

| File | Feature | Change |
|------|---------|--------|
| `src/chartfold/spa/js/sections.js` | 5, 3 | Add `print_summary` and `visit_prep` sections |
| `src/chartfold/spa/js/app.js` | 5, 3 | Add sidebar entries |
| `src/chartfold/spa/css/styles.css` | 5 | `@media print` rules for summary |
| `src/chartfold/spa/js/chat.js` | 2 | Add `render_chart` tool + `_executeRenderChart` |
| `src/chartfold/spa/css/chat.css` | 2 | `.chat-chart` inline chart styling |
| `src/chartfold/spa/chat_prompt.py` | 2 | Add chart tool to system prompt |
| `tests/test_spa_export.py` | 5, 3, 2 | Structural tests for all 3 features |
| `tests/test_chat_prompt.py` | 2 | Test render_chart in system prompt |
