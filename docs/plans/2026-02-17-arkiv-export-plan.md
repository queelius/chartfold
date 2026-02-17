# arkiv Export Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Export chartfold clinical data as arkiv JSONL + manifest for personal data archival and interchange.

**Architecture:** New module `src/chartfold/export_arkiv.py` converts each DB table row to an arkiv record (JSONL), generates schema discovery metadata, and writes a manifest. Wired into CLI as `chartfold export arkiv`. Design doc: `docs/plans/2026-02-17-arkiv-export-design.md`.

**Tech Stack:** Python stdlib only (`json`, `os`, `pathlib`). No new dependencies.

---

### Task 1: Core record conversion — `_row_to_record()`

**Files:**
- Create: `src/chartfold/export_arkiv.py`
- Create: `tests/test_export_arkiv.py`

**Step 1: Write the failing test**

```python
"""Tests for arkiv export functionality."""

import json
import os

import pytest

from chartfold.db import ChartfoldDB
from chartfold.models import (
    LabResult,
    FamilyHistoryRecord,
    UnifiedRecords,
)


def test_row_to_record_lab_result():
    """A lab result row becomes an arkiv record with correct uri, timestamp, metadata."""
    from chartfold.export_arkiv import _row_to_record

    row = {
        "id": 42,
        "source": "epic_anderson",
        "source_doc_id": "DOC0001",
        "test_name": "CEA",
        "test_loinc": "2039-6",
        "panel_name": "Tumor Markers",
        "value": "2.3",
        "value_numeric": 2.3,
        "unit": "ng/mL",
        "ref_range": "0.0-3.0",
        "interpretation": "N",
        "result_date": "2025-01-15",
        "status": "final",
    }
    record = _row_to_record(row, table="lab_results", timestamp_field="result_date")

    assert record["mimetype"] == "application/json"
    assert record["uri"] == "chartfold:lab_results/42"
    assert record["timestamp"] == "2025-01-15"
    assert record["metadata"]["table"] == "lab_results"
    assert record["metadata"]["test_name"] == "CEA"
    assert record["metadata"]["value_numeric"] == 2.3
    # id should NOT appear in metadata (it's in the uri)
    assert "id" not in record["metadata"]
    # content should not be present
    assert "content" not in record


def test_row_to_record_null_fields_skipped():
    """Null/empty fields are omitted from metadata."""
    from chartfold.export_arkiv import _row_to_record

    row = {
        "id": 1,
        "source": "test",
        "source_doc_id": None,
        "allergen": "Penicillin",
        "reaction": None,
        "severity": "",
        "status": "active",
        "onset_date": "2020-01-01",
    }
    record = _row_to_record(row, table="allergies", timestamp_field="onset_date")

    assert "source_doc_id" not in record["metadata"]
    assert "reaction" not in record["metadata"]
    assert "severity" not in record["metadata"]
    assert record["metadata"]["allergen"] == "Penicillin"


def test_row_to_record_no_timestamp_field():
    """Tables with no date field (family_history) get no timestamp."""
    from chartfold.export_arkiv import _row_to_record

    row = {
        "id": 7,
        "source": "test",
        "source_doc_id": None,
        "relation": "Father",
        "condition": "Heart Disease",
        "age_at_onset": None,
        "deceased": 0,
    }
    record = _row_to_record(row, table="family_history", timestamp_field=None)

    assert "timestamp" not in record
    assert record["uri"] == "chartfold:family_history/7"
    assert record["metadata"]["relation"] == "Father"


def test_row_to_record_fk_converted_to_uri():
    """pathology_reports.procedure_id becomes procedure_uri."""
    from chartfold.export_arkiv import _row_to_record

    row = {
        "id": 3,
        "source": "test",
        "source_doc_id": None,
        "procedure_id": 5,
        "report_date": "2024-07-15",
        "specimen": "Colon",
        "diagnosis": "Adenocarcinoma",
        "gross_description": None,
        "microscopic_description": None,
        "staging": "pT3N1",
        "margins": "negative",
        "lymph_nodes": "1/12 positive",
        "full_text": None,
    }
    record = _row_to_record(row, table="pathology_reports", timestamp_field="report_date")

    assert "procedure_id" not in record["metadata"]
    assert record["metadata"]["procedure_uri"] == "chartfold:procedures/5"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_export_arkiv.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chartfold.export_arkiv'`

