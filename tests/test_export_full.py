"""Tests for full-fidelity export and import functionality."""

import json
import sqlite3

import pytest

from chartfold.db import ChartfoldDB
from chartfold.export_full import (
    CLINICAL_TABLES,
    EXPORT_VERSION,
    NOTE_TABLES,
    SCHEMA_VERSION,
    export_full_json,
    export_full_markdown,
    import_json,
    validate_json_export,
)
from chartfold.models import (
    AllergyRecord,
    ClinicalNote,
    ConditionRecord,
    DocumentRecord,
    EncounterRecord,
    FamilyHistoryRecord,
    ImagingReport,
    ImmunizationRecord,
    LabResult,
    MedicationRecord,
    MentalStatusRecord,
    PathologyReport,
    PatientRecord,
    ProcedureRecord,
    SocialHistoryRecord,
    SourceAsset,
    UnifiedRecords,
    VitalRecord,
)


@pytest.fixture
def populated_db(tmp_path):
    """Create a database with comprehensive test data."""
    db_path = str(tmp_path / "test.db")
    db = ChartfoldDB(db_path)
    db.init_schema()

    # Create comprehensive test records
    records = UnifiedRecords(
        source="test_source",
        patient=PatientRecord(
            source="test_source",
            name="John Doe",
            date_of_birth="1975-06-15",
            gender="male",
            mrn="12345",
            address="123 Main St",
            phone="555-0100",
        ),
        documents=[
            DocumentRecord(
                source="test_source",
                doc_id="DOC0001",
                doc_type="CDA",
                title="Test Document",
                encounter_date="2025-01-15",
                file_path="/path/to/doc.xml",
                file_size_kb=100,
            ),
        ],
        encounters=[
            EncounterRecord(
                source="test_source",
                source_doc_id="DOC0001",
                encounter_date="2025-01-15",
                encounter_type="office visit",
                facility="Test Hospital",
                provider="Dr. Smith",
                reason="Follow-up",
            ),
        ],
        lab_results=[
            LabResult(
                source="test_source",
                test_name="CEA",
                test_loinc="2039-6",
                panel_name="Tumor Markers",
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
        vitals=[
            VitalRecord(
                source="test_source",
                vital_type="bp_systolic",
                value=130.0,
                unit="mmHg",
                recorded_date="2025-01-15",
            ),
        ],
        medications=[
            MedicationRecord(
                source="test_source",
                name="Capecitabine 500mg",
                rxnorm_code="200328",
                status="active",
                sig="2 tablets twice daily",
                route="oral",
            ),
        ],
        conditions=[
            ConditionRecord(
                source="test_source",
                condition_name="Colon cancer",
                icd10_code="C18.9",
                snomed_code="363406005",
                clinical_status="active",
                onset_date="2021-11-22",
            ),
        ],
        procedures=[
            ProcedureRecord(
                source="test_source",
                name="Colonoscopy",
                snomed_code="73761001",
                procedure_date="2021-11-22",
                provider="Dr. GI",
                facility="Test Hospital",
            ),
        ],
        imaging_reports=[
            ImagingReport(
                source="test_source",
                study_name="CT Chest Abdomen Pelvis",
                modality="CT",
                study_date="2025-01-10",
                impression="No evidence of recurrence.",
            ),
        ],
        clinical_notes=[
            ClinicalNote(
                source="test_source",
                note_type="progress",
                author="Dr. Smith",
                note_date="2025-01-15",
                content="Patient seen for follow-up. Doing well.",
            ),
        ],
        immunizations=[
            ImmunizationRecord(
                source="test_source",
                vaccine_name="Influenza",
                cvx_code="158",
                admin_date="2024-10-15",
                status="completed",
            ),
        ],
        allergies=[
            AllergyRecord(
                source="test_source",
                allergen="Penicillin",
                reaction="Rash",
                severity="moderate",
                status="active",
            ),
        ],
        social_history=[
            SocialHistoryRecord(
                source="test_source",
                category="smoking",
                value="Never smoker",
                recorded_date="2025-01-15",
            ),
        ],
        family_history=[
            FamilyHistoryRecord(
                source="test_source",
                relation="Father",
                condition="Heart Disease",
            ),
        ],
        mental_status=[
            MentalStatusRecord(
                source="test_source",
                instrument="PHQ-9",
                question="Little interest",
                answer="Not at all",
                score=0,
                total_score=3,
                recorded_date="2025-01-15",
            ),
        ],
        source_assets=[
            SourceAsset(
                source="test_source",
                asset_type="pdf",
                file_path="/path/to/file.pdf",
                file_name="file.pdf",
                file_size_kb=500,
                title="Test PDF",
            ),
        ],
    )

    db.load_source(records)

    # Add personal notes
    note_id = db.save_note(
        title="Treatment Analysis",
        content="Analysis of current treatment regimen.",
        tags=["oncology", "treatment"],
        ref_table="conditions",
        ref_id=1,
    )

    yield db
    db.close()


@pytest.fixture
def populated_db_with_pathology(tmp_path):
    """Create a database with pathology reports linked to procedures (FK test)."""
    db_path = str(tmp_path / "test_fk.db")
    db = ChartfoldDB(db_path)
    db.init_schema()

    records = UnifiedRecords(
        source="test_source",
        procedures=[
            ProcedureRecord(
                source="test_source",
                name="Right hemicolectomy",
                procedure_date="2024-07-01",
                provider="Dr. Surgeon",
            ),
            ProcedureRecord(
                source="test_source",
                name="Liver resection",
                procedure_date="2025-05-14",
                provider="Dr. Hepato",
            ),
        ],
    )
    db.load_source(records)

    # Get procedure IDs
    procs = db.query("SELECT id, name FROM procedures ORDER BY id")
    proc_id_1 = procs[0]["id"]
    proc_id_2 = procs[1]["id"]

    # Insert pathology reports with FK references
    db.conn.execute(
        """INSERT INTO pathology_reports
           (source, procedure_id, report_date, specimen, diagnosis)
           VALUES (?, ?, ?, ?, ?)""",
        ("test_source", proc_id_1, "2024-07-03", "Right colon", "Adenocarcinoma"),
    )
    db.conn.execute(
        """INSERT INTO pathology_reports
           (source, procedure_id, report_date, specimen, diagnosis)
           VALUES (?, ?, ?, ?, ?)""",
        ("test_source", proc_id_2, "2025-05-16", "Liver segment 2", "Metastatic adenocarcinoma"),
    )
    db.conn.commit()

    yield db
    db.close()


class TestExportFullJson:
    """Tests for JSON export functionality."""

    def test_export_creates_file(self, populated_db, tmp_path):
        """Export should create a valid JSON file."""
        output_path = str(tmp_path / "export.json")
        result = export_full_json(populated_db, output_path)

        assert result == output_path
        assert (tmp_path / "export.json").exists()

        with open(output_path) as f:
            data = json.load(f)

        assert "chartfold_export" in data
        assert "tables" in data

    def test_export_metadata(self, populated_db, tmp_path):
        """Export should include correct metadata."""
        output_path = str(tmp_path / "export.json")
        export_full_json(populated_db, output_path)

        with open(output_path) as f:
            data = json.load(f)

        meta = data["chartfold_export"]
        assert meta["version"] == EXPORT_VERSION
        assert meta["schema_version"] == SCHEMA_VERSION
        assert "exported_at" in meta

    def test_export_includes_clinical_tables(self, populated_db, tmp_path):
        """Export should include all clinical tables."""
        output_path = str(tmp_path / "export.json")
        export_full_json(populated_db, output_path)

        with open(output_path) as f:
            data = json.load(f)

        tables = data["tables"]
        for table in CLINICAL_TABLES:
            assert table in tables, f"Missing table: {table}"

    def test_export_includes_notes_by_default(self, populated_db, tmp_path):
        """Export should include notes tables by default."""
        output_path = str(tmp_path / "export.json")
        export_full_json(populated_db, output_path)

        with open(output_path) as f:
            data = json.load(f)

        tables = data["tables"]
        assert "notes" in tables
        assert "note_tags" in tables
        assert len(tables["notes"]) == 1
        assert len(tables["note_tags"]) == 2  # Two tags

    def test_export_excludes_notes_when_requested(self, populated_db, tmp_path):
        """Export should exclude notes when include_notes=False."""
        output_path = str(tmp_path / "export.json")
        export_full_json(populated_db, output_path, include_notes=False)

        with open(output_path) as f:
            data = json.load(f)

        tables = data["tables"]
        assert "notes" not in tables
        assert "note_tags" not in tables

    def test_export_excludes_load_log_by_default(self, populated_db, tmp_path):
        """Export should exclude load_log by default."""
        output_path = str(tmp_path / "export.json")
        export_full_json(populated_db, output_path)

        with open(output_path) as f:
            data = json.load(f)

        tables = data["tables"]
        assert "load_log" not in tables

    def test_export_includes_load_log_when_requested(self, populated_db, tmp_path):
        """Export should include load_log when requested."""
        output_path = str(tmp_path / "export.json")
        export_full_json(populated_db, output_path, include_load_log=True)

        with open(output_path) as f:
            data = json.load(f)

        tables = data["tables"]
        assert "load_log" in tables
        assert len(tables["load_log"]) == 1  # One load entry

    def test_export_preserves_data_types(self, populated_db, tmp_path):
        """Export should preserve numeric and null values correctly."""
        output_path = str(tmp_path / "export.json")
        export_full_json(populated_db, output_path)

        with open(output_path) as f:
            data = json.load(f)

        labs = data["tables"]["lab_results"]
        cea = next(l for l in labs if l["test_name"] == "CEA")
        assert cea["value_numeric"] == 5.8
        assert cea["interpretation"] == "H"


class TestExportFullMarkdown:
    """Tests for markdown export functionality."""

    def test_export_creates_file(self, populated_db, tmp_path):
        """Export should create a valid markdown file."""
        output_path = str(tmp_path / "export.md")
        result = export_full_markdown(populated_db, output_path)

        assert result == output_path
        assert (tmp_path / "export.md").exists()

    def test_export_includes_header(self, populated_db, tmp_path):
        """Export should include header with timestamp."""
        output_path = str(tmp_path / "export.md")
        export_full_markdown(populated_db, output_path)

        with open(output_path) as f:
            content = f.read()

        assert "# Chartfold Full Data Export" in content
        assert "*Exported:" in content

    def test_export_includes_summary(self, populated_db, tmp_path):
        """Export should include summary section."""
        output_path = str(tmp_path / "export.md")
        export_full_markdown(populated_db, output_path)

        with open(output_path) as f:
            content = f.read()

        assert "## Summary" in content
        assert "lab_results" in content

    def test_export_includes_tables(self, populated_db, tmp_path):
        """Export should include markdown tables for populated data."""
        output_path = str(tmp_path / "export.md")
        export_full_markdown(populated_db, output_path)

        with open(output_path) as f:
            content = f.read()

        # Check for table headers
        assert "## lab_results" in content
        assert "## medications" in content
        assert "| test_name |" in content or "| id |" in content

    def test_export_truncates_long_values(self, populated_db, tmp_path):
        """Export should truncate very long values in markdown."""
        # Add a note with very long content
        populated_db.save_note(
            title="Long Note",
            content="x" * 200,  # Very long content
        )

        output_path = str(tmp_path / "export.md")
        export_full_markdown(populated_db, output_path)

        with open(output_path) as f:
            content = f.read()

        # Long content should be truncated with "..."
        assert "..." in content


class TestValidateJsonExport:
    """Tests for JSON validation functionality."""

    def test_validate_valid_file(self, populated_db, tmp_path):
        """Validation should pass for valid export file."""
        output_path = str(tmp_path / "export.json")
        export_full_json(populated_db, output_path)

        result = validate_json_export(output_path)
        assert result["valid"] is True
        assert result["errors"] == []
        assert result["summary"]["lab_results"] == 2

    def test_validate_missing_file(self, tmp_path):
        """Validation should fail for missing file."""
        result = validate_json_export(str(tmp_path / "nonexistent.json"))
        assert result["valid"] is False
        assert "File not found" in result["errors"][0]

    def test_validate_invalid_json(self, tmp_path):
        """Validation should fail for invalid JSON."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json {")

        result = validate_json_export(str(bad_file))
        assert result["valid"] is False
        assert "Invalid JSON" in result["errors"][0]

    def test_validate_missing_metadata(self, tmp_path):
        """Validation should fail for missing metadata."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text('{"tables": {}}')

        result = validate_json_export(str(bad_file))
        assert result["valid"] is False
        assert any("metadata" in e.lower() or "chartfold_export" in e for e in result["errors"])

    def test_validate_missing_version(self, tmp_path):
        """Validation should fail for missing version in metadata."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text('{"chartfold_export": {"schema_version": 1}, "tables": {}}')

        result = validate_json_export(str(bad_file))
        assert result["valid"] is False
        assert any("version" in e.lower() for e in result["errors"])

    def test_validate_missing_schema_version(self, tmp_path):
        """Validation should fail for missing schema_version in metadata."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text('{"chartfold_export": {"version": "1.0"}, "tables": {}}')

        result = validate_json_export(str(bad_file))
        assert result["valid"] is False
        assert any("schema" in e.lower() for e in result["errors"])

    def test_validate_missing_tables_block(self, tmp_path):
        """Validation should fail for missing tables block."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text('{"chartfold_export": {"version": "1.0", "schema_version": 1}}')

        result = validate_json_export(str(bad_file))
        assert result["valid"] is False
        assert any("tables" in e.lower() for e in result["errors"])

    def test_validate_table_not_list(self, tmp_path):
        """Validation should fail if a table is not a list."""
        bad_file = tmp_path / "bad.json"
        data = {
            "chartfold_export": {"version": "1.0", "schema_version": 1},
            "tables": {
                "patients": "not a list",  # Should be a list
                "documents": [],
                "encounters": [],
                "lab_results": [],
                "vitals": [],
                "medications": [],
                "conditions": [],
                "procedures": [],
                "pathology_reports": [],
                "imaging_reports": [],
                "clinical_notes": [],
                "immunizations": [],
                "allergies": [],
                "social_history": [],
                "family_history": [],
                "mental_status": [],
                "source_assets": [],
            },
        }
        bad_file.write_text(json.dumps(data))

        result = validate_json_export(str(bad_file))
        assert result["valid"] is False
        assert any("not a list" in e for e in result["errors"])


class TestImportJson:
    """Tests for JSON import functionality."""

    def test_import_creates_database(self, populated_db, tmp_path):
        """Import should create a new database from export."""
        export_path = str(tmp_path / "export.json")
        export_full_json(populated_db, export_path)

        import_db_path = str(tmp_path / "imported.db")
        result = import_json(export_path, import_db_path)

        assert result["success"] is True
        assert (tmp_path / "imported.db").exists()

    def test_import_preserves_record_counts(self, populated_db, tmp_path):
        """Import should preserve all record counts."""
        export_path = str(tmp_path / "export.json")
        export_full_json(populated_db, export_path)

        # Get original counts
        original_summary = populated_db.summary()

        import_db_path = str(tmp_path / "imported.db")
        result = import_json(export_path, import_db_path)

        # Check counts match
        with ChartfoldDB(import_db_path) as imported_db:
            imported_summary = imported_db.summary()

        for table in CLINICAL_TABLES:
            assert original_summary.get(table, 0) == imported_summary.get(table, 0), \
                f"Count mismatch for {table}"

    def test_import_preserves_data_values(self, populated_db, tmp_path):
        """Import should preserve actual data values."""
        export_path = str(tmp_path / "export.json")
        export_full_json(populated_db, export_path)

        import_db_path = str(tmp_path / "imported.db")
        import_json(export_path, import_db_path)

        with ChartfoldDB(import_db_path) as imported_db:
            labs = imported_db.query("SELECT * FROM lab_results WHERE test_name = 'CEA'")
            assert len(labs) == 1
            assert labs[0]["value_numeric"] == 5.8
            assert labs[0]["interpretation"] == "H"

    def test_import_preserves_fk_relationships(self, populated_db_with_pathology, tmp_path):
        """Import should preserve foreign key relationships."""
        export_path = str(tmp_path / "export.json")
        export_full_json(populated_db_with_pathology, export_path)

        import_db_path = str(tmp_path / "imported.db")
        import_json(export_path, import_db_path)

        with ChartfoldDB(import_db_path) as imported_db:
            # Check FK relationship is preserved
            result = imported_db.query("""
                SELECT p.name as proc_name, pr.diagnosis
                FROM pathology_reports pr
                JOIN procedures p ON pr.procedure_id = p.id
                ORDER BY pr.report_date
            """)
            assert len(result) == 2
            assert result[0]["proc_name"] == "Right hemicolectomy"
            assert result[0]["diagnosis"] == "Adenocarcinoma"
            assert result[1]["proc_name"] == "Liver resection"

    def test_import_preserves_notes_and_tags(self, populated_db, tmp_path):
        """Import should preserve notes and their tags."""
        export_path = str(tmp_path / "export.json")
        export_full_json(populated_db, export_path)

        import_db_path = str(tmp_path / "imported.db")
        import_json(export_path, import_db_path)

        with ChartfoldDB(import_db_path) as imported_db:
            notes = imported_db.search_notes_personal()
            assert len(notes) == 1
            assert notes[0]["title"] == "Treatment Analysis"
            assert set(notes[0]["tags"]) == {"oncology", "treatment"}

    def test_import_validate_only(self, populated_db, tmp_path):
        """Validate-only mode should not create database."""
        export_path = str(tmp_path / "export.json")
        export_full_json(populated_db, export_path)

        import_db_path = str(tmp_path / "imported.db")
        result = import_json(export_path, import_db_path, validate_only=True)

        assert result["success"] is True
        assert result.get("validated_only") is True
        assert not (tmp_path / "imported.db").exists()

    def test_import_refuses_overwrite_by_default(self, populated_db, tmp_path):
        """Import should refuse to overwrite existing database."""
        export_path = str(tmp_path / "export.json")
        export_full_json(populated_db, export_path)

        import_db_path = str(tmp_path / "existing.db")
        # Create existing database
        with ChartfoldDB(import_db_path) as _:
            pass

        result = import_json(export_path, import_db_path)
        assert result["success"] is False
        assert "already exists" in result["errors"][0]

    def test_import_overwrites_when_requested(self, populated_db, tmp_path):
        """Import should overwrite when --overwrite flag is used."""
        export_path = str(tmp_path / "export.json")
        export_full_json(populated_db, export_path)

        import_db_path = str(tmp_path / "existing.db")
        # Create existing database with different data
        with ChartfoldDB(import_db_path) as existing_db:
            existing_db.init_schema()
            existing_db.conn.execute(
                "INSERT INTO patients (source, name) VALUES (?, ?)",
                ("old_source", "Old Patient"),
            )
            existing_db.conn.commit()

        result = import_json(export_path, import_db_path, overwrite=True)
        assert result["success"] is True

        # Verify old data is gone, new data is present
        with ChartfoldDB(import_db_path) as imported_db:
            patients = imported_db.query("SELECT * FROM patients")
            assert len(patients) == 1
            assert patients[0]["name"] == "John Doe"


class TestRoundTrip:
    """End-to-end round-trip tests."""

    def test_full_round_trip(self, populated_db, tmp_path):
        """Complete export -> import -> verify cycle."""
        # Export
        export_path = str(tmp_path / "export.json")
        export_full_json(populated_db, export_path, include_notes=True, include_load_log=True)

        # Get original data
        original_labs = populated_db.query("SELECT * FROM lab_results ORDER BY test_name")
        original_meds = populated_db.query("SELECT * FROM medications ORDER BY name")
        original_notes = populated_db.search_notes_personal()

        # Import
        import_db_path = str(tmp_path / "imported.db")
        result = import_json(export_path, import_db_path)
        assert result["success"] is True

        # Verify
        with ChartfoldDB(import_db_path) as imported_db:
            imported_labs = imported_db.query("SELECT * FROM lab_results ORDER BY test_name")
            imported_meds = imported_db.query("SELECT * FROM medications ORDER BY name")
            imported_notes = imported_db.search_notes_personal()

            # Compare counts
            assert len(imported_labs) == len(original_labs)
            assert len(imported_meds) == len(original_meds)
            assert len(imported_notes) == len(original_notes)

            # Compare values (excluding auto-generated IDs)
            for orig, imp in zip(original_labs, imported_labs):
                assert orig["test_name"] == imp["test_name"]
                assert orig["value"] == imp["value"]
                assert orig["value_numeric"] == imp["value_numeric"]

    def test_round_trip_with_empty_tables(self, tmp_path):
        """Round-trip should work with empty tables."""
        # Create minimal database
        db_path = str(tmp_path / "minimal.db")
        with ChartfoldDB(db_path) as db:
            db.init_schema()
            # Only add one record
            db.conn.execute(
                "INSERT INTO patients (source, name) VALUES (?, ?)",
                ("test", "Test Patient"),
            )
            db.conn.commit()

        # Export
        export_path = str(tmp_path / "export.json")
        with ChartfoldDB(db_path) as db:
            export_full_json(db, export_path)

        # Import
        import_db_path = str(tmp_path / "imported.db")
        result = import_json(export_path, import_db_path)
        assert result["success"] is True

        # Verify
        with ChartfoldDB(import_db_path) as imported_db:
            patients = imported_db.query("SELECT * FROM patients")
            assert len(patients) == 1
            assert patients[0]["name"] == "Test Patient"

    def test_round_trip_preserves_nulls(self, tmp_path):
        """Round-trip should preserve NULL values correctly."""
        db_path = str(tmp_path / "nulls.db")
        with ChartfoldDB(db_path) as db:
            db.init_schema()
            # Insert record with NULL values
            db.conn.execute(
                """INSERT INTO lab_results
                   (source, test_name, value, value_numeric, interpretation)
                   VALUES (?, ?, ?, ?, ?)""",
                ("test", "Test", "positive", None, None),
            )
            db.conn.commit()

        # Export
        export_path = str(tmp_path / "export.json")
        with ChartfoldDB(db_path) as db:
            export_full_json(db, export_path)

        # Import
        import_db_path = str(tmp_path / "imported.db")
        result = import_json(export_path, import_db_path)
        assert result["success"] is True

        # Verify NULLs preserved
        with ChartfoldDB(import_db_path) as imported_db:
            labs = imported_db.query("SELECT * FROM lab_results")
            assert labs[0]["value_numeric"] is None
            assert labs[0]["interpretation"] is None
