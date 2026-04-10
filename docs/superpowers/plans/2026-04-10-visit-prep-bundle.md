# Visit Prep Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `get_visit_prep_bundle` MCP tool that returns a comprehensive clinical context bundle in a single call, enabling LLM-driven visit preparation without follow-up queries.

**Architecture:** New function `generate_visit_prep_bundle()` in `analysis/visit_prep.py` assembles 10 data sections (lab trends, imaging, notes, medications, conditions, procedures, saved notes/analyses, treatment context note) from SQL queries + config. New MCP tool in `server.py` wraps it. Existing `get_visit_prep` is unchanged.

**Tech Stack:** Python 3.11+, SQLite, pytest, chartfold config (TOML)

---

### Task 1: Treatment Context Note Scoring Helper

This is a pure function with no DB dependency, so it's the easiest to TDD first.

**Files:**
- Modify: `src/chartfold/analysis/visit_prep.py`
- Test: `tests/test_visit_prep_bundle.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_visit_prep_bundle.py`:

```python
"""Tests for the visit prep bundle feature."""

from __future__ import annotations

import pytest


class TestScoreTreatmentContextNote:
    """Test the heuristic that identifies the most comprehensive clinical note."""

    def test_oncology_keyword_scores_highest(self):
        from chartfold.analysis.visit_prep import _score_treatment_context_note

        note = {
            "note_date": "2026-03-05",
            "note_type": "Progress Notes",
            "author": "Dr. Tan",
            "content": "Oncology Return/Follow Up Visit. Treatment history reviewed.",
            "source": "epic",
        }
        score = _score_treatment_context_note(note)
        # +3 (oncology) + 2 (treatment+history) + 1 (progress) = 6, plus length
        assert score >= 6

    def test_short_note_without_keywords_scores_zero(self):
        from chartfold.analysis.visit_prep import _score_treatment_context_note

        note = {
            "note_date": "2026-03-01",
            "note_type": "Vitals",
            "author": "",
            "content": "BP 120/80",
            "source": "epic",
        }
        assert _score_treatment_context_note(note) == 0

    def test_long_note_scores_by_length(self):
        from chartfold.analysis.visit_prep import _score_treatment_context_note

        note = {
            "note_date": "2026-03-05",
            "note_type": "H&P Notes",
            "author": "",
            "content": "x" * 5000,
            "source": "epic",
        }
        score = _score_treatment_context_note(note)
        # +1 per 1000 chars = 5
        assert score == 5

    def test_progress_note_type_adds_one(self):
        from chartfold.analysis.visit_prep import _score_treatment_context_note

        note = {
            "note_date": "2026-03-05",
            "note_type": "Progress Notes",
            "author": "",
            "content": "Short note.",
            "source": "epic",
        }
        assert _score_treatment_context_note(note) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/spinoza/github/beta/chartfold && python -m pytest tests/test_visit_prep_bundle.py -v`
Expected: FAIL with `ImportError: cannot import name '_score_treatment_context_note'`

- [ ] **Step 3: Implement the scoring function**

Add to `src/chartfold/analysis/visit_prep.py` (after the existing `generate_visit_prep` function):

```python
def _score_treatment_context_note(note: dict) -> int:
    """Score a clinical note for likelihood of being a treatment context note.

    Higher scores indicate more comprehensive oncology notes. Returns 0
    for notes with no relevant signals.
    """
    score = 0
    content = (note.get("content") or "").lower()
    note_type = (note.get("note_type") or "").lower()

    if "oncolog" in content:
        score += 3
    if "treatment" in content and "history" in content:
        score += 2
    if "progress" in note_type:
        score += 1

    # Longer notes are more likely to be comprehensive
    score += len(content) // 1000

    return score
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/spinoza/github/beta/chartfold && python -m pytest tests/test_visit_prep_bundle.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd /home/spinoza/github/beta/chartfold
git add tests/test_visit_prep_bundle.py src/chartfold/analysis/visit_prep.py
git commit -m "feat: add treatment context note scoring helper for visit prep bundle"
```