**Step 3: Write minimal implementation**

```python
"""Export chartfold data to arkiv universal record format (JSONL + manifest)."""

from __future__ import annotations

# Table name -> column that becomes the arkiv timestamp
_TIMESTAMP_FIELDS: dict[str, str | None] = {
    "lab_results": "result_date",
    "encounters": "encounter_date",
    "medications": "start_date",
    "procedures": "procedure_date",
    "imaging_reports": "study_date",
    "pathology_reports": "report_date",
    "clinical_notes": "note_date",
    "vitals": "recorded_date",
    "immunizations": "admin_date",
    "allergies": "onset_date",
    "conditions": "onset_date",
    "social_history": "recorded_date",
    "family_history": None,
    "mental_status": "recorded_date",
    "patients": "date_of_birth",
    "notes": "created_at",
    "analyses": "created_at",
}

# FK columns -> (target_table, metadata_key_name)
_FK_FIELDS: dict[str, tuple[str, str]] = {
    "procedure_id": ("procedures", "procedure_uri"),
}

# Columns to strip from metadata (they go elsewhere in the arkiv record)
_STRIP_COLS = {"id"}


def _row_to_record(
    row: dict,
    table: str,
    timestamp_field: str | None,
) -> dict:
    """Convert a single DB row to an arkiv record."""
    record: dict = {
        "mimetype": "application/json",
        "uri": f"chartfold:{table}/{row['id']}",
    }

    # Timestamp
    if timestamp_field and row.get(timestamp_field):
        record["timestamp"] = row[timestamp_field]

    # Metadata: all non-null, non-empty fields, minus id
    metadata: dict = {"table": table}
    for key, value in row.items():
        if key in _STRIP_COLS:
            continue
        if value is None or value == "":
            continue
        # FK -> URI conversion
        if key in _FK_FIELDS:
            target_table, uri_key = _FK_FIELDS[key]
            metadata[uri_key] = f"chartfold:{target_table}/{value}"
            continue
        metadata[key] = value

    record["metadata"] = metadata
    return record
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_export_arkiv.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add src/chartfold/export_arkiv.py tests/test_export_arkiv.py
git commit -m "feat(arkiv): add _row_to_record for converting DB rows to arkiv records"
```

---

### Task 2: Table export — `_export_table()`

Writes all rows from one table to a JSONL file. Returns the list of records (for schema discovery later).

**Files:**
- Modify: `src/chartfold/export_arkiv.py`
- Modify: `tests/test_export_arkiv.py`

**Step 1: Write the failing test**

```python
@pytest.fixture
def populated_db(tmp_path):
    """DB with a few records across tables."""
    db_path = str(tmp_path / "test.db")
    db = ChartfoldDB(db_path)
    db.init_schema()
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
        family_history=[
            FamilyHistoryRecord(
                source="test_source",
                relation="Father",
                condition="Heart Disease",
            ),
        ],
    )
    db.load_source(records)
    yield db
    db.close()


def test_export_table_writes_jsonl(populated_db, tmp_path):
    """_export_table writes one JSONL line per row and returns records."""
    from chartfold.export_arkiv import _export_table

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    records = _export_table(populated_db, "lab_results", "result_date", str(output_dir))

    assert len(records) == 2
    jsonl_path = output_dir / "lab_results.jsonl"
    assert jsonl_path.exists()

    lines = jsonl_path.read_text().strip().split("\n")
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["mimetype"] == "application/json"
    assert first["uri"].startswith("chartfold:lab_results/")
    assert first["metadata"]["table"] == "lab_results"


def test_export_table_empty_returns_none(populated_db, tmp_path):
    """_export_table returns None for empty tables, writes no file."""
    from chartfold.export_arkiv import _export_table

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = _export_table(populated_db, "immunizations", "admin_date", str(output_dir))

    assert result is None
    assert not (output_dir / "immunizations.jsonl").exists()


def test_export_table_no_timestamp(populated_db, tmp_path):
    """Tables with no timestamp field still export correctly."""
    from chartfold.export_arkiv import _export_table

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    records = _export_table(populated_db, "family_history", None, str(output_dir))

    assert len(records) == 1
    line = json.loads((output_dir / "family_history.jsonl").read_text().strip())
    assert "timestamp" not in line
    assert line["metadata"]["relation"] == "Father"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_export_arkiv.py::test_export_table_writes_jsonl -v`
