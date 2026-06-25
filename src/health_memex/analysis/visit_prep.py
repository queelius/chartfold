"""Visit preparation — generate a summary for upcoming appointments."""

from __future__ import annotations

from datetime import date, timedelta

from health_memex.config import LabTestConfig, get_lab_test_configs, load_config
from health_memex.db import HealthMemexDB


def generate_visit_prep(
    db: HealthMemexDB,
    visit_date: str = "",
    lookback_months: int = 3,
) -> dict:
    """Generate a visit preparation summary.

    Args:
        db: Database connection.
        visit_date: The upcoming visit date (ISO). Defaults to today.
        lookback_months: How many months back to include data.

    Returns dict with:
    - recent_labs: Labs from the lookback period
    - active_meds: Current active medications
    - recent_encounters: Encounters in lookback period
    - active_conditions: Active conditions/diagnoses
    - recent_imaging: Imaging studies in lookback period
    - upcoming_due: Lab tests that may be due for recheck
    """
    if not visit_date:
        visit_date = date.today().isoformat()

    try:
        vdate = date.fromisoformat(visit_date)
    except ValueError:
        vdate = date.today()

    lookback = (vdate - timedelta(days=lookback_months * 30)).isoformat()

    prep = {
        "visit_date": visit_date,
        "lookback_start": lookback,
        "recent_labs": db.query(
            "SELECT test_name, value, value_numeric, unit, ref_range, "
            "interpretation, result_date, source "
            "FROM lab_results WHERE archived_at IS NULL AND result_date >= ? "
            "ORDER BY result_date DESC",
            (lookback,),
        ),
        "active_meds": db.query(
            "SELECT name, sig, route, start_date, prescriber, source "
            "FROM medications WHERE archived_at IS NULL AND LOWER(status) = 'active' "
            "ORDER BY name"
        ),
        "recent_encounters": db.query(
            "SELECT encounter_date, encounter_type, facility, provider, reason, source "
            "FROM encounters WHERE archived_at IS NULL AND encounter_date >= ? "
            "ORDER BY encounter_date DESC",
            (lookback,),
        ),
        "active_conditions": db.query(
            "SELECT condition_name, icd10_code, onset_date, source "
            "FROM conditions WHERE archived_at IS NULL AND LOWER(clinical_status) = 'active' "
            "ORDER BY condition_name"
        ),
        "recent_imaging": db.query(
            "SELECT study_name, modality, study_date, impression, source "
            "FROM imaging_reports WHERE archived_at IS NULL AND study_date >= ? "
            "ORDER BY study_date DESC",
            (lookback,),
        ),
    }

    # Identify labs that might be due for recheck
    # Find tests with most recent result > 3 months before visit
    three_months_ago = lookback
    prep["upcoming_due"] = db.query(
        "SELECT test_name, MAX(result_date) as last_date, value, unit "
        "FROM lab_results "
        "WHERE archived_at IS NULL "
        "GROUP BY test_name "
        "HAVING MAX(result_date) < ? "
        "ORDER BY last_date DESC "
        "LIMIT 20",
        (three_months_ago,),
    )

    return prep


def _resolve_key_test_trends(
    db: HealthMemexDB,
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
    db: HealthMemexDB,
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
            f"FROM lab_results WHERE archived_at IS NULL AND LOWER(test_name) IN ({placeholders}) "
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
    db: HealthMemexDB,
    max_readings: int,
    top_n: int = 10,
) -> dict[str, list[dict]]:
    """Fall back to the top N most-frequent test names."""
    frequent = db.query(
        "SELECT test_name, COUNT(*) as cnt "
        "FROM lab_results WHERE archived_at IS NULL "
        "GROUP BY test_name ORDER BY cnt DESC LIMIT ?",
        (top_n,),
    )
    config_tests = [LabTestConfig(name=r["test_name"], match=[r["test_name"]]) for r in frequent]
    return _trends_from_config(db, config_tests, max_readings)


def generate_visit_prep_bundle(
    db: HealthMemexDB,
    visit_date: str = "",
    lookback_months: int = 6,
    key_test_readings: int = 8,
    include_analyses: bool = True,
    include_notes: bool = True,
    config_path: str = "",
) -> dict:
    """Generate a comprehensive visit preparation context bundle.

    Returns a structured dict with all data sections that give an LLM
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
        "FROM lab_results WHERE archived_at IS NULL AND result_date >= ? "
        "ORDER BY result_date DESC",
        (lookback,),
    )

    # 3. Imaging with full impressions and findings
    recent_imaging = db.query(
        "SELECT study_name, modality, study_date, impression, findings, source "
        "FROM imaging_reports WHERE archived_at IS NULL AND study_date >= ? "
        "ORDER BY study_date DESC",
        (lookback,),
    )

    # 4. Clinical notes (full content)
    recent_notes = db.query(
        "SELECT note_date, note_type, author, content, source "
        "FROM clinical_notes WHERE archived_at IS NULL AND note_date >= ? "
        "ORDER BY note_date DESC",
        (lookback,),
    )

    # 5. Active medications
    active_medications = db.query(
        "SELECT name, sig, route, start_date, prescriber, source "
        "FROM medications WHERE archived_at IS NULL AND LOWER(status) = 'active' "
        "ORDER BY name"
    )

    # 6. Active conditions
    active_conditions = db.query(
        "SELECT condition_name, icd10_code, onset_date, source "
        "FROM conditions WHERE archived_at IS NULL AND LOWER(clinical_status) = 'active' "
        "ORDER BY condition_name"
    )

    # 7. Recent procedures
    recent_procedures = db.query(
        "SELECT name, procedure_date, provider, facility, source "
        "FROM procedures WHERE archived_at IS NULL AND procedure_date >= ? "
        "ORDER BY procedure_date DESC",
        (lookback,),
    )

    # 8. Saved notes (full content with tags)
    saved_notes: list[dict] = []
    if include_notes:
        saved_notes = db.query(
            "SELECT id, title, content, created_at, updated_at FROM notes "
            "WHERE archived_at IS NULL ORDER BY updated_at DESC"
        )
        for note in saved_notes:
            note["tags"] = db.get_note_tags(note["id"])

    # 9. Saved analyses (full content with tags)
    saved_analyses: list[dict] = []
    if include_analyses:
        saved_analyses = db.query(
            "SELECT id, slug, title, category, summary, content, updated_at "
            "FROM analyses WHERE archived_at IS NULL ORDER BY updated_at DESC"
        )
        for analysis in saved_analyses:
            analysis["tags"] = db.get_analysis_tags(analysis["id"])

    # 10. Treatment context note
    treatment_context_note = _pick_treatment_context_note(recent_notes)

    # Provider from most recent encounter
    latest_encounter = db.query(
        "SELECT provider FROM encounters WHERE archived_at IS NULL "
        "ORDER BY encounter_date DESC LIMIT 1"
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