---

### Task 2: Key Test Resolution Helper

Resolves key tests from config (with fallback to frequent tests from DB).

**Files:**
- Modify: `src/chartfold/analysis/visit_prep.py`
- Test: `tests/test_visit_prep_bundle.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_visit_prep_bundle.py`:

```python
from chartfold.config import LabTestConfig
from chartfold.db import ChartfoldDB
from chartfold.models import LabResult, UnifiedRecords


@pytest.fixture
def prep_db(tmp_path):
    """Database with enough data for visit prep bundle tests."""
    db = ChartfoldDB(str(tmp_path / "prep.db"))
    db.init_schema()

    records = UnifiedRecords(
        source="test_source",
        lab_results=[
            # CEA: 8 readings for trend
            LabResult(source="test_source", test_name="CEA", value="5.8",
                      value_numeric=5.8, ref_range="<=5.0", result_date="2025-07-08"),
            LabResult(source="test_source", test_name="CEA", value="4.6",
                      value_numeric=4.6, ref_range="<=5.0", result_date="2025-07-31"),
            LabResult(source="test_source", test_name="CEA", value="3.9",
                      value_numeric=3.9, ref_range="<=5.0", result_date="2025-08-14"),
            LabResult(source="test_source", test_name="CEA", value="2.9",
                      value_numeric=2.9, ref_range="<=5.0", result_date="2025-11-06"),
            LabResult(source="test_source", test_name="CEA", value="1.8",
                      value_numeric=1.8, ref_range="<=5.0", result_date="2026-01-15"),
            LabResult(source="test_source", test_name="CEA", value="1.7",
                      value_numeric=1.7, ref_range="<=5.0", result_date="2026-02-05"),
            LabResult(source="test_source", test_name="CEA", value="1.8",
                      value_numeric=1.8, ref_range="<=5.0", result_date="2026-03-05"),
            LabResult(source="test_source", test_name="CEA", value="2.3",
                      value_numeric=2.3, ref_range="<=5.0", result_date="2026-03-19"),
            # Hemoglobin: 3 readings
            LabResult(source="test_source", test_name="Hemoglobin", value="15.8",
                      value_numeric=15.8, result_date="2026-01-15"),
            LabResult(source="test_source", test_name="Hemoglobin", value="14.3",
                      value_numeric=14.3, result_date="2026-03-19"),
            LabResult(source="test_source", test_name="Hemoglobin", value="16.1",
                      value_numeric=16.1, result_date="2026-02-19"),
            # WBC: 2 readings
            LabResult(source="test_source", test_name="WBC", value="4.57",
                      value_numeric=4.57, result_date="2026-03-05"),
            LabResult(source="test_source", test_name="WBC", value="4.32",
                      value_numeric=4.32, result_date="2026-03-19"),
            # Glucose: 1 reading (least frequent)
            LabResult(source="test_source", test_name="Glucose", value="103",
                      value_numeric=103.0, result_date="2026-03-19"),
        ],
    )
    db.load_source(records)
    yield db
    db.close()


class TestResolveKeyTestTrends:

    def test_with_config(self, prep_db):
        from chartfold.analysis.visit_prep import _resolve_key_test_trends

        config_tests = [
            LabTestConfig(name="CEA", match=["CEA"]),
            LabTestConfig(name="Hemoglobin", match=["Hemoglobin"]),
        ]
        trends = _resolve_key_test_trends(prep_db, config_tests, max_readings=8)
        assert "CEA" in trends
        assert "Hemoglobin" in trends
        assert len(trends["CEA"]) == 8
        assert len(trends["Hemoglobin"]) == 3
        # Verify chronological order (oldest first)
        dates = [r["date"] for r in trends["CEA"]]
        assert dates == sorted(dates)

    def test_fallback_without_config(self, prep_db):
        from chartfold.analysis.visit_prep import _resolve_key_test_trends

        trends = _resolve_key_test_trends(prep_db, config_tests=[], max_readings=8)
        # Should fall back to top 10 most-frequent tests
        assert "CEA" in trends  # 8 readings, most frequent
        assert "Hemoglobin" in trends  # 3 readings
        assert "WBC" in trends  # 2 readings
        assert "Glucose" in trends  # 1 reading

    def test_max_readings_limits_output(self, prep_db):
        from chartfold.analysis.visit_prep import _resolve_key_test_trends

        config_tests = [LabTestConfig(name="CEA", match=["CEA"])]
        trends = _resolve_key_test_trends(prep_db, config_tests, max_readings=3)
        # Should return last 3 only
        assert len(trends["CEA"]) == 3
        assert trends["CEA"][-1]["date"] == "2026-03-19"

    def test_match_aliases(self, prep_db):
        from chartfold.analysis.visit_prep import _resolve_key_test_trends

        # Match "Hemoglobin" via alias "Hgb" (case-insensitive match on display name)
        config_tests = [LabTestConfig(name="Hgb", match=["Hemoglobin", "Hgb"])]
        trends = _resolve_key_test_trends(prep_db, config_tests, max_readings=8)
        assert "Hgb" in trends
        assert len(trends["Hgb"]) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/spinoza/github/beta/chartfold && python -m pytest tests/test_visit_prep_bundle.py::TestResolveKeyTestTrends -v`