Expected: FAIL — `ImportError: cannot import name '_export_table'`

**Step 3: Write minimal implementation**

Add to `src/chartfold/export_arkiv.py`:

```python
import json
import os
from chartfold.db import ChartfoldDB


def _export_table(
    db: ChartfoldDB,
    table: str,
    timestamp_field: str | None,
    output_dir: str,
) -> list[dict] | None:
    """Export all rows from one table to a JSONL file.

    Returns the list of arkiv records, or None if the table is empty.
    """
    rows = db.query(f"SELECT * FROM {table}")
    if not rows:
        return None

    records = [_row_to_record(row, table, timestamp_field) for row in rows]

    jsonl_path = os.path.join(output_dir, f"{table}.jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return records
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_export_arkiv.py -v`
Expected: PASS (7 tests)

**Step 5: Commit**

```bash
git add src/chartfold/export_arkiv.py tests/test_export_arkiv.py
git commit -m "feat(arkiv): add _export_table to write JSONL per table"
```

---

### Task 3: Tag folding for notes and analyses

Notes and analyses have separate tag tables. These need to be folded in.

**Files:**
- Modify: `src/chartfold/export_arkiv.py`
- Modify: `tests/test_export_arkiv.py`

**Step 1: Write the failing test**

```python
def test_notes_include_folded_tags(tmp_path):
    """Notes export includes tags folded from note_tags table."""
    from chartfold.export_arkiv import _export_table_with_tags

    db_path = str(tmp_path / "test.db")
    db = ChartfoldDB(db_path)
    db.init_schema()
    db.save_note(
        title="CEA Trend",
        content="CEA rising since surgery.",
        tags=["oncology", "cea"],
    )
    db.save_note(
        title="Visit Prep",
        content="Questions for Dr. Smith.",
        tags=["visit-prep"],
    )

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    records = _export_table_with_tags(
        db, "notes", "note_tags", "note_id", "created_at", str(output_dir)
    )

    assert len(records) == 2
    # First note should have tags
    cea_note = [r for r in records if r["metadata"]["title"] == "CEA Trend"][0]
    assert set(cea_note["metadata"]["tags"]) == {"oncology", "cea"}

    db.close()


def test_analyses_include_folded_tags(tmp_path):
    """Analyses export includes tags folded from analysis_tags table."""
    from chartfold.export_arkiv import _export_table_with_tags

    db_path = str(tmp_path / "test.db")
    db = ChartfoldDB(db_path)
    db.init_schema()
    db.save_analysis(
        slug="cancer-timeline",
        title="Cancer Timeline",
        content="# Timeline\n\nDiagnosed 2021...",
        tags=["cancer", "timeline"],
        category="oncology",
    )

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    records = _export_table_with_tags(
        db, "analyses", "analysis_tags", "analysis_id", "created_at", str(output_dir)
    )

    assert len(records) == 1
    assert set(records[0]["metadata"]["tags"]) == {"cancer", "timeline"}
    assert records[0]["metadata"]["category"] == "oncology"

    db.close()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_export_arkiv.py::test_notes_include_folded_tags -v`
Expected: FAIL — `ImportError: cannot import name '_export_table_with_tags'`

**Step 3: Write minimal implementation**

Add to `src/chartfold/export_arkiv.py`:

```python
def _export_table_with_tags(
    db: ChartfoldDB,
    table: str,
    tag_table: str,
    tag_fk_col: str,
    timestamp_field: str | None,
    output_dir: str,
) -> list[dict] | None:
    """Export a table with tags folded in from a separate tag table."""
    rows = db.query(f"SELECT * FROM {table}")
    if not rows:
        return None

    # Build tag lookup: parent_id -> [tag1, tag2, ...]
    tag_rows = db.query(f"SELECT {tag_fk_col}, tag FROM {tag_table}")
    tags_by_id: dict[int, list[str]] = {}
    for tr in tag_rows:
        tags_by_id.setdefault(tr[tag_fk_col], []).append(tr["tag"])

    records = []
    for row in rows:
        record = _row_to_record(row, table, timestamp_field)
        tags = tags_by_id.get(row["id"], [])
        if tags:
            record["metadata"]["tags"] = sorted(tags)
        records.append(record)

    jsonl_path = os.path.join(output_dir, f"{table}.jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return records
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_export_arkiv.py -v`
Expected: PASS (9 tests)

