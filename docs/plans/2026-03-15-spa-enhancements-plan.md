# SPA Enhancements Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add print summary section, visit prep section, and inline charts in AI chat to the HTML SPA export.

**Architecture:** Three independent features. Features 1-2 are new SPA sections (JS only). Feature 3 extends the AI chat agent loop with a second tool and updates the system prompt (JS + Python).

**Tech Stack:** JavaScript (vanilla, existing SPA patterns — `UI.el`, `UI.table`, `DB.query`), Python (chat_prompt.py), CSS, pytest.

**Design doc:** `docs/plans/2026-03-15-spa-enhancements-design.md`

---

## Chunk 1: Print Summary + Visit Prep Sections

### Task 1: Print Summary Section

**Files:**
- Modify: `src/chartfold/spa/js/sections.js` (add `print_summary` function before closing `};`)
- Modify: `src/chartfold/spa/js/app.js:34` (add sidebar entry)
- Modify: `src/chartfold/spa/css/styles.css:601` (add print summary `@media print` rules)
- Modify: `tests/test_spa_export.py` (add tests to `TestAiChatExport` or new class)

**Context:** Sections follow a pattern: `function(el, db)` receives the content container and the DB object. Query data with `db.query(sql)`, render with `UI.el()`, `UI.table()`, `UI.sectionHeader()`. Sidebar entries in `app.js` are objects `{ id, label, table, group }` where `id` must match the `Sections[id]` key.

- [ ] **Step 1: Write failing test**

Add to `tests/test_spa_export.py`:

```python
class TestPrintSummary:
    """Tests for the print summary section."""

    def test_print_summary_in_sidebar(self, exported_html):
        assert "print_summary" in exported_html

    def test_print_summary_section_exists(self, exported_html):
        assert "Sections.print_summary" in exported_html
        # Python-style function definition won't exist; check for the section key pattern
        # Actually sections use: print_summary: function(el, db)
        # But exported_html contains concatenated JS where this pattern lives

    def test_print_button_in_section(self, exported_html):
        assert "window.print()" in exported_html
```

Note: `exported_html` fixture already exists in the test file (default export without ai_chat).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_spa_export.py::TestPrintSummary -v`

- [ ] **Step 3: Add sidebar entry in app.js**

In `src/chartfold/spa/js/app.js`, add after the `ask_ai` entry (line 35):

```javascript
      { id: "print_summary", label: "Print Summary", table: null, group: "Tools" },
      { id: "visit_prep",    label: "Visit Prep",    table: null, group: "Tools" },
