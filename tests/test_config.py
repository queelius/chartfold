"""Tests for chartfold.config module."""

import pytest

from chartfold.config import (
    FALLBACK_KEY_TESTS,
    KNOWN_ABBREVIATIONS,
    LabTestConfig,
    _group_test_names,
    generate_config,
    get_lab_test_configs,
    load_config,
)
from chartfold.db import ChartfoldDB
from chartfold.models import LabResult, UnifiedRecords


@pytest.fixture
def config_db(tmp_path):
    """Database with lab data for config generation."""
    db = ChartfoldDB(str(tmp_path / "config.db"))
    db.init_schema()

    records = UnifiedRecords(
        source="test",
        lab_results=[
            LabResult(
                source="test",
                test_name="CEA",
                value="5.8",
                value_numeric=5.8,
                unit="ng/mL",
                result_date="2025-01-01",
            ),
            LabResult(
                source="test",
                test_name="CEA",
                value="3.2",
                value_numeric=3.2,
                unit="ng/mL",
                result_date="2025-03-01",
            ),
            LabResult(
                source="test",
                test_name="CEA",
                value="4.1",
                value_numeric=4.1,
                unit="ng/mL",
                result_date="2025-06-01",
            ),
            LabResult(
                source="test",
                test_name="Hemoglobin",
                value="12.5",
                value_numeric=12.5,
                unit="g/dL",
                result_date="2025-01-01",
            ),
            LabResult(
                source="test",
                test_name="Hemoglobin",
                value="13.0",
                value_numeric=13.0,
                unit="g/dL",
                result_date="2025-06-01",
            ),
            LabResult(
                source="test",
                test_name="WBC",
                value="6.2",
                value_numeric=6.2,
                unit="K/mm3",
                result_date="2025-01-01",
            ),
        ],
    )
    db.load_source(records)
    yield db
    db.close()


@pytest.fixture
def alias_db(tmp_path):
    """Database with cross-source lab data for name grouping."""
    db = ChartfoldDB(str(tmp_path / "alias.db"))
    db.init_schema()

    epic_records = UnifiedRecords(
        source="epic_anderson",
        lab_results=[
            LabResult(
                source="epic_anderson",
                test_name="CEA",
                test_loinc="2039-6",
                value="5.8",
                value_numeric=5.8,
                unit="ng/mL",
                ref_range="0.0-3.0",
                result_date="2025-01-15",
            ),
            LabResult(
                source="epic_anderson",
                test_name="CEA",
                test_loinc="2039-6",
                value="3.2",
                value_numeric=3.2,
                unit="ng/mL",
                ref_range="0.0-3.0",
                result_date="2025-06-15",
            ),
        ],
    )
    meditech_records = UnifiedRecords(
        source="meditech_siteman",
        lab_results=[
            LabResult(
                source="meditech_siteman",
                test_name="Carcinoembryonic Antigen",
                test_loinc="2039-6",
                value="4.1",
                value_numeric=4.1,
                unit="ng/mL",
                ref_range="0.0-5.0",
                result_date="2024-11-01",
            ),
            LabResult(
                source="meditech_siteman",
                test_name="Carcinoembryonic Antigen",
                test_loinc="2039-6",
                value="2.5",
                value_numeric=2.5,
                unit="ng/mL",
                ref_range="0.0-5.0",
                result_date="2025-03-01",
            ),
            LabResult(
                source="meditech_siteman",
                test_name="Hemoglobin",
                value="13.5",
                value_numeric=13.5,
                unit="g/dL",
                ref_range="13.0-17.0",
                result_date="2025-01-15",
            ),
        ],
    )
    db.load_source(epic_records)
    db.load_source(meditech_records)
    yield db
    db.close()


# ---------------------------------------------------------------------------
# LabTestConfig dataclass
# ---------------------------------------------------------------------------


