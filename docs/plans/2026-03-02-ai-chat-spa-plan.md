# AI Chat SPA Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an AI-powered natural language chat interface to the chartfold HTML SPA export, allowing doctors to ask questions about the patient's medical data.

**Architecture:** Client-side agent loop. The browser sends user questions to a Cloudflare Worker proxy, which injects the Anthropic API key and forwards to Claude Haiku 4.5. Claude responds with `tool_use` blocks containing SQL queries. The browser executes those against the embedded sql.js database and returns results. The loop continues until Claude produces a text response.

**Tech Stack:** JavaScript (vanilla, no frameworks — matches existing SPA), Python (export-time system prompt generation), sql.js (already embedded).

**Design doc:** `docs/plans/2026-03-02-ai-chat-spa-design.md`

**Security note on innerHTML:** The existing SPA uses `Markdown.render()` + `innerHTML` throughout (analysis content, clinical notes, etc.). The chat assistant messages follow this same pattern. The content originates from Claude's API response (not arbitrary user input) and passes through the same `Markdown.render()` function used elsewhere in the SPA. This is an accepted pattern in the codebase.

---

### Task 1: System Prompt Generation (Python)

**Files:**
- Create: `src/chartfold/spa/chat_prompt.py`
- Test: `tests/test_chat_prompt.py`

This module generates the system prompt that gets embedded in the HTML at export time. It combines role instructions, the full DB schema, summary statistics, and any "current" analyses.

**Step 1: Write the failing test**

```python
# tests/test_chat_prompt.py
"""Tests for the AI chat system prompt generation."""

from __future__ import annotations

import json
import sqlite3

import pytest

from chartfold.db import ChartfoldDB


@pytest.fixture
def chat_db(tmp_path):
    """Create a DB with data for system prompt generation."""
    db_path = tmp_path / "test.db"
    db = ChartfoldDB(str(db_path))
    db.init_schema()
    db.conn.execute(
        "INSERT INTO patients (source, name, date_of_birth) VALUES (?, ?, ?)",
        ("epic_anderson", "Jane Doe", "1970-05-15"),
    )
    db.conn.execute(
        "INSERT INTO lab_results (source, test_name, value, result_date) "
        "VALUES (?, ?, ?, ?)",
        ("epic_anderson", "CEA", "3.2", "2025-06-01"),
    )
    db.conn.execute(
        "INSERT INTO lab_results (source, test_name, value, result_date) "
        "VALUES (?, ?, ?, ?)",
        ("meditech_houston", "CBC", "normal", "2025-07-01"),
    )
    db.conn.execute(
        "INSERT INTO analyses (slug, title, content, source, category, "
        "frontmatter, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "cancer-timeline",
            "Cancer Timeline",
            "# Timeline\n\nDiagnosed 2024...",
            "claude",
            "oncology",
            json.dumps({"status": "current"}),
            "2025-08-01T00:00:00",
            "2025-08-01T00:00:00",
        ),
    )
    db.conn.execute(
        "INSERT INTO analyses (slug, title, content, source, category, "
        "frontmatter, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "old-draft",
            "Old Draft",
            "archived content",
            "claude",
            "misc",
            json.dumps({"status": "archived"}),
            "2025-01-01T00:00:00",
            "2025-01-01T00:00:00",
        ),
    )
    db.conn.commit()
    db.close()
    return str(db_path)


class TestGenerateSystemPrompt:
    def test_includes_role_instructions(self, chat_db):
        from chartfold.spa.chat_prompt import generate_system_prompt

        prompt = generate_system_prompt(chat_db)
        assert "medical data analyst" in prompt.lower()
        assert "SELECT" in prompt

    def test_includes_schema(self, chat_db):
        from chartfold.spa.chat_prompt import generate_system_prompt

        prompt = generate_system_prompt(chat_db)
        assert "CREATE TABLE" in prompt
        assert "lab_results" in prompt
        assert "medications" in prompt

    def test_includes_summary_stats(self, chat_db):
        from chartfold.spa.chat_prompt import generate_system_prompt

        prompt = generate_system_prompt(chat_db)
        # Should mention the sources present
        assert "epic_anderson" in prompt
        assert "meditech_houston" in prompt
        # Should mention record counts
        assert "lab_results" in prompt

    def test_includes_current_analyses(self, chat_db):
        from chartfold.spa.chat_prompt import generate_system_prompt

        prompt = generate_system_prompt(chat_db)
        assert "Cancer Timeline" in prompt
        assert "Diagnosed 2024" in prompt

    def test_excludes_archived_analyses(self, chat_db):
        from chartfold.spa.chat_prompt import generate_system_prompt

        prompt = generate_system_prompt(chat_db)
        assert "Old Draft" not in prompt
        assert "archived content" not in prompt

    def test_handles_empty_db(self, tmp_path):
        from chartfold.spa.chat_prompt import generate_system_prompt

        db_path = tmp_path / "empty.db"
        db = ChartfoldDB(str(db_path))
        db.init_schema()
        db.close()
        prompt = generate_system_prompt(str(db_path))
        assert "CREATE TABLE" in prompt
        assert len(prompt) > 100
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_chat_prompt.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chartfold.spa.chat_prompt'`