```

- [ ] **Step 4: Add `Sections.print_summary` in sections.js**

Add before the closing `};` of the `Sections` object (before `ask_ai`, around line 1716):

```javascript
  print_summary: function(el, db) {
    el.appendChild(UI.sectionHeader('Print Summary', 'One-page summary for your doctor'));

    // Print button
    el.appendChild(UI.el('button', {
      className: 'chat-send-btn',
      textContent: 'Print This Page',
      style: 'margin-bottom: 16px;',
      onClick: function() { window.print(); }
    }));

    // Patient demographics
    var patient = db.queryOne('SELECT name, date_of_birth, gender FROM patients LIMIT 1');
    if (patient) {
      el.appendChild(UI.el('h3', { textContent: 'Patient', className: 'print-section-title' }));
      var items = [];
      if (patient.name) items.push('Name: ' + patient.name);
      if (patient.date_of_birth) items.push('DOB: ' + patient.date_of_birth);
      if (patient.gender) items.push('Gender: ' + patient.gender);
      el.appendChild(UI.el('p', { textContent: items.join(' | ') }));
    }

    // Active conditions
    try {
      var conditions = db.query('SELECT condition_name, icd10_code FROM conditions ORDER BY condition_name');
      if (conditions.length > 0) {
        el.appendChild(UI.el('h3', { textContent: 'Active Conditions (' + conditions.length + ')', className: 'print-section-title' }));
        el.appendChild(UI.table([
          { label: 'Condition', key: 'condition_name' },
          { label: 'ICD-10', key: 'icd10_code' }
        ], conditions));
      }
    } catch (e) { /* table may not exist */ }

    // Active medications
    try {
      var meds = db.query("SELECT name, dose, frequency, status FROM medications WHERE status IS NULL OR LOWER(status) = 'active' OR stop_date IS NULL ORDER BY name");
      if (meds.length > 0) {
        el.appendChild(UI.el('h3', { textContent: 'Active Medications (' + meds.length + ')', className: 'print-section-title' }));
        el.appendChild(UI.table([
          { label: 'Medication', key: 'name' },
          { label: 'Dose', key: 'dose' },
          { label: 'Frequency', key: 'frequency' }
        ], meds));
      }
    } catch (e) { /* ignore */ }

    // Recent labs — last value per test with trend
    try {
      var labs = db.query(
        "SELECT l1.test_name, l1.value, l1.unit, l1.result_date, l1.source " +
        "FROM lab_results l1 " +
        "INNER JOIN (SELECT test_name, MAX(result_date) AS max_date FROM lab_results GROUP BY test_name) l2 " +
        "ON l1.test_name = l2.test_name AND l1.result_date = l2.max_date " +
        "ORDER BY l1.test_name"
      );
      if (labs.length > 0) {
        // Get prior values for trend arrows
        var priorMap = {};
        try {
          var priors = db.query(
            "SELECT l1.test_name, l1.value_numeric " +
            "FROM lab_results l1 " +
            "INNER JOIN (" +
            "  SELECT test_name, MAX(result_date) AS max_date FROM lab_results " +
            "  WHERE (test_name, result_date) NOT IN " +
            "    (SELECT test_name, MAX(result_date) FROM lab_results GROUP BY test_name) " +
            "  GROUP BY test_name" +
            ") l2 ON l1.test_name = l2.test_name AND l1.result_date = l2.max_date"
          );
          for (var pi = 0; pi < priors.length; pi++) {
            priorMap[priors[pi].test_name] = priors[pi].value_numeric;
          }
        } catch (e) { /* ignore */ }

        el.appendChild(UI.el('h3', { textContent: 'Recent Labs (' + labs.length + ')', className: 'print-section-title' }));
        el.appendChild(UI.table([
          { label: 'Test', key: 'test_name' },
          { label: 'Value', key: 'value' },
          { label: 'Unit', key: 'unit' },
          { label: 'Trend', key: 'test_name', format: function(testName, row) {
            var current = parseFloat(row.value);
            var prior = priorMap[testName];
            if (prior == null || isNaN(current) || isNaN(prior)) return '';
            if (current > prior * 1.05) return '\u2191';  // ↑
            if (current < prior * 0.95) return '\u2193';  // ↓
            return '\u2192';  // →
          }},
          { label: 'Date', key: 'result_date' },
          { label: 'Source', key: 'source' }
        ], labs));
      }
    } catch (e) { /* ignore */ }

    // Recent encounters
    try {
      var encounters = db.query('SELECT encounter_date, encounter_type, facility, source FROM encounters ORDER BY encounter_date DESC LIMIT 3');
      if (encounters.length > 0) {
        el.appendChild(UI.el('h3', { textContent: 'Recent Encounters', className: 'print-section-title' }));
        el.appendChild(UI.table([
          { label: 'Date', key: 'encounter_date' },
          { label: 'Type', key: 'encounter_type' },
          { label: 'Facility', key: 'facility' },
          { label: 'Source', key: 'source' }
        ], encounters));
      }
    } catch (e) { /* ignore */ }
  },
```

- [ ] **Step 5: Add print-specific CSS in styles.css**

Add after the existing `@media print` block (line 601) in `src/chartfold/spa/css/styles.css`:

```css
/* Print Summary compact formatting */
.print-section-title {
  font-size: 14px;
  margin: 12px 0 4px;
  padding-bottom: 2px;
  border-bottom: 1px solid #ccc;
}

@media print {
  .print-section-title {
    font-size: 12px;
    margin: 8px 0 2px;
  }
  .chat-send-btn { display: none !important; }
}
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_spa_export.py -v`
Expected: All pass.

- [ ] **Step 7: Commit**

```
feat: add print summary section to SPA