Expected: FAIL with `ImportError: cannot import name '_resolve_key_test_trends'`

- [ ] **Step 3: Implement key test resolution**

Add to `src/chartfold/analysis/visit_prep.py`:

```python
from chartfold.config import LabTestConfig


def _resolve_key_test_trends(
    db: ChartfoldDB,
    config_tests: list[LabTestConfig],
    max_readings: int = 8,
) -> dict[str, list[dict]]:
    """Resolve key test trends from config or fallback to most-frequent tests.

    Returns {display_name: [{"date", "value", "numeric", "ref_range", "source"}, ...]}.
    Results are in chronological order (oldest first).
    """
    if config_tests:
        return _trends_from_config(db, config_tests, max_readings)
    return _trends_from_frequent(db, max_readings)


def _trends_from_config(
    db: ChartfoldDB,
    config_tests: list[LabTestConfig],
    max_readings: int,
) -> dict[str, list[dict]]:
    """Build trend data using configured test names and aliases."""
    trends: dict[str, list[dict]] = {}
    for test in config_tests:
        if not test.match:
            continue
        placeholders = ", ".join("?" for _ in test.match)
        params = [m.lower() for m in test.match]
        rows = db.query(
            f"SELECT test_name, value, value_numeric, ref_range, result_date, source "
            f"FROM lab_results WHERE LOWER(test_name) IN ({placeholders}) "
            f"ORDER BY result_date DESC LIMIT ?",
            tuple(params + [max_readings]),
        )
        if rows:
            trends[test.name] = [
                {
                    "date": r["result_date"],
                    "value": r["value"],
                    "numeric": r["value_numeric"],
                    "ref_range": r["ref_range"],
                    "source": r["source"],
                }
                for r in reversed(rows)  # chronological order
            ]
    return trends


def _trends_from_frequent(
    db: ChartfoldDB,
    max_readings: int,
    top_n: int = 10,
) -> dict[str, list[dict]]:
    """Fall back to the top N most-frequent test names."""
    frequent = db.query(
        "SELECT test_name, COUNT(*) as cnt "
        "FROM lab_results GROUP BY test_name ORDER BY cnt DESC LIMIT ?",
        (top_n,),
    )
    config_tests = [LabTestConfig(name=r["test_name"], match=[r["test_name"]]) for r in frequent]
    return _trends_from_config(db, config_tests, max_readings)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/spinoza/github/beta/chartfold && python -m pytest tests/test_visit_prep_bundle.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
cd /home/spinoza/github/beta/chartfold
git add tests/test_visit_prep_bundle.py src/chartfold/analysis/visit_prep.py
git commit -m "feat: add key test trend resolution for visit prep bundle"
```

---

### Task 3: The Bundle Function

Assembles all 10 sections into the complete bundle dict.

