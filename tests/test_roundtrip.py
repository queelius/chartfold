"""Round-trip tests verifying no silent data loss through the pipeline.

Pipeline stages:
    Raw Files -> [Parser] -> dict -> [Adapter] -> UnifiedRecords -> [DB.load_source()] -> SQLite

These tests verify that record counts are preserved (or intentionally reduced
via deduplication) at each stage transition.
"""

from chartfold.adapters.epic_adapter import epic_to_unified, _parser_counts as epic_parser_counts
from chartfold.adapters.meditech_adapter import (
    meditech_to_unified,
    _parser_counts as meditech_parser_counts,
)
from chartfold.adapters.athena_adapter import (
    athena_to_unified,
    _parser_counts as athena_parser_counts,
)


class TestUnifiedRecordsCounts:
    """Test that UnifiedRecords.counts() returns accurate counts."""

    def test_counts_empty(self):
        from chartfold.models import UnifiedRecords

        records = UnifiedRecords(source="test")
        counts = records.counts()
        expected_keys = {
            "patients",
            "documents",
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
            "source_assets",
            "genetic_variants",
        }
        assert set(counts.keys()) == expected_keys
        assert all(v == 0 for v in counts.values())

    def test_counts_with_data(self, sample_unified_records):
        counts = sample_unified_records.counts()
        assert counts["patients"] == 1
        assert counts["documents"] == 1
        assert counts["encounters"] == 1
        assert counts["lab_results"] == 2
        assert counts["medications"] == 1
        assert counts["conditions"] == 1

    def test_counts_keys_match_db_load(self, tmp_db, sample_unified_records):
        """counts() keys should match the keys returned by db.load_source()."""
        adapter_counts = sample_unified_records.counts()
        db_counts = tmp_db.load_source(sample_unified_records)
        assert set(adapter_counts.keys()) == set(db_counts.keys())


class TestEpicRoundTrip:
    """Verify Epic pipeline preserves all records from parser through DB."""

    def test_parser_counts_structure(self, sample_epic_data):
        counts = epic_parser_counts(sample_epic_data)
        assert isinstance(counts, dict)
        assert counts["patients"] == 1
        assert counts["documents"] == 2
        assert counts["lab_results"] == 3  # 2 CBC components + 1 CEA
        assert counts["medications"] == 2
        assert counts["conditions"] == 2
        assert counts["family_history"] == 2

    def test_adapter_preserves_all_parser_records(self, sample_epic_data):
        """Adapter output count should match parser input count.

        Epic has no dedup in the adapter, so counts must match exactly
        for all record types.
        """
        parser_counts = epic_parser_counts(sample_epic_data)
        records = epic_to_unified(sample_epic_data)
        adapter_counts = records.counts()

        for key in (
            "patients",
            "documents",
            "encounters",
            "lab_results",
            "imaging_reports",
            "pathology_reports",
            "clinical_notes",
            "medications",
            "conditions",
            "vitals",
            "immunizations",
            "allergies",
            "social_history",
            "family_history",
            "procedures",
        ):
            assert adapter_counts[key] == parser_counts[key], (
                f"{key}: parser={parser_counts[key]}, adapter={adapter_counts[key]}"
            )

    def test_db_preserves_all_adapter_records(self, tmp_db, sample_epic_data):
        """DB should store exactly what the adapter produces."""
        records = epic_to_unified(sample_epic_data)
        adapter_counts = records.counts()
        db_counts = tmp_db.load_source(records)

        for key in adapter_counts:
            assert db_counts[key] == adapter_counts[key], (
                f"{key}: adapter={adapter_counts[key]}, db={db_counts[key]}"
            )

    def test_full_pipeline_roundtrip(self, tmp_db, sample_epic_data):
        """End-to-end: parser counts == DB counts for Epic (no dedup)."""
        parser_counts = epic_parser_counts(sample_epic_data)
        records = epic_to_unified(sample_epic_data)
        db_counts = tmp_db.load_source(records)

        for key in (
            "patients",
            "documents",
            "encounters",
            "lab_results",
            "medications",
            "conditions",
            "vitals",
            "immunizations",
            "allergies",
            "social_history",
            "family_history",
            "procedures",
        ):
            assert db_counts[key] == parser_counts[key], (
                f"{key}: parser={parser_counts[key]}, db={db_counts[key]}"
            )

    def test_empty_epic_data(self):
        """Empty parser output should produce empty UnifiedRecords."""
        data = {"inventory": [], "lab_results": [], "cea_values": [], "errors": []}
        parser_counts = epic_parser_counts(data)
        records = epic_to_unified(data)
        adapter_counts = records.counts()
        assert all(v == 0 for v in adapter_counts.values())
        for key, val in parser_counts.items():
            if key != "errors":
                assert val == 0, f"parser {key}={val} should be 0"