**Step 5: Commit**

```bash
git add src/chartfold/export_arkiv.py tests/test_export_arkiv.py
git commit -m "feat(arkiv): fold tags into notes/analyses records"
```

---

### Task 4: Schema discovery — `_build_schema()`

Scans a list of records and produces metadata key stats per the arkiv spec.

**Files:**
- Modify: `src/chartfold/export_arkiv.py`
- Modify: `tests/test_export_arkiv.py`

**Step 1: Write the failing test**

```python
def test_build_schema_types_and_counts():
    """Schema discovery detects types, counts, and low/high cardinality."""
    from chartfold.export_arkiv import _build_schema

    records = [
        {"metadata": {"table": "lab_results", "source": "epic", "test_name": "CEA", "value_numeric": 2.3, "interpretation": "H"}},
        {"metadata": {"table": "lab_results", "source": "epic", "test_name": "Hemoglobin", "value_numeric": 12.5, "interpretation": "L"}},
        {"metadata": {"table": "lab_results", "source": "meditech", "test_name": "WBC", "value_numeric": 6.2}},
    ]

    schema = _build_schema(records)
    keys = schema["metadata_keys"]

    # "table" is always "lab_results" -> low cardinality, values listed
    assert keys["table"]["type"] == "string"
    assert keys["table"]["count"] == 3
    assert keys["table"]["values"] == ["lab_results"]

    # "source" has 2 unique values -> low cardinality
    assert set(keys["source"]["values"]) == {"epic", "meditech"}

    # "test_name" has 3 unique values -> still low cardinality (< 20)
    assert len(keys["test_name"]["values"]) == 3

    # "value_numeric" is a number
    assert keys["value_numeric"]["type"] == "number"
    assert keys["value_numeric"]["count"] == 3

    # "interpretation" present in only 2 of 3
    assert keys["interpretation"]["count"] == 2


def test_build_schema_high_cardinality_uses_example():
    """When unique values >= 20, schema uses example instead of values."""
    from chartfold.export_arkiv import _build_schema

    records = [
        {"metadata": {"name": f"item_{i}"}} for i in range(25)
    ]

    schema = _build_schema(records)
    keys = schema["metadata_keys"]

    assert "values" not in keys["name"]
    assert "example" in keys["name"]
    assert keys["name"]["count"] == 25


def test_build_schema_mixed_types():
    """Arrays and booleans are detected correctly."""
    from chartfold.export_arkiv import _build_schema

    records = [
        {"metadata": {"tags": ["a", "b"], "active": True}},
        {"metadata": {"tags": ["c"], "active": False}},
    ]

    schema = _build_schema(records)
    assert schema["metadata_keys"]["tags"]["type"] == "array"
    assert schema["metadata_keys"]["active"]["type"] == "boolean"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_export_arkiv.py::test_build_schema_types_and_counts -v`
Expected: FAIL — `ImportError: cannot import name '_build_schema'`

**Step 3: Write minimal implementation**

Add to `src/chartfold/export_arkiv.py`:

```python
_MAX_ENUM_VALUES = 20


def _json_type(value) -> str:
    """Return the arkiv/JSON type name for a Python value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _build_schema(records: list[dict]) -> dict:
    """Build arkiv schema discovery metadata from a list of records."""
    key_stats: dict[str, dict] = {}  # key -> {type, count, unique_values}

    for record in records:
        for key, value in record.get("metadata", {}).items():
            if key not in key_stats:
                key_stats[key] = {
                    "type": _json_type(value),
                    "count": 0,
                    "unique_values": set(),
                }
            stats = key_stats[key]
            stats["count"] += 1
            # Track unique values for cardinality check (skip non-hashable)
            try:
                stats["unique_values"].add(value)
            except TypeError:
                # lists, dicts are unhashable — use str repr
                stats["unique_values"].add(str(value))

    metadata_keys = {}
    for key, stats in key_stats.items():
        entry: dict = {"type": stats["type"], "count": stats["count"]}
        unique = stats["unique_values"]
        if len(unique) < _MAX_ENUM_VALUES:
            entry["values"] = sorted(str(v) for v in unique)
        else:
            entry["example"] = next(iter(unique))
        metadata_keys[key] = entry

    return {"metadata_keys": metadata_keys}
```

