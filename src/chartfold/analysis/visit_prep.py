"""Visit preparation — generate a summary for upcoming appointments."""

from __future__ import annotations

from datetime import date, timedelta

from chartfold.db import ChartfoldDB


def generate_visit_prep(
    db: ChartfoldDB,
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
            "FROM lab_results WHERE result_date >= ? "
            "ORDER BY result_date DESC",
            (lookback,),
        ),
        "active_meds": db.query(
            "SELECT name, sig, route, start_date, prescriber, source "
            "FROM medications WHERE LOWER(status) = 'active' "
            "ORDER BY name"
        ),
        "recent_encounters": db.query(
            "SELECT encounter_date, encounter_type, facility, provider, reason, source "
            "FROM encounters WHERE encounter_date >= ? "
            "ORDER BY encounter_date DESC",
            (lookback,),
        ),
        "active_conditions": db.query(
            "SELECT condition_name, icd10_code, onset_date, source "
            "FROM conditions WHERE LOWER(clinical_status) = 'active' "
            "ORDER BY condition_name"
        ),
        "recent_imaging": db.query(
            "SELECT study_name, modality, study_date, impression, source "
            "FROM imaging_reports WHERE study_date >= ? "
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
        "GROUP BY test_name "
        "HAVING MAX(result_date) < ? "
        "ORDER BY last_date DESC "
        "LIMIT 20",
        (three_months_ago,),
    )

    return prep