**Step 3: Write minimal implementation**

```python
# src/chartfold/spa/chat_prompt.py
"""Generate the AI chat system prompt for the SPA export.

Combines role instructions, database schema, summary statistics,
and current analyses into a single prompt string for Claude.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


_SCHEMA_PATH = Path(__file__).parent.parent / "schema.sql"

_ROLE_INSTRUCTIONS = """\
You are a medical data analyst assistant. You have access to a patient's \
complete health record stored in a SQLite database. Your job is to answer \
questions about the patient's medical data by running SQL queries.

Guidelines:
- Use the run_sql tool to query the database. Only SELECT statements are allowed.
- Always cite specific data (dates, values, sources) in your answers.
- Do not provide diagnostic opinions or treatment recommendations.
- If a query returns no results, say so clearly.
- Use LIMIT to keep result sets manageable (max 100 rows).
- The database may contain records from multiple EHR sources. \
Use the `source` column to distinguish them when relevant.
- Dates are stored as ISO strings (YYYY-MM-DD). Use string comparison for date filtering.
- Lab results have `value` (text) and `value_numeric` (float, NULL if not parseable). \
Use value_numeric for numeric comparisons and sorting.
"""


def _get_schema() -> str:
    """Read the schema.sql file."""
    return _SCHEMA_PATH.read_text(encoding="utf-8")


def _get_summary_stats(db_path: str) -> str:
    """Generate summary statistics from the database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    lines = []

    # Sources
    try:
        rows = conn.execute(
            "SELECT DISTINCT source FROM load_log ORDER BY source"
        ).fetchall()
        sources = [r["source"] for r in rows]
        if sources:
            lines.append(f"Data sources: {', '.join(sources)}")
    except sqlite3.Error:
        pass

    # If no load_log entries, gather sources from clinical tables
    if not lines:
        try:
            rows = conn.execute(
                "SELECT DISTINCT source FROM lab_results "
                "UNION SELECT DISTINCT source FROM medications "
                "UNION SELECT DISTINCT source FROM encounters "
                "ORDER BY source"
            ).fetchall()
            sources = [r["source"] for r in rows]
            if sources:
                lines.append(f"Data sources: {', '.join(sources)}")
        except sqlite3.Error:
            pass

    # Table counts
    tables = [
        "patients", "encounters", "lab_results", "vitals", "medications",
        "conditions", "procedures", "pathology_reports", "imaging_reports",
        "clinical_notes", "immunizations", "allergies", "social_history",
        "family_history", "mental_status", "genetic_variants",
    ]
    count_lines = []
    for table in tables:
        try:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            n = row["n"] if row else 0
            if n > 0:
                count_lines.append(f"  {table}: {n}")
        except sqlite3.Error:
            pass

    if count_lines:
        lines.append("Record counts:")
        lines.extend(count_lines)

    # Date range
    try:
        row = conn.execute(
            "SELECT MIN(result_date) AS earliest, MAX(result_date) AS latest "
            "FROM lab_results WHERE result_date IS NOT NULL"
        ).fetchone()
        if row and row["earliest"]:
            lines.append(f"Lab results date range: {row['earliest']} to {row['latest']}")
    except sqlite3.Error:
        pass

    conn.close()
    return "\n".join(lines)


def _get_current_analyses(db_path: str) -> str:
    """Fetch analyses with status='current' from the database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    parts = []

    try:
        rows = conn.execute(
            "SELECT title, content, frontmatter FROM analyses ORDER BY updated_at DESC"
        ).fetchall()
        for row in rows:
            fm = {}
            if row["frontmatter"]:
                try:
                    fm = json.loads(row["frontmatter"])
                except (json.JSONDecodeError, TypeError):
                    pass
            if fm.get("status") == "current":
                parts.append(f"### {row['title']}\n\n{row['content']}")
    except sqlite3.Error:
        pass

    conn.close()
    return "\n\n".join(parts)


def generate_system_prompt(db_path: str) -> str:
    """Generate the complete system prompt for the AI chat interface.

    Combines:
    1. Role instructions (how to behave, what tools are available)
    2. Full database schema (CREATE TABLE statements)
    3. Summary statistics (sources, record counts, date ranges)
    4. Current analyses (case briefing context)

    Args:
        db_path: Path to the SQLite database.

    Returns:
        The system prompt string.
    """
    sections = [_ROLE_INSTRUCTIONS]

    # Schema
    schema = _get_schema()
    sections.append(f"## Database Schema\n\n```sql\n{schema}\n```")

    # Summary
    stats = _get_summary_stats(db_path)
    if stats:
        sections.append(f"## Data Summary\n\n{stats}")

    # Analyses
    analyses = _get_current_analyses(db_path)
    if analyses:
        sections.append(f"## Case Briefing (Current Analyses)\n\n{analyses}")

    return "\n\n".join(sections)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_chat_prompt.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add src/chartfold/spa/chat_prompt.py tests/test_chat_prompt.py
git commit -m "feat: add system prompt generation for AI chat"
```