Note: `values` in the schema are sorted strings for consistency. The `example` is an arbitrary sample.

**Step 4: Run tests**

Run: `python -m pytest tests/test_export_arkiv.py -v`
Expected: PASS (12 tests)

**Step 5: Commit**

```bash
git add src/chartfold/export_arkiv.py tests/test_export_arkiv.py
git commit -m "feat(arkiv): add _build_schema for metadata key discovery"
```

---

### Task 5: Collection descriptions

Each manifest collection entry has a human-readable description. We need a mapping.

**Files:**
- Modify: `src/chartfold/export_arkiv.py`

**Step 1: Add the constant**

```python
_COLLECTION_DESCRIPTIONS: dict[str, str] = {
    "patients": "Patient demographics",
    "encounters": "Clinical encounters and visits",
    "lab_results": "Laboratory test results with values, reference ranges, and interpretations",
    "vitals": "Vital sign measurements",
    "medications": "Medication orders and prescriptions",
    "conditions": "Diagnosed conditions and problems",
    "procedures": "Surgical and clinical procedures",
    "pathology_reports": "Pathology and histology reports linked to procedures",
    "imaging_reports": "Radiology and imaging study reports",
    "clinical_notes": "Progress notes, H&P, and other clinical documentation",
    "immunizations": "Vaccination records",
    "allergies": "Allergy and adverse reaction records",
    "social_history": "Social history (smoking, alcohol, etc.)",
    "family_history": "Family medical history",
    "mental_status": "Mental health screening instruments (PHQ-9, GAD-7, etc.)",
    "notes": "Personal notes and annotations",
    "analyses": "Structured analysis documents",
}
```

No test needed — it's a data constant. Will be tested through the integration test in Task 6.

**Step 2: Commit**

```bash
git add src/chartfold/export_arkiv.py
git commit -m "feat(arkiv): add collection description mapping"
```

---

### Task 6: Main export function — `export_arkiv()`

Ties everything together: iterates tables, writes JSONL files, builds manifest.

**Files:**
- Modify: `src/chartfold/export_arkiv.py`
- Modify: `tests/test_export_arkiv.py`

**Step 1: Write the failing test**

```python
def test_export_arkiv_full(tmp_path):
    """Full integration: export creates JSONL files + manifest."""
    from chartfold.export_arkiv import export_arkiv

    db_path = str(tmp_path / "test.db")
    db = ChartfoldDB(db_path)
    db.init_schema()
    records = UnifiedRecords(
        source="test_source",
        lab_results=[
            LabResult(
                source="test_source",
                test_name="CEA",
                value="5.8",
                value_numeric=5.8,
                unit="ng/mL",
                result_date="2025-01-15",
            ),
        ],
        family_history=[
            FamilyHistoryRecord(
                source="test_source",
                relation="Father",
                condition="Heart Disease",
            ),
        ],
    )
    db.load_source(records)
    db.save_note(title="My Note", content="Some content", tags=["test"])

    output_dir = str(tmp_path / "arkiv-out")
    export_arkiv(db, output_dir)
    db.close()

    # Check directory created
    assert os.path.isdir(output_dir)

    # Check JSONL files exist for non-empty tables
    assert os.path.exists(os.path.join(output_dir, "lab_results.jsonl"))
    assert os.path.exists(os.path.join(output_dir, "family_history.jsonl"))
    assert os.path.exists(os.path.join(output_dir, "notes.jsonl"))

    # Check empty tables are skipped
    assert not os.path.exists(os.path.join(output_dir, "medications.jsonl"))
    assert not os.path.exists(os.path.join(output_dir, "immunizations.jsonl"))

    # Check manifest
    with open(os.path.join(output_dir, "manifest.json")) as f:
        manifest = json.load(f)
    assert "collections" in manifest
    assert manifest["description"] == "Chartfold clinical data export"
    assert manifest["metadata"]["source_tool"] == "chartfold"

    collection_files = {c["file"] for c in manifest["collections"]}
    assert "lab_results.jsonl" in collection_files
    assert "family_history.jsonl" in collection_files
    assert "notes.jsonl" in collection_files
    assert "medications.jsonl" not in collection_files

    # Check schema in manifest
    lab_collection = [c for c in manifest["collections"] if c["file"] == "lab_results.jsonl"][0]
    assert lab_collection["record_count"] == 1
    assert "metadata_keys" in lab_collection["schema"]
    assert "test_name" in lab_collection["schema"]["metadata_keys"]


def test_export_arkiv_exclude_notes(tmp_path):
    """--exclude-notes omits notes and analyses."""
    from chartfold.export_arkiv import export_arkiv

    db_path = str(tmp_path / "test.db")
    db = ChartfoldDB(db_path)
    db.init_schema()
    records = UnifiedRecords(
        source="test_source",
        lab_results=[
            LabResult(
                source="test_source",
                test_name="CEA",
                value="5.8",
                value_numeric=5.8,
                unit="ng/mL",
                result_date="2025-01-15",
            ),
        ],
    )
    db.load_source(records)
    db.save_note(title="My Note", content="Content", tags=["test"])

    output_dir = str(tmp_path / "arkiv-out")
    export_arkiv(db, output_dir, include_notes=False)
    db.close()

    assert os.path.exists(os.path.join(output_dir, "lab_results.jsonl"))
    assert not os.path.exists(os.path.join(output_dir, "notes.jsonl"))
    assert not os.path.exists(os.path.join(output_dir, "analyses.jsonl"))


def test_export_arkiv_note_tags_folded(tmp_path):
    """Notes in the export have their tags folded in."""
    from chartfold.export_arkiv import export_arkiv

    db_path = str(tmp_path / "test.db")
    db = ChartfoldDB(db_path)
    db.init_schema()
    db.save_note(title="Tagged", content="Has tags", tags=["oncology", "cea"])

    output_dir = str(tmp_path / "arkiv-out")
    export_arkiv(db, output_dir)
    db.close()

    lines = open(os.path.join(output_dir, "notes.jsonl")).read().strip().split("\n")
    record = json.loads(lines[0])
    assert set(record["metadata"]["tags"]) == {"oncology", "cea"}
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_export_arkiv.py::test_export_arkiv_full -v`
Expected: FAIL — `ImportError: cannot import name 'export_arkiv'`