class TestMeditechRoundTrip:
    """Verify MEDITECH pipeline — adapter may dedup, so count <= parser count."""

    def test_parser_counts_structure(self, sample_meditech_data):
        counts = meditech_parser_counts(sample_meditech_data)
        assert isinstance(counts, dict)
        assert counts["patients"] == 1
        assert counts["documents"] == 1
        assert counts["lab_results"] == 2  # 1 FHIR + 1 CCDA
        assert counts["conditions"] == 2  # 1 FHIR + 1 CCDA
        assert counts["imaging_reports"] == 1  # 1 FHIR diagnostic report (Radiology)
        assert counts["allergies"] == 1  # 1 FHIR allergy intolerance
        assert counts["procedures"] == 1  # 1 FHIR procedure
        assert counts["social_history"] == 2  # 1 FHIR social-history + 1 CCDA
        assert counts["mental_status"] == 2  # 1 FHIR survey + 1 CCDA

    def test_adapter_output_lte_combined_parser_input(self, sample_meditech_data):
        """Adapter may dedup, so count <= parser count for all keys."""
        parser_counts = meditech_parser_counts(sample_meditech_data)
        records = meditech_to_unified(sample_meditech_data)
        adapter_counts = records.counts()

        for key in (
            "lab_results",
            "conditions",
            "medications",
            "vitals",
            "immunizations",
            "patients",
            "documents",
            "encounters",
            "procedures",
            "pathology_reports",
            "imaging_reports",
            "clinical_notes",
            "allergies",
            "social_history",
            "family_history",
            "mental_status",
        ):
            assert adapter_counts[key] <= parser_counts[key], (
                f"{key}: adapter={adapter_counts[key]} > parser={parser_counts[key]}"
            )

    def test_adapter_never_creates_extra_records(self, sample_meditech_data):
        """Adapter should never produce MORE records than the parser provided."""
        parser_counts = meditech_parser_counts(sample_meditech_data)
        records = meditech_to_unified(sample_meditech_data)
        adapter_counts = records.counts()

        for key in (
            "patients",
            "documents",
            "encounters",
            "procedures",
            "pathology_reports",
            "imaging_reports",
            "clinical_notes",
            "allergies",
            "social_history",
            "family_history",
            "mental_status",
            "lab_results",
            "conditions",
            "medications",
            "vitals",
            "immunizations",
        ):
            assert adapter_counts[key] <= parser_counts[key], (
                f"{key}: adapter={adapter_counts[key]} > parser={parser_counts[key]}"
            )

    def test_db_preserves_all_adapter_records(self, tmp_db, sample_meditech_data):
        """DB should store exactly what the adapter produces."""
        records = meditech_to_unified(sample_meditech_data)
        adapter_counts = records.counts()
        db_counts = tmp_db.load_source(records)

        for key in adapter_counts:
            assert db_counts[key] == adapter_counts[key], (
                f"{key}: adapter={adapter_counts[key]}, db={db_counts[key]}"
            )

    def test_empty_meditech_data(self):
        """Empty parser output should produce empty UnifiedRecords."""
        data = {"fhir_data": {}, "ccda_data": {}, "toc_data": []}
        parser_counts = meditech_parser_counts(data)
        records = meditech_to_unified(data)
        adapter_counts = records.counts()
        assert all(v == 0 for v in adapter_counts.values())
        assert all(v == 0 for v in parser_counts.values())