class TestLabTestConfig:
    def test_basic_creation(self):
        lt = LabTestConfig(name="CEA", match=["CEA", "Carcinoembryonic Antigen"])
        assert lt.name == "CEA"
        assert lt.match == ["CEA", "Carcinoembryonic Antigen"]

    def test_default_match_is_empty(self):
        lt = LabTestConfig(name="Glucose")
        assert lt.match == []

    def test_single_match(self):
        lt = LabTestConfig(name="RBC", match=["RBC"])
        assert lt.match == ["RBC"]


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_missing_file_returns_defaults(self, tmp_path):
        config = load_config(str(tmp_path / "nonexistent.toml"))
        lab_tests = get_lab_test_configs(config)
        assert len(lab_tests) == len(FALLBACK_KEY_TESTS)
        assert lab_tests[0].name == "CEA"
        assert "CEA" in lab_tests[0].match

    def test_loads_lab_tests_format(self, tmp_path):
        toml_path = tmp_path / "test.toml"
        toml_path.write_text("""
[[lab_tests]]
name = "CEA"
match = ["CEA", "Carcinoembryonic Antigen"]

[[lab_tests]]
name = "Hemoglobin"
match = ["Hemoglobin", "Hgb", "HGB"]
""")
        config = load_config(str(toml_path))
        lab_tests = get_lab_test_configs(config)
        assert len(lab_tests) == 2
        assert lab_tests[0].name == "CEA"
        assert lab_tests[0].match == ["CEA", "Carcinoembryonic Antigen"]
        assert lab_tests[1].name == "Hemoglobin"
        assert lab_tests[1].match == ["Hemoglobin", "Hgb", "HGB"]

    def test_empty_config_uses_defaults(self, tmp_path):
        toml_path = tmp_path / "empty.toml"
        toml_path.write_text("")
        config = load_config(str(toml_path))
        lab_tests = get_lab_test_configs(config)
        assert len(lab_tests) == len(FALLBACK_KEY_TESTS)

    def test_malformed_entries_skipped(self, tmp_path):
        toml_path = tmp_path / "bad.toml"
        toml_path.write_text("""
[[lab_tests]]
name = "CEA"
match = ["CEA"]

[[lab_tests]]
name = "Missing Match Field"

[[lab_tests]]
match = ["Missing Name Field"]
""")
        config = load_config(str(toml_path))
        lab_tests = get_lab_test_configs(config)
        assert len(lab_tests) == 1
        assert lab_tests[0].name == "CEA"

    def test_legacy_key_tests_format(self, tmp_path):
        """Legacy [key_tests] format is loaded with KNOWN_ABBREVIATIONS."""
        toml_path = tmp_path / "legacy.toml"
        toml_path.write_text("""
[key_tests]
tests = ["CEA", "Hemoglobin"]
""")
        config = load_config(str(toml_path))
        lab_tests = get_lab_test_configs(config)
        assert len(lab_tests) == 2
        cea = lab_tests[0]
        assert cea.name == "CEA"
        assert "CEA" in cea.match
        assert "Carcinoembryonic Antigen" in cea.match

    def test_legacy_key_tests_with_aliases(self, tmp_path):
        """Legacy [key_tests.aliases] overrides are merged with KNOWN_ABBREVIATIONS."""
        toml_path = tmp_path / "legacy_aliases.toml"
        toml_path.write_text("""
[key_tests]
tests = ["CEA"]

[key_tests.aliases]
CEA = ["Carcinoembryonic Ag"]
""")
        config = load_config(str(toml_path))
        lab_tests = get_lab_test_configs(config)
        cea = lab_tests[0]
        # Should have the user-specified alias
        assert "Carcinoembryonic Ag" in cea.match
        # And the KNOWN_ABBREVIATIONS alias
        assert "Carcinoembryonic Antigen" in cea.match

    def test_legacy_key_tests_not_used_when_lab_tests_present(self, tmp_path):
        """[[lab_tests]] format takes precedence over legacy [key_tests]."""
        toml_path = tmp_path / "both.toml"
        toml_path.write_text("""
[[lab_tests]]
name = "WBC"
match = ["WBC"]

[key_tests]
tests = ["CEA", "Hemoglobin"]
""")
        config = load_config(str(toml_path))
        lab_tests = get_lab_test_configs(config)
        assert len(lab_tests) == 1
        assert lab_tests[0].name == "WBC"

    def test_default_config_includes_known_abbreviations(self, tmp_path):
        """Default config includes KNOWN_ABBREVIATIONS in match lists."""
        config = load_config(str(tmp_path / "nonexistent.toml"))
        lab_tests = get_lab_test_configs(config)
        cea = next(lt for lt in lab_tests if lt.name == "CEA")
        assert "Carcinoembryonic Antigen" in cea.match
        hgb = next(lt for lt in lab_tests if lt.name == "Hemoglobin")
        # Hemoglobin is not a key in KNOWN_ABBREVIATIONS (Hgb is), so no extra aliases
        assert "Hemoglobin" in hgb.match