**Files:**
- Modify: `src/chartfold/analysis/visit_prep.py`
- Test: `tests/test_visit_prep_bundle.py`

- [ ] **Step 1: Extend the fixture and write the failing test**

Add more data to the `prep_db` fixture in `tests/test_visit_prep_bundle.py`. Replace the existing `prep_db` fixture with:

```python
from chartfold.models import (
    ClinicalNote, ConditionRecord, EncounterRecord, ImagingReport,
    LabResult, MedicationRecord, ProcedureRecord, UnifiedRecords,
)


@pytest.fixture
def prep_db(tmp_path):
    """Database with enough data for visit prep bundle tests."""
    db = ChartfoldDB(str(tmp_path / "prep.db"))
    db.init_schema()

    records = UnifiedRecords(
        source="test_source",
        lab_results=[
            LabResult(source="test_source", test_name="CEA", value="5.8",
                      value_numeric=5.8, ref_range="<=5.0", result_date="2025-07-08"),
            LabResult(source="test_source", test_name="CEA", value="4.6",
                      value_numeric=4.6, ref_range="<=5.0", result_date="2025-07-31"),
            LabResult(source="test_source", test_name="CEA", value="3.9",
                      value_numeric=3.9, ref_range="<=5.0", result_date="2025-08-14"),
            LabResult(source="test_source", test_name="CEA", value="2.9",
                      value_numeric=2.9, ref_range="<=5.0", result_date="2025-11-06"),
            LabResult(source="test_source", test_name="CEA", value="1.8",
                      value_numeric=1.8, ref_range="<=5.0", result_date="2026-01-15"),
            LabResult(source="test_source", test_name="CEA", value="1.7",
                      value_numeric=1.7, ref_range="<=5.0", result_date="2026-02-05"),
            LabResult(source="test_source", test_name="CEA", value="1.8",
                      value_numeric=1.8, ref_range="<=5.0", result_date="2026-03-05"),
            LabResult(source="test_source", test_name="CEA", value="2.3",
                      value_numeric=2.3, ref_range="<=5.0", result_date="2026-03-19"),
            LabResult(source="test_source", test_name="Hemoglobin", value="15.8",
                      value_numeric=15.8, result_date="2026-01-15"),
            LabResult(source="test_source", test_name="Hemoglobin", value="14.3",
                      value_numeric=14.3, result_date="2026-03-19"),
            LabResult(source="test_source", test_name="Hemoglobin", value="16.1",
                      value_numeric=16.1, result_date="2026-02-19"),
            LabResult(source="test_source", test_name="WBC", value="4.57",
                      value_numeric=4.57, result_date="2026-03-05"),
            LabResult(source="test_source", test_name="WBC", value="4.32",
                      value_numeric=4.32, result_date="2026-03-19"),
            LabResult(source="test_source", test_name="Glucose", value="103",
                      value_numeric=103.0, result_date="2026-03-19"),
        ],
        encounters=[
            EncounterRecord(source="test_source", encounter_date="2026-03-05",
                            encounter_type="Office Visit", provider="Dr. Tan",
                            facility="Siteman"),
            EncounterRecord(source="test_source", encounter_date="2026-03-19",
                            encounter_type="Infusion", provider="Amy Ngo, NP",
                            facility="Siteman"),
        ],
        imaging_reports=[
            ImagingReport(source="test_source", study_name="MRI Abdomen Pelvis",
                          modality="MRI", study_date="2026-03-31",
                          impression="No new disease.",
                          findings="Evolving postsurgical changes."),
        ],
        clinical_notes=[
            ClinicalNote(source="test_source", note_type="Progress Notes",
                         author="Dr. Tan", note_date="2026-03-05",
                         content="Oncology Return Visit. Treatment history reviewed. "
                                 "Metastatic Terminal Ileum Adenocarcinoma. " + "x" * 2000),
            ClinicalNote(source="test_source", note_type="Progress Notes",
                         author="Amy Ngo, NP", note_date="2026-03-19",
                         content="Pt presenting for C4 FOLFOX."),
        ],
        medications=[
            MedicationRecord(source="test_source", name="levothyroxine 125 mcg",
                             status="active", sig="1 tablet daily"),
        ],
        conditions=[
            ConditionRecord(source="test_source", condition_name="Colon cancer",
                            icd10_code="C18.9", clinical_status="active"),
        ],
        procedures=[
            ProcedureRecord(source="test_source", name="Liver resection",
                            procedure_date="2025-12-18", facility="BJH"),
        ],
    )
    db.load_source(records)

    # Add saved notes and analyses
    db.save_note("Trial Research", "Bot/Bal and BNT122 options...",
                 tags=["oncology", "clinical-trials"])
    db.save_analysis(
        slug="cancer-timeline", title="Cancer Timeline",
        content="Full chronological narrative...", category="oncology",
        summary="Timeline from diagnosis to present", tags=["oncology"],
    )

    yield db
    db.close()
```

