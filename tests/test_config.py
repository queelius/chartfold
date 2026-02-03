"""Tests for chartfold.config module."""

import pytest

from chartfold.config import (
    FALLBACK_KEY_TESTS,
    generate_config,
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
            LabResult(source="test", test_name="CEA", value="5.8", value_numeric=5.8,
                      unit="ng/mL", result_date="2025-01-01"),
            LabResult(source="test", test_name="CEA", value="3.2", value_numeric=3.2,
                      unit="ng/mL", result_date="2025-03-01"),
            LabResult(source="test", test_name="CEA", value="4.1", value_numeric=4.1,
                      unit="ng/mL", result_date="2025-06-01"),
            LabResult(source="test", test_name="Hemoglobin", value="12.5", value_numeric=12.5,
                      unit="g/dL", result_date="2025-01-01"),
            LabResult(source="test", test_name="Hemoglobin", value="13.0", value_numeric=13.0,
                      unit="g/dL", result_date="2025-06-01"),
            LabResult(source="test", test_name="WBC", value="6.2", value_numeric=6.2,
                      unit="K/mm3", result_date="2025-01-01"),
        ],
    )
    db.load_source(records)
    yield db
    db.close()


class TestLoadConfig:
    def test_missing_file_returns_defaults(self, tmp_path):
        config = load_config(str(tmp_path / "nonexistent.toml"))
        assert config["key_tests"] == list(FALLBACK_KEY_TESTS)
        assert config["hugo"]["dashboard_recent_labs"] == 10

    def test_loads_toml_file(self, tmp_path):
        toml_path = tmp_path / "test.toml"
        toml_path.write_text("""
[key_tests]
tests = ["Alpha", "Beta", "Gamma"]

[hugo]
dashboard_recent_labs = 20
""")
        config = load_config(str(toml_path))
        assert config["key_tests"] == ["Alpha", "Beta", "Gamma"]
        assert config["hugo"]["dashboard_recent_labs"] == 20

    def test_partial_config_preserves_defaults(self, tmp_path):
        toml_path = tmp_path / "partial.toml"
        toml_path.write_text("""
[key_tests]
tests = ["OnlyOne"]
""")
        config = load_config(str(toml_path))
        assert config["key_tests"] == ["OnlyOne"]
        # Hugo defaults still present
        assert config["hugo"]["dashboard_recent_labs"] == 10

    def test_empty_config(self, tmp_path):
        toml_path = tmp_path / "empty.toml"
        toml_path.write_text("")
        config = load_config(str(toml_path))
        assert config["key_tests"] == list(FALLBACK_KEY_TESTS)


class TestGenerateConfig:
    def test_generates_from_db(self, config_db, tmp_path):
        out = str(tmp_path / "generated.toml")
        generate_config(config_db, config_path=out)

        config = load_config(out)
        # CEA has 3 results, Hemoglobin has 2, WBC has 1 — so CEA should be first
        assert config["key_tests"][0] == "CEA"
        assert "Hemoglobin" in config["key_tests"]
        assert "WBC" in config["key_tests"]

    def test_generated_file_is_valid_toml(self, config_db, tmp_path):
        out = str(tmp_path / "valid.toml")
        generate_config(config_db, config_path=out)

        import tomllib
        with open(out, "rb") as f:
            data = tomllib.load(f)
        assert "key_tests" in data
        assert isinstance(data["key_tests"]["tests"], list)

    def test_empty_db_uses_fallbacks(self, tmp_path):
        db = ChartfoldDB(str(tmp_path / "empty.db"))
        db.init_schema()

        out = str(tmp_path / "fallback.toml")
        generate_config(db, config_path=out)
        db.close()

        config = load_config(out)
        assert config["key_tests"] == list(FALLBACK_KEY_TESTS)

    def test_top_n_limits_tests(self, config_db, tmp_path):
        out = str(tmp_path / "limited.toml")
        generate_config(config_db, config_path=out, top_n=2)

        config = load_config(out)
        assert len(config["key_tests"]) == 2