# ---------------------------------------------------------------------------
# get_lab_test_configs
# ---------------------------------------------------------------------------


class TestGetLabTestConfigs:
    def test_returns_empty_for_empty_config(self):
        assert get_lab_test_configs({}) == []

    def test_returns_configs_from_dict(self):
        config = {
            "lab_tests": [
                LabTestConfig(name="CEA", match=["CEA"]),
                LabTestConfig(name="WBC", match=["WBC", "White Blood Count"]),
            ]
        }
        result = get_lab_test_configs(config)
        assert len(result) == 2
        assert result[0].name == "CEA"


# ---------------------------------------------------------------------------
# _group_test_names
# ---------------------------------------------------------------------------


class TestGroupTestNames:
    def test_loinc_grouping(self, alias_db):
        """Same LOINC code groups names together."""
        groups = _group_test_names(alias_db, ["CEA"])
        assert len(groups) == 1
        name, match = groups[0]
        assert name == "CEA"
        assert "CEA" in match
        assert "Carcinoembryonic Antigen" in match

    def test_single_name_returns_singleton(self, config_db):
        """Test with only one name variant gets single-element match list."""
        groups = _group_test_names(config_db, ["CEA"])
        assert len(groups) == 1
        name, match = groups[0]
        assert name == "CEA"
        assert match == ["CEA"]

    def test_preserves_order(self, config_db):
        """Output order matches input key_tests order."""
        groups = _group_test_names(config_db, ["WBC", "CEA", "Hemoglobin"])
        assert [g[0] for g in groups] == ["WBC", "CEA", "Hemoglobin"]

    def test_abbreviation_grouping_without_loinc(self, tmp_path):
        """KNOWN_ABBREVIATIONS groups names even without shared LOINC."""
        db = ChartfoldDB(str(tmp_path / "abbrev.db"))
        db.init_schema()
        records = UnifiedRecords(
            source="test",
            lab_results=[
                LabResult(
                    source="test",
                    test_name="CEA",
                    value="5.8",
                    value_numeric=5.8,
                    unit="ng/mL",
                    result_date="2025-01-01",
                ),
                LabResult(
                    source="test",
                    test_name="Carcinoembryonic Antigen",
                    value="4.1",
                    value_numeric=4.1,
                    unit="ng/mL",
                    result_date="2025-02-01",
                ),
            ],
        )
        db.load_source(records)

        groups = _group_test_names(db, ["CEA"])
        _name, match = groups[0]
        assert "Carcinoembryonic Antigen" in match
        db.close()

    def test_reverse_lookup(self, tmp_path):
        """If a known alias is in key_tests, the abbreviation is grouped in."""
        db = ChartfoldDB(str(tmp_path / "reverse.db"))
        db.init_schema()
        records = UnifiedRecords(
            source="test",
            lab_results=[
                LabResult(
                    source="test",
                    test_name="Carcinoembryonic Antigen",
                    value="4.1",
                    value_numeric=4.1,
                    unit="ng/mL",
                    result_date="2025-01-01",
                ),
                LabResult(
                    source="test",
                    test_name="CEA",
                    value="5.8",
                    value_numeric=5.8,
                    unit="ng/mL",
                    result_date="2025-02-01",
                ),
            ],
        )
        db.load_source(records)

        groups = _group_test_names(db, ["Carcinoembryonic Antigen"])
        _name, match = groups[0]
        assert "CEA" in match
        db.close()

    def test_non_standard_loinc_codes_ignored(self, tmp_path):
        """Internal codes like IMO0002 should not create false groupings."""
        db = ChartfoldDB(str(tmp_path / "bad_loinc.db"))
        db.init_schema()
        records = UnifiedRecords(
            source="test",
            lab_results=[
                LabResult(
                    source="test",
                    test_name="Creatinine",
                    test_loinc="IMO0002",
                    value="0.9",
                    value_numeric=0.9,
                    unit="mg/dL",
                    result_date="2025-01-01",
                ),
                LabResult(
                    source="test",
                    test_name="Hemoglobin",
                    test_loinc="IMO0002",
                    value="13.5",
                    value_numeric=13.5,
                    unit="g/dL",
                    result_date="2025-01-01",
                ),
                LabResult(
                    source="test",
                    test_name="Glucose Level",
                    test_loinc="IMO0002",
                    value="95",
                    value_numeric=95.0,
                    unit="mg/dL",
                    result_date="2025-01-01",
                ),
            ],
        )
        db.load_source(records)

        groups = _group_test_names(db, ["Creatinine", "Hemoglobin"])
        creat_match = next(m for n, m in groups if n == "Creatinine")
        hgb_match = next(m for n, m in groups if n == "Hemoglobin")
        assert "Hemoglobin" not in creat_match
        assert "Creatinine" not in hgb_match
        db.close()