Then add the bundle tests:

```python
class TestGenerateVisitPrepBundle:

    def test_returns_all_sections(self, prep_db):
        from chartfold.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02")
        expected_keys = {
            "visit_date", "lookback_start", "provider",
            "lab_trends", "new_labs", "recent_imaging", "recent_notes",
            "active_medications", "active_conditions", "recent_procedures",
            "saved_notes", "saved_analyses", "treatment_context_note",
        }
        assert set(bundle.keys()) == expected_keys

    def test_visit_date_defaults_to_today(self, prep_db):
        from chartfold.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db)
        assert bundle["visit_date"] != ""

    def test_provider_from_recent_encounter(self, prep_db):
        from chartfold.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02")
        # Most recent encounter provider
        assert bundle["provider"] == "Amy Ngo, NP"

    def test_lab_trends_populated(self, prep_db):
        from chartfold.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02")
        # Fallback mode (no config file) should pick up all 4 tests
        assert len(bundle["lab_trends"]) >= 3

    def test_new_labs_from_lookback(self, prep_db):
        from chartfold.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(
            prep_db, visit_date="2026-04-02", lookback_months=6
        )
        assert len(bundle["new_labs"]) > 0

    def test_imaging_includes_findings(self, prep_db):
        from chartfold.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02")
        assert len(bundle["recent_imaging"]) == 1
        assert bundle["recent_imaging"][0]["findings"] == "Evolving postsurgical changes."

    def test_notes_include_full_content(self, prep_db):
        from chartfold.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02")
        assert len(bundle["recent_notes"]) == 2
        # Full content, not truncated preview
        assert len(bundle["recent_notes"][0]["content"]) > 300

    def test_treatment_context_note_identified(self, prep_db):
        from chartfold.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02")
        ctx = bundle["treatment_context_note"]
        assert ctx is not None
        assert "Oncology" in ctx["content"]

    def test_saved_notes_included(self, prep_db):
        from chartfold.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02")
        assert len(bundle["saved_notes"]) == 1
        assert bundle["saved_notes"][0]["title"] == "Trial Research"
        assert "tags" in bundle["saved_notes"][0]

    def test_saved_analyses_included(self, prep_db):
        from chartfold.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(prep_db, visit_date="2026-04-02")
        assert len(bundle["saved_analyses"]) == 1
        assert bundle["saved_analyses"][0]["slug"] == "cancer-timeline"

    def test_exclude_analyses(self, prep_db):
        from chartfold.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(
            prep_db, visit_date="2026-04-02", include_analyses=False
        )
        assert bundle["saved_analyses"] == []

    def test_exclude_notes(self, prep_db):
        from chartfold.analysis.visit_prep import generate_visit_prep_bundle

        bundle = generate_visit_prep_bundle(
            prep_db, visit_date="2026-04-02", include_notes=False
        )
        assert bundle["saved_notes"] == []

    def test_empty_db(self, tmp_path):
        from chartfold.analysis.visit_prep import generate_visit_prep_bundle

        db = ChartfoldDB(str(tmp_path / "empty.db"))
        db.init_schema()
        bundle = generate_visit_prep_bundle(db)
        assert bundle["lab_trends"] == {}
        assert bundle["new_labs"] == []
        assert bundle["recent_imaging"] == []
        assert bundle["treatment_context_note"] is None
        db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/spinoza/github/beta/chartfold && python -m pytest tests/test_visit_prep_bundle.py::TestGenerateVisitPrepBundle -v`