**Step 3: Write minimal implementation**

Add to `src/chartfold/export_arkiv.py`:

```python
from datetime import date


_NOTE_TABLES = {"notes", "analyses"}
_TAG_TABLES = {"notes", "analyses"}

# Tables excluded from export entirely
_EXCLUDED_TABLES = {
    "load_log", "source_assets", "documents",
    "note_tags", "analysis_tags", "sqlite_sequence",
}

# Tag table config: parent_table -> (tag_table, fk_column)
_TAG_CONFIG = {
    "notes": ("note_tags", "note_id"),
    "analyses": ("analysis_tags", "analysis_id"),
}


def export_arkiv(
    db: ChartfoldDB,
    output_dir: str,
    include_notes: bool = True,
) -> str:
    """Export database to arkiv format (JSONL + manifest).

    Args:
        db: Database connection.
        output_dir: Directory to write output files.
        include_notes: Include personal notes and analyses.

    Returns the output directory path.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Determine which tables to export
    tables_to_export = [
        t for t in _TIMESTAMP_FIELDS
        if t not in _EXCLUDED_TABLES
        and (include_notes or t not in _NOTE_TABLES)
    ]

    collections = []
    for table in tables_to_export:
        ts_field = _TIMESTAMP_FIELDS[table]

        # Tables with tags use the special exporter
        if table in _TAG_CONFIG:
            tag_table, tag_fk = _TAG_CONFIG[table]
            records = _export_table_with_tags(
                db, table, tag_table, tag_fk, ts_field, output_dir
            )
        else:
            records = _export_table(db, table, ts_field, output_dir)

        if records is None:
            continue

        schema = _build_schema(records)
        collections.append({
            "file": f"{table}.jsonl",
            "description": _COLLECTION_DESCRIPTIONS.get(table, table),
            "record_count": len(records),
            "schema": schema,
        })

    # Write manifest
    manifest = {
        "description": "Chartfold clinical data export",
        "created": date.today().isoformat(),
        "metadata": {
            "source_tool": "chartfold",
        },
        "collections": collections,
    }
    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return output_dir
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_export_arkiv.py -v`
Expected: PASS (15 tests)

**Step 5: Commit**

```bash
git add src/chartfold/export_arkiv.py tests/test_export_arkiv.py
git commit -m "feat(arkiv): add export_arkiv main function with manifest generation"
```