One-page printable view with demographics, active conditions,
active meds, recent labs with trend arrows, and last 3 encounters.
```

---

### Task 2: Visit Prep Section

**Files:**
- Modify: `src/chartfold/spa/js/sections.js` (add `visit_prep` function)
- Modify: `tests/test_spa_export.py`

Sidebar entry was already added in Task 1.

- [ ] **Step 1: Write failing test**

Add to `tests/test_spa_export.py`:

```python
class TestVisitPrep:
    """Tests for the visit prep section."""

    def test_visit_prep_in_sidebar(self, exported_html):
        assert "visit_prep" in exported_html

    def test_visit_prep_section_exists(self, exported_html):
        assert "visit_prep" in exported_html
        assert "encounter_date" in exported_html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_spa_export.py::TestVisitPrep -v`

- [ ] **Step 3: Add `Sections.visit_prep` in sections.js**

Add before `print_summary` in the Sections object:

```javascript
  visit_prep: function(el, db) {
    el.appendChild(UI.sectionHeader('Visit Prep', "What's new since your last visit"));

    // Auto-detect most recent encounter date
    var sinceDate = '';
    try {
      var maxRow = db.queryOne('SELECT MAX(encounter_date) AS d FROM encounters');
      if (maxRow && maxRow.d) sinceDate = maxRow.d;
    } catch (e) { /* ignore */ }

    // Fallback: 6 months ago
    if (!sinceDate) {
      var d = new Date();
      d.setMonth(d.getMonth() - 6);
      sinceDate = d.toISOString().slice(0, 10);
    }

    // Date input
    var dateInput = UI.el('input', {
      type: 'date',
      value: sinceDate,
      style: 'font-size: 14px; padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; margin-bottom: 16px;'
    });

    var resultsEl = UI.el('div');

    dateInput.addEventListener('change', function() {
      renderDiff(dateInput.value);
    });

    el.appendChild(UI.el('div', { style: 'margin-bottom: 8px;' }, [
      UI.el('label', { textContent: 'Since: ', style: 'font-weight: 600; margin-right: 8px;' }),
      dateInput
    ]));
    el.appendChild(resultsEl);

    function renderDiff(since) {
      resultsEl.textContent = '';

      var categories = [
        { title: 'Lab Results', sql: "SELECT test_name, value, unit, result_date, source FROM lab_results WHERE result_date >= '" + since + "' ORDER BY result_date DESC",
          cols: [{ label: 'Test', key: 'test_name' }, { label: 'Value', key: 'value' }, { label: 'Unit', key: 'unit' }, { label: 'Date', key: 'result_date' }, { label: 'Source', key: 'source' }] },
        { title: 'Encounters', sql: "SELECT encounter_date, encounter_type, facility, source FROM encounters WHERE encounter_date >= '" + since + "' ORDER BY encounter_date DESC",
          cols: [{ label: 'Date', key: 'encounter_date' }, { label: 'Type', key: 'encounter_type' }, { label: 'Facility', key: 'facility' }, { label: 'Source', key: 'source' }] },
        { title: 'Medications', sql: "SELECT name, status, start_date, stop_date, source FROM medications WHERE start_date >= '" + since + "' OR stop_date >= '" + since + "' ORDER BY start_date DESC",
          cols: [{ label: 'Name', key: 'name' }, { label: 'Status', key: 'status' }, { label: 'Start', key: 'start_date' }, { label: 'Stop', key: 'stop_date' }, { label: 'Source', key: 'source' }] },
        { title: 'Imaging', sql: "SELECT study_name, study_date, source FROM imaging_reports WHERE study_date >= '" + since + "' ORDER BY study_date DESC",
          cols: [{ label: 'Study', key: 'study_name' }, { label: 'Date', key: 'study_date' }, { label: 'Source', key: 'source' }] },
        { title: 'Clinical Notes', sql: "SELECT note_date, note_type, author, SUBSTR(content, 1, 200) AS preview FROM clinical_notes WHERE note_date >= '" + since + "' ORDER BY note_date DESC",
          cols: [{ label: 'Date', key: 'note_date' }, { label: 'Type', key: 'note_type' }, { label: 'Author', key: 'author' }, { label: 'Preview', key: 'preview' }] },
        { title: 'Conditions', sql: "SELECT condition_name, onset_date, source FROM conditions WHERE onset_date >= '" + since + "' ORDER BY onset_date DESC",
          cols: [{ label: 'Condition', key: 'condition_name' }, { label: 'Onset', key: 'onset_date' }, { label: 'Source', key: 'source' }] },
        { title: 'Procedures', sql: "SELECT name, procedure_date, source FROM procedures WHERE procedure_date >= '" + since + "' ORDER BY procedure_date DESC",
          cols: [{ label: 'Procedure', key: 'name' }, { label: 'Date', key: 'procedure_date' }, { label: 'Source', key: 'source' }] },
        { title: 'Pathology', sql: "SELECT report_date, specimen, source FROM pathology_reports WHERE report_date >= '" + since + "' ORDER BY report_date DESC",
          cols: [{ label: 'Date', key: 'report_date' }, { label: 'Specimen', key: 'specimen' }, { label: 'Source', key: 'source' }] },
        { title: 'Genetic Variants', sql: "SELECT gene, variant_type, classification, collection_date FROM genetic_variants WHERE collection_date >= '" + since + "' ORDER BY collection_date DESC",
          cols: [{ label: 'Gene', key: 'gene' }, { label: 'Type', key: 'variant_type' }, { label: 'Classification', key: 'classification' }, { label: 'Date', key: 'collection_date' }] }
      ];

      var totalNew = 0;
      for (var i = 0; i < categories.length; i++) {
        var cat = categories[i];
        try {
          var rows = db.query(cat.sql);
          if (rows.length === 0) continue;
          totalNew += rows.length;
          resultsEl.appendChild(UI.el('h3', {
            textContent: cat.title + ' (' + rows.length + ')',
            style: 'margin: 16px 0 4px; font-size: 15px;'
          }));
          resultsEl.appendChild(UI.table(cat.cols, rows));
        } catch (e) { /* table may not exist */ }
      }

      if (totalNew === 0) {
        resultsEl.appendChild(UI.empty('No new records since ' + since));
      }
    }

    // Initial render
    renderDiff(sinceDate);
  },
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_spa_export.py -v`
Expected: All pass.

- [ ] **Step 5: Run full suite**

Run: `python -m pytest tests/ -x -q`

- [ ] **Step 6: Commit**

```
feat: add visit prep section to SPA

