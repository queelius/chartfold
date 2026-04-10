# Visit Prep Bundle: Design Spec

## Problem

The current `get_visit_prep` MCP tool returns a shallow data dump: recent labs, active meds, recent encounters, active conditions, and recent imaging from a lookback window. An LLM using this for visit preparation must make 10-15 additional tool calls to assemble the context it actually needs: lab trend history, full imaging impressions, clinical note content, saved analyses, treatment history, and prior patient-authored notes.

In practice, a useful visit prep session (like the April 2026 Dr. Tan prep) required calls to `get_visit_diff`, multiple `run_sql` queries for specific lab series, `get_lab_series_tool`, imaging queries with full findings, clinical note reads, and `search_analyses`. The LLM had to know what to ask for.

## Solution

A single MCP tool (`get_visit_prep_bundle`) that returns a comprehensive, structured context bundle. The LLM receives everything it needs in one call to run an interactive visit preparation session. Chartfold assembles; the LLM reasons.

## Design Decisions

**Chartfold does not do clinical reasoning.** No flagging, no interpretation, no question generation. The LLM handles all synthesis. Chartfold's job is to make sure the LLM has complete context.

**Full content, not summaries.** The patient database is bounded (single patient, ~1900 labs, ~125 notes, ~60 imaging reports). The full bundle fits well within a 1M-token context window. We return full text for imaging impressions, clinical notes, and saved analyses rather than truncated previews.

**Key test trends go deep.** Instead of only returning labs from the lookback window, the bundle includes the last N readings for each key test (configured in `chartfold.toml`). This gives the LLM the full trajectory (e.g., CEA trending from 4.7 to 1.8 over 8 months) without requiring follow-up queries.

**Saved notes and analyses are included by default.** These contain prior clinical reasoning, trial research, question lists, and molecular profiles authored by the patient or by Claude in prior sessions. They are first-class context for visit prep, not an afterthought.

## Bundle Structure

```python
{
    # Metadata
    "visit_date": "2026-04-02",           # ISO date (defaults to today)
    "lookback_start": "2025-10-02",       # computed from lookback_months
    "provider": "Dr. Tan",                # from most recent encounter, if available

    # 1. Lab trends for key tests (last N readings each)
    #    Key tests come from chartfold.toml [[lab_tests]].
    #    Falls back to top N most-frequent tests if no config.
    "lab_trends": {
        "CEA": [
            {"date": "2026-03-19", "value": "2.3", "numeric": 2.3,
             "ref_range": "<=5.0 ng/mL", "source": "epic_ihe_xdm"},
            ...
        ],
        "Platelets": [...],
        "Hemoglobin": [...],
        ...
    },

    # 2. All labs from the lookback window (includes key tests too;
    #    duplication with lab_trends is intentional so the LLM sees
    #    both the focused trend view and the full chronological list)
    "new_labs": [
        {"test_name": ..., "value": ..., "value_numeric": ..., "unit": ...,
         "ref_range": ..., "result_date": ..., "source": ...},
        ...
    ],

    # 3. Imaging with full impressions AND findings text
    "recent_imaging": [
        {"study_date": ..., "study_name": ..., "modality": ...,
         "impression": ..., "findings": ..., "source": ...},
        ...
    ],

    # 4. Clinical notes (full content, not previews)
    "recent_notes": [
        {"note_date": ..., "note_type": ..., "author": ...,
         "content": ..., "source": ...},
        ...
    ],

    # 5. Active medications
    "active_medications": [
        {"name": ..., "sig": ..., "route": ..., "start_date": ...,
         "prescriber": ..., "source": ...},
        ...
    ],

    # 6. Active conditions
    "active_conditions": [
        {"condition_name": ..., "icd10_code": ..., "onset_date": ...,
         "source": ...},
        ...
    ],

    # 7. Recent procedures (from lookback window)
    "recent_procedures": [
        {"name": ..., "procedure_date": ..., "provider": ...,
         "facility": ..., "source": ...},
        ...
    ],

    # 8. Saved chartfold notes (full content, all notes)
    "saved_notes": [
        {"id": 1, "title": ..., "content": ..., "tags": [...],
         "updated_at": ...},
        ...
    ],

    # 9. Saved analyses (full content, all analyses)
    "saved_analyses": [
        {"slug": ..., "title": ..., "category": ..., "summary": ...,
         "content": ..., "updated_at": ...},
        ...
    ],

    # 10. Treatment context note
    #     The most recent clinical note likely containing the full oncologic
    #     history and treatment plan. Identified by: longest recent note, or
    #     note containing provider name / "oncology" / "treatment".
    #     null if no candidate found.
    "treatment_context_note": {
        "note_date": ..., "note_type": ..., "author": ...,
        "content": ..., "source": ...
    }
}
```

## Parameters

```python
def get_visit_prep_bundle(
    visit_date: str = "",         # ISO date, defaults to today
    lookback_months: int = 6,     # wider default than current 3
    key_test_readings: int = 8,   # how many readings per key test trend
    include_analyses: bool = True, # include saved analyses
    include_notes: bool = True,    # include saved personal notes
) -> dict:
```

## Key Test Resolution

1. Read `chartfold.toml` via `config.py` to get `[[lab_tests]]` entries (each has `name` and `match` fields).
2. For each key test, query the last `key_test_readings` results using the `match` aliases (case-insensitive).
3. If no `chartfold.toml` exists or has no `[[lab_tests]]`, fall back to the 10 most-frequently-occurring test names in the database.

## Treatment Context Note Identification

Heuristic to find the most recent comprehensive oncology note:

1. From `recent_notes`, score each note:
   - +3 if content contains "oncology" or "oncologic" (case-insensitive)
   - +2 if content contains "treatment" and "history" (case-insensitive)
   - +1 if note_type contains "progress" (case-insensitive)
   - +1 per 1000 characters of content length (longer notes are more comprehensive)
2. Return the highest-scoring note. If no note scores above 0, return null.
3. The treatment context note is also included in `recent_notes` (no dedup needed; the LLM can see both the structured list and the highlighted pick).

## What Changes

| Component | Action |
|-----------|--------|
| `analysis/visit_prep.py` | Add `generate_visit_prep_bundle()` alongside existing `generate_visit_prep()` |
| `mcp/server.py` | Add `get_visit_prep_bundle` tool. Keep existing `get_visit_prep` unchanged. |
| `config.py` | No changes (already parses `[[lab_tests]]`) |
| `schema.sql` | No changes |
| `models.py` | No changes |
| `db.py` | No changes |

## What It Does NOT Do

- No clinical reasoning, flagging, or interpretation.
- No question generation.
- No external lookups (trials, web search, HealthEx).
- No PDF generation or formatting.

The LLM handles all synthesis, interpretation, and question formulation using the bundle as context.

## Testing Strategy

1. **Unit test `generate_visit_prep_bundle()`** using existing `analysis_db` or a new `visit_prep_db` fixture with labs, imaging, notes, medications, conditions, procedures, saved notes, and saved analyses.
2. **Test key test resolution** from config and fallback path.
3. **Test treatment context note scoring** with notes of varying lengths and keyword content.
4. **Test MCP tool wiring** in `test_mcp.py`.
5. **Test with no config file** (fallback to frequent tests).
6. **Test with empty database** (all fields present but empty lists).