---

### Task 2: Chat CSS

**Files:**
- Create: `src/chartfold/spa/css/chat.css`

This is a pure styling file — no logic to test. It will be conditionally included at export time.

**Step 1: Create the chat stylesheet**

```css
/* src/chartfold/spa/css/chat.css */
/* === AI Chat panel === */

.chat-container {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 56px - 48px); /* viewport - topbar - padding */
  max-height: calc(100vh - 56px - 48px);
  background: var(--surface);
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06), 0 1px 2px rgba(0, 0, 0, 0.04);
  overflow: hidden;
}

/* --- Message history --- */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.chat-message {
  max-width: 85%;
  padding: 12px 16px;
  border-radius: 16px;
  font-size: 14px;
  line-height: 1.6;
  word-wrap: break-word;
}

.chat-message.user {
  align-self: flex-end;
  background: var(--accent);
  color: white;
  border-bottom-right-radius: 4px;
}

.chat-message.assistant {
  align-self: flex-start;
  background: var(--bg);
  color: var(--text);
  border-bottom-left-radius: 4px;
}

/* Markdown inside assistant messages */
.chat-message.assistant p { margin: 0 0 8px; }
.chat-message.assistant p:last-child { margin-bottom: 0; }
.chat-message.assistant ul,
.chat-message.assistant ol { margin: 0 0 8px; padding-left: 20px; }
.chat-message.assistant code {
  font-family: "SF Mono", "Menlo", "Monaco", "Consolas", monospace;
  font-size: 12px;
  background: rgba(0, 0, 0, 0.06);
  padding: 1px 5px;
  border-radius: 4px;
}
.chat-message.assistant pre {
  background: rgba(0, 0, 0, 0.06);
  border-radius: 8px;
  padding: 10px;
  overflow-x: auto;
  margin: 4px 0 8px;
}
.chat-message.assistant pre code {
  background: none;
  padding: 0;
}
.chat-message.assistant table {
  font-size: 12px;
  margin: 4px 0 8px;
}
.chat-message.assistant table th,
.chat-message.assistant table td {
  padding: 4px 8px;
}

/* --- Tool use indicator --- */
.chat-tool-use {
  align-self: flex-start;
  font-size: 12px;
  color: var(--text-secondary);
  padding: 4px 12px;
  background: rgba(0, 113, 227, 0.06);
  border-radius: 8px;
  font-family: "SF Mono", "Menlo", "Monaco", "Consolas", monospace;
  max-width: 85%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* --- Status indicator --- */
.chat-status {
  padding: 8px 20px;
  font-size: 12px;
  color: var(--text-secondary);
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-status .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--green);
  flex-shrink: 0;
}

.chat-status .dot.thinking {
  background: var(--orange);
  animation: pulse-dot 1.2s ease-in-out infinite;
}

.chat-status .dot.error {
  background: var(--red);
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* --- Input area --- */
.chat-input-area {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
  background: var(--surface);
}

.chat-input-area textarea {
  flex: 1;
  resize: none;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 10px 14px;
  font-size: 14px;
  font-family: inherit;
  background: var(--bg);
  color: var(--text);
  outline: none;
  transition: border-color 0.15s;
  min-height: 44px;
  max-height: 120px;
}

.chat-input-area textarea:focus {
  border-color: var(--accent);
}

.chat-input-area textarea::placeholder {
  color: var(--text-secondary);
}

.chat-send-btn {
  align-self: flex-end;
  background: var(--accent);
  color: white;
  border: none;
  border-radius: 12px;
  padding: 10px 20px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
  white-space: nowrap;
}

.chat-send-btn:hover {
  background: #005bb5;
}

.chat-send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* --- Settings link --- */
.chat-settings {
  font-size: 12px;
  color: var(--text-secondary);
  padding: 6px 16px;
  text-align: right;
}

.chat-settings a {
  color: var(--text-secondary);
  text-decoration: none;
  cursor: pointer;
}

.chat-settings a:hover {
  color: var(--accent);
}

/* --- Dark mode adjustments --- */
@media (prefers-color-scheme: dark) {
  .chat-message.assistant code {
    background: rgba(255, 255, 255, 0.08);
  }
  .chat-message.assistant pre {
    background: rgba(255, 255, 255, 0.06);
  }
  .chat-tool-use {
    background: rgba(10, 132, 255, 0.1);
  }
}

/* --- Print: hide chat --- */
@media print {
  .chat-container { display: none !important; }
}
```

**Step 2: Commit**

```bash
git add src/chartfold/spa/css/chat.css
git commit -m "feat: add chat panel CSS for AI chat"
```