Auto-detects most recent encounter date, shows everything new since
then across 9 clinical categories. Date is editable for custom range.
```

---

## Chunk 2: Inline Charts in Chat

### Task 3: Add render_chart Tool to Chat Agent Loop

**Files:**
- Modify: `src/chartfold/spa/js/chat.js`
- Modify: `src/chartfold/spa/css/chat.css`
- Modify: `tests/test_spa_export.py`

- [ ] **Step 1: Write failing tests**

Add to `TestAiChatExport` in `tests/test_spa_export.py`:

```python
    def test_ai_chat_has_render_chart_tool(self, ai_chat_html):
        """Chat JS should define the render_chart tool."""
        assert "render_chart" in ai_chat_html

    def test_ai_chat_has_execute_render_chart(self, ai_chat_html):
        """Chat JS should have the chart rendering method."""
        assert "_executeRenderChart" in ai_chat_html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_spa_export.py::TestAiChatExport::test_ai_chat_has_render_chart_tool tests/test_spa_export.py::TestAiChatExport::test_ai_chat_has_execute_render_chart -v`

- [ ] **Step 3: Add render_chart tool definition to _agentLoop**

In `src/chartfold/spa/js/chat.js`, in `_agentLoop`, after the `runSqlTool` definition (around line 196), add:

```javascript
    var renderChartTool = {
      name: 'render_chart',
      description: 'Render a line chart inline in the chat. Use after querying time-series lab data to visualize trends. Provide data points with date and numeric value.',
      input_schema: {
        type: 'object',
        properties: {
          title: { type: 'string', description: 'Chart title' },
          y_label: { type: 'string', description: 'Y-axis label (units)' },
          data: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                date: { type: 'string', description: 'ISO date (YYYY-MM-DD)' },
                value: { type: 'number' },
                source: { type: 'string' }
              },
              required: ['date', 'value']
            }
          },
          ref_range: {
            type: 'object',
            properties: {
              low: { type: 'number' },
              high: { type: 'number' }
            }
          }
        },
        required: ['title', 'data']
      }
    };
```

Update the `tools` array in the request body (around line 211):

```javascript
          tools: [runSqlTool, renderChartTool]
