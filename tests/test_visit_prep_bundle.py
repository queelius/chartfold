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
