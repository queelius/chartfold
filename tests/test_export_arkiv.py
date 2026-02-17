"""Tests for chartfold arkiv export (JSONL + manifest format)."""

import json
import os

import pytest

from chartfold.db import ChartfoldDB
from chartfold.export_arkiv import (
    _FK_FIELDS,
    _MAX_ENUM_VALUES,
    _STRIP_COLS,
    _TIMESTAMP_FIELDS,
    _COLLECTION_DESCRIPTIONS,
    _build_schema,
    _export_table,
    _export_table_with_tags,
    _row_to_record,
)
from chartfold.models import (
    FamilyHistoryRecord,
    LabResult,
    MedicationRecord,
    PathologyReport,
    ProcedureRecord,
    UnifiedRecords,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite database with schema initialized."""
    db_path = str(tmp_path / "test.db")
    db = ChartfoldDB(db_path)
    db.init_schema()
    yield db
    db.close()


@pytest.fixture
def lab_row():
    """A typical lab_results row dict as returned by db.query()."""
    return {
        "id": 42,
        "source": "epic_anderson",
        "source_doc_id": "DOC0003",
        "test_name": "CEA",
        "test_loinc": "2039-6",
        "panel_name": "Tumor Markers",
        "value": "5.8",
        "value_numeric": 5.8,
        "unit": "ng/mL",
        "ref_range": "0.0-3.0",
        "interpretation": "H",
        "result_date": "2025-01-15",
        "status": "final",
    }


@pytest.fixture
def family_history_row():
    """A family_history row with no timestamp field."""
    return {
        "id": 7,
        "source": "epic_anderson",
        "source_doc_id": "DOC0001",
        "relation": "Father",
        "condition": "Colon cancer",
        "age_at_onset": None,
        "deceased": 0,
    }


@pytest.fixture
def pathology_row():
    """A pathology_reports row with a procedure_id FK."""
    return {
        "id": 3,
        "source": "test_surgical",
        "source_doc_id": None,
        "procedure_id": 10,
        "report_date": "2024-07-03",
        "specimen": "Right colon",
        "diagnosis": "Invasive adenocarcinoma",
        "gross_description": None,
        "microscopic_description": None,
        "staging": "pT3N2a",
        "margins": "Positive",
        "lymph_nodes": "4 of 14",
        "full_text": None,
    }


@pytest.fixture
def db_with_labs(tmp_db):
    """DB with a few lab results loaded."""
    records = UnifiedRecords(
        source="test_source",
        lab_results=[
            LabResult(
                source="test_source",
                test_name="CEA",
                test_loinc="2039-6",
                value="5.8",
                value_numeric=5.8,
                unit="ng/mL",
                ref_range="0.0-3.0",
                interpretation="H",
                result_date="2025-01-15",
                status="final",
            ),
            LabResult(
                source="test_source",
                test_name="Hemoglobin",
                value="12.5",
                value_numeric=12.5,
                unit="g/dL",
                ref_range="13.0-17.0",
                interpretation="L",
                result_date="2025-01-15",
            ),
        ],
    )
    tmp_db.load_source(records)
    return tmp_db


@pytest.fixture
def db_with_family_history(tmp_db):
    """DB with family history entries (no timestamp field)."""
    records = UnifiedRecords(
        source="test_source",
        family_history=[
            FamilyHistoryRecord(
                source="test_source",
                relation="Father",
                condition="Colon cancer",
            ),
            FamilyHistoryRecord(
                source="test_source",
                relation="Mother",
                condition="Hypertension",
            ),
        ],
    )
    tmp_db.load_source(records)
    return tmp_db


@pytest.fixture
def db_with_notes(tmp_db):
    """DB with notes that have tags."""
    tmp_db.save_note(
        title="CEA Trend Analysis",
        content="CEA trending up since 2024",
        tags=["oncology", "cea"],
    )
    tmp_db.save_note(
        title="Visit Prep 2025-02",
        content="Prepare for February visit",
        tags=["visit-prep"],
    )
    return tmp_db


@pytest.fixture
def db_with_analyses(tmp_db):
    """DB with analyses that have tags."""
    tmp_db.save_analysis(
        slug="cancer-timeline",
        title="Cancer Timeline",
        content="# Cancer Timeline\n\nDetailed analysis...",
        tags=["oncology", "timeline"],
        category="oncology",
    )
    tmp_db.save_analysis(
        slug="medication-review",
        title="Medication Review",
        content="# Medication Review\n\nAll active meds...",
        tags=["medications"],
        category="pharmacy",
    )
    return tmp_db


@pytest.fixture
def db_with_pathology_and_procedures(tmp_db):
    """DB with procedures and pathology reports linked by FK."""
    records = UnifiedRecords(
        source="test_surgical",
        procedures=[
            ProcedureRecord(
                source="test_surgical",
                name="Right hemicolectomy",
                procedure_date="2024-07-01",
                provider="Dr. Surgeon",
            ),
        ],
        pathology_reports=[
            PathologyReport(
                source="test_surgical",
                report_date="2024-07-03",
                specimen="Right colon",
                diagnosis="Adenocarcinoma",
            ),
        ],
    )
    tmp_db.load_source(records)
    return tmp_db


# ---------------------------------------------------------------------------
# Tests: _row_to_record
# ---------------------------------------------------------------------------


class TestRowToRecord:
    def test_row_to_record_lab_result(self, lab_row):
        """Basic conversion with all fields present."""
        record = _row_to_record(lab_row, "lab_results", "result_date")

        assert record["mimetype"] == "application/json"
        assert record["uri"] == "chartfold:lab_results/42"
        assert record["timestamp"] == "2025-01-15"
        assert record["metadata"]["table"] == "lab_results"
        assert record["metadata"]["source"] == "epic_anderson"
        assert record["metadata"]["test_name"] == "CEA"
        assert record["metadata"]["value_numeric"] == 5.8
        assert "id" not in record["metadata"]
        assert "content" not in record

    def test_row_to_record_null_fields_skipped(self):
        """None and empty-string fields should be omitted from metadata."""
        row = {
            "id": 1,
            "source": "test",
            "source_doc_id": None,
            "test_name": "WBC",
            "test_loinc": "",
            "panel_name": None,
            "value": "6.2",
            "value_numeric": 6.2,
            "unit": "K/mm3",
            "ref_range": "4.5-11.0",
            "interpretation": "",
            "result_date": "2025-01-15",
            "status": None,
        }
        record = _row_to_record(row, "lab_results", "result_date")

        assert "source_doc_id" not in record["metadata"]
        assert "test_loinc" not in record["metadata"]
        assert "panel_name" not in record["metadata"]
        assert "interpretation" not in record["metadata"]
        assert "status" not in record["metadata"]
        # Present fields should be there
        assert record["metadata"]["test_name"] == "WBC"
        assert record["metadata"]["value"] == "6.2"
        assert record["metadata"]["unit"] == "K/mm3"

    def test_row_to_record_no_timestamp_field(self, family_history_row):
        """family_history has timestamp_field=None, so no timestamp key."""
        record = _row_to_record(family_history_row, "family_history", None)

        assert record["uri"] == "chartfold:family_history/7"
        assert "timestamp" not in record
        assert record["metadata"]["relation"] == "Father"
        assert record["metadata"]["condition"] == "Colon cancer"
        # age_at_onset is None, should be skipped
        assert "age_at_onset" not in record["metadata"]

    def test_row_to_record_fk_converted_to_uri(self, pathology_row):
        """procedure_id FK should become procedure_uri with chartfold: URI."""
        record = _row_to_record(pathology_row, "pathology_reports", "report_date")

        assert "procedure_id" not in record["metadata"]
        assert record["metadata"]["procedure_uri"] == "chartfold:procedures/10"
        assert record["metadata"]["specimen"] == "Right colon"

    def test_row_to_record_fk_null_not_included(self):
        """If procedure_id is None, no procedure_uri should be in metadata."""
        row = {
            "id": 5,
            "source": "test",
            "source_doc_id": None,
            "procedure_id": None,
            "report_date": "2025-01-01",
            "specimen": "Tissue",
            "diagnosis": "Benign",
            "gross_description": None,
            "microscopic_description": None,
            "staging": None,
            "margins": None,
            "lymph_nodes": None,
            "full_text": None,
        }
        record = _row_to_record(row, "pathology_reports", "report_date")
        assert "procedure_id" not in record["metadata"]
        assert "procedure_uri" not in record["metadata"]

    def test_row_to_record_timestamp_field_value_none(self):
        """If the timestamp field exists but its value is None, omit timestamp."""
        row = {
            "id": 1,
            "source": "test",
            "name": "Unknown med",
            "start_date": None,
        }
        record = _row_to_record(row, "medications", "start_date")
        assert "timestamp" not in record

    def test_row_to_record_zero_value_included(self):
        """Numeric zero should be included (not treated as falsy)."""
        row = {
            "id": 1,
            "source": "test",
            "score": 0,
            "total_score": 0,
            "instrument": "PHQ-9",
            "recorded_date": "2025-01-15",
        }
        record = _row_to_record(row, "mental_status", "recorded_date")
        assert record["metadata"]["score"] == 0
        assert record["metadata"]["total_score"] == 0


# ---------------------------------------------------------------------------
# Tests: _export_table
# ---------------------------------------------------------------------------


class TestExportTable:
    def test_export_table_writes_jsonl(self, db_with_labs, tmp_path):
        """Should write correct JSONL file with one record per line."""
        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)

        records = _export_table(
            db_with_labs, "lab_results", "result_date", output_dir
        )

        assert records is not None
        assert len(records) == 2

        # Verify file was written
        jsonl_path = os.path.join(output_dir, "lab_results.jsonl")
        assert os.path.exists(jsonl_path)

        # Verify JSONL content
        with open(jsonl_path) as f:
            lines = f.readlines()
        assert len(lines) == 2

        first = json.loads(lines[0])
        assert first["mimetype"] == "application/json"
        assert first["uri"].startswith("chartfold:lab_results/")
        assert first["metadata"]["table"] == "lab_results"

    def test_export_table_empty_returns_none(self, tmp_db, tmp_path):
        """Empty table should return None and write no file."""
        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)

        result = _export_table(
            tmp_db, "lab_results", "result_date", output_dir
        )

        assert result is None
        jsonl_path = os.path.join(output_dir, "lab_results.jsonl")
        assert not os.path.exists(jsonl_path)

    def test_export_table_no_timestamp(self, db_with_family_history, tmp_path):
        """Tables with timestamp_field=None should still export correctly."""
        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)

        records = _export_table(
            db_with_family_history, "family_history", None, output_dir
        )

        assert records is not None
        assert len(records) == 2

        # Verify no timestamp field on records
        for rec in records:
            assert "timestamp" not in rec

        # Verify file
        jsonl_path = os.path.join(output_dir, "family_history.jsonl")
        assert os.path.exists(jsonl_path)


# ---------------------------------------------------------------------------
# Tests: _export_table_with_tags
# ---------------------------------------------------------------------------


class TestExportTableWithTags:
    def test_notes_include_folded_tags(self, db_with_notes, tmp_path):
        """Notes export should include tags from note_tags table."""
        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)

        records = _export_table_with_tags(
            db_with_notes,
            "notes",
            "note_tags",
            "note_id",
            "created_at",
            output_dir,
        )

        assert records is not None
        assert len(records) == 2

        # Find the CEA note
        cea_records = [
            r for r in records if "CEA" in r["metadata"].get("title", "")
        ]
        assert len(cea_records) == 1
        cea_rec = cea_records[0]
        assert "tags" in cea_rec["metadata"]
        assert cea_rec["metadata"]["tags"] == ["cea", "oncology"]  # sorted

        # Find the visit prep note
        visit_records = [
            r for r in records if "Visit" in r["metadata"].get("title", "")
        ]
        assert len(visit_records) == 1
        visit_rec = visit_records[0]
        assert visit_rec["metadata"]["tags"] == ["visit-prep"]

        # Verify JSONL file
        jsonl_path = os.path.join(output_dir, "notes.jsonl")
        assert os.path.exists(jsonl_path)

    def test_analyses_include_folded_tags(self, db_with_analyses, tmp_path):
        """Analyses export should include tags from analysis_tags table."""
        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)

        records = _export_table_with_tags(
            db_with_analyses,
            "analyses",
            "analysis_tags",
            "analysis_id",
            "created_at",
            output_dir,
        )

        assert records is not None
        assert len(records) == 2

        # Find the cancer timeline analysis
        cancer_records = [
            r for r in records if "Cancer" in r["metadata"].get("title", "")
        ]
        assert len(cancer_records) == 1
        cancer_rec = cancer_records[0]
        assert cancer_rec["metadata"]["tags"] == ["oncology", "timeline"]  # sorted

        # Verify JSONL file
        jsonl_path = os.path.join(output_dir, "analyses.jsonl")
        assert os.path.exists(jsonl_path)


# ---------------------------------------------------------------------------
# Tests: _build_schema
# ---------------------------------------------------------------------------


class TestBuildSchema:
    def test_build_schema_types_and_counts(self):
        """Should detect types and counts; low cardinality gets values list."""
        records = [
            {
                "mimetype": "application/json",
                "uri": "chartfold:lab_results/1",
                "timestamp": "2025-01-15",
                "metadata": {
                    "table": "lab_results",
                    "source": "epic",
                    "test_name": "CEA",
                    "value_numeric": 5.8,
                },
            },
            {
                "mimetype": "application/json",
                "uri": "chartfold:lab_results/2",
                "timestamp": "2025-01-15",
                "metadata": {
                    "table": "lab_results",
                    "source": "epic",
                    "test_name": "Hemoglobin",
                    "value_numeric": 12.5,
                    "interpretation": "L",
                },
            },
        ]

        schema = _build_schema(records)

        assert "metadata_keys" in schema
        keys = schema["metadata_keys"]

        # 'table' key
        assert keys["table"]["type"] == "string"
        assert keys["table"]["count"] == 2
        assert "values" in keys["table"]
        assert "lab_results" in keys["table"]["values"]

        # 'source' key
        assert keys["source"]["type"] == "string"
        assert keys["source"]["count"] == 2

        # 'value_numeric' should be number
        assert keys["value_numeric"]["type"] == "number"
        assert keys["value_numeric"]["count"] == 2

        # 'interpretation' only on one record
        assert keys["interpretation"]["count"] == 1

    def test_build_schema_high_cardinality_uses_example(self):
        """When >= 20 unique values, should use 'example' instead of 'values'."""
        records = [
            {
                "mimetype": "application/json",
                "uri": f"chartfold:lab_results/{i}",
                "metadata": {
                    "table": "lab_results",
                    "test_name": f"Test_{i}",
                    "value_numeric": float(i),
                },
            }
            for i in range(25)
        ]

        schema = _build_schema(records)
        keys = schema["metadata_keys"]

        # test_name has 25 unique values (>= 20)
        assert "example" in keys["test_name"]
        assert "values" not in keys["test_name"]

        # value_numeric has 25 unique values
        assert "example" in keys["value_numeric"]
        assert "values" not in keys["value_numeric"]

        # table has 1 unique value (< 20)
        assert "values" in keys["table"]
        assert "example" not in keys["table"]

    def test_build_schema_mixed_types(self):
        """Should detect arrays and booleans."""
        records = [
            {
                "mimetype": "application/json",
                "uri": "chartfold:notes/1",
                "metadata": {
                    "table": "notes",
                    "tags": ["oncology", "cea"],
                    "active": True,
                },
            },
            {
                "mimetype": "application/json",
                "uri": "chartfold:notes/2",
                "metadata": {
                    "table": "notes",
                    "tags": ["visit-prep"],
                    "active": False,
                },
            },
        ]

        schema = _build_schema(records)
        keys = schema["metadata_keys"]

        assert keys["tags"]["type"] == "array"
        assert keys["tags"]["count"] == 2

        assert keys["active"]["type"] == "boolean"
        assert keys["active"]["count"] == 2
        # Booleans have low cardinality, should have values
        assert "values" in keys["active"]
        assert set(keys["active"]["values"]) == {True, False}

    def test_build_schema_empty_records(self):
        """Empty records list should return empty metadata_keys."""
        schema = _build_schema([])
        assert schema == {"metadata_keys": {}}


# ---------------------------------------------------------------------------
# Tests: Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_timestamp_fields_covers_all_tables(self):
        """Every clinical table should have an entry in _TIMESTAMP_FIELDS."""
        expected_tables = {
            "patients",
            "encounters",
            "lab_results",
            "vitals",
            "medications",
            "conditions",
            "procedures",
            "pathology_reports",
            "imaging_reports",
            "clinical_notes",
            "immunizations",
            "allergies",
            "social_history",
            "family_history",
            "mental_status",
            "notes",
            "analyses",
        }
        assert set(_TIMESTAMP_FIELDS.keys()) == expected_tables

    def test_collection_descriptions_covers_all_tables(self):
        """Every table in _TIMESTAMP_FIELDS should have a description."""
        assert set(_COLLECTION_DESCRIPTIONS.keys()) == set(
            _TIMESTAMP_FIELDS.keys()
        )

    def test_fk_fields_procedure_id(self):
        """procedure_id FK should map to procedures table."""
        assert "procedure_id" in _FK_FIELDS
        table, uri_key = _FK_FIELDS["procedure_id"]
        assert table == "procedures"
        assert uri_key == "procedure_uri"

    def test_strip_cols_includes_id(self):
        """id should always be stripped from metadata."""
        assert "id" in _STRIP_COLS

    def test_max_enum_values(self):
        """Max enum values threshold should be 20."""
        assert _MAX_ENUM_VALUES == 20


# ---------------------------------------------------------------------------
# Additional coverage tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_export_table_with_tags_empty_returns_none(self, tmp_db, tmp_path):
        """Empty tag-bearing table returns None and writes no file."""
        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)

        result = _export_table_with_tags(
            tmp_db, "notes", "note_tags", "note_id", "created_at", output_dir
        )
        assert result is None
        assert not os.path.exists(os.path.join(output_dir, "notes.jsonl"))

    def test_build_schema_object_type(self):
        """Dict values should be detected as 'object' type."""
        records = [
            {
                "mimetype": "application/json",
                "uri": "chartfold:analyses/1",
                "metadata": {
                    "table": "analyses",
                    "frontmatter": {"key": "value"},
                },
            },
        ]
        schema = _build_schema(records)
        assert schema["metadata_keys"]["frontmatter"]["type"] == "object"

    def test_build_schema_mixed_sort_fallback(self):
        """When values contain incomparable types, fall back to str-based sort."""
        records = [
            {
                "mimetype": "application/json",
                "uri": "chartfold:test/1",
                "metadata": {"mixed": 42},
            },
            {
                "mimetype": "application/json",
                "uri": "chartfold:test/2",
                "metadata": {"mixed": "hello"},
            },
        ]
        schema = _build_schema(records)
        # Should not raise; values should be present (only 2 unique < 20)
        assert "values" in schema["metadata_keys"]["mixed"]
        assert len(schema["metadata_keys"]["mixed"]["values"]) == 2

    def test_export_table_with_tags_no_tags(self, tmp_db, tmp_path):
        """Records with no tags should not have 'tags' in metadata."""
        # Create a note without tags
        tmp_db.save_note(title="No Tags", content="Content without tags")

        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)

        records = _export_table_with_tags(
            tmp_db, "notes", "note_tags", "note_id", "created_at", output_dir
        )

        assert records is not None
        assert len(records) == 1
        assert "tags" not in records[0]["metadata"]

    def test_export_table_jsonl_roundtrip(self, db_with_labs, tmp_path):
        """Each JSONL line should be valid JSON that round-trips correctly."""
        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)

        records = _export_table(
            db_with_labs, "lab_results", "result_date", output_dir
        )

        jsonl_path = os.path.join(output_dir, "lab_results.jsonl")
        with open(jsonl_path) as f:
            for i, line in enumerate(f):
                parsed = json.loads(line)
                assert parsed == records[i]

    def test_row_to_record_deceased_false_included(self):
        """Boolean false (0 in SQLite) should be included in metadata."""
        row = {
            "id": 1,
            "source": "test",
            "relation": "Father",
            "condition": "Cancer",
            "deceased": 0,
        }
        record = _row_to_record(row, "family_history", None)
        assert record["metadata"]["deceased"] == 0