# ---------------------------------------------------------------------------
# generate_config
# ---------------------------------------------------------------------------


class TestGenerateConfig:
    def test_generates_from_db(self, config_db, tmp_path):
        out = str(tmp_path / "generated.toml")
        generate_config(config_db, config_path=out)

        config = load_config(out)
        lab_tests = get_lab_test_configs(config)
        assert lab_tests[0].name == "CEA"
        names = [lt.name for lt in lab_tests]
        # Hemoglobin canonicalizes to "Hgb" via KNOWN_ABBREVIATIONS
        assert "Hgb" in names or "Hemoglobin" in names
        assert "WBC" in names

    def test_generated_file_is_valid_toml(self, config_db, tmp_path):
        out = str(tmp_path / "valid.toml")
        generate_config(config_db, config_path=out)

        import tomllib

        with open(out, "rb") as f:
            data = tomllib.load(f)
        assert "lab_tests" in data
        assert isinstance(data["lab_tests"], list)
        assert data["lab_tests"][0]["name"] == "CEA"
        assert isinstance(data["lab_tests"][0]["match"], list)

    def test_empty_db_uses_fallbacks(self, tmp_path):
        db = ChartfoldDB(str(tmp_path / "empty.db"))
        db.init_schema()

        out = str(tmp_path / "fallback.toml")
        generate_config(db, config_path=out)
        db.close()

        config = load_config(out)
        lab_tests = get_lab_test_configs(config)
        assert [lt.name for lt in lab_tests] == list(FALLBACK_KEY_TESTS)

    def test_top_n_limits_tests(self, config_db, tmp_path):
        out = str(tmp_path / "limited.toml")
        generate_config(config_db, config_path=out, top_n=2)

        config = load_config(out)
        lab_tests = get_lab_test_configs(config)
        # top_n=2 picks the 2 most frequent, but clinically important
        # fallback tests present in the DB are also appended
        assert len(lab_tests) >= 2

    def test_generated_stanza_format(self, config_db, tmp_path):
        """Verify the raw TOML output has [[lab_tests]] stanzas."""
        out = str(tmp_path / "format.toml")
        generate_config(config_db, config_path=out)

        with open(out) as f:
            content = f.read()
        assert "[[lab_tests]]" in content
        assert 'name = "CEA"' in content
        assert "match = [" in content

    def test_auto_detects_cross_source_names(self, alias_db, tmp_path):
        out = str(tmp_path / "auto.toml")
        generate_config(alias_db, config_path=out)

        config = load_config(out)
        lab_tests = get_lab_test_configs(config)
        cea = next((lt for lt in lab_tests if lt.name == "CEA"), None)
        assert cea is not None
        assert "Carcinoembryonic Antigen" in cea.match

    def test_generated_config_round_trips(self, alias_db, tmp_path):
        out = str(tmp_path / "roundtrip.toml")
        generate_config(alias_db, config_path=out)

        import tomllib

        with open(out, "rb") as f:
            data = tomllib.load(f)
        assert "lab_tests" in data
        assert isinstance(data["lab_tests"], list)

    def test_alias_dedup_merges_counts(self, tmp_path):
        """Cross-source name variants are merged before selecting top-N."""
        db = ChartfoldDB(str(tmp_path / "dedup.db"))
        db.init_schema()
        # BUN (19 results) and Blood Urea Nitrogen (17 results)
        # should merge into one slot, not two
        results = []
        for i in range(19):
            results.append(
                LabResult(
                    source="epic",
                    test_name="BUN",
                    value=str(10 + i),
                    value_numeric=float(10 + i),
                    unit="mg/dL",
                    result_date=f"2025-01-{i + 1:02d}",
                )
            )
        for i in range(17):
            results.append(
                LabResult(
                    source="meditech",
                    test_name="Blood Urea Nitrogen",
                    value=str(10 + i),
                    value_numeric=float(10 + i),
                    unit="mg/dL",
                    result_date=f"2025-02-{i + 1:02d}",
                )
            )
        # Also add a unique test that should not conflict
        for i in range(5):
            results.append(
                LabResult(
                    source="epic",
                    test_name="Potassium",
                    value="4.0",
                    value_numeric=4.0,
                    unit="mEq/L",
                    result_date=f"2025-01-{i + 1:02d}",
                )
            )
        db.load_source(
            UnifiedRecords(source="epic", lab_results=[r for r in results if r.source == "epic"])
        )
        db.load_source(
            UnifiedRecords(
                source="meditech", lab_results=[r for r in results if r.source == "meditech"]
            )
        )

        out = str(tmp_path / "dedup.toml")
        generate_config(db, config_path=out, top_n=5)
        db.close()

        config = load_config(out)
        lab_tests = get_lab_test_configs(config)
        names = [lt.name for lt in lab_tests]
        # BUN should appear once (as the canonical name), not twice
        assert names.count("BUN") == 1
        assert "Blood Urea Nitrogen" not in names

    def test_fallback_tests_always_included(self, tmp_path):
        """Clinically important tests from FALLBACK_KEY_TESTS are always included."""
        db = ChartfoldDB(str(tmp_path / "fallback_include.db"))
        db.init_schema()
        # Create many high-frequency tests that push CEA out of top-N
        results = []
        for _i, name in enumerate(["Test_A", "Test_B", "Test_C"]):
            for j in range(50):
                results.append(
                    LabResult(
                        source="test",
                        test_name=name,
                        value=str(j),
                        value_numeric=float(j),
                        unit="U/L",
                        result_date=f"2025-01-{j % 28 + 1:02d}",
                    )
                )
        # CEA with just 2 results
        results.append(
            LabResult(
                source="test",
                test_name="CEA",
                value="5.0",
                value_numeric=5.0,
                unit="ng/mL",
                result_date="2025-01-01",
            )
        )
        results.append(
            LabResult(
                source="test",
                test_name="CEA",
                value="3.0",
                value_numeric=3.0,
                unit="ng/mL",
                result_date="2025-06-01",
            )
        )
        db.load_source(UnifiedRecords(source="test", lab_results=results))

        out = str(tmp_path / "fallback_include.toml")
        generate_config(db, config_path=out, top_n=2)
        db.close()

        config = load_config(out)
        lab_tests = get_lab_test_configs(config)
        names = [lt.name for lt in lab_tests]
        # CEA should be included even though it's not in the top 2 by frequency
        assert "CEA" in names

    def test_default_top_n_is_25(self, config_db, tmp_path):
        """Default top_n is 25 (was 15)."""
        import inspect

        sig = inspect.signature(generate_config)
        assert sig.parameters["top_n"].default == 25