Expected: FAIL with `ImportError: cannot import name 'generate_visit_prep_bundle'`

- [ ] **Step 3: Implement generate_visit_prep_bundle**

Add to `src/chartfold/analysis/visit_prep.py`:

```python
from chartfold.config import LabTestConfig, load_config, get_lab_test_configs


def generate_visit_prep_bundle(
    db: ChartfoldDB,
    visit_date: str = "",
    lookback_months: int = 6,
    key_test_readings: int = 8,
    include_analyses: bool = True,
    include_notes: bool = True,
    config_path: str = "",
) -> dict:
    """Generate a comprehensive visit preparation context bundle.

    Returns a structured dict with 10 data sections that give an LLM
    everything it needs for interactive visit prep in a single call.
    """
    if not visit_date:
        visit_date = date.today().isoformat()

    try:
        vdate = date.fromisoformat(visit_date)
    except ValueError:
        vdate = date.today()
        visit_date = vdate.isoformat()

    lookback = (vdate - timedelta(days=lookback_months * 30)).isoformat()

    # Resolve key tests from config
    config_tests: list[LabTestConfig] = []
    if config_path:
        config = load_config(config_path)
        config_tests = get_lab_test_configs(config)

    # 1. Lab trends
    lab_trends = _resolve_key_test_trends(db, config_tests, max_readings=key_test_readings)

    # 2. All labs from lookback window
    new_labs = db.query(
        "SELECT test_name, value, value_numeric, unit, ref_range, "
        "interpretation, result_date, source "
        "FROM lab_results WHERE result_date >= ? "
        "ORDER BY result_date DESC",
        (lookback,),
    )

    # 3. Imaging with full impressions and findings
    recent_imaging = db.query(
        "SELECT study_name, modality, study_date, impression, findings, source "
        "FROM imaging_reports WHERE study_date >= ? "
        "ORDER BY study_date DESC",
        (lookback,),
    )

    # 4. Clinical notes (full content)
    recent_notes = db.query(
        "SELECT note_date, note_type, author, content, source "
        "FROM clinical_notes WHERE note_date >= ? "
        "ORDER BY note_date DESC",
        (lookback,),
    )

    # 5. Active medications
    active_medications = db.query(
        "SELECT name, sig, route, start_date, prescriber, source "
        "FROM medications WHERE LOWER(status) = 'active' "
        "ORDER BY name"
    )

    # 6. Active conditions
    active_conditions = db.query(
        "SELECT condition_name, icd10_code, onset_date, source "
        "FROM conditions WHERE LOWER(clinical_status) = 'active' "
        "ORDER BY condition_name"
    )

    # 7. Recent procedures
    recent_procedures = db.query(
        "SELECT name, procedure_date, provider, facility, source "
        "FROM procedures WHERE procedure_date >= ? "
        "ORDER BY procedure_date DESC",
        (lookback,),
    )

    # 8. Saved notes (full content with tags)
    saved_notes: list[dict] = []
    if include_notes:
        saved_notes = db.query(
            "SELECT id, title, content, created_at, updated_at "
            "FROM notes ORDER BY updated_at DESC"
        )
        for note in saved_notes:
            note["tags"] = db._fetch_tags("note_tags", "note_id", note["id"])

    # 9. Saved analyses (full content with tags)
    saved_analyses: list[dict] = []
    if include_analyses:
        saved_analyses = db.query(
            "SELECT id, slug, title, category, summary, content, updated_at "
            "FROM analyses ORDER BY updated_at DESC"
        )
        for analysis in saved_analyses:
            analysis["tags"] = db._fetch_tags("analysis_tags", "analysis_id", analysis["id"])

    # 10. Treatment context note
    treatment_context_note = _pick_treatment_context_note(recent_notes)

    # Provider from most recent encounter
    latest_encounter = db.query(
        "SELECT provider FROM encounters ORDER BY encounter_date DESC LIMIT 1"
    )
    provider = latest_encounter[0]["provider"] if latest_encounter else ""

    return {
        "visit_date": visit_date,
        "lookback_start": lookback,
        "provider": provider,
        "lab_trends": lab_trends,
        "new_labs": new_labs,
        "recent_imaging": recent_imaging,
        "recent_notes": recent_notes,
        "active_medications": active_medications,
        "active_conditions": active_conditions,
        "recent_procedures": recent_procedures,
        "saved_notes": saved_notes,
        "saved_analyses": saved_analyses,
        "treatment_context_note": treatment_context_note,
    }


def _pick_treatment_context_note(notes: list[dict]) -> dict | None:
    """Pick the most likely treatment context note from a list of clinical notes."""
    if not notes:
        return None
    best = max(notes, key=_score_treatment_context_note)
    if _score_treatment_context_note(best) <= 0:
        return None
    return best
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/spinoza/github/beta/chartfold && python -m pytest tests/test_visit_prep_bundle.py -v`
Expected: 21 passed