```

- [ ] **Step 4: Add tool dispatch in the content block loop**

In the `for` loop that iterates `data.content` (around line 237), after the `tool_use` block for `run_sql`, add handling for `render_chart`:

```javascript
          } else if (block.type === 'tool_use') {
            if (block.name === 'render_chart') {
              self._executeRenderChart(block.input || {});
              toolResults.push({
                type: 'tool_result',
                tool_use_id: block.id,
                content: 'Chart rendered: ' + (block.input && block.input.title || 'chart'),
                is_error: false
              });
            } else {
              var queryStr = (block.input && block.input.query) ? block.input.query : '';
              self._renderToolUse(queryStr);
              var result = self._executeSql(queryStr);
              toolResults.push({
                type: 'tool_result',
                tool_use_id: block.id,
                content: result.content,
                is_error: result.is_error
              });
            }
          }
```

This replaces the current `else if (block.type === 'tool_use')` block.

- [ ] **Step 5: Add `_executeRenderChart` method**

Add after `_executeSql` in chat.js:

```javascript
  _executeRenderChart: function(input) {
    var chartDiv = UI.el('div', { className: 'chat-chart' });

    // Title
    if (input.title) {
      chartDiv.appendChild(UI.el('div', {
        textContent: input.title,
        style: 'font-weight: 600; font-size: 13px; margin-bottom: 4px;'
      }));
    }

    // Map tool input format {date, value, source} to ChartRenderer format {x, y, source}
    var dataPoints = [];
    var data = input.data || [];
    for (var i = 0; i < data.length; i++) {
      dataPoints.push({
        x: data[i].date,
        y: data[i].value,
        source: data[i].source || ''
      });
    }

    var canvas = UI.el('canvas');
    chartDiv.appendChild(canvas);

    var opts = {};
    if (input.y_label) opts.yLabel = input.y_label;
    if (input.ref_range) opts.refRange = input.ref_range;

    ChartRenderer.line(canvas, [{ label: input.title || 'Values', data: dataPoints }], opts);

    this.messagesEl.appendChild(chartDiv);
    this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
  },
```

- [ ] **Step 6: Add `.chat-chart` CSS**

Add to `src/chartfold/spa/css/chat.css`:

```css
/* --- Inline chart in chat --- */
.chat-chart {
  align-self: flex-start;
  max-width: 85%;
  padding: 10px;
  margin: 4px 0;
  background: var(--bg);
  border-radius: 12px;
  border-bottom-left-radius: 4px;
}

.chat-chart canvas {
  width: 100%;
  max-width: 600px;
}
```

- [ ] **Step 7: Run tests**

Run: `python -m pytest tests/test_spa_export.py -v`

- [ ] **Step 8: Commit**

```
feat: add render_chart tool to AI chat agent loop

LLM can now generate inline line charts in the chat by calling
render_chart with structured data points. Maps {date, value} to
ChartRenderer's {x, y} format. Supports title, y_label, and ref_range.
```

---

### Task 4: Update System Prompt for Chart Tool

**Files:**
- Modify: `src/chartfold/spa/chat_prompt.py`
- Modify: `tests/test_chat_prompt.py`

- [ ] **Step 1: Write failing test**

Add to `TestGenerateSystemPrompt` in `tests/test_chat_prompt.py`:

```python
    def test_includes_chart_tool_instructions(self, chat_db):
        prompt = generate_system_prompt(chat_db.db_path)
        assert "render_chart" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_chat_prompt.py::TestGenerateSystemPrompt::test_includes_chart_tool_instructions -v`

- [ ] **Step 3: Update `_role_instructions` in chat_prompt.py**

In `src/chartfold/spa/chat_prompt.py`, in the `_role_instructions()` function, add after the existing guidelines:

```python
        "- When asked to show trends or visualize data over time, first query the data with "
        "run_sql, then call render_chart with the results to display an inline chart.\n"
        "- The render_chart tool accepts: title, data (array of {date, value, source}), "
        "y_label (units), and optional ref_range ({low, high})."
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_chat_prompt.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```
feat: add render_chart tool description to system prompt

Instruct the LLM to use render_chart for trend visualization
after querying data with run_sql.
```

---

### Task 5: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q`

- [ ] **Step 2: Lint check**

Run: `ruff check src/ tests/`

- [ ] **Step 3: Verify default export unaffected**

Run: `python -m pytest tests/test_spa_export.py -k "not AiChat" -q`

- [ ] **Step 4: Check coverage**

Run: `python -m pytest tests/ --cov=chartfold --cov-report=term-missing -q 2>&1 | tail -20`
Expected: Coverage >= 68%.