---

### Task 7: Wire into CLI

Add `chartfold export arkiv` subcommand.

**Files:**
- Modify: `src/chartfold/cli.py:112-124` (add arkiv parser after html parser)
- Modify: `src/chartfold/cli.py:565-599` (add arkiv branch in `_handle_export`)

**Step 1: Write the failing test**

Add to `tests/test_export_arkiv.py`:

```python
import subprocess
import sys


def test_cli_export_arkiv(tmp_path):
    """CLI: chartfold export arkiv --output <dir> works end-to-end."""
    db_path = str(tmp_path / "test.db")
    db = ChartfoldDB(db_path)
    db.init_schema()
    records = UnifiedRecords(
        source="test_source",
        lab_results=[
            LabResult(
                source="test_source",
                test_name="CEA",
                value="5.8",
                value_numeric=5.8,
                unit="ng/mL",
                result_date="2025-01-15",
            ),
        ],
    )
    db.load_source(records)
    db.close()

    output_dir = str(tmp_path / "arkiv-out")
    result = subprocess.run(
        [sys.executable, "-m", "chartfold", "export", "arkiv",
         "--db", db_path, "--output", output_dir],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "Exported to" in result.stdout
    assert os.path.exists(os.path.join(output_dir, "manifest.json"))
    assert os.path.exists(os.path.join(output_dir, "lab_results.jsonl"))
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_export_arkiv.py::test_cli_export_arkiv -v`
Expected: FAIL — argparse error, "arkiv" not recognized

**Step 3: Modify CLI**

In `src/chartfold/cli.py`, after the html_parser block (~line 123), add:

```python
    # export arkiv
    arkiv_parser = export_sub.add_parser(
        "arkiv", help="Export as arkiv universal record format (JSONL + manifest)"
    )
    arkiv_parser.add_argument("--db", default=DEFAULT_DB, help=db_help)
    arkiv_parser.add_argument(
        "--output", default="chartfold_arkiv", help="Output directory path"
    )
    arkiv_parser.add_argument(
        "--exclude-notes", action="store_true", help="Exclude personal notes and analyses"
    )
```

In `_handle_export()`, update the usage message and add the arkiv branch:

```python
    if args.export_format is None:
        print("Usage: chartfold export <arkiv|html|json> [options]")
        print("\nSubcommands:")
        print("  arkiv      Export as arkiv universal record format (JSONL + manifest)")
        print("  html       Export as self-contained HTML SPA with embedded SQLite")
        print("  json       Export as JSON (full database dump)")
        print("\nRun 'chartfold export <subcommand> --help' for options.")
        sys.exit(1)
```

After the `elif args.export_format == "html":` block, add:

```python
        elif args.export_format == "arkiv":
            from chartfold.export_arkiv import export_arkiv

            path = export_arkiv(
                db,
                output_dir=args.output,
                include_notes=not args.exclude_notes,
            )
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_export_arkiv.py -v`
Expected: PASS (16 tests)

**Step 5: Commit**

```bash
git add src/chartfold/cli.py tests/test_export_arkiv.py
git commit -m "feat(arkiv): wire export arkiv into CLI"
```

---

### Task 8: Run full test suite and coverage

**Step 1: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All existing tests pass + all new arkiv tests pass.

**Step 2: Run coverage**

Run: `python -m pytest tests/ --cov=chartfold --cov-report=term-missing`
Expected: `export_arkiv.py` has high coverage. Check for any missed branches.

**Step 3: Add any missing edge-case tests if coverage reveals gaps**

Likely candidates:
- `_json_type` with `dict` input
- `_build_schema` with empty records list
- `export_arkiv` with completely empty database

**Step 4: Commit**

```bash
git add tests/test_export_arkiv.py
git commit -m "test(arkiv): add edge-case tests for full coverage"
```

---

### Task 9: Update CLAUDE.md

Add `arkiv` to the export commands section.

**Files:**
- Modify: `CLAUDE.md` — add to the CLI commands section

Add after the `export html` line:

```
python -m chartfold export arkiv --output ./arkiv/           # arkiv universal record format
python -m chartfold export arkiv --output ./arkiv/ --exclude-notes
```

**Step 1: Make the edit**

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add arkiv export to CLAUDE.md commands"
```