---

### Task 3: Chat JS — Agent Loop and UI

**Files:**
- Create: `src/chartfold/spa/js/chat.js`

This is the core agent loop. It builds the chat UI, manages conversation state, and orchestrates the tool_use loop between Claude (via the proxy) and the local sql.js database. Testing this in isolation would require mocking fetch + sql.js. Since the SPA JS has no test framework (it runs in-browser only), we test it indirectly through integration tests in Task 6. Focus here is correct implementation.

The existing SPA renders assistant content via `Markdown.render()` which returns an HTML string. This is the same pattern used throughout the SPA for analysis content, clinical notes, etc. The content comes from Claude API responses, not from arbitrary external input.

**Step 1: Create chat.js**

The file must be structured as a `Chat` object (matching the SPA convention of `DB`, `UI`, `Router`, `Sections` objects). The section render function `Sections.ask_ai` calls `Chat.init(el, db)`.

```javascript
// src/chartfold/spa/js/chat.js

var Chat = {
  messages: [],      // conversation history [{role, content}]
  db: null,          // sql.js DB reference
  proxyUrl: null,    // proxy endpoint URL
  systemPrompt: null,
  busy: false,

  // DOM references
  messagesEl: null,
  inputEl: null,
  sendBtn: null,
  statusDot: null,
  statusText: null,

  init: function(el, db) {
    this.db = db;
    this.messages = [];
    this.busy = false;

    // Read config
    try {
      var configEl = document.getElementById('chartfold-chat-config');
      if (configEl) {
        var config = JSON.parse(configEl.textContent);
        this.proxyUrl = config.proxyUrl || null;
      }
    } catch (e) { /* ignore */ }

    // Allow localStorage override for dev/testing
    var override = null;
    try { override = localStorage.getItem('chartfold_proxy_url'); } catch (e) { /* ignore */ }
    if (override) this.proxyUrl = override;

    // Read system prompt
    try {
      var promptEl = document.getElementById('chartfold-system-prompt');
      if (promptEl) this.systemPrompt = promptEl.textContent;
    } catch (e) { /* ignore */ }

    this._buildUI(el);
    this._updateStatus('ready');

    if (!this.proxyUrl) {
      this._updateStatus('error', 'No proxy URL configured');
    }
  },

  _buildUI: function(container) {
    // Section header
    container.appendChild(UI.sectionHeader('Ask AI', 'Ask questions about this medical record'));

    // Chat container
    var chatContainer = UI.el('div', { className: 'chat-container' });

    // Messages area
    this.messagesEl = UI.el('div', { className: 'chat-messages' });
    chatContainer.appendChild(this.messagesEl);

    // Status bar
    this.statusDot = UI.el('span', { className: 'dot' });
    this.statusText = UI.el('span', { textContent: 'Ready' });
    var statusBar = UI.el('div', { className: 'chat-status' }, [
      this.statusDot, this.statusText
    ]);
    chatContainer.appendChild(statusBar);

    // Input area
    var self = this;
    this.inputEl = UI.el('textarea', {
      placeholder: 'Ask a question about the medical data...',
      rows: 1
    });
    this.inputEl.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        self._onSend();
      }
    });
    // Auto-resize textarea
    this.inputEl.addEventListener('input', function() {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });

    this.sendBtn = UI.el('button', {
      className: 'chat-send-btn',
      textContent: 'Send',
      onClick: function() { self._onSend(); }
    });

    var inputArea = UI.el('div', { className: 'chat-input-area' }, [
      this.inputEl, this.sendBtn
    ]);
    chatContainer.appendChild(inputArea);

    // Settings link
    var settingsEl = UI.el('div', { className: 'chat-settings' });
    var settingsLink = UI.el('a', { textContent: 'Proxy settings' });
    settingsLink.addEventListener('click', function() { self._showSettings(); });
    settingsEl.appendChild(settingsLink);
    chatContainer.appendChild(settingsEl);

    container.appendChild(chatContainer);

    // Focus input
    setTimeout(function() { self.inputEl.focus(); }, 100);
  },

  _onSend: function() {
    if (this.busy) return;
    var text = this.inputEl.value.trim();
    if (!text) return;
    if (!this.proxyUrl) {
      this._updateStatus('error', 'No proxy URL configured');
      return;
    }

    this.inputEl.value = '';
    this.inputEl.style.height = 'auto';

    // Add user message
    this.messages.push({ role: 'user', content: text });
    this._renderMessage('user', text);

    // Start agent loop
    this._agentLoop();
  },

  _agentLoop: async function() {
    this.busy = true;
    this.sendBtn.disabled = true;
    this._updateStatus('thinking', 'Thinking...');

    try {
      while (true) {
        // Build API request
        var body = {
          model: 'unused',  // Worker overrides this
          max_tokens: 4096,
          messages: this.messages,
          tools: [{
            name: 'run_sql',
            description: 'Execute a read-only SQL query against the patient health database. Returns results as an array of objects. Use SELECT only.',
            input_schema: {
              type: 'object',
              properties: {
                query: {
                  type: 'string',
                  description: 'SQL SELECT query to execute'
                }
              },
              required: ['query']
            }
          }]
        };

        if (this.systemPrompt) {
          body.system = this.systemPrompt;
        }

        // Call proxy
        var response = await fetch(this.proxyUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        });

        if (!response.ok) {
          var errText = '';
          try { errText = await response.text(); } catch (e) { /* ignore */ }
          throw new Error('API error (' + response.status + '): ' + errText);
        }

        var data = await response.json();

        // Process response content blocks
        var toolResults = [];
        var textParts = [];

        for (var i = 0; i < data.content.length; i++) {
          var block = data.content[i];
          if (block.type === 'text') {
            textParts.push(block.text);
          } else if (block.type === 'tool_use') {
            // Show tool use indicator
            var queryPreview = (block.input.query || '').substring(0, 100);
            this._renderToolUse(queryPreview);

            // Execute SQL locally
            var toolResult = this._executeSql(block.input.query);
            toolResults.push({
              type: 'tool_result',
              tool_use_id: block.id,
              content: toolResult.content,
              is_error: toolResult.is_error
            });
          }
        }

        // If there were tool_use blocks, add assistant message + tool results and loop
        if (toolResults.length > 0) {
          this.messages.push({ role: 'assistant', content: data.content });
          this.messages.push({ role: 'user', content: toolResults });
          continue;
        }

        // Text-only response — we're done
        var fullText = textParts.join('\n');
        this.messages.push({ role: 'assistant', content: data.content });
        this._renderMessage('assistant', fullText);
        break;
      }

      this._updateStatus('ready');
    } catch (err) {
      this._renderMessage('assistant', 'Error: ' + err.message);
      this._updateStatus('error', err.message);
    } finally {
      this.busy = false;
      this.sendBtn.disabled = false;
      this.inputEl.focus();
    }
  },

  _executeSql: function(query) {
    try {
      // Safety: reject non-SELECT statements
      var trimmed = query.trim().toUpperCase();
      if (!trimmed.startsWith('SELECT') && !trimmed.startsWith('WITH') &&
          !trimmed.startsWith('EXPLAIN')) {
        return { content: 'Error: Only SELECT queries are allowed.', is_error: true };
      }

      // Add LIMIT if not present (prevent huge result sets)
      var upperQuery = query.toUpperCase();
      if (upperQuery.indexOf('LIMIT') === -1) {
        query = query.replace(/;?\s*$/, '') + ' LIMIT 100';
      }

      var rows = this.db.query(query);
      var resultStr = JSON.stringify(rows, null, 2);

      // Cap result size at 50KB to keep the conversation manageable
      if (resultStr.length > 50000) {
        resultStr = resultStr.substring(0, 50000) + '\n... (truncated, ' + rows.length + ' rows total)';
      }

      return { content: rows.length + ' rows returned.\n' + resultStr, is_error: false };
    } catch (e) {
      return { content: 'SQL error: ' + e.message, is_error: true };
    }
  },

  _renderMessage: function(role, text) {
    var msgEl = UI.el('div', { className: 'chat-message ' + role });
    if (role === 'assistant') {
      // Render markdown for assistant messages (same pattern as analysis content
      // throughout the SPA — content originates from Claude API, not user input)
      msgEl.innerHTML = Markdown.render(text);  // nosec: trusted source (Claude API)
    } else {
      msgEl.textContent = text;
    }
    this.messagesEl.appendChild(msgEl);
    this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
  },

  _renderToolUse: function(queryPreview) {
    var el = UI.el('div', {
      className: 'chat-tool-use',
      textContent: 'Running: ' + queryPreview + (queryPreview.length >= 100 ? '...' : '')
    });
    this.messagesEl.appendChild(el);
    this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
  },

  _updateStatus: function(state, text) {
    if (this.statusDot) {
      this.statusDot.className = 'dot' + (state === 'thinking' ? ' thinking' : '') + (state === 'error' ? ' error' : '');
    }
    if (this.statusText) {
      this.statusText.textContent = text || (state === 'ready' ? 'Ready' : state);
    }
  },

  _showSettings: function() {
    var currentUrl = '';
    try { currentUrl = localStorage.getItem('chartfold_proxy_url') || ''; } catch (e) { /* ignore */ }
    var newUrl = prompt('Proxy URL override (leave empty to use default):', currentUrl);
    if (newUrl === null) return; // cancelled
    try {
      if (newUrl) {
        localStorage.setItem('chartfold_proxy_url', newUrl);
        this.proxyUrl = newUrl;
      } else {
        localStorage.removeItem('chartfold_proxy_url');
        // Re-read default from config
        try {
          var configEl = document.getElementById('chartfold-chat-config');
          if (configEl) {
            var config = JSON.parse(configEl.textContent);
            this.proxyUrl = config.proxyUrl || null;
          }
        } catch (e) { /* ignore */ }
      }
      this._updateStatus('ready');
    } catch (e) { /* ignore localStorage errors */ }
  }
};
```