# ---------------------------------------------------------------------------
# KNOWN_ABBREVIATIONS
# ---------------------------------------------------------------------------


class TestKnownAbbreviations:
    """Verify the expanded KNOWN_ABBREVIATIONS dictionary."""

    def test_cbc_abbreviations(self):
        """CBC panel abbreviations are present."""
        assert "Hgb" in KNOWN_ABBREVIATIONS
        assert "Hemoglobin" in KNOWN_ABBREVIATIONS["Hgb"]
        assert "WBC" in KNOWN_ABBREVIATIONS
        assert "RBC" in KNOWN_ABBREVIATIONS
        assert "PLT" in KNOWN_ABBREVIATIONS
        assert "HCT" in KNOWN_ABBREVIATIONS
        assert "MCV" in KNOWN_ABBREVIATIONS
        assert "MCH" in KNOWN_ABBREVIATIONS
        assert "MCHC" in KNOWN_ABBREVIATIONS

    def test_metabolic_panel_abbreviations(self):
        """BMP/CMP abbreviations are present."""
        assert "BUN" in KNOWN_ABBREVIATIONS
        assert "Glucose" in KNOWN_ABBREVIATIONS
        assert "Glucose Level" in KNOWN_ABBREVIATIONS["Glucose"]
        assert "Creatinine" in KNOWN_ABBREVIATIONS
        assert "Serum Creatinine" in KNOWN_ABBREVIATIONS["Creatinine"]
        assert "eGFR" in KNOWN_ABBREVIATIONS
        assert "Potassium" in KNOWN_ABBREVIATIONS
        assert "Sodium" in KNOWN_ABBREVIATIONS
        assert "Calcium" in KNOWN_ABBREVIATIONS
        assert "CO2" in KNOWN_ABBREVIATIONS

    def test_liver_function_abbreviations(self):
        """LFT abbreviations are present."""
        assert "ALT" in KNOWN_ABBREVIATIONS
        assert "AST" in KNOWN_ABBREVIATIONS
        assert "ALP" in KNOWN_ABBREVIATIONS
        assert "Alkaline Phosphatase" in KNOWN_ABBREVIATIONS["ALP"]
        assert "Albumin" in KNOWN_ABBREVIATIONS
        assert "Bilirubin" in KNOWN_ABBREVIATIONS

    def test_thyroid_abbreviations(self):
        assert "TSH" in KNOWN_ABBREVIATIONS
        assert "Free T4" in KNOWN_ABBREVIATIONS
        assert "FT4" in KNOWN_ABBREVIATIONS["Free T4"]

    def test_lipid_panel_abbreviations(self):
        assert "LDL" in KNOWN_ABBREVIATIONS
        assert "HDL" in KNOWN_ABBREVIATIONS
        assert "Triglycerides" in KNOWN_ABBREVIATIONS
        assert "Cholesterol" in KNOWN_ABBREVIATIONS

    def test_coagulation_abbreviations(self):
        assert "PT" in KNOWN_ABBREVIATIONS
        assert "INR" in KNOWN_ABBREVIATIONS
        assert "PTT" in KNOWN_ABBREVIATIONS
        assert "aPTT" in KNOWN_ABBREVIATIONS["PTT"]

    def test_glycemic_abbreviation(self):
        assert "HbA1c" in KNOWN_ABBREVIATIONS
        assert "Hemoglobin A1C" in KNOWN_ABBREVIATIONS["HbA1c"]

    def test_abbreviation_grouping_metabolic(self, tmp_path):
        """Metabolic panel abbreviations group correctly."""
        db = ChartfoldDB(str(tmp_path / "metabolic.db"))
        db.init_schema()
        records = UnifiedRecords(
            source="test",
            lab_results=[
                LabResult(
                    source="test",
                    test_name="Glucose",
                    value="95",
                    value_numeric=95.0,
                    unit="mg/dL",
                    result_date="2025-01-01",
                ),
                LabResult(
                    source="test",
                    test_name="Glucose Level",
                    value="100",
                    value_numeric=100.0,
                    unit="mg/dL",
                    result_date="2025-02-01",
                ),
            ],
        )
        db.load_source(records)

        groups = _group_test_names(db, ["Glucose"])
        _name, match = groups[0]
        assert "Glucose Level" in match
        db.close()

    def test_abbreviation_grouping_liver(self, tmp_path):
        """Liver function abbreviations group ALT/SGPT."""
        db = ChartfoldDB(str(tmp_path / "liver.db"))
        db.init_schema()
        records = UnifiedRecords(
            source="test",
            lab_results=[
                LabResult(
                    source="test",
                    test_name="ALT",
                    value="25",
                    value_numeric=25.0,
                    unit="U/L",
                    result_date="2025-01-01",
                ),
                LabResult(
                    source="test",
                    test_name="SGPT",
                    value="28",
                    value_numeric=28.0,
                    unit="U/L",
                    result_date="2025-02-01",
                ),
            ],
        )
        db.load_source(records)

        groups = _group_test_names(db, ["ALT"])
        _name, match = groups[0]
        assert "SGPT" in match
        db.close()

    def test_abbreviation_grouping_coag(self, tmp_path):
        """Coagulation abbreviations group PTT/aPTT."""
        db = ChartfoldDB(str(tmp_path / "coag.db"))
        db.init_schema()
        records = UnifiedRecords(
            source="test",
            lab_results=[
                LabResult(
                    source="test",
                    test_name="PTT",
                    value="28",
                    value_numeric=28.0,
                    unit="sec",
                    result_date="2025-01-01",
                ),
                LabResult(
                    source="test",
                    test_name="aPTT",
                    value="30",
                    value_numeric=30.0,
                    unit="sec",
                    result_date="2025-02-01",
                ),
            ],
        )
        db.load_source(records)

        groups = _group_test_names(db, ["PTT"])
        _name, match = groups[0]
        assert "aPTT" in match
        db.close()