- [ ] **Step 5: Run full test suite for regressions**

Run: `cd /home/spinoza/github/beta/chartfold && python -m pytest --tb=short -q`
Expected: 1145 passed (1124 existing + 21 new)

- [ ] **Step 6: Commit**

```bash
cd /home/spinoza/github/beta/chartfold
git add src/chartfold/analysis/visit_prep.py tests/test_visit_prep_bundle.py
git commit -m "feat: add generate_visit_prep_bundle with 10-section context assembly"
```

---

### Task 4: MCP Tool Wiring

Wire the bundle function into the MCP server.

**Files:**
- Modify: `src/chartfold/mcp/server.py`
- Test: `tests/test_mcp.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mcp.py` (find the existing visit prep test class or add a new one):

```python
class TestVisitPrepBundle:
    def test_get_visit_prep_bundle_returns_all_sections(self, mcp_db):
        from chartfold.mcp.server import get_visit_prep_bundle

        result = get_visit_prep_bundle(visit_date="2026-04-02")
        assert isinstance(result, dict)
        expected_keys = {
            "visit_date", "lookback_start", "provider",
            "lab_trends", "new_labs", "recent_imaging", "recent_notes",
            "active_medications", "active_conditions", "recent_procedures",
            "saved_notes", "saved_analyses", "treatment_context_note",
        }
        assert set(result.keys()) == expected_keys
        # mcp_db has CEA lab data
        assert "CEA" in result["lab_trends"] or len(result["lab_trends"]) > 0

    def test_get_visit_prep_bundle_exclude_flags(self, mcp_db):
        from chartfold.mcp.server import get_visit_prep_bundle

        result = get_visit_prep_bundle(
            include_analyses=False, include_notes=False
        )
        assert result["saved_analyses"] == []
        assert result["saved_notes"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/spinoza/github/beta/chartfold && python -m pytest tests/test_mcp.py::TestVisitPrepBundle -v`
Expected: FAIL with `ImportError: cannot import name 'get_visit_prep_bundle'`

- [ ] **Step 3: Add the MCP tool**

Add to `src/chartfold/mcp/server.py`, near the existing `get_visit_prep` tool:

```python
@mcp.tool()
def get_visit_prep_bundle(
    visit_date: str = "",
    lookback_months: int = 6,
    key_test_readings: int = 8,
    include_analyses: bool = True,
    include_notes: bool = True,
) -> dict:
    """Get a comprehensive visit preparation context bundle in a single call.

    Returns a structured dict with 10 data sections for LLM-driven visit prep:
    lab_trends (key tests with last N readings), new_labs, recent_imaging (full
    impressions + findings), recent_notes (full content), active_medications,
    active_conditions, recent_procedures, saved_notes, saved_analyses, and
    treatment_context_note (auto-identified comprehensive oncology note).

    The LLM receives everything it needs for interactive visit preparation
    without follow-up queries. Chartfold assembles; the LLM reasons.

    Args:
        visit_date: Upcoming visit date (ISO). Defaults to today.
        lookback_months: Months of history to include (default 6).
        key_test_readings: Number of trend readings per key test (default 8).
        include_analyses: Include saved analysis documents (default True).
        include_notes: Include saved personal notes (default True).
    """
    db = _get_db()
    try:
        from chartfold.analysis.visit_prep import generate_visit_prep_bundle

        config_path = os.environ.get("CHARTFOLD_CONFIG", "")
        return generate_visit_prep_bundle(
            db,
            visit_date=visit_date,
            lookback_months=lookback_months,
            key_test_readings=key_test_readings,
            include_analyses=include_analyses,
            include_notes=include_notes,
            config_path=config_path,
        )
    finally:
        db.close()
```

Also add `import os` at the top of `server.py` if not already present.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/spinoza/github/beta/chartfold && python -m pytest tests/test_mcp.py::TestVisitPrepBundle -v`
Expected: 2 passed

- [ ] **Step 5: Run full test suite**

Run: `cd /home/spinoza/github/beta/chartfold && python -m pytest --tb=short -q`
Expected: 1147 passed

- [ ] **Step 6: Commit**

```bash
cd /home/spinoza/github/beta/chartfold
git add src/chartfold/mcp/server.py tests/test_mcp.py
git commit -m "feat: add get_visit_prep_bundle MCP tool"
```

---

### Task 5: Verify Against Real Data

Smoke test the bundle against the actual patient database.

**Files:** None (manual verification)

- [ ] **Step 1: Run against real database**

```bash
cd /home/spinoza/github/personal/health_stats/chartfold
python -c "
import sys
sys.path.insert(0, '/home/spinoza/github/beta/chartfold/src')
from chartfold.db import ChartfoldDB
from chartfold.analysis.visit_prep import generate_visit_prep_bundle

db = ChartfoldDB('chartfold.db')
bundle = generate_visit_prep_bundle(
    db, visit_date='2026-04-02', config_path='chartfold.toml'
)

print(f'Visit: {bundle[\"visit_date\"]}, Lookback: {bundle[\"lookback_start\"]}')
print(f'Provider: {bundle[\"provider\"]}')
print(f'Lab trends: {list(bundle[\"lab_trends\"].keys())}')
for name, readings in bundle['lab_trends'].items():
    print(f'  {name}: {len(readings)} readings, latest {readings[-1][\"date\"]} = {readings[-1][\"value\"]}')
print(f'New labs: {len(bundle[\"new_labs\"])}')
print(f'Imaging: {len(bundle[\"recent_imaging\"])}')
print(f'Notes: {len(bundle[\"recent_notes\"])}')
print(f'Active meds: {len(bundle[\"active_medications\"])}')
print(f'Active conditions: {len(bundle[\"active_conditions\"])}')
print(f'Procedures: {len(bundle[\"recent_procedures\"])}')
print(f'Saved notes: {len(bundle[\"saved_notes\"])}')
print(f'Saved analyses: {len(bundle[\"saved_analyses\"])}')
ctx = bundle['treatment_context_note']
if ctx:
    print(f'Treatment ctx: {ctx[\"note_date\"]} by {ctx[\"author\"]} ({len(ctx[\"content\"])} chars)')
else:
    print('Treatment ctx: None')
db.close()
"
```

Expected output should show:
- Lab trends for CEA, Hemoglobin, etc. with ~8 readings each
- Multiple imaging reports, clinical notes
- Saved notes (Trial Research, etc.) and analyses (cancer-timeline, molecular-profile, etc.)
- Treatment context note identified as the long Dr. Tan progress note

- [ ] **Step 2: Run full test suite one final time**

Run: `cd /home/spinoza/github/beta/chartfold && python -m pytest --tb=short -q`
Expected: All tests pass