**Step 2: Commit**

```bash
git add src/chartfold/spa/js/chat.js
git commit -m "feat: add chat.js agent loop and UI for AI chat"
```

---

### Task 4: Wire Chat into SPA Sections and Sidebar

**Files:**
- Modify: `src/chartfold/spa/js/sections.js` (end of file — add `Sections.ask_ai`)
- Modify: `src/chartfold/spa/js/app.js:14-35` (add entry to `sidebarSections` array)

**Step 1: Add the `ask_ai` section renderer to sections.js**

Append to the very end of `src/chartfold/spa/js/sections.js` (before the file ends):

```javascript
// Append to end of sections.js:

Sections.ask_ai = function(el, db) {
  // Only render chat if system prompt is embedded
  var promptEl = document.getElementById('chartfold-system-prompt');
  if (!promptEl) {
    el.appendChild(UI.sectionHeader('Ask AI', ''));
    el.appendChild(UI.empty('AI chat is not enabled in this export. Re-export with --ai-chat to enable.'));
    return;
  }
  Chat.init(el, db);
};
```

Note: The `Chat` object is defined in `chat.js`. When chat is not enabled (no `--ai-chat` flag at export time), the `chartfold-system-prompt` script tag won't exist, so this function shows a fallback message. When chat IS enabled, `chat.js` is loaded before `sections.js` in the dependency order (see Task 5).