class TestAthenaRoundTrip:
    """Verify Athena pipeline preserves all records (no dedup)."""

    def test_parser_counts_structure(self, sample_athena_data):
        counts = athena_parser_counts(sample_athena_data)
        assert isinstance(counts, dict)
        assert counts["patients"] == 1
        assert counts["lab_results"] == 2
        assert counts["vitals"] == 2

    def test_adapter_preserves_all_parser_records(self, sample_athena_data):
        """Athena has no dedup, so counts must match exactly."""
        parser_counts = athena_parser_counts(sample_athena_data)
        records = athena_to_unified(sample_athena_data)
        adapter_counts = records.counts()

        for key in (
            "patients",
            "documents",
            "encounters",
            "lab_results",
            "vitals",
            "medications",
            "conditions",
            "immunizations",
            "allergies",
            "social_history",
            "family_history",
            "mental_status",
            "clinical_notes",
            "procedures",
        ):
            assert adapter_counts[key] == parser_counts[key], (
                f"{key}: parser={parser_counts[key]}, adapter={adapter_counts[key]}"
            )

    def test_db_preserves_all_adapter_records(self, tmp_db, sample_athena_data):
        """DB should store exactly what the adapter produces."""
        records = athena_to_unified(sample_athena_data)
        adapter_counts = records.counts()
        db_counts = tmp_db.load_source(records)

        for key in adapter_counts:
            assert db_counts[key] == adapter_counts[key], (
                f"{key}: adapter={adapter_counts[key]}, db={db_counts[key]}"
            )

    def test_full_pipeline_roundtrip(self, tmp_db, sample_athena_data):
        """End-to-end: parser counts == DB counts for Athena (no dedup)."""
        parser_counts = athena_parser_counts(sample_athena_data)
        records = athena_to_unified(sample_athena_data)
        db_counts = tmp_db.load_source(records)

        for key in (
            "patients",
            "documents",
            "encounters",
            "lab_results",
            "vitals",
            "medications",
            "conditions",
            "immunizations",
            "allergies",
            "social_history",
            "family_history",
            "mental_status",
            "clinical_notes",
            "procedures",
        ):
            assert db_counts[key] == parser_counts[key], (
                f"{key}: parser={parser_counts[key]}, db={db_counts[key]}"
            )

    def test_empty_athena_data(self):
        """Empty parser output should produce empty UnifiedRecords."""
        data = {}
        parser_counts = athena_parser_counts(data)
        records = athena_to_unified(data)
        adapter_counts = records.counts()
        assert all(v == 0 for v in adapter_counts.values())
        assert all(v == 0 for v in parser_counts.values())


class TestLastLoadCounts:
    """Test db.last_load_counts() retrieves correct historical data."""

    def test_returns_none_for_unknown_source(self, tmp_db):
        assert tmp_db.last_load_counts("nonexistent") is None

    def test_returns_counts_after_load(self, tmp_db, sample_unified_records):
        tmp_db.load_source(sample_unified_records)
        result = tmp_db.last_load_counts("test_source")
        assert result is not None
        assert result["patients"] == 1
        assert result["lab_results"] == 2
        assert result["medications"] == 1

    def test_returns_latest_load(self, tmp_db, sample_unified_records):
        """When loaded twice, should return the most recent counts."""
        tmp_db.load_source(sample_unified_records)

        # Modify and load again
        sample_unified_records.lab_results = sample_unified_records.lab_results[:1]
        tmp_db.load_source(sample_unified_records)

        result = tmp_db.last_load_counts("test_source")
        assert result["lab_results"] == 1  # Latest load had only 1

    def test_counts_match_load_source_return(self, tmp_db, sample_unified_records):
        """last_load_counts() should match the dict returned by load_source()."""
        db_counts = tmp_db.load_source(sample_unified_records)
        log_counts = tmp_db.last_load_counts("test_source")
        assert log_counts is not None
        for key in db_counts:
            assert log_counts[key] == db_counts[key], (
                f"{key}: load_source={db_counts[key]}, last_load_counts={log_counts[key]}"
            )


class TestIdempotentLoad:
    """Verify that loading the same source twice doesn't double records."""

    def test_epic_idempotent(self, tmp_db, sample_epic_data):
        records = epic_to_unified(sample_epic_data)
        result1 = tmp_db.load_source(records)
        result2 = tmp_db.load_source(records)
        # Second load should be skipped (identical content hash)
        assert result2["skipped"] is True

        # DB totals should match single load (not doubled)
        summary = tmp_db.summary()
        for key in result1:
            assert summary[key] == result1[key]

    def test_athena_idempotent(self, tmp_db, sample_athena_data):
        records = athena_to_unified(sample_athena_data)
        result1 = tmp_db.load_source(records)
        result2 = tmp_db.load_source(records)
        # Second load should be skipped (identical content hash)
        assert result2["skipped"] is True


