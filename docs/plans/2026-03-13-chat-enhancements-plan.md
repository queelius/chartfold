# Chat Enhancements Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add conversation persistence, sliding window with clear button, and derive `_CLINICAL_TABLES` from `_UNIQUE_KEYS`.

**Architecture:** Three independent changes to the chat SPA feature. Item 8 (Python) has no dependency on Items 6/7 (JavaScript). Items 6 and 7 both modify `chat.js` but touch different functions.

**Tech Stack:** JavaScript (vanilla, existing SPA patterns), Python, pytest.

**Design doc:** `docs/plans/2026-03-13-chat-enhancements-design.md`

---

### Task 1: Derive _CLINICAL_TABLES from _UNIQUE_KEYS (Item 8 — Python, TDD)

**Files:**
- Modify: `src/chartfold/spa/chat_prompt.py:14-32`
- Modify: `tests/test_chat_prompt.py`

This is the simplest task and fully testable with pytest. Do it first.

- [ ] **Step 1: Write failing tests for derived table list**

Add to `tests/test_chat_prompt.py`:

```python
from chartfold.db import _UNIQUE_KEYS
from chartfold.spa.chat_prompt import _CLINICAL_TABLES, _NON_CLINICAL_TABLES


class TestClinicalTablesList:
    """Tests for the derived _CLINICAL_TABLES list."""

    def test_contains_expected_clinical_tables(self):
        expected = {
            "patients", "encounters", "lab_results", "vitals",
            "medications", "conditions", "procedures", "pathology_reports",
            "imaging_reports", "clinical_notes", "immunizations", "allergies",
            "social_history", "family_history", "mental_status", "genetic_variants",
        }
        assert set(_CLINICAL_TABLES) == expected

    def test_excludes_non_clinical_tables(self):
        for table in _NON_CLINICAL_TABLES:
            assert table not in _CLINICAL_TABLES

    def test_auto_tracks_unique_keys(self):
        """Length matches _UNIQUE_KEYS minus exclusions — catches new tables."""
        expected_count = len(_UNIQUE_KEYS) - len(_NON_CLINICAL_TABLES)
        assert len(_CLINICAL_TABLES) == expected_count
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chat_prompt.py::TestClinicalTablesList -v`
Expected: ImportError for `_NON_CLINICAL_TABLES` (doesn't exist yet).

- [ ] **Step 3: Replace hardcoded list with derivation**

In `src/chartfold/spa/chat_prompt.py`, replace lines 14-32:

```python
# Tables to report record counts for in the summary stats section.
_CLINICAL_TABLES = [
    "patients",
    "encounters",
    ...
    "genetic_variants",
]
```

With:

```python
from chartfold.db import _UNIQUE_KEYS

# Tables excluded from clinical summary stats (metadata/system tables).
_NON_CLINICAL_TABLES = {
    "documents", "load_log", "notes", "note_tags",
    "analyses", "analysis_tags", "source_assets",
}
_CLINICAL_TABLES = [t for t in _UNIQUE_KEYS if t not in _NON_CLINICAL_TABLES]
```

Also update the existing `import sqlite3` block — `_UNIQUE_KEYS` import goes with the other chartfold imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_chat_prompt.py -v`
Expected: All tests pass (both new and existing).

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All 1109+ tests pass.

- [ ] **Step 6: Commit**

```
feat: derive _CLINICAL_TABLES from _UNIQUE_KEYS

Replace hardcoded 16-table list with derivation from db.py's
_UNIQUE_KEYS dict, filtering out non-clinical tables. Auto-updates
when new clinical tables are added.
```

---

### Task 2: DOM Persistence — Wrap UI in Container (Item 6 — JavaScript)

**Files:**
- Modify: `src/chartfold/spa/js/chat.js:1-30, 53-127`
- Modify: `src/chartfold/spa/js/sections.js:1717-1726`
- Modify: `tests/test_spa_export.py`

- [ ] **Step 1: Write failing test for container reattach logic**

Add to `TestAiChatExport` in `tests/test_spa_export.py`:

```python
def test_ai_chat_has_container_reattach(self, ai_chat_html):
    """Chat JS should check for existing _container before rebuilding."""
    assert "Chat._container" in ai_chat_html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_spa_export.py::TestAiChatExport::test_ai_chat_has_container_reattach -v`
Expected: FAIL (Chat._container not found in current JS).

- [ ] **Step 3: Modify chat.js — add _container property and wrap _buildUI**

Add `_container: null` to the state properties (after line 7):

```javascript
  _container: null,
```

In `init()` (line 16), add an early-return reattach path before the existing init logic:

```javascript
  init: function(el, db) {
    // Reattach existing container if navigating back
    if (this._container) {
      el.appendChild(this._container);
      this.inputEl.focus();
      return;
    }

    this.messages = [];
    this.db = db;
    this.busy = false;
    // ... rest of existing init
```

In `_buildUI()` (line 53), wrap everything in a single container div. Replace the current pattern where items are appended directly to `container` param:

```javascript
  _buildUI: function(container) {
    var self = this;

    // Create a single wrapper that can be detached/reattached
    this._container = UI.el('div', {});

    this._container.appendChild(
      UI.sectionHeader('Ask AI', 'Ask questions about this medical record')
    );

    var chatContainer = UI.el('div', { className: 'chat-container' });
    // ... (existing chatContainer children unchanged) ...
    this._container.appendChild(chatContainer);

    container.appendChild(this._container);

    // Focus input after brief delay
    setTimeout(function() {
      self.inputEl.focus();
    }, 100);
  },
```

The key change: `container.appendChild(sectionHeader)` and `container.appendChild(chatContainer)` become `this._container.appendChild(sectionHeader)` and `this._container.appendChild(chatContainer)`, then `container.appendChild(this._container)`.

- [ ] **Step 4: Modify sections.js — simplify ask_ai**

Replace `sections.js` lines 1717-1726:

```javascript
  ask_ai: function(el, db) {
    var promptEl = document.getElementById('chartfold-system-prompt');
    if (!promptEl) {
      el.appendChild(UI.sectionHeader('Ask AI', ''));
      el.appendChild(UI.empty('AI chat is not enabled in this export. Re-export with --ai-chat to enable.'));
      return;
    }
    Chat.init(el, db);
  }
```

No change needed here — `Chat.init()` now handles the reattach internally. The `sections.js` code stays the same.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_spa_export.py -v`
Expected: All tests pass including the new `test_ai_chat_has_container_reattach`.

- [ ] **Step 6: Commit**

```
feat: persist chat conversation across section navigation

Wrap chat UI in a single _container div that survives DOM detach.
On re-entry, reattach the existing container instead of rebuilding,
preserving messages, scroll position, and input state.
```

---

### Task 3: Sliding Window + Clear Button (Item 7 — JavaScript + CSS)

**Files:**
- Modify: `src/chartfold/spa/js/chat.js`
- Modify: `src/chartfold/spa/css/chat.css`
- Modify: `tests/test_spa_export.py`

- [ ] **Step 1: Write failing tests for clear button and trim function**

Add to `TestAiChatExport` in `tests/test_spa_export.py`:

```python
def test_ai_chat_has_clear_button(self, ai_chat_html):
    """Chat UI should include a clear conversation button."""
    assert "chat-clear-btn" in ai_chat_html

def test_ai_chat_has_trim_history(self, ai_chat_html):
    """Chat JS should include the _trimHistory function."""
    assert "_trimHistory" in ai_chat_html

def test_ai_chat_has_max_messages(self, ai_chat_html):
    """Chat JS should define MAX_MESSAGES constant."""
    assert "MAX_MESSAGES" in ai_chat_html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_spa_export.py::TestAiChatExport::test_ai_chat_has_clear_button tests/test_spa_export.py::TestAiChatExport::test_ai_chat_has_trim_history tests/test_spa_export.py::TestAiChatExport::test_ai_chat_has_max_messages -v`
Expected: All 3 FAIL.

- [ ] **Step 3: Add MAX_MESSAGES constant and _trimHistory to chat.js**

After the state properties block (around line 8), add:

```javascript
  _container: null,

  // Sliding window: keep conversation within token budget
  MAX_MESSAGES: 40,
```

Add `_trimHistory` method (after `_onSend`):

```javascript
  _trimHistory: function() {
    if (this.messages.length <= this.MAX_MESSAGES) return;
    // Slice to keep the last MAX_MESSAGES entries
    this.messages = this.messages.slice(-this.MAX_MESSAGES);
    // Don't start with an orphaned tool_result (its paired tool_use was trimmed)
    while (
      this.messages.length > 0 &&
      this.messages[0].role === 'user' &&
      Array.isArray(this.messages[0].content)
    ) {
      this.messages.shift();
    }
  },
```

Call `_trimHistory()` in `_agentLoop` after the successful completion (line 233, after `self._updateStatus('ready', 'Ready')`):

```javascript
      self._trimHistory();
      self._updateStatus('ready', 'Ready');
```

- [ ] **Step 4: Add clear button to _buildUI**

In `_buildUI`, add a clear button to the status bar. Replace the status bar construction:

```javascript
    // Clear button
    var clearBtn = UI.el('button', {
      className: 'chat-clear-btn',
      textContent: 'Clear',
      onClick: function() { self._onClear(); }
    });

    var statusBar = UI.el('div', { className: 'chat-status' }, [
      this.statusDot,
      this.statusText,
      clearBtn
    ]);
```

Add the `_onClear` method (after `_trimHistory`):

```javascript
  _onClear: function() {
    this.messages = [];
    this.messagesEl.textContent = '';
  },
```

- [ ] **Step 5: Add clear button CSS**

Add to `src/chartfold/spa/css/chat.css`, after the `.chat-status` block (around line 160):

```css
.chat-clear-btn {
  margin-left: auto;
  padding: 2px 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
}

.chat-clear-btn:hover {
  background: var(--bg);
  color: var(--text);
}
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_spa_export.py -v`
Expected: All tests pass including the 3 new ones.

- [ ] **Step 7: Run full test suite + lint**

Run: `python -m pytest tests/ -x -q && ruff check src/ tests/`
Expected: All tests pass, lint clean.

- [ ] **Step 8: Commit**

```
feat: add sliding window and clear button to AI chat

- MAX_MESSAGES = 40 with pair-aware trimming (won't orphan tool_results)
- Clear button in status bar to reset conversation
- _trimHistory() called after each agent loop completion
```

---

### Task 4: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 2: Lint check**

Run: `ruff check src/ tests/`
Expected: Clean.

- [ ] **Step 3: Verify default export unaffected**

Run: `python -m pytest tests/test_spa_export.py -k "not AiChat" -q`
Expected: All default export tests pass (no chat features leak into non-chat exports).

- [ ] **Step 4: Check coverage**

Run: `python -m pytest tests/ --cov=chartfold --cov-report=term-missing -q 2>&1 | tail -20`
Expected: Coverage >= 68% minimum.