**Step 2: Add the `ask_ai` sidebar entry to app.js**

In `src/chartfold/spa/js/app.js`, add a new entry to the `sidebarSections` array after `sql_console` (line 34):

Current (lines 33-35):
```javascript
      { id: "analysis",       label: "Analysis",         table: "analyses",          group: "Tools" },
      { id: "sql_console",    label: "SQL Console",      table: null,                group: "Tools" },
    ];
```

Change to:
```javascript
      { id: "analysis",       label: "Analysis",         table: "analyses",          group: "Tools" },
      { id: "sql_console",    label: "SQL Console",      table: null,                group: "Tools" },
      { id: "ask_ai",         label: "Ask AI",           table: null,                group: "Tools" },
    ];
```

**Step 3: Commit**

```bash
git add src/chartfold/spa/js/sections.js src/chartfold/spa/js/app.js
git commit -m "feat: wire ask_ai section into SPA sidebar and sections"
```

---

### Task 5: Modify export.py — Conditional Chat Inclusion

**Files:**
- Modify: `src/chartfold/spa/export.py`
- Test: `tests/test_spa_export.py` (add new tests)

This is the key integration point. When `ai_chat=True`, the export must:
1. Include `chat.js` in the JS bundle (before `sections.js` in dependency order)
2. Include `chat.css` in the CSS
3. Embed the system prompt in a `<script id="chartfold-system-prompt">` tag
4. Embed the chat config (proxy URL) in a `<script id="chartfold-chat-config">` tag

**Step 1: Write the failing tests**

Add these tests to `tests/test_spa_export.py`:

```python
# Add to tests/test_spa_export.py

class TestAiChatExport:
    """Tests for the --ai-chat conditional export."""

    def test_default_export_has_no_chat(self, exported_html):
        """Without ai_chat flag, no chat artifacts should appear."""
        assert "chartfold-system-prompt" not in exported_html
        assert "chartfold-chat-config" not in exported_html
        assert "Chat.init" not in exported_html

    def test_ai_chat_includes_system_prompt(self, spa_db, spa_output):
        """With ai_chat, the system prompt is embedded."""
        export_spa(spa_db, spa_output, ai_chat=True, proxy_url="https://example.com/v1/messages")
        with open(spa_output) as f:
            html = f.read()
        assert 'id="chartfold-system-prompt"' in html
        assert "CREATE TABLE" in html  # schema is in the system prompt
        assert "medical data analyst" in html.lower()

    def test_ai_chat_includes_config(self, spa_db, spa_output):
        """With ai_chat, the chat config is embedded."""
        export_spa(spa_db, spa_output, ai_chat=True, proxy_url="https://proxy.example.com/v1/messages")
        with open(spa_output) as f:
            html = f.read()
        assert 'id="chartfold-chat-config"' in html
        assert "proxy.example.com" in html

    def test_ai_chat_includes_chat_js(self, spa_db, spa_output):
        """With ai_chat, chat.js code is present in the bundle."""
        export_spa(spa_db, spa_output, ai_chat=True, proxy_url="https://example.com/v1/messages")
        with open(spa_output) as f:
            html = f.read()
        assert "Chat" in html
        assert "_agentLoop" in html

    def test_ai_chat_includes_chat_css(self, spa_db, spa_output):
        """With ai_chat, chat.css is present."""
        export_spa(spa_db, spa_output, ai_chat=True, proxy_url="https://example.com/v1/messages")
        with open(spa_output) as f:
            html = f.read()
        assert "chat-container" in html
        assert "chat-messages" in html

    def test_ai_chat_requires_proxy_url(self, spa_db, spa_output):
        """ai_chat=True without proxy_url should still work (user overrides via localStorage)."""
        export_spa(spa_db, spa_output, ai_chat=True)
        with open(spa_output) as f:
            html = f.read()
        assert 'id="chartfold-system-prompt"' in html
        # Config should be present but with null proxy
        assert 'id="chartfold-chat-config"' in html
```

