"""Tests for the AI chat system prompt generation module."""

from __future__ import annotations

import json

import pytest

from chartfold.db import ChartfoldDB
from chartfold.models import LabResult, PatientRecord, UnifiedRecords
from chartfold.spa.chat_prompt import generate_system_prompt


@pytest.fixture
def chat_db(tmp_path):
    """Create a DB with patient, labs from two sources, and analyses."""
    db_path = str(tmp_path / "chat_test.db")
    db = ChartfoldDB(db_path)
    db.init_schema()

    # Load patient + labs from epic_anderson
    epic_records = UnifiedRecords(
        source="epic_anderson",
        patient=PatientRecord(
            source="epic_anderson",
            name="Jane Doe",
            date_of_birth="1970-05-15",
        ),
        lab_results=[
            LabResult(
                source="epic_anderson",
                test_name="CEA",
                value="3.2",
                value_numeric=3.2,
                result_date="2025-06-01",
            ),
        ],
    )
    db.load_source(epic_records, replace=True)

    # Load labs from meditech_houston
    meditech_records = UnifiedRecords(
        source="meditech_houston",
        lab_results=[
            LabResult(
                source="meditech_houston",
                test_name="CBC",
                value="normal",
                result_date="2025-07-01",
            ),
        ],
    )
    db.load_source(meditech_records, replace=True)

    # Save a current analysis
    db.save_analysis(
        slug="cancer-timeline",
        title="Cancer Timeline",
        content="# Timeline\n\nDiagnosed 2024...",
        frontmatter_json=json.dumps({"status": "current"}),
        category="oncology",
        tags=["cancer"],
    )

    # Save an archived analysis
    db.save_analysis(
        slug="old-draft",
        title="Old Draft",
        content="archived content",
        frontmatter_json=json.dumps({"status": "archived"}),
        category="general",
        tags=["draft"],
    )

    yield db
    db.close()


class TestGenerateSystemPrompt:
    """Tests for generate_system_prompt()."""

    def test_includes_role_instructions(self, chat_db):
        prompt = generate_system_prompt(chat_db.db_path)
        assert "medical data analyst" in prompt.lower()
        assert "SELECT" in prompt

    def test_includes_schema(self, chat_db):
        prompt = generate_system_prompt(chat_db.db_path)
        assert "CREATE TABLE" in prompt
        assert "lab_results" in prompt
        assert "medications" in prompt

    def test_includes_summary_stats(self, chat_db):
        prompt = generate_system_prompt(chat_db.db_path)
        assert "epic_anderson" in prompt
        assert "meditech_houston" in prompt

    def test_includes_current_analyses(self, chat_db):
        prompt = generate_system_prompt(chat_db.db_path)
        assert "Cancer Timeline" in prompt
        assert "Diagnosed 2024" in prompt

    def test_excludes_archived_analyses(self, chat_db):
        prompt = generate_system_prompt(chat_db.db_path)
        assert "Old Draft" not in prompt
        assert "archived content" not in prompt

    def test_handles_empty_db(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        db = ChartfoldDB(db_path)
        db.init_schema()
        db.close()

        prompt = generate_system_prompt(db_path)
        assert "CREATE TABLE" in prompt
        assert len(prompt) > 100  # Still has schema + role instructions
