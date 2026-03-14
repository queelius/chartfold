# Chat Enhancements Design (v1.2.1)

**Date:** 2026-03-13
**Scope:** Three improvements to the AI chat SPA feature

## Item 6: Conversation Persistence Across Navigation

**Problem:** `Chat.init()` resets `this.messages = []` and rebuilds the UI every time the user navigates to the "Ask AI" section. Navigating to "Lab Results" and back destroys the entire conversation.

**Solution:** Detach/reattach DOM.

When `Sections.ask_ai` is called, check if `Chat` already has a built container (`Chat._container`). If yes, reattach it to the content area instead of calling full init. The SPA's `contentEl.textContent = ''` removes the element from the DOM on navigate-away, but the JS reference survives. On re-entry, `appendChild(Chat._container)` restores everything: messages, scroll position, input state.

**Changes:**
- `chat.js`: Split `init()` into first-time build vs re-entry reattach. Store container reference as `Chat._container`.
- `sections.js`: `ask_ai` section checks `Chat._container` existence before deciding init vs reattach.

**Edge case:** If the user exports a new HTML file and opens it, `Chat._container` is null and full init runs. No special handling needed.

## Item 7: Conversation Length Management

**Problem:** `this.messages` grows unboundedly. Long sessions could exceed Haiku 4.5's context window (200K tokens), causing API errors.

**Solution:** Sliding window + clear button.

- `MAX_MESSAGES = 40`: After each agent loop completion, if `this.messages.length > MAX_MESSAGES`, slice to keep the last 40 entries. The system prompt is sent fresh on every API request (not stored in `messages`), so truncation preserves schema context.
- "Clear" button in the status bar area. Resets `this.messages = []` and clears the messages DOM container. Quick way to start fresh.

**Changes:**
- `chat.js`: Add `_trimHistory()` called after agent loop. Add clear button in `_buildUI()`. Add `_onClear()` handler.
- `chat.css`: Style the clear button (small, unobtrusive, near status bar).

**Why 40?** Each message pair (user + assistant) averages ~500-2000 tokens depending on SQL results. 40 messages ≈ 20 turns ≈ 10K-40K tokens, well within Haiku's 200K window while providing substantial conversation context.

## Item 8: Derive _CLINICAL_TABLES from _TABLE_MAP

**Problem:** `chat_prompt.py` has a hardcoded `_CLINICAL_TABLES` list of 16 table names that must stay in sync with `schema.sql` and `db.py` manually. Per project convention: "Always prefer principled, scalable, non-ad-hoc solutions."

**Solution:** Import from `db.py`'s `_TABLE_MAP` and filter out system tables.

```python
from chartfold.db import _TABLE_MAP

_SYSTEM_TABLES = {"load_log", "notes", "note_tags", "analyses", "analysis_tags", "source_assets"}
_CLINICAL_TABLES = [t for t in _TABLE_MAP if t not in _SYSTEM_TABLES]
```

`_TABLE_MAP` is the canonical mapping of table names to model field names, maintained in `db.py`. It auto-updates when new clinical tables are added. The `_SYSTEM_TABLES` exclusion set is small (6 entries), stable, and intentional.

**Changes:** `chat_prompt.py` only — replace the 16-line list with a 2-line derivation.

## Testing Strategy

All changes will use TDD (red-green-refactor):

- **Item 6:** Test that `Chat.init()` reuses existing container on second call. Test that messages survive re-entry.
- **Item 7:** Test `_trimHistory()` trims to MAX_MESSAGES. Test `_onClear()` empties messages. Test that agent loop calls trim after completion.
- **Item 8:** Test that `_CLINICAL_TABLES` matches expected tables. Test that adding a table to `_TABLE_MAP` (hypothetically) would auto-include it. Test that system tables are excluded.

## Files Changed

| File | Item | Change |
|------|------|--------|
| `src/chartfold/spa/js/chat.js` | 6, 7 | DOM persistence, sliding window, clear button |
| `src/chartfold/spa/js/sections.js` | 6 | Reattach check in `ask_ai` |
| `src/chartfold/spa/css/chat.css` | 7 | Clear button styling |
| `src/chartfold/spa/chat_prompt.py` | 8 | Derive _CLINICAL_TABLES from _TABLE_MAP |
| `tests/test_chat_prompt.py` | 8 | Test derived table list |
| `tests/test_spa_export.py` | 6, 7 | Test DOM persistence and clear button presence |