**Step 2: Run test to verify they fail**

Run: `python -m pytest tests/test_spa_export.py::TestAiChatExport -v`
Expected: FAIL — `export_spa() got an unexpected keyword argument 'ai_chat'`

**Step 3: Implement the changes to export.py**

In `src/chartfold/spa/export.py`, make these edits:

**Edit 1:** Replace the `_JS_FILES` constant (lines 20-29) with split lists:

```python
# JS files concatenated in dependency order (chat.js inserted before sections.js when enabled)
_JS_FILES_BASE = [
    "db.js",
    "ui.js",
    "markdown.js",
    "chart.js",
]

_JS_FILES_CHAT = [
    "chat.js",     # Must come before sections.js (Sections.ask_ai calls Chat.init)
]

_JS_FILES_TAIL = [
    "sections.js",
    "router.js",
    "app.js",
]
```

**Edit 2:** Update the `export_spa` signature (line 101-106) to add `ai_chat` and `proxy_url`:

```python
def export_spa(
    db_path: str,
    output_path: str,
    config_path: str = "",
    embed_images: bool = False,
    ai_chat: bool = False,
    proxy_url: str = "",
) -> str:
```

**Edit 3:** Replace JS file concatenation (lines 132-139) with conditional logic:

```python
    # 4. Concatenate JS files in dependency order
    js_files = _JS_FILES_BASE[:]
    if ai_chat:
        js_files.extend(_JS_FILES_CHAT)
    js_files.extend(_JS_FILES_TAIL)

    js_parts = []
    js_dir = _SPA_DIR / "js"
    for js_file in js_files:
        js_path = js_dir / js_file
        if js_path.is_file():
            js_parts.append(js_path.read_text(encoding="utf-8"))
    app_js = "\n".join(js_parts)
```

**Edit 4:** After CSS loading (lines 141-143), add conditional chat CSS:

```python
    # 5. Read CSS (base + chat if enabled)
    css_path = _SPA_DIR / "css" / "styles.css"
    css = css_path.read_text(encoding="utf-8") if css_path.is_file() else ""
    if ai_chat:
        chat_css_path = _SPA_DIR / "css" / "chat.css"
        if chat_css_path.is_file():
            css += "\n" + chat_css_path.read_text(encoding="utf-8")
```

**Edit 5:** After optional data loading (lines 145-149), add chat prompt generation:

```python
    # 7. AI chat data (system prompt + config)
    chat_prompt_tag = ""
    chat_config_tag = ""
    if ai_chat:
        from chartfold.spa.chat_prompt import generate_system_prompt

        system_prompt = _safe_json_for_script(generate_system_prompt(db_path))
        chat_prompt_tag = (
            f'\n    <script id="chartfold-system-prompt" type="text/plain">'
            f"{system_prompt}</script>"
        )
        chat_config = _safe_json_for_script(
            json.dumps({"proxyUrl": proxy_url or None})
        )
        chat_config_tag = (
            f'\n    <script id="chartfold-chat-config" type="application/json">'
            f"{chat_config}</script>"
        )
```

**Edit 6:** In the HTML template (lines 152-174), insert `{chat_prompt_tag}{chat_config_tag}` after the images script tag:

```
    <script id="chartfold-images" type="application/json">{images_json}</script>{chat_prompt_tag}{chat_config_tag}
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_spa_export.py -v`
Expected: All existing tests + new `TestAiChatExport` tests PASS

**Step 5: Commit**

```bash
git add src/chartfold/spa/export.py tests/test_spa_export.py
git commit -m "feat: conditional AI chat inclusion in SPA export"
```

---

### Task 6: Wire CLI Flags (`--ai-chat`, `--proxy-url`)

**Files:**
- Modify: `src/chartfold/cli.py:117-128` (html subparser), `src/chartfold/cli.py:672-680` (export handler)

**Step 1: Add CLI arguments to the html subparser**

In `src/chartfold/cli.py`, after the `--embed-images` argument (line 128), add:

```python
    html_parser.add_argument(
        "--ai-chat",
        action="store_true",
        help="Include AI chat interface (requires proxy deployment)",
    )
    html_parser.add_argument(
        "--proxy-url",
        default="",
        help="Proxy URL for AI chat API calls",
    )
```

**Step 2: Pass the new flags to export_spa**

In `_handle_export()` (around line 675), change the `export_spa` call from:

```python
            path = export_spa(
                db_path=args.db,
                output_path=args.output,
                config_path=args.config,
                embed_images=args.embed_images,
            )
```

To:

```python
            path = export_spa(
                db_path=args.db,
                output_path=args.output,
                config_path=args.config,
                embed_images=args.embed_images,
                ai_chat=args.ai_chat,
                proxy_url=args.proxy_url,
            )
```

**Step 3: Update docstring**

At the top of `cli.py`, update the usage comment (line 11) to include the new flags:

```python
    python -m chartfold export html [--output FILE] [--embed-images] [--config FILE] [--ai-chat] [--proxy-url URL]
```

**Step 4: Run all tests to verify nothing broke**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/chartfold/cli.py
git commit -m "feat: add --ai-chat and --proxy-url CLI flags for HTML export"
```

---

### Task 7: Integration Test — Full Export with AI Chat

**Files:**
- Modify: `tests/test_spa_export.py` (add integration test)

This test verifies the full round-trip: create DB with analyses, export with `--ai-chat`, check that all pieces are present and correctly assembled.

**Step 1: Write the integration test**

```python
# Add to tests/test_spa_export.py

class TestAiChatIntegration:
    """Integration test: full export with AI chat enabled."""

    def test_full_export_with_ai_chat(self, tmp_path):
        """End-to-end: DB with analyses -> export with ai_chat -> all pieces present."""
        import json
        from pathlib import Path
        from chartfold.db import ChartfoldDB
        from chartfold.spa.export import export_spa

        # Create DB with clinical data + analyses
        db_path = str(tmp_path / "test.db")
        db = ChartfoldDB(db_path)
        db.init_schema()
        db.conn.execute(
            "INSERT INTO patients (source, name, date_of_birth) VALUES (?, ?, ?)",
            ("epic", "Test Patient", "1970-01-01"),
        )
        db.conn.execute(
            "INSERT INTO lab_results (source, test_name, value, result_date) "
            "VALUES (?, ?, ?, ?)",
            ("epic", "CEA", "4.5", "2025-06-01"),
        )
        db.conn.execute(
            "INSERT INTO analyses (slug, title, content, source, category, "
            "frontmatter, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "summary",
                "Case Summary",
                "Patient has stage II colon cancer.",
                "claude",
                "oncology",
                json.dumps({"status": "current"}),
                "2025-08-01T00:00:00",
                "2025-08-01T00:00:00",
            ),
        )
        db.conn.commit()
        db.close()

        # Export with AI chat
        out_path = str(tmp_path / "export.html")
        export_spa(
            db_path, out_path,
            ai_chat=True,
            proxy_url="https://proxy.example.com/v1/messages",
        )

        html = Path(out_path).read_text()

        # System prompt embedded
        assert 'id="chartfold-system-prompt"' in html
        assert "CREATE TABLE" in html
        assert "Case Summary" in html
        assert "colon cancer" in html

        # Chat config embedded
        assert 'id="chartfold-chat-config"' in html
        assert "proxy.example.com" in html

        # Chat JS included
        assert "Chat" in html
        assert "_agentLoop" in html
        assert "run_sql" in html

        # Chat CSS included
        assert "chat-container" in html

        # Sidebar entry exists
        assert "ask_ai" in html
        assert "Ask AI" in html

        # Existing features still work
        assert "sql-wasm" in html
        assert "chartfold-db" in html
```

**Step 2: Run the test**

Run: `python -m pytest tests/test_spa_export.py::TestAiChatIntegration -v`
Expected: PASS

**Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add tests/test_spa_export.py
git commit -m "test: add integration test for AI chat export"
```

---

### Task 8: Update Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md` (if it mentions export flags)

**Step 1: Update CLAUDE.md**

In the Commands section, add an `export html` line showing the AI chat flags:

```
python -m chartfold export html --output summary.html --ai-chat --proxy-url https://proxy.example.com/v1/messages
```

In the Export Modules section, add:

```
- `spa/chat_prompt.py` — System prompt generation for AI chat (schema + stats + analyses)
- `spa/js/chat.js` — Client-side agent loop + chat UI (conditionally included with `--ai-chat`)
- `spa/css/chat.css` — Chat panel styling (conditionally included with `--ai-chat`)
```

**Step 2: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: add AI chat export documentation"
```

---

### Task 9: Final Verification

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 2: Run lint**

Run: `ruff check src/ tests/ && ruff format --check src/ tests/`
Expected: Clean

**Step 3: Run coverage**

Run: `python -m pytest tests/ --cov=chartfold --cov-report=term-missing`
Expected: Coverage >= 68% (configured minimum)

**Step 4: Verify no regressions in default export**

Run: `python -m pytest tests/test_spa_export.py -v -k "not AiChat"`
Expected: All existing SPA tests still PASS (default export unchanged)

**Step 5: Commit any lint fixes if needed, then tag**

```bash
git log --oneline -10  # verify commit history looks clean
```
