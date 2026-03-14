# Chat Enhancements Design (v1.2.1)

**Date:** 2026-03-13
**Scope:** Three improvements to the AI chat SPA feature

## Item 6: Conversation Persistence Across Navigation

**Problem:** `Chat.init()` resets `this.messages = []` and rebuilds the UI every time the user navigates to the "Ask AI" section. Navigating to "Lab Results" and back destroys the entire conversation.

**Solution:** Detach/reattach DOM.

`_buildUI()` must wrap everything (section header + chat container) in a single wrapper div stored as `Chat._container`. When `Sections.ask_ai` is called, check if `Chat._container` exists. If yes, just `el.appendChild(Chat._container)` to reattach. The SPA's `contentEl.textContent = ''` on navigate-away removes the wrapper from the DOM, but the JS reference and all child elements (messages, input state, scroll position) survive.

On first visit, `Chat._container` is null and full `init()` runs. On re-entry, the wrapper is reattached and input is re-focused.

**Changes:**
- `chat.js`: Wrap all UI in a single `_container` div. Split `init()` into first-time build vs re-entry reattach path.
- `sections.js`: `ask_ai` section checks `Chat._container` existence before deciding init vs reattach.

**Edge case:** Fresh page load → `Chat._container` is null → full init. No special handling needed.

## Item 7: Conversation Length Management

**Problem:** `this.messages` grows unboundedly. Long sessions could exceed Haiku 4.5's context window (200K tokens), causing API errors.

**Solution:** Sliding window + clear button.

**Sliding window:** `MAX_MESSAGES = 40`. After each agent loop completion, if `this.messages.length > MAX_MESSAGES`, trim from the front to keep the last 40 entries. The system prompt is sent fresh on every API request (not in `messages`), so truncation preserves schema context.

**Pair-aware trimming:** The Anthropic API requires every `tool_use` block in an assistant message to have a corresponding `tool_result` in the next user message. `_trimHistory()` must not split these pairs. Implementation: after slicing, check if `messages[0]` is a tool_result user message (i.e., `messages[0].role === 'user'` and `messages[0].content` is an array of tool_result objects). If so, drop it too (since its paired assistant tool_use message was already trimmed). Continue until `messages[0]` is a plain user text message.

**Clear button:** Small button in the status bar area. Resets `this.messages = []` and clears rendered messages via `this.messagesEl.textContent = ''`.

**Changes:**
- `chat.js`: Add `_trimHistory()` called after agent loop. Add clear button in `_buildUI()`. Add `_onClear()` handler.
- `chat.css`: Style the clear button (small, unobtrusive, near status bar).

**Why 40?** Each message pair (user + assistant) averages ~500-2000 tokens depending on SQL results. 40 messages ≈ 20 turns ≈ 10K-40K tokens, well within Haiku's 200K window while providing substantial conversation context. Heavy tool-use conversations may use more tokens per message, but 40 messages is conservative enough to stay well under the 200K limit even in worst cases.

## Item 8: Derive _CLINICAL_TABLES from _UNIQUE_KEYS

**Problem:** `chat_prompt.py` has a hardcoded `_CLINICAL_TABLES` list of 16 table names that must stay in sync with `schema.sql` and `db.py` manually. Per project convention: "Always prefer principled, scalable, non-ad-hoc solutions."

**Solution:** Import from `db.py`'s `_UNIQUE_KEYS` dict and filter out non-clinical tables.

```python
from chartfold.db import _UNIQUE_KEYS

_NON_CLINICAL_TABLES = {
    "documents", "load_log", "notes", "note_tags",
    "analyses", "analysis_tags", "source_assets",
}
_CLINICAL_TABLES = [t for t in _UNIQUE_KEYS if t not in _NON_CLINICAL_TABLES]
```

**Why `_UNIQUE_KEYS` not `_TABLE_MAP`:** `_TABLE_MAP` is a `list[tuple[str, str, type]]`, not a dict — iterating yields tuples, not table names. `_UNIQUE_KEYS` is a `dict[str, tuple[str, ...]]` with table names as string keys, and it includes `patients` (which `_TABLE_MAP` does not, since patients are loaded as a special case in `load_source()`).

**Why `documents` is excluded:** The current hardcoded list intentionally omits `documents` (a metadata table tracking source file references, not clinical content). It's added to the exclusion set.

**Changes:** `chat_prompt.py` only — replace the 16-line list with a 3-line derivation.

## Testing Strategy

All changes will use TDD (red-green-refactor).

**Item 6 (DOM persistence):** Test in `test_spa_export.py` that the generated HTML contains the reattach logic (presence of `Chat._container` check in the JS). Runtime behavior (messages surviving navigation) cannot be tested without a headless browser — out of scope for unit tests.

**Item 7 (sliding window + clear):**
- Test in `test_spa_export.py` that the clear button is present in the generated HTML.
- `_trimHistory()` logic is JavaScript and tested structurally (function exists in output JS). Pair-aware trimming correctness is verified by code review, not automated test.

**Item 8 (_CLINICAL_TABLES derivation):**
- Test that `_CLINICAL_TABLES` contains expected tables (patients, encounters, lab_results, etc.).
- Test that non-clinical tables (load_log, notes, documents, etc.) are excluded.
- Test that `_CLINICAL_TABLES` length matches `len(_UNIQUE_KEYS) - len(_NON_CLINICAL_TABLES)` — this automatically catches new tables being added to `_UNIQUE_KEYS`.

## Files Changed

| File | Item | Change |
|------|------|--------|
| `src/chartfold/spa/js/chat.js` | 6, 7 | Single wrapper div, DOM persistence, sliding window, clear button |
| `src/chartfold/spa/js/sections.js` | 6 | Reattach check in `ask_ai` |
| `src/chartfold/spa/css/chat.css` | 7 | Clear button styling |
| `src/chartfold/spa/chat_prompt.py` | 8 | Derive _CLINICAL_TABLES from _UNIQUE_KEYS |
| `tests/test_chat_prompt.py` | 8 | Test derived table list |
| `tests/test_spa_export.py` | 6, 7 | Test reattach logic and clear button in generated HTML |