class TestStageComparison:
    """Test the CLI _print_load_result display."""

    @staticmethod
    def _make_result(table_stats):
        """Build a LoadResult from a simple {table: total} dict."""
        from chartfold.db import LoadResult
        tables = {
            k: {"new": v, "existing": 0, "removed": 0, "total": v}
            for k, v in table_stats.items()
        }
        return LoadResult(tables=tables, content_hash="test", skipped=False)

    def test_matching_counts_no_flags(self, capsys):
        """When all stages match, no flags should be printed."""
        from chartfold.cli import _print_load_result

        counts = {"lab_results": 10, "medications": 5}
        result = self._make_result(counts)
        _print_load_result(result, counts, counts)
        output = capsys.readouterr().out
        assert "lab_results" in output
        assert "(dedup)" not in output

    def test_dedup_flagged(self, capsys):
        """Parser > adapter should show (dedup) flag."""
        from chartfold.cli import _print_load_result

        parser = {"lab_results": 10}
        adapter = {"lab_results": 8}
        result = self._make_result(adapter)
        _print_load_result(result, parser, adapter)
        output = capsys.readouterr().out
        assert "dedup" in output

    def test_expand_flagged(self, capsys):
        """Parser < adapter should show (expand) flag."""
        from chartfold.cli import _print_load_result

        parser = {"lab_results": 5}
        adapter = {"lab_results": 10}
        result = self._make_result(adapter)
        _print_load_result(result, parser, adapter)
        output = capsys.readouterr().out
        assert "expand" in output

    def test_all_zero_rows_hidden(self, capsys):
        """Rows where all counts are 0 should not be displayed."""
        from chartfold.cli import _print_load_result

        parser = {"lab_results": 0, "medications": 5}
        adapter = {"lab_results": 0, "medications": 5}
        result = self._make_result(adapter)
        _print_load_result(result, parser, adapter)
        output = capsys.readouterr().out
        assert "lab_results" not in output
        assert "medications" in output

    def test_empty_counts_prints_nothing(self, capsys):
        """All-empty input should produce no output."""
        from chartfold.cli import _print_load_result
        from chartfold.db import LoadResult

        result = LoadResult(tables={}, content_hash="test", skipped=False)
        _print_load_result(result, {}, {})
        assert capsys.readouterr().out == ""

    def test_diff_shows_new_count(self, capsys):
        """Diff column should show +N for new records."""
        from chartfold.cli import _print_load_result
        from chartfold.db import LoadResult

        tables = {
            "lab_results": {"new": 3, "existing": 7, "removed": 0, "total": 10},
        }
        result = LoadResult(tables=tables, content_hash="test", skipped=False)
        _print_load_result(result, {"lab_results": 10}, {"lab_results": 10})
        output = capsys.readouterr().out
        assert "+3" in output
        assert "=7" in output

    def test_diff_shows_removed_count(self, capsys):
        """Diff column should show -N for removed records."""
        from chartfold.cli import _print_load_result
        from chartfold.db import LoadResult

        tables = {
            "lab_results": {"new": 0, "existing": 8, "removed": 2, "total": 8},
        }
        result = LoadResult(tables=tables, content_hash="test", skipped=False)
        _print_load_result(result, {"lab_results": 8}, {"lab_results": 8})
        output = capsys.readouterr().out
        assert "-2" in output

    def test_summary_line(self, capsys):
        """Summary line should show totals."""
        from chartfold.cli import _print_load_result
        from chartfold.db import LoadResult

        tables = {
            "lab_results": {"new": 3, "existing": 7, "removed": 0, "total": 10},
            "medications": {"new": 1, "existing": 4, "removed": 0, "total": 5},
        }
        result = LoadResult(tables=tables, content_hash="test", skipped=False)
        _print_load_result(
            result, {"lab_results": 10, "medications": 5}, {"lab_results": 10, "medications": 5}
        )
        output = capsys.readouterr().out
        assert "4 new" in output
        assert "11 existing" in output
